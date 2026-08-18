"""Orquestador de los artículos de Hypermotion: el resumen diario y la
crónica de partido.

DOS entry points/cron (ver CLAUDE.md):
- `--matches-only`, cada 5 min: publica la crónica de cada partido de
  Hypermotion terminado hoy NADA MÁS TERMINAR (no espera a las 23:59).
- sin flags, a las 23:59 hora de España: el resumen diario + explicador de
  siempre, Y ADEMÁS vuelve a pasar por los partidos del día como red de
  seguridad (si el cron frecuente se perdió alguno por lo que sea). Ambos
  caminos llaman a `_run_match`, que es idempotente
  (`_match_already_handled`): si el partido ya tiene HTML publicado o ya
  quedó en cuarentena, no vuelve a gastar Gemini en él.

Best-effort: si no hay partidos no pasa nada (día normal, sin alerta). Si
Gemini falla o el validador de grounding no acepta el texto, NO se publica
y se manda un email — mismo patrón que seo/generate_site.py. Una excepción
en un partido no aborta los demás.

Al publicar CUALQUIERA de los dos (resumen diario o crónica de partido), se
manda un aviso a Telegram (mismo bot que seo/tweets.py) con el titular, una
frase de invitación a entrar (_TWEET_CTAS, determinista por clave, SIN
Gemini) y el enlace del artículo, para que el dueño lo tuitee a mano.

Uso:
    python -m articles.generate                  # resumen diario (23:59) + red de seguridad
    python -m articles.generate --matches-only    # solo crónicas de partido (cron frecuente)
    python -m articles.generate --dry-run         # no llama a Gemini ni escribe
"""

import argparse
import hashlib
import json
import os
import sys
import traceback
from datetime import datetime
from xml.sax.saxutils import escape as xesc
from zoneinfo import ZoneInfo

from seo import espn, notify
from seo.config import SITE, league_by_slug
from seo.textutil import pct
from seo.tweets import _caption, _tg_send_message

from . import grounding, layout_estimate, render, writer
from .config import ARTICLES_OUT_DIR, DATA_DIR

_MADRID_TZ = ZoneInfo("Europe/Madrid")
_LEAGUE_SLUG = "hypermotion"
_FLAGGED_DIR = DATA_DIR / "articles_flagged"

# Frase que anima a entrar al artículo, para el tweet — a propósito SIN
# Gemini (el titular ya lleva un porcentaje real, ver writer._HEADLINE_INSTR/
# _MATCH_HEADLINE_INSTR, pero esta línea sigue aportando la invitación a
# entrar a ver el resto — "el análisis completo", no solo esa cifra suelta).
# Elegida a mano, determinista por clave (mismo patrón que illustration.pick
# — fecha para el resumen diario, _match_flag_id(payload) para cada crónica
# de partido, así dos artículos del mismo día no repiten frase) para que no
# haga falta gastar una llamada a Gemini ni validarla — es solo una
# invitación a hacer clic, no un dato.
_TWEET_CTAS = [
    "Los porcentajes completos, en el artículo 👇",
    "¿Cuánto ha cambiado cada equipo? Entra a verlo.",
    "Las probabilidades actualizadas, aquí:",
    "El modelo ha movido las opciones de varios equipos. Compruébalo.",
    "Con cifras y explicación, un clic más abajo.",
    "Todo el análisis de probabilidades, en el artículo completo.",
    "¿Qué dice el modelo ahora? Descúbrelo aquí.",
]


def _pick_tweet_cta(key):
    idx = int(hashlib.md5(f"tweet-cta|{key}".encode()).hexdigest(), 16) % len(_TWEET_CTAS)
    return _TWEET_CTAS[idx]


def _pick_highlight_team_id(partidos):
    """Equipo con mayor cambio de probabilidad (pp) en su zona hoy — el más
    noticiable del día, sin gastar una llamada a Gemini en elegirlo."""
    best_id, best_delta = None, -1
    for m in partidos:
        for t in (m["local"], m["visitante"]):
            actual, antes = t.get("prob_zona_actual"), t.get("prob_zona_antes_del_partido")
            if actual is None or antes is None:
                continue
            d = abs(actual - antes)
            if d > best_delta:
                best_delta, best_id = d, t["id"]
    if best_id is not None:
        return best_id
    return partidos[0]["local"]["id"]  # sin histórico previo (p.ej. jornada 1)


def _write_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _save_flagged(fecha, kind, payload, article):
    _FLAGGED_DIR.mkdir(parents=True, exist_ok=True)
    path = _FLAGGED_DIR / f"{kind}-{fecha}.json"
    path.write_text(json.dumps({"payload": payload, **article}, ensure_ascii=False, indent=1), encoding="utf-8")


def _write_latest_pointer(fecha, title):
    """data/articles/latest.json: puntero al broadsheet más reciente, para que
    /noticias pueda enlazarlo sin hardcodear una fecha en un HTML estático."""
    path = DATA_DIR / "articles" / "latest.json"
    _write_atomic(path, json.dumps({"url": render.url_for(fecha), "title": title, "fecha": fecha},
                                    ensure_ascii=False))


def _notify_telegram(headline, cta, article_url):
    """Best-effort: aviso a Telegram (mismo bot que seo/tweets.py) con el
    titular + una frase que invita a entrar (ver _TWEET_CTAS, NO el
    subtítulo generado por Gemini — ese ya cumplió su función en la propia
    página) + enlace del artículo, para que el dueño lo tuitee a mano —
    reusa _caption()/_tg_send_message() (texto + enlace directo al
    compositor de X precargado), sin el teclado inline de los tuits de
    jornada: esto es de un solo uso, no hay nada que regenerar."""
    notify._load_env()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not chat_id:
        print("hypermotion: sin TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID, no se avisa a Telegram")
        return
    tweet_text = f"{headline}\n{cta}\n{article_url}"
    if not _tg_send_message(chat_id, _caption(tweet_text)):
        print("hypermotion: aviso a Telegram no confirmado", file=sys.stderr)


def _match_flag_id(payload):
    l, v = payload["local"], payload["visitante"]
    return f'{payload["fecha"]}-{l["id"]}-{v["id"]}'


def _match_already_handled(payload):
    """True si este partido ya tiene HTML publicado o ya quedó en
    cuarentena (grounding fallido) en un intento anterior. Sin estado propio
    que mantener (mismo criterio self-healing que _write_sitemap): con DOS
    caminos llamando a _run_match (el cron frecuente y la red de seguridad
    de las 23:59), esto evita generar dos veces el mismo partido y gastar
    Gemini de más."""
    l, v = payload["local"], payload["visitante"]
    slug = render.slug_for_match(payload["fecha"], l["nombre"], v["nombre"])
    if (ARTICLES_OUT_DIR / f"{slug}.html").exists():
        return True
    flag_id = _match_flag_id(payload)
    return any(_FLAGGED_DIR.glob(f"match-*-{flag_id}.json"))


def _run_match(league, snap, match, dry_run):
    """Crónica de UN partido terminado (broadsheet de partido, ver
    render.render_match_broadsheet). Best-effort igual que el resumen diario:
    si el grounding marca alguno de los 3 textos, no se publica y se avisa;
    el llamador (_run_finished_matches) además aísla las excepciones por
    partido para que una jornada de varios partidos no se caiga entera por
    uno."""
    payload = grounding.ground_match(league, snap, match)
    if not payload:
        return 0
    l, v = payload["local"], payload["visitante"]

    if _match_already_handled(payload):
        return 0

    if dry_run:
        print(f"hypermotion: publicaría crónica {render.slug_for_match(payload['fecha'], l['nombre'], v['nombre'])}")
        return 0

    results = {
        "local": writer.write_article(dict(payload, tipo="match_local")),
        "visitante": writer.write_article(dict(payload, tipo="match_visitante")),
        "cronica": writer.write_article(dict(payload, tipo="match_cronica")),
    }
    if any(r["status"] != "draft" for r in results.values()):
        flag_id = _match_flag_id(payload)
        bad = []
        for key, r in results.items():
            if r["status"] != "draft":
                _save_flagged(flag_id, f"match-{key}", payload, r)
                bad += r["flagged_values"]
        notify.send_alert(
            "[PredictMotion] crónica de partido de Hypermotion sin publicar (grounding)",
            f"El texto generado por Gemini para {l['nombre']} {payload['resultado']['local']}-"
            f"{payload['resultado']['visitante']} {v['nombre']} ({payload['fecha']}) citaba cifras "
            f"que no están en los datos reales, así que no se publica: {bad}\n\n"
            f"Detalle en {_FLAGGED_DIR}/match-*-{flag_id}.json (en el servidor).",
            dedup_key="articles_match_flagged",
        )
        return 1

    catchy = writer.write_match_headline(dict(payload, tipo="match_cronica"))
    if catchy:
        headline, teaser = catchy
    else:
        print(f"hypermotion: titular de partido no disponible ({l['nombre']}-{v['nombre']}), cae al determinista")
        headline = f'{l["nombre"]} {payload["resultado"]["local"]}-{payload["resultado"]["visitante"]} {v["nombre"]}'
        teaser = results["cronica"]["meta_description"]

    html = render.render_match_broadsheet(
        payload, results["local"]["body"], results["visitante"]["body"], results["cronica"]["body"],
        headline=headline, teaser=teaser, league_logo=snap.get("league_logo"),
    )
    slug = render.slug_for_match(payload["fecha"], l["nombre"], v["nombre"])
    _write_atomic(ARTICLES_OUT_DIR / f"{slug}.html", html)
    article_url = render.url_for_match(payload["fecha"], l["nombre"], v["nombre"])
    print(f"hypermotion: publicado {article_url}")

    flag_id = _match_flag_id(payload)
    _notify_telegram(headline, _pick_tweet_cta(flag_id), SITE + article_url)
    return 0


def _write_sitemap():
    """sitemap-articles.xml: se reconstruye escaneando los HTML ya en disco —
    self-healing, sin estado aparte que pueda desincronizarse."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for f in sorted(ARTICLES_OUT_DIR.glob("*.html")):
        loc = xesc(f"{SITE}/articulos/{f.stem}")
        lastmod = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
        lines.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod><changefreq>daily</changefreq></url>")
    lines.append("</urlset>")
    (ARTICLES_OUT_DIR.parent / "sitemap-articles.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_finished_matches(league, snap, finished, today, dry_run):
    """Bucle best-effort sobre los partidos terminados de hoy — lo comparten
    _run_matches_only (cron frecuente) y _run (red de seguridad de las
    23:59). Una excepción en un partido no aborta los demás."""
    for m in finished:
        try:
            _run_match(league, snap, m, dry_run)
        except Exception:
            tb = traceback.format_exc()
            print(tb, file=sys.stderr)
            if not dry_run:
                notify.send_alert(
                    "[PredictMotion] crónica de partido de Hypermotion cayó con una excepción",
                    f"Partido {m.get('home', {}).get('name')}-{m.get('away', {}).get('name')} "
                    f"({today}) abortó con una excepción:\n\n{tb}",
                    dedup_key="articles_match_crash",
                )


def _run_matches_only(dry_run, date_override=None):
    """Entry point del cron frecuente (cada 5 min, ver CLAUDE.md): publica la
    crónica de cada partido de Hypermotion nada más terminar, en vez de
    esperar al resumen diario de las 23:59. Sin resumen ni explicador —
    _run_match es idempotente (_match_already_handled), así que no importa
    si esta pasada y la red de seguridad de las 23:59 se solapan."""
    league = league_by_slug(_LEAGUE_SLUG)
    snap = grounding.load_snapshot(_LEAGUE_SLUG)
    if not snap:
        return 0
    today = date_override or datetime.now(_MADRID_TZ).strftime("%Y-%m-%d")
    compact = today.replace("-", "")
    events = espn.fetch_scoreboard_range(league["espn_code"], compact, compact)
    finished = [e for e in events if e["state"] == "post"]
    if not finished:
        return 0
    _run_finished_matches(league, snap, finished, today, dry_run)
    if not dry_run:
        _write_sitemap()  # para que la crónica sea descubrible ya, sin esperar a las 23:59
    return 0


def _run(dry_run, date_override=None):
    league = league_by_slug(_LEAGUE_SLUG)
    snap = grounding.load_snapshot(_LEAGUE_SLUG)
    if not snap:
        print("hypermotion: sin snapshot (offseason o el cron SEO no ha corrido aún)")
        return 0

    # El cron corre a las 23:59 hora de España, así que "hoy" en ese momento
    # sigue siendo el día natural de los partidos. --date es solo para
    # relanzar a mano un día concreto (p.ej. tras medianoche, cuando "hoy"
    # ya habría rodado al día siguiente y los partidos de ayer quedarían
    # invisibles).
    today = date_override or datetime.now(_MADRID_TZ).strftime("%Y-%m-%d")
    compact = today.replace("-", "")
    events = espn.fetch_scoreboard_range(league["espn_code"], compact, compact)
    finished = [e for e in events if e["state"] == "post"]
    if not finished:
        print(f"hypermotion: sin partidos terminados hoy ({today})")
        return 0

    payload_resumen = grounding.ground_resumen_diario(league, snap, finished)
    if not payload_resumen["partidos"]:
        print("hypermotion: partidos de hoy sin equipo resoluble en el snapshot")
        return 0

    # Red de seguridad: por si el cron frecuente (--matches-only) se perdió
    # algún partido. _run_match es idempotente, así que esto es gratis si ya
    # están todos publicados.
    _run_finished_matches(league, snap, finished, today, dry_run)

    team_id = _pick_highlight_team_id(payload_resumen["partidos"])
    team = grounding.team_by_id(snap, team_id)
    payload_explainer = grounding.ground_explainer(league, snap, team)

    if dry_run:
        print(f"hypermotion: publicaría {render.slug_for(today)} "
              f"({len(payload_resumen['partidos'])} partidos, explicador: {team['name']})")
        return 0

    resumen = writer.write_article(payload_resumen)
    explainer = writer.write_article(payload_explainer)

    if resumen["status"] != "draft" or explainer["status"] != "draft":
        if resumen["status"] != "draft":
            _save_flagged(today, "resumen", payload_resumen, resumen)
        if explainer["status"] != "draft":
            _save_flagged(today, "explicador", payload_explainer, explainer)
        bad = resumen["flagged_values"] + explainer["flagged_values"]
        notify.send_alert(
            "[PredictMotion] broadsheet de Hypermotion sin publicar (grounding)",
            f"El texto generado por Gemini el {today} citaba cifras que no están en "
            f"los datos reales, así que no se publica: {bad}\n\n"
            f"Detalle en {_FLAGGED_DIR}/*-{today}.json (en el servidor).",
            dedup_key="articles_flagged",
        )
        return 1

    # Titular+subtítulo "llamativos" (a petición expresa) — best-effort: si
    # Gemini falla el formato o cuela una cifra inventada, cae a la cabecera
    # determinista de siempre en vez de bloquear la publicación por esto.
    catchy = writer.write_headline(payload_resumen)
    if catchy:
        headline, subtitle = catchy
    else:
        print("hypermotion: titular llamativo no disponible, cae al determinista")
        headline = resumen["title"].replace(" | PredictMotion", "")
        subtitle = render._teaser(payload_resumen["partidos"])

    # Estimar si sobra espacio en alguna columna para un grabado extra (ver
    # layout_estimate.py: viable porque la página fuerza un ancho de layout
    # fijo). Puramente decorativo — si la estimación se equivoca, el peor
    # caso es un hueco algo distinto del ideal, nunca un diseño roto.
    pairs = render._split_briefs(resumen["body"], payload_resumen["partidos"])
    has_side = pairs is not None and len(pairs) > 2
    widths = layout_estimate.column_widths(has_side)
    if pairs is not None:
        lead_paras = [t for _, t in pairs[:2]]
        side_paras_matches = [t for _, t in pairs[2:]]
    else:
        lead_paras, side_paras_matches = [resumen["body"]], []

    ex_side_paras, ex_note_paras = writer.split_explainer_paragraphs(explainer["body"])
    ex_top_zona, ex_top_val = grounding.explainer_best_zone(payload_explainer)
    ex_headline_text = f'El modelo da al {team["name"]} un {pct(ex_top_val)} de {ex_top_zona.lower()}'

    exp_h = layout_estimate.explainer_height(ex_headline_text, ex_side_paras, widths["explainer"])
    main_h = layout_estimate.main_height(headline, subtitle, lead_paras, ex_note_paras, widths["main"])
    side_h = layout_estimate.side_height(side_paras_matches, widths["side"]) if has_side else 0
    fillers = layout_estimate.plan_fillers(exp_h, main_h, side_h, has_side)

    html = render.render_broadsheet(
        payload_resumen, resumen["body"], payload_explainer, explainer["body"],
        fecha=today, league_logo=snap.get("league_logo"),
        headline=headline, subtitle=subtitle,
        explainer_filler_h=fillers.get("explainer"), side_filler_h=fillers.get("side"),
    )
    _write_atomic(ARTICLES_OUT_DIR / f"{render.slug_for(today)}.html", html)
    _write_sitemap()
    _write_latest_pointer(today, headline)
    print(f"hypermotion: publicado {render.url_for(today)}")

    _notify_telegram(headline, _pick_tweet_cta(today), SITE + render.url_for(today))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="No llama a Gemini ni escribe, solo informa")
    ap.add_argument("--date", help="YYYY-MM-DD — relanzar un día concreto en vez de 'hoy' (backfill manual)")
    ap.add_argument("--matches-only", action="store_true",
                     help="Solo crónicas de partido (cron frecuente); sin resumen diario ni explicador")
    args = ap.parse_args(argv)
    try:
        if args.matches_only:
            return _run_matches_only(args.dry_run, date_override=args.date)
        return _run(args.dry_run, date_override=args.date)
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        if not args.dry_run:
            notify.send_alert(
                "[PredictMotion] articles.generate cayó con una excepción",
                f"El cron del broadsheet de Hypermotion abortó con una excepción:\n\n{tb}",
                dedup_key="articles_generate_crash",
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
