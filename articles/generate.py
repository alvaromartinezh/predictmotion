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
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from seo import espn, notify
from seo.config import LEAGUES, league_by_slug

from . import grounding, render, writer
from .config import (ARTICLE_LEAGUES, ARTICLES_DATA_DIR, ARTICLES_MAX_PER_DAY,
                     ARTICLES_OUT_DIR, ARTICLES_PREVIEW_DIR, ARTICLES_STATE_FILE,
                     DATA_DIR, EXPLAINER_COOLDOWN_DAYS, PREVIA_NEWS_REVIEW_UNTIL,
                     TITLE_RACE_MIN_GAP_DAYS, TITLE_RACE_PROB_SWING_TRIGGER_PP)
from .gemini_client import GeminiError

# Ventana hacia atrás al buscar partidos de Hypermotion recién finalizados
# (no solo "hoy"): cubre el caso de que una pasada del cron se salte un
# partido (caída de ESPN, cron parado) sin perderlo — el dedupe por
# event_id en `reported_matches` hace que reintentar la ventana sea inofensivo.
MATCH_REPORT_LOOKBACK_DAYS = 3

# previa_diaria/resumen_diario están anclados a la hora local de la
# audiencia (España), no a UTC — usa zoneinfo (stdlib) para que el cambio
# CEST/CET no desfase el horario dos veces al año. El resto del state file
# (reset de ARTICLES_MAX_PER_DAY, cooldowns de explicador/carrera) sigue en
# UTC sin cambios: no es lo que se pidió y tocarlo movería el presupuesto de
# TODOS los tipos, no solo estos dos.
MADRID_TZ = ZoneInfo("Europe/Madrid")
PREVIEW_LOCAL_HOUR = 8   # previa_diaria no se dispara antes de esta hora local


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


def _fmt_compact(iso_date):
    return iso_date.replace("-", "")


def _pick_match_reports(league, snap, lstate, today):
    """Solo Hypermotion: un artículo por partido recién finalizado (no un
    resumen de jornada). Puede devolver varios candidatos en una misma
    pasada si varios partidos han terminado desde la última vez."""
    if league["slug"] != "hypermotion":
        return []
    reported = set(lstate.get("reported_matches", []))
    end = date.fromisoformat(today)
    start = end - timedelta(days=MATCH_REPORT_LOOKBACK_DAYS)
    events = espn.fetch_scoreboard_range(
        league["espn_code"], start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    return [grounding.ground_cronica_partido(league, snap, ev)
            for ev in events if ev["state"] == "post" and ev["event_id"] not in reported]


def _pick_daily_preview(league, snap, lstate, today_local, now_local):
    """Una vez al día por liga, solo si hoy (calendario de España) hay
    partidos programados, y no antes de PREVIEW_LOCAL_HOUR hora local — así
    "hoy" significa lo mismo para el lector que para el cron, y la previa no
    sale a las 00:05 solo porque esa fue la primera pasada del día."""
    if lstate.get("last_preview_date") == today_local:
        return None
    if now_local.hour < PREVIEW_LOCAL_HOUR:
        return None
    compact = _fmt_compact(today_local)
    events = espn.fetch_scoreboard_range(league["espn_code"], compact, compact)
    if not events:
        return None
    return grounding.ground_previa_diaria(league, snap, events)


def _pick_daily_wrap(league, snap, lstate, today_local):
    """Una vez al día por liga: en la primera pasada de un nuevo día local
    (no hace falta guardia de hora — "primer pase del día" YA es ~00:00 con
    el cron corriendo cada pocos minutos), resume los partidos de AYER
    (día local) si terminó alguno. Sin guardia de hora explícita porque el
    dedupe es por fecha resumida, no por cuándo se generó."""
    end = date.fromisoformat(today_local)
    yesterday_local = (end - timedelta(days=1)).isoformat()
    if lstate.get("last_wrap_date") == yesterday_local:
        return None
    compact = _fmt_compact(yesterday_local)
    events = espn.fetch_scoreboard_range(league["espn_code"], compact, compact)
    finished = [ev for ev in events if ev["state"] == "post"]
    if not finished:
        return None
    return grounding.ground_resumen_diario(league, snap, finished)


def _record(lstate, kind, payload, team_id, today):
    """`today` es la fecha que corresponda al `kind` (UTC para
    recap/explainer/title_race, local España para preview/wrap — ver
    llamadas en _run) — esta función solo la guarda bajo la clave que toque."""
    if kind == "recap":
        lstate["last_recap_jornada"] = payload["jornada"]
    elif kind == "explainer":
        lstate.setdefault("explainer_teams", {})[str(team_id)] = today
    elif kind == "title_race":
        c = payload["candidatos"][0] if payload["candidatos"] else None
        lstate["last_title_race"] = {"date": today, "leader_prob": (c or {}).get("prob_titulo", 0)}
    elif kind == "cronica":
        lstate.setdefault("reported_matches", []).append(payload["event_id"])
    elif kind == "preview":
        lstate["last_preview_date"] = today
    elif kind == "wrap":
        lstate["last_wrap_date"] = payload["fecha"]


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


def _article_cards(index):
    """Metadata mínima para las tarjetas del hub y del carrusel "Seguir
    viendo…" de cada artículo — misma forma en los dos sitios."""
    return [{"slug": a["slug"], "title": a["title"], "meta_description": a["meta_description"],
            "league_name": league_by_slug(a["league"])["name"], "generated_at": a["generated_at"]}
           for a in index]


def _preview_index():
    """Metadata completa de TODO lo que el pipeline ha generado y AÚN NO es
    público: lo que run() (sin --publish, el modo normal del cron) va
    guardando en ARTICLES_PREVIEW_DIR, más lo que un --publish haya dejado
    pending_review/flagged en ARTICLES_DATA_DIR (nunca lo ya 'published' —
    eso vive en su URL pública de siempre). A diferencia de _published_index,
    devuelve el dict COMPLETO (no solo metadata): render_article lo necesita
    entero para poder renderizar la vista preview."""
    out = []
    for d in (ARTICLES_PREVIEW_DIR, ARTICLES_DATA_DIR):
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            if f.name == _PUBLIC_INDEX_NAME:   # el índice agregado, no un artículo
                continue
            try:
                a = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if a.get("status") != "published":
                out.append(a)
    out.sort(key=lambda a: a["generated_at"], reverse=True)
    return out


def _preview_cards(index):
    """Como _article_cards, pero con `status` (el hub de preview lo pinta
    como badge; el hub público no, porque solo lista publicados)."""
    return [{"slug": a["slug"], "title": a["title"], "meta_description": a["meta_description"],
            "league_name": league_by_slug(a["league"])["name"], "generated_at": a["generated_at"],
            "status": a["status"]}
           for a in index]


_PUBLIC_INDEX_NAME = "latest.json"


def _index_payload(index):
    """{generated, count, items} para un índice de artículos consumible por
    el home — `leagues`/`teams` salen de `render._mentioned_teams` (dato ya
    estructurado en el payload de grounding, sin heurística de alias como
    noticias). Compartido por el índice público y el de preview: la única
    diferencia entre los dos es de qué lista de artículos parten y dónde se
    escriben."""
    items = []
    for a in index:
        teams = render._mentioned_teams(a["type"], a["grounding_data"])
        items.append({
            "slug": a["slug"], "title": a["title"], "meta_description": a["meta_description"],
            "type": a["type"], "league": a["league"], "leagues": [a["league"]],
            "teams": [{"id": tid, "name": name} for tid, name, _logo in teams],
            "generated_at": a["generated_at"],
        })
    return {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "count": len(items), "items": items}


def _write_json_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _write_public_index(index):
    """Índice público de artículos PUBLICADOS (`data/articles/latest.json`,
    en el mismo `ARTICLES_DATA_DIR` que los JSON por artículo pero con
    nombre reservado — ver el skip en _preview_index de arriba), servido sin
    gate por el `file_server` genérico de Caddy (mismo bucket que
    `data/news/latest.json`, que ya se sirve así). `index`: artículos
    publicados (`_published_index()`), más recientes primero. Escritura
    atómica para que un lector concurrente (el home, en pleno fetch) nunca
    vea el fichero a medias."""
    _write_json_atomic(ARTICLES_DATA_DIR / _PUBLIC_INDEX_NAME, _index_payload(index))


def _write_preview_index(index):
    """Como _write_public_index pero para /preview-home (ver plan): se
    escribe DENTRO de `preview-articulos/` — la misma carpeta que ya sirve
    Caddy gateada por basic_auth (`@previewarticulos path /preview-articulos
    /preview-articulos/*`) — para que este índice, que expone títulos y
    equipos de artículos AÚN NO públicos, quede protegido igual que las
    páginas que enlaza, sin una regla de Caddy nueva. `index`:
    `_preview_index()` (draft/pending_review/flagged), más recientes
    primero. Se regenera SIEMPRE (no solo en --publish) — mismo trigger que
    el resto del preview, ver más abajo."""
    _write_json_atomic(ARTICLES_OUT_DIR.parent / "preview-articulos" / _PUBLIC_INDEX_NAME,
                       _index_payload(index))


def _fuentes_txt(article):
    return "\n".join(f"- {s['title']}: {s['uri']}" for s in article.get("sources", []))


def _notify_pending_review(article):
    """Aviso de que hay una previa con contexto de búsqueda esperando un
    vistazo. dedup_hours=0 + clave por slug: se manda una vez por artículo,
    nunca se repite (no hace falta ventana de tiempo)."""
    notify.send_alert(
        f"[PredictMotion] previa pendiente de revisión: {article['slug']}",
        f"Contiene contexto de búsqueda (lesiones/noticias) que conviene revisar antes "
        f"de publicar.\n\nPara publicarla: cambia \"status\": \"pending_review\" a "
        f"\"draft\" en data/articles/{article['slug']}.json y vuelve a correr "
        f"--publish. Se auto-publicará sola (sin revisión) a partir del "
        f"{PREVIA_NEWS_REVIEW_UNTIL}.\n\nFuentes citadas:\n\n{_fuentes_txt(article)}",
        dedup_key=f"articles_pending_review_{article['slug']}", dedup_hours=0,
    )


def _notify_published_with_sources(article):
    """Aviso pasivo (no de aprobación) tras la ventana de revisión: la previa
    ya salió sola, esto es solo visibilidad de qué fuentes citó."""
    notify.send_alert(
        f"[PredictMotion] previa publicada con fuentes externas: {article['slug']}",
        f"Se publicó automáticamente con contexto de búsqueda (fuera de la ventana "
        f"de revisión).\n\n{render.article_url(article['slug'])}\n\n"
        f"Fuentes citadas:\n\n{_fuentes_txt(article)}",
        dedup_key=f"articles_published_sources_{article['slug']}", dedup_hours=0,
    )


# ── Orquestador ───────────────────────────────────────────────────────────────

def _run(args):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_local = datetime.now(MADRID_TZ)
    today_local = now_local.strftime("%Y-%m-%d")
    state = _load_state()
    if state.get("date") != today:
        state = {"date": today, "count_today": 0, "leagues": {}}

    if args.league:
        leagues = [league_by_slug(args.league)]
        if not leagues[0]:
            print(f"Liga desconocida: {args.league}", file=sys.stderr)
            return 1, []
    else:
        leagues = [lg for lg in LEAGUES if lg["slug"] in ARTICLE_LEAGUES]

    generated, failures = [], []
    files, urls = {}, []

    # Contexto por liga (snapshot + estado), calculado una vez y compartido
    # entre las dos fases de abajo.
    ctx = []
    for league in leagues:
        snap = grounding.load_snapshot(league["slug"])
        if snap:
            ctx.append((league, snap, state["leagues"].setdefault(league["slug"], {})))

    def _emit(kind, payload, team_id, league, snap, lstate, record_date):
        """Devuelve False si el presupuesto diario ya está agotado (el
        llamador debe dejar de intentar más artículos). `record_date`: la
        fecha que _record debe guardar para este kind — UTC para
        recap/explainer/title_race/cronica, local España para preview/wrap
        (ver las llamadas en las fases A/B de abajo)."""
        if state["count_today"] >= ARTICLES_MAX_PER_DAY:
            return False
        if args.dry_run:
            print(f"[dry] {league['slug']} · {kind} · {payload['tipo']}")
            return True
        try:
            article = writer.write_article(league["slug"], payload)
        except GeminiError as e:
            print(f"  [SKIP] {league['slug']} {kind}: {e}", file=sys.stderr)
            failures.append((league["slug"], kind, str(e)))
            return True

        state["count_today"] += 1
        _record(lstate, kind, payload, team_id, record_date)
        generated.append(article)

        if args.publish and article["status"] == "draft":
            article["status"] = "published"
            _save_metadata(article, ARTICLES_DATA_DIR)
            recent = _article_cards(a for a in _published_index() if a["slug"] != article["slug"])
            path, html = render.render_article(article, league, logo=snap.get("league_logo"),
                                               recent=recent[:7])
            files[path] = html
            urls.append((render.article_url(article["slug"]), today))
            if article.get("sources"):
                _notify_published_with_sources(article)
        elif args.publish and article["status"] == "pending_review":
            # Contiene contexto de búsqueda (previa_diaria) — se audita pero
            # NO se publica hasta que alguien lo revise o pase
            # PREVIA_NEWS_REVIEW_UNTIL (ver write_article). El sitio no se
            # rompe si nadie mira el email: ese artículo concreto simplemente
            # no sale hasta entonces.
            _save_metadata(article, ARTICLES_DATA_DIR)
            _notify_pending_review(article)
        elif args.publish:
            # flagged: se audita pero nunca se publica.
            _save_metadata(article, ARTICLES_DATA_DIR)
        else:
            _save_metadata(article, ARTICLES_PREVIEW_DIR)
        return True

    # Fase A: tipos de baja frecuencia / disparo único al día (previa,
    # recap, explicador, carrera por el título), para TODAS las ligas antes
    # que la fase B. Así un día con varias crónicas de Hypermotion no les
    # quita presupuesto — la crónica es el único tipo seguro de aplazar al
    # siguiente cron (ESPN sigue reportando el partido como 'post' hasta
    # que lo registramos), los demás no tienen esa garantía de reintento.
    for league, snap, lstate in ctx:
        preview = _pick_daily_preview(league, snap, lstate, today_local, now_local)
        if preview and not _emit("preview", preview, None, league, snap, lstate, today_local):
            break
        wrap = _pick_daily_wrap(league, snap, lstate, today_local)
        if wrap and not _emit("wrap", wrap, None, league, snap, lstate, today_local):
            break
        recap = _pick_recap(league, snap, lstate)
        if recap and not _emit("recap", recap, None, league, snap, lstate, today):
            break
        explainer, team_id = _pick_explainer(league, snap, lstate, today)
        if explainer and not _emit("explainer", explainer, team_id, league, snap, lstate, today):
            break
        title_race = _pick_title_race(league, snap, lstate, today)
        if title_race and not _emit("title_race", title_race, None, league, snap, lstate, today):
            break

    # Fase B: crónicas de partido (Hypermotion), después de garantizar el
    # resto de tipos.
    for league, snap, lstate in ctx:
        for report in _pick_match_reports(league, snap, lstate, today):
            if not _emit("cronica", report, None, league, snap, lstate, today):
                break

    if args.publish and files:
        published = _published_index()
        hub_path, hub_html = render.render_hub(_article_cards(published))
        files[hub_path] = hub_html
        urls.append((render.hub_url(), today))
        _write_public_index(published)

    # Preview privado (/preview-articulos, gateado por basic_auth en Caddy —
    # ver CLAUDE.md "Preview privado de artículos"): TODO lo que el pipeline
    # ha generado y aún no es público, siempre fresco (no solo lo de esta
    # pasada — _preview_index() relee de disco, así lo de pasadas anteriores
    # sigue visible). Independiente de --publish: incluso una pasada
    # --publish puede dejar cosas pending_review/flagged que conviene poder
    # revisar. Best-effort por artículo: un fallo de render no debe tirar
    # el resto del preview.
    if not args.dry_run:
        snap_by_slug = {lg["slug"]: sn for lg, sn, _ in ctx}
        preview_articles = _preview_index()
        for a in preview_articles:
            lg = league_by_slug(a["league"])
            if not lg:
                continue
            try:
                ppath, phtml = render.render_article(
                    a, lg, logo=(snap_by_slug.get(a["league"]) or {}).get("league_logo"), preview=True)
                files[ppath] = phtml
            except Exception as e:
                print(f"  [WARN] preview render failed {a['slug']}: {e}", file=sys.stderr)
        hub_path, hub_html = render.render_preview_hub(_preview_cards(preview_articles))
        files[hub_path] = hub_html
        _write_preview_index(preview_articles)

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
