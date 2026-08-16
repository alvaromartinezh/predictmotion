"""Orquestador del generador de artículos.

Se llama best-effort desde seo/generate_site.py tras el bucle de ligas (sin
cron propio: hereda la cadencia del cron SEO existente). La cadencia REAL de
artículos la decide el *gating* interno de este módulo (state file), igual
que seo/tweets.py decide si hay algo nuevo que publicar.

Tres niveles, de menos a más intrusivo:
  --dry-run              no llama a Gemini; solo imprime qué se generaría.
  (por defecto)           llama a Gemini y escribe a data/articles_preview/
                          (gitignored) — nada público, ni sitemap ni hub.
  --publish               además renderiza a articulos/*.html, actualiza el
                          hub y devuelve las URLs para el sitemap.

Uso:
    python -m articles.generate --dry-run
    python -m articles.generate --league laliga
    python -m articles.generate --league laliga --publish
"""

import argparse
import json
import sys
from datetime import date, datetime, timezone

from seo import notify
from seo.config import LEAGUES, league_by_slug

from . import grounding, render, writer
from .config import (ARTICLES_DATA_DIR, ARTICLES_MAX_PER_DAY, ARTICLES_OUT_DIR,
                     ARTICLES_PREVIEW_DIR, ARTICLES_STATE_FILE,
                     EXPLAINER_COOLDOWN_DAYS, TITLE_RACE_MIN_GAP_DAYS,
                     TITLE_RACE_PROB_SWING_TRIGGER_PP)
from .gemini_client import GeminiError


# ── Estado (dedupe/cadencia) ─────────────────────────────────────────────────

def _load_state():
    try:
        return json.loads(ARTICLES_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(state):
    ARTICLES_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ARTICLES_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                                   encoding="utf-8")


def _days_since(iso_date, today):
    return (date.fromisoformat(today) - date.fromisoformat(iso_date)).days


# ── Selección de candidatos (qué hay nuevo que contar) ───────────────────────

def _pick_recap(league, snap, lstate):
    if snap["jornada"] > lstate.get("last_recap_jornada", 0):
        prev = grounding.load_previous_jornada_snapshot(league["slug"], snap)
        return grounding.ground_recap(league, snap, prev)
    return None


def _pick_explainer(league, snap, lstate, today):
    cooled = lstate.get("explainer_teams", {})
    for t in grounding.teams_near_boundary(snap):
        last = cooled.get(str(t["id"]))
        if last and _days_since(last, today) < EXPLAINER_COOLDOWN_DAYS:
            continue
        return grounding.ground_explainer(league, snap, t), t["id"]
    return None, None


def _pick_title_race(league, snap, lstate, today):
    prev = grounding.load_previous_jornada_snapshot(league["slug"], snap)
    payload = grounding.ground_title_race(league, snap, prev)
    leader_prob = (payload["candidatos"][0]["prob_titulo"] or 0) if payload["candidatos"] else 0
    last = lstate.get("last_title_race")
    if not last:
        return payload
    stale = _days_since(last["date"], today) >= TITLE_RACE_MIN_GAP_DAYS
    swung = abs(leader_prob - last.get("leader_prob", leader_prob)) >= TITLE_RACE_PROB_SWING_TRIGGER_PP
    return payload if (stale or swung) else None


def _candidates(league, snap, lstate, today):
    """Lista de payloads de hechos a generar para esta liga en esta pasada
    (como mucho uno por tipo — no hace falta más por ejecución)."""
    out = []
    recap = _pick_recap(league, snap, lstate)
    if recap:
        out.append(("recap", recap, None))
    explainer, team_id = _pick_explainer(league, snap, lstate, today)
    if explainer:
        out.append(("explainer", explainer, team_id))
    title_race = _pick_title_race(league, snap, lstate, today)
    if title_race:
        out.append(("title_race", title_race, None))
    return out


def _record(lstate, kind, payload, team_id, today):
    if kind == "recap":
        lstate["last_recap_jornada"] = payload["jornada"]
    elif kind == "explainer":
        lstate.setdefault("explainer_teams", {})[str(team_id)] = today
    elif kind == "title_race":
        c = payload["candidatos"][0] if payload["candidatos"] else None
        lstate["last_title_race"] = {"date": today, "leader_prob": (c or {}).get("prob_titulo", 0)}


# ── Persistencia ─────────────────────────────────────────────────────────────

def _save_metadata(article, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{article['slug']}.json"
    path.write_text(json.dumps(article, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _published_index():
    """Metadata mínima de artículos ya publicados, para el hub — lee
    data/articles/*.json con status 'published', más recientes primero."""
    if not ARTICLES_DATA_DIR.exists():
        return []
    out = []
    for f in ARTICLES_DATA_DIR.glob("*.json"):
        try:
            a = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if a.get("status") == "published":
            out.append(a)
    out.sort(key=lambda a: a["generated_at"], reverse=True)
    return out


# ── Orquestador ───────────────────────────────────────────────────────────────

def _run(args):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = _load_state()
    if state.get("date") != today:
        state = {"date": today, "count_today": 0, "leagues": {}}

    leagues = [league_by_slug(args.league)] if args.league else LEAGUES
    if args.league and not leagues[0]:
        print(f"Liga desconocida: {args.league}", file=sys.stderr)
        return 1, []

    generated, failures = [], []
    files, urls = {}, []

    for league in leagues:
        if state["count_today"] >= ARTICLES_MAX_PER_DAY:
            break
        slug = league["slug"]
        snap = grounding.load_snapshot(slug)
        if not snap:
            continue
        lstate = state["leagues"].setdefault(slug, {})

        for kind, payload, team_id in _candidates(league, snap, lstate, today):
            if state["count_today"] >= ARTICLES_MAX_PER_DAY:
                break
            if args.dry_run:
                print(f"[dry] {slug} · {kind} · {payload['tipo']}")
                continue
            try:
                article = writer.write_article(slug, payload)
            except GeminiError as e:
                print(f"  [SKIP] {slug} {kind}: {e}", file=sys.stderr)
                failures.append((slug, kind, str(e)))
                continue

            state["count_today"] += 1
            _record(lstate, kind, payload, team_id, today)
            generated.append(article)

            if args.publish and article["status"] == "draft":
                article["status"] = "published"
                _save_metadata(article, ARTICLES_DATA_DIR)
                path, html = render.render_article(article, league, logo=snap.get("league_logo"))
                files[path] = html
                urls.append((render.article_url(article["slug"]), today))
            elif args.publish:
                # flagged: se audita pero nunca se publica.
                _save_metadata(article, ARTICLES_DATA_DIR)
            else:
                _save_metadata(article, ARTICLES_PREVIEW_DIR)

    if args.publish and files:
        index = _published_index()
        cards = [{"slug": a["slug"], "title": a["title"], "meta_description": a["meta_description"],
                 "league_name": league_by_slug(a["league"])["name"], "generated_at": a["generated_at"]}
                for a in index]
        hub_path, hub_html = render.render_hub(cards)
        files[hub_path] = hub_html
        urls.append((render.hub_url(), today))

    if not args.dry_run:
        for relpath, html in files.items():
            path = ARTICLES_OUT_DIR.parent / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
        _write_state(state)

    flagged = sum(1 for a in generated if a["status"] in ("flagged",))
    print(f"\nFin — {len(generated)} artículos generados "
          f"({len(generated) - flagged} ok, {flagged} flagged por grounding), "
          f"{len(failures)} fallos de Gemini.")

    if not generated and failures and not args.dry_run:
        motivos = "\n".join(f"  - {slug} {kind}: {err}" for slug, kind, err in failures)
        notify.send_alert(
            "[PredictMotion] articles: 0 artículos generados",
            f"El generador de artículos no consiguió generar ninguno.\n\n{motivos}",
            dedup_key="articles_zero",
        )
    return 0, urls


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="No llama a Gemini; solo imprime qué se generaría")
    ap.add_argument("--publish", action="store_true",
                    help="Renderiza a articulos/*.html y actualiza el hub (si no, solo preview)")
    ap.add_argument("--league", help="Procesar solo esta liga (slug)")
    args = ap.parse_args(argv)
    try:
        code, _urls = _run(args)
        return code
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        if not args.dry_run:
            notify.send_alert(
                "[PredictMotion] articles: excepción no capturada",
                f"El generador de artículos abortó con una excepción:\n\n{tb}",
                dedup_key="articles_crash",
            )
        return 1


def run():
    """Punto de entrada para seo/generate_site.py: ejecución completa (todas las
    ligas), sin --publish todavía (se activa a mano cuando se decida que la
    calidad es suficiente — ver plan). Devuelve la lista de (url, lastmod)
    para el sitemap (vacía mientras no se pase --publish)."""
    args = argparse.Namespace(dry_run=False, publish=False, league=None)
    _code, urls = _run(args)
    return urls


if __name__ == "__main__":
    sys.exit(main())
