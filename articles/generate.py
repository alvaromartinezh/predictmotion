"""Orquestador de los artículos: el resumen diario y la crónica de partido,
para cada liga en articles.config.ARTICLE_LEAGUES.

DOS entry points/cron (ver CLAUDE.md):
- `--matches-only`, cada 5 min: publica la crónica de cada partido
  terminado hoy NADA MÁS TERMINAR (no espera a las 23:59).
- sin flags, a las 23:59 hora de España: el resumen diario + explicador de
  siempre, Y ADEMÁS vuelve a pasar por los partidos del día como red de
  seguridad (si el cron frecuente se perdió alguno por lo que sea). Ambos
  caminos llaman a `_run_match`, que es idempotente
  (`_match_already_handled`): si el partido ya tiene HTML publicado o ya
  quedó en cuarentena, no vuelve a gastar Gemini en él.

`main()` itera ARTICLE_LEAGUES y aísla los fallos por liga (una excepción o
un grounding fallido en una liga no bloquea a las demás) — mismo criterio
que `_run_finished_matches` aísla por partido.

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
import re
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
from .config import ARTICLE_LEAGUES, ARTICLES_OUT_DIR, DATA_DIR, STAT_ARTICLE_HOURS, STAT_KINDS

_MADRID_TZ = ZoneInfo("Europe/Madrid")
_FLAGGED_DIR = DATA_DIR / "articles_flagged"

# Frase que anima a entrar al artículo, para el tweet — a propósito SIN
# Gemini (el titular ya lleva un porcentaje real, ver writer._HEADLINE_INSTR/
# _MATCH_HEADLINE_INSTR, pero esta línea sigue aportando la invitación a
# entrar a ver el resto — "el análisis completo", no solo esa cifra suelta).
# Elegida a mano, determinista por clave (mismo patrón que illustration.pick
# — liga+fecha para el resumen diario, _match_flag_id(league_slug, payload)
# para cada crónica de partido, así dos artículos del mismo día no repiten
# frase) para que no haga falta gastar una llamada a Gemini ni validarla —
# es solo una invitación a hacer clic, no un dato.
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


def _save_flagged(league_slug, fecha, kind, payload, article):
    _FLAGGED_DIR.mkdir(parents=True, exist_ok=True)
    path = _FLAGGED_DIR / f"{league_slug}-{kind}-{fecha}.json"
    path.write_text(json.dumps({"payload": payload, **article}, ensure_ascii=False, indent=1), encoding="utf-8")


def _write_latest_pointer(league_slug, fecha, title):
    """data/articles/latest.json: puntero al broadsheet más reciente (de
    cualquier liga), para que /noticias pueda enlazarlo sin hardcodear una
    fecha en un HTML estático. Un solo puntero global (no por liga): el
    frontend (noticias.html) ya deriva la liga del propio slug de la URL, así
    que solo hace falta el más reciente — con varias ligas, cada una lo
    sobrescribe al publicar, y la tarjeta de /noticias enseña el último
    broadsheet publicado en el sitio, no uno fijo por liga."""
    path = DATA_DIR / "articles" / "latest.json"
    _write_atomic(path, json.dumps(
        {"url": render.url_for(league_slug, fecha), "title": title, "fecha": fecha}, ensure_ascii=False))


_DIARIO_SLUG_RE = re.compile(r"^(?P<liga>[a-z0-9]+)-resumen-(?P<fecha>\d{4}-\d{2}-\d{2})$")
_DATO_SLUG_RE = re.compile(
    r"^(?P<liga>[a-z0-9]+)-dato-(?:" + "|".join(re.escape(k) for k in STAT_KINDS)
    + r")-(?P<fecha>\d{4}-\d{2}-\d{2})-\d{2}$")
_MATCH_SLUG_RE = re.compile(r"^(?P<liga>[a-z0-9]+)-.+-(?P<fecha>\d{4}-\d{2}-\d{2})$")
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)


def _article_meta_from_file(path):
    """(tipo, liga, fecha, title) a partir del NOMBRE del fichero (patrón de
    slug, ver render.py:slug_for/slug_for_match/slug_for_stat) y su <title>.
    None si el nombre no encaja con ningún patrón conocido (p.ej. restos de
    un sistema anterior) o su liga no está en ARTICLE_LEAGUES."""
    stem = path.stem
    for tipo, rx in (("diario", _DIARIO_SLUG_RE), ("dato", _DATO_SLUG_RE)):
        m = rx.match(stem)
        if m:
            break
    else:
        # Crónica de partido: <liga>-<local>-<visitante>-<fecha> — los slugs
        # de equipo no tienen un patrón fijo, así que se detecta por
        # eliminación (no es diario ni dato, pero sí liga+fecha conocidas).
        m = _MATCH_SLUG_RE.match(stem)
        tipo = "partido"
    if not m or m.group("liga") not in ARTICLE_LEAGUES:
        return None
    title_m = _TITLE_RE.search(path.read_text(encoding="utf-8"))
    title = (title_m.group(1) if title_m else stem).replace(" | PredictMotion", "")
    return tipo, m.group("liga"), m.group("fecha"), title


def _write_articles_index():
    """data/articles/index.json: TODOS los artículos publicados (diario/
    partido/dato), para que /kiosco (assets/articles.js) los liste y filtre
    por tipo. Self-healing — igual que _write_sitemap: se reconstruye entero
    escaneando articulos/*.html, sin estado propio que pueda desincronizarse
    (un artículo publicado antes de que existiera este índice, o cualquiera
    republicado a mano, aparece igual sin necesitar un backfill)."""
    items = []
    for path in ARTICLES_OUT_DIR.glob("*.html"):
        meta = _article_meta_from_file(path)
        if not meta:
            continue
        tipo, liga, fecha, title = meta
        items.append({"slug": path.stem, "tipo": tipo, "liga": liga, "title": title,
                      "url": f"/articulos/{path.stem}", "fecha": fecha})
    items.sort(key=lambda it: (it["fecha"], it["slug"]), reverse=True)
    _write_atomic(DATA_DIR / "articles" / "index.json", json.dumps(items[:300], ensure_ascii=False))


def _notify_telegram(league_slug, headline, cta, article_url):
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
        print(f"{league_slug}: sin TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID, no se avisa a Telegram")
        return
    tweet_text = f"{headline}\n{cta}\n{article_url}"
    if not _tg_send_message(chat_id, _caption(tweet_text)):
        print(f"{league_slug}: aviso a Telegram no confirmado", file=sys.stderr)


def _match_flag_id(league_slug, payload):
    l, v = payload["local"], payload["visitante"]
    return f'{league_slug}-{payload["fecha"]}-{l["id"]}-{v["id"]}'


def _match_already_handled(league_slug, payload):
    """True si este partido ya tiene HTML publicado o ya quedó en
    cuarentena (grounding fallido) en un intento anterior. Sin estado propio
    que mantener (mismo criterio self-healing que _write_sitemap): con DOS
    caminos llamando a _run_match (el cron frecuente y la red de seguridad
    de las 23:59), esto evita generar dos veces el mismo partido y gastar
    Gemini de más."""
    l, v = payload["local"], payload["visitante"]
    slug = render.slug_for_match(league_slug, payload["fecha"], l["nombre"], v["nombre"])
    if (ARTICLES_OUT_DIR / f"{slug}.html").exists():
        return True
    flag_id = _match_flag_id(league_slug, payload)
    return any(_FLAGGED_DIR.glob(f"{league_slug}-match-*-{flag_id}.json"))


def _run_match(league, snap, match, dry_run):
    """Crónica de UN partido terminado (broadsheet de partido, ver
    render.render_match_broadsheet). Best-effort igual que el resumen diario:
    si el grounding marca alguno de los 3 textos, no se publica y se avisa;
    el llamador (_run_finished_matches) además aísla las excepciones por
    partido para que una jornada de varios partidos no se caiga entera por
    uno."""
    league_slug = league["slug"]
    payload = grounding.ground_match(league, snap, match)
    if not payload:
        return 0
    l, v = payload["local"], payload["visitante"]

    if _match_already_handled(league_slug, payload):
        return 0

    if dry_run:
        print(f"{league_slug}: publicaría crónica "
              f"{render.slug_for_match(league_slug, payload['fecha'], l['nombre'], v['nombre'])}")
        return 0

    results = {
        "local": writer.write_article(dict(payload, tipo="match_local")),
        "visitante": writer.write_article(dict(payload, tipo="match_visitante")),
        "cronica": writer.write_article(dict(payload, tipo="match_cronica")),
    }
    if any(r["status"] != "draft" for r in results.values()):
        flag_id = _match_flag_id(league_slug, payload)
        bad = []
        for key, r in results.items():
            if r["status"] != "draft":
                _save_flagged(league_slug, flag_id, f"match-{key}", payload, r)
                bad += r["flagged_values"]
        notify.send_alert(
            f"[PredictMotion] crónica de partido de {league['name']} sin publicar (grounding)",
            f"El texto generado por Gemini para {l['nombre']} {payload['resultado']['local']}-"
            f"{payload['resultado']['visitante']} {v['nombre']} ({payload['fecha']}) citaba cifras "
            f"que no están en los datos reales, así que no se publica: {bad}\n\n"
            f"Detalle en {_FLAGGED_DIR}/{league_slug}-match-*-{flag_id}.json (en el servidor).",
            dedup_key=f"articles_match_flagged_{league_slug}",
        )
        return 1

    catchy = writer.write_match_headline(dict(payload, tipo="match_cronica"))
    if catchy:
        headline, teaser = catchy
    else:
        print(f"{league_slug}: titular de partido no disponible ({l['nombre']}-{v['nombre']}), cae al determinista")
        headline = f'{l["nombre"]} {payload["resultado"]["local"]}-{payload["resultado"]["visitante"]} {v["nombre"]}'
        teaser = results["cronica"]["meta_description"]

    html = render.render_match_broadsheet(
        payload, results["local"]["body"], results["visitante"]["body"], results["cronica"]["body"],
        league_slug=league_slug, headline=headline, teaser=teaser, league_logo=snap.get("league_logo"),
    )
    slug = render.slug_for_match(league_slug, payload["fecha"], l["nombre"], v["nombre"])
    _write_atomic(ARTICLES_OUT_DIR / f"{slug}.html", html)
    article_url = render.url_for_match(league_slug, payload["fecha"], l["nombre"], v["nombre"])
    print(f"{league_slug}: publicado {article_url}")

    flag_id = _match_flag_id(league_slug, payload)
    _notify_telegram(league_slug, headline, _pick_tweet_cta(flag_id), SITE + article_url)
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
    league_slug = league["slug"]
    for m in finished:
        try:
            _run_match(league, snap, m, dry_run)
        except Exception:
            tb = traceback.format_exc()
            print(tb, file=sys.stderr)
            if not dry_run:
                notify.send_alert(
                    f"[PredictMotion] crónica de partido de {league['name']} cayó con una excepción",
                    f"Partido {m.get('home', {}).get('name')}-{m.get('away', {}).get('name')} "
                    f"({today}) abortó con una excepción:\n\n{tb}",
                    dedup_key=f"articles_match_crash_{league_slug}",
                )


def _run_matches_only(league_slug, dry_run, date_override=None):
    """Entry point del cron frecuente (cada 5 min, ver CLAUDE.md): publica la
    crónica de cada partido de esta liga nada más terminar, en vez de
    esperar al resumen diario de las 23:59. Sin resumen ni explicador —
    _run_match es idempotente (_match_already_handled), así que no importa
    si esta pasada y la red de seguridad de las 23:59 se solapan."""
    league = league_by_slug(league_slug)
    snap = grounding.load_snapshot(league_slug)
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
        _write_articles_index()
    return 0


def _stat_flag_id(league_slug, fecha, hour, kind):
    return f"{league_slug}-{fecha}-{hour:02d}-{kind}"


def _stat_already_handled(league_slug, fecha, hour, kind):
    """Mismo criterio que _match_already_handled: sin estado propio, mira si
    ya existe el HTML publicado o un registro de cuarentena para esta franja
    (liga+fecha+hora+kind ya determina el slug, así que dos disparos del
    mismo cron en la misma hora no duplican ni gastan Gemini de más)."""
    slug = render.slug_for_stat(league_slug, fecha, hour, kind)
    if (ARTICLES_OUT_DIR / f"{slug}.html").exists():
        return True
    flag_id = _stat_flag_id(league_slug, fecha, hour, kind)
    return any(_FLAGGED_DIR.glob(f"{league_slug}-stat-*-{flag_id}.json"))


def _run_stat(league_slug, dry_run, date_override=None):
    """Entry point del cron de "dato curioso" (cada 2h, 10:00-20:00 hora de
    España -> 6 al día, ver CLAUDE.md y STAT_ARTICLE_HOURS). Un artículo
    corto sobre un dato que el modelo/snapshot ya calcula pero que no
    aparece en ningún dashboard (ver STAT_KINDS en config.py). El kind lo
    elige grounding.pick_stat_kind(hour, day) — determinista, sin estado que
    mantener: con 7 kinds y 6 franjas por día, el offset del día (YYYYMMDD)
    desplaza la rotación para que cada franja del día siguiente caiga en un
    kind distinto y ningún kind quede sistemáticamente fuera. Best-effort
    igual que el resto: si el grounding marca alguno de los 2 textos, no se
    publica y se avisa por email."""
    league = league_by_slug(league_slug)
    now = datetime.now(_MADRID_TZ)
    hour = now.hour
    if hour not in STAT_ARTICLE_HOURS:
        return 0  # defensa en profundidad: el cron ya solo dispara 10-20h/2
    snap = grounding.load_snapshot(league_slug)
    if not snap:
        return 0
    fecha = date_override or now.strftime("%Y-%m-%d")
    day = int(fecha.replace("-", ""))
    kind = grounding.pick_stat_kind(hour, day=day)
    payload = grounding.ground_stat(league, snap, kind, fecha, hour)
    if not payload:
        print(f"{league_slug}: sin datos suficientes para el dato curioso ({kind})")
        return 0

    if _stat_already_handled(league_slug, fecha, hour, kind):
        return 0

    if dry_run:
        print(f"{league_slug}: publicaría dato curioso {render.slug_for_stat(league_slug, fecha, hour, kind)}")
        return 0

    results = {
        "protagonista": writer.write_article(dict(payload, tipo=f"dato_{kind}_protagonista")),
        "perseguidores": writer.write_article(dict(payload, tipo=f"dato_{kind}_perseguidores")),
    }
    if any(r["status"] != "draft" for r in results.values()):
        flag_id = _stat_flag_id(league_slug, fecha, hour, kind)
        bad = []
        for key, r in results.items():
            if r["status"] != "draft":
                _save_flagged(league_slug, flag_id, f"stat-{key}", payload, r)
                bad += r["flagged_values"]
        notify.send_alert(
            f"[PredictMotion] dato curioso de {league['name']} sin publicar (grounding)",
            f"El texto generado por Gemini para el dato '{kind}' del {fecha} {hour:02d}h citaba "
            f"cifras que no están en los datos reales, así que no se publica: {bad}\n\n"
            f"Detalle en {_FLAGGED_DIR}/{league_slug}-stat-*-{flag_id}.json (en el servidor).",
            dedup_key=f"articles_stat_flagged_{league_slug}",
        )
        return 1

    catchy = writer.write_stat_headline(payload)
    if catchy:
        headline, teaser = catchy
    else:
        print(f"{league_slug}: titular de dato curioso no disponible, cae al determinista")
        p = payload["protagonista"]
        headline = f'{p["nombre"]}, el más cerca de {payload["dato_verbo"]} en {payload["liga"]}'
        teaser = results["protagonista"]["meta_description"]

    html = render.render_stat_broadsheet(
        payload, results["protagonista"]["body"], results["perseguidores"]["body"],
        league_slug=league_slug, headline=headline, teaser=teaser, league_logo=snap.get("league_logo"),
    )
    slug = render.slug_for_stat(league_slug, fecha, hour, kind)
    _write_atomic(ARTICLES_OUT_DIR / f"{slug}.html", html)
    article_url = render.url_for_stat(league_slug, fecha, hour, kind)
    print(f"{league_slug}: publicado {article_url}")
    _write_sitemap()
    _write_articles_index()

    flag_id = _stat_flag_id(league_slug, fecha, hour, kind)
    _notify_telegram(league_slug, headline, _pick_tweet_cta(flag_id), SITE + article_url)
    return 0


def _run(league_slug, dry_run, date_override=None):
    league = league_by_slug(league_slug)
    snap = grounding.load_snapshot(league_slug)
    if not snap:
        print(f"{league_slug}: sin snapshot (offseason o el cron SEO no ha corrido aún)")
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
        print(f"{league_slug}: sin partidos terminados hoy ({today})")
        return 0

    payload_resumen = grounding.ground_resumen_diario(league, snap, finished)
    if not payload_resumen["partidos"]:
        print(f"{league_slug}: partidos de hoy sin equipo resoluble en el snapshot")
        return 0

    # Red de seguridad: por si el cron frecuente (--matches-only) se perdió
    # algún partido. _run_match es idempotente, así que esto es gratis si ya
    # están todos publicados.
    _run_finished_matches(league, snap, finished, today, dry_run)

    team_id = _pick_highlight_team_id(payload_resumen["partidos"])
    team = grounding.team_by_id(snap, team_id)
    payload_explainer = grounding.ground_explainer(league, snap, team)

    if dry_run:
        print(f"{league_slug}: publicaría {render.slug_for(league_slug, today)} "
              f"({len(payload_resumen['partidos'])} partidos, explicador: {team['name']})")
        return 0

    resumen = writer.write_article(payload_resumen)
    explainer = writer.write_article(payload_explainer)

    if resumen["status"] != "draft" or explainer["status"] != "draft":
        if resumen["status"] != "draft":
            _save_flagged(league_slug, today, "resumen", payload_resumen, resumen)
        if explainer["status"] != "draft":
            _save_flagged(league_slug, today, "explicador", payload_explainer, explainer)
        bad = resumen["flagged_values"] + explainer["flagged_values"]
        notify.send_alert(
            f"[PredictMotion] broadsheet de {league['name']} sin publicar (grounding)",
            f"El texto generado por Gemini el {today} citaba cifras que no están en "
            f"los datos reales, así que no se publica: {bad}\n\n"
            f"Detalle en {_FLAGGED_DIR}/{league_slug}-*-{today}.json (en el servidor).",
            dedup_key=f"articles_flagged_{league_slug}",
        )
        return 1

    # Titular+subtítulo "llamativos" (a petición expresa) — best-effort: si
    # Gemini falla el formato o cuela una cifra inventada, cae a la cabecera
    # determinista de siempre en vez de bloquear la publicación por esto.
    catchy = writer.write_headline(payload_resumen)
    if catchy:
        headline, subtitle = catchy
    else:
        print(f"{league_slug}: titular llamativo no disponible, cae al determinista")
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
        league_slug=league_slug, fecha=today, league_logo=snap.get("league_logo"),
        headline=headline, subtitle=subtitle,
        explainer_filler_h=fillers.get("explainer"), side_filler_h=fillers.get("side"),
    )
    _write_atomic(ARTICLES_OUT_DIR / f"{render.slug_for(league_slug, today)}.html", html)
    _write_sitemap()
    _write_articles_index()
    _write_latest_pointer(league_slug, today, headline)
    print(f"{league_slug}: publicado {render.url_for(league_slug, today)}")

    _notify_telegram(league_slug, headline, _pick_tweet_cta(f"{league_slug}|{today}"),
                      SITE + render.url_for(league_slug, today))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="No llama a Gemini ni escribe, solo informa")
    ap.add_argument("--date", help="YYYY-MM-DD — relanzar un día concreto en vez de 'hoy' (backfill manual)")
    ap.add_argument("--matches-only", action="store_true",
                     help="Solo crónicas de partido (cron frecuente); sin resumen diario ni explicador")
    ap.add_argument("--stat-only", action="store_true",
                     help="Solo el dato curioso de la franja (cron cada 2h, 10-20h); sin resumen ni crónicas")
    ap.add_argument("--league", choices=ARTICLE_LEAGUES, help="Solo esta liga (por defecto, todas ARTICLE_LEAGUES)")
    args = ap.parse_args(argv)
    rc = 0
    for league_slug in ([args.league] if args.league else ARTICLE_LEAGUES):
        try:
            if args.matches_only:
                rc |= _run_matches_only(league_slug, args.dry_run, date_override=args.date)
            elif args.stat_only:
                rc |= _run_stat(league_slug, args.dry_run, date_override=args.date)
            else:
                rc |= _run(league_slug, args.dry_run, date_override=args.date)
        except Exception:
            tb = traceback.format_exc()
            print(tb, file=sys.stderr)
            rc = 1
            if not args.dry_run:
                notify.send_alert(
                    f"[PredictMotion] articles.generate cayó con una excepción ({league_slug})",
                    f"El cron del broadsheet de {league_slug} abortó con una excepción:\n\n{tb}",
                    dedup_key=f"articles_generate_crash_{league_slug}",
                )
    return rc


if __name__ == "__main__":
    sys.exit(main())
