"""Orquestador de los artículos: previa diaria, resumen diario, crónica de
partido y dato curioso, para cada liga en articles.config.ARTICLE_LEAGUES.

CUATRO entry points/cron (ver CLAUDE.md), todos disparando cada hora (o cada
5 min) en UTC — CRON_TZ no se aplica en /etc/cron.d en este servidor, así que
cada script filtra por hora de Madrid él mismo:
- `--matches-only`, cada 5 min: publica la crónica de cada partido
  terminado hoy NADA MÁS TERMINAR (no espera a las 23:59).
- `--previa-only`, filtra la hora PREVIEW_LOCAL_HOUR (8) de Madrid: la
  previa del día, con TODOS los partidos programados hoy y su 1X2 según el
  modelo, antes de que empiecen.
- `--stat-only`, filtra STAT_ARTICLE_HOURS (10-22h cada 2h) de Madrid: el
  dato curioso de la franja.
- sin flags, filtra la hora 23 de Madrid: el resumen diario + explicador de
  siempre, Y ADEMÁS vuelve a pasar por los partidos del día como red de
  seguridad (si el cron frecuente se perdió alguno por lo que sea).

Todos los caminos que publican una crónica de partido llaman a `_run_match`,
que es idempotente (`_match_already_handled`): si el partido ya tiene HTML
publicado o ya quedó en cuarentena, no vuelve a gastar Gemini en él. La
previa y el resumen tienen su propio guard equivalente
(`_previa_already_handled`/`_resumen_already_handled`).

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
    python -m articles.generate                  # resumen diario (hora 23 Madrid) + red de seguridad
    python -m articles.generate --previa-only     # previa diaria (hora 8 Madrid)
    python -m articles.generate --matches-only    # solo crónicas de partido (cron frecuente)
    python -m articles.generate --stat-only       # dato curioso (cron cada hora, filtra 10-22h Madrid)
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
from .gemini_client import GeminiError
from .config import (ARTICLE_LEAGUES, ARTICLES_OUT_DIR, DATA_DIR, PREVIEW_LOCAL_HOUR,
                     STAT_ARTICLE_HOURS, STAT_KINDS)

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
    cualquier liga), para que el feed /kiosco pueda destacarlo sin hardcodear
    una fecha en un HTML estático. Un solo puntero global (no por liga): el
    frontend ya deriva la liga del propio slug de la URL, así que solo hace
    falta el más reciente — con varias ligas, cada una lo sobrescribe al
    publicar, y el feed enseña el último broadsheet publicado en el sitio,
    no uno fijo por liga."""
    path = DATA_DIR / "articles" / "latest.json"
    _write_atomic(path, json.dumps(
        {"url": render.url_for(league_slug, fecha), "title": title, "fecha": fecha}, ensure_ascii=False))


_DIARIO_SLUG_RE = re.compile(r"^(?P<liga>[a-z0-9]+)-resumen-(?P<fecha>\d{4}-\d{2}-\d{2})$")
_PREVIA_SLUG_RE = re.compile(r"^(?P<liga>[a-z0-9]+)-previa-(?P<fecha>\d{4}-\d{2}-\d{2})$")
_DATO_SLUG_RE = re.compile(
    r"^(?P<liga>[a-z0-9]+)-dato-(?P<kind>" + "|".join(re.escape(k) for k in STAT_KINDS)
    + r")-(?P<fecha>\d{4}-\d{2}-\d{2})-\d{2}$")
_MATCH_SLUG_RE = re.compile(r"^(?P<liga>[a-z0-9]+)-.+-(?P<fecha>\d{4}-\d{2}-\d{2})$")
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_STAT_KINDS_STATE_PATH = DATA_DIR / "articles" / "stat_kinds_used.json"


def _article_meta_from_file(path):
    """(tipo, liga, fecha, title) a partir del NOMBRE del fichero (patrón de
    slug, ver render.py:slug_for/slug_for_match/slug_for_stat) y su <title>.
    None si el nombre no encaja con ningún patrón conocido (p.ej. restos de
    un sistema anterior) o su liga no está en ARTICLE_LEAGUES."""
    stem = path.stem
    for tipo, rx in (("diario", _DIARIO_SLUG_RE), ("previa", _PREVIA_SLUG_RE), ("dato", _DATO_SLUG_RE)):
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
        except Exception as e:
            # Igual que en main(): un timeout o un 429 se reintenta solo en la
            # pasada de dentro de 5 min (_run_match es idempotente por
            # _match_already_handled), así que no merece alerta.
            if isinstance(e, GeminiError) and e.transient:
                print(f"[SKIP] {league_slug} crónica: {e}", file=sys.stderr)
                continue
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


def _load_stat_kinds_state():
    if _STAT_KINDS_STATE_PATH.exists():
        return json.loads(_STAT_KINDS_STATE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_stat_kinds_state(state):
    _STAT_KINDS_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(_STAT_KINDS_STATE_PATH, json.dumps(state, ensure_ascii=False, indent=1))


def _snapshot_jornada_for_date(league_slug, fecha):
    """Devuelve (season, jornada) del snapshot diario de `fecha` para la liga,
    o (None, None) si no se encuentra. Usado para reconstruir self-healing el
    registro de kinds usados por jornada."""
    from seo.snapshots import load_all
    seasons_dir = DATA_DIR / league_slug
    if not seasons_dir.exists():
        return None, None
    for season_dir in seasons_dir.iterdir():
        if not season_dir.is_dir() or not (season_dir / "snapshots").exists():
            continue
        for s in load_all(league_slug, season_dir.name):
            if s.get("date") == fecha:
                return season_dir.name, s.get("jornada")
    return None, None


def _rebuild_stat_kinds_state(league_slug):
    """Reconstruye el registro de kinds usados por jornada a partir de los
    artículos publicados (self-healing). Así no hace falta mantener un estado
    propio: si se pierde el JSON, se regenera escaneando los HTML y los
    snapshots diarios."""
    state = _load_stat_kinds_state()
    league_state = {}
    for path in ARTICLES_OUT_DIR.glob(f"{league_slug}-dato-*.html"):
        m = _DATO_SLUG_RE.match(path.stem)
        if not m:
            continue
        kind, fecha = m.group("kind"), m.group("fecha")
        season, jornada = _snapshot_jornada_for_date(league_slug, fecha)
        if season is None or jornada is None:
            continue
        key = f"{season}|{jornada}"
        league_state.setdefault(key, [])
        if kind not in league_state[key]:
            league_state[key].append(kind)
    state[league_slug] = league_state
    _save_stat_kinds_state(state)
    return league_state


def _stat_kinds_used_for_matchday(league_slug, season, jornada):
    """Kinds ya usados para esta liga+temporada+jornada. Carga el estado y,
    si no existe la entrada de la liga, lo reconstruye desde los artículos
    publicados."""
    state = _load_stat_kinds_state()
    league_state = state.get(league_slug)
    if league_state is None:
        league_state = _rebuild_stat_kinds_state(league_slug)
    key = f"{season}|{jornada}"
    return league_state.get(key, [])


def _run_stat(league_slug, dry_run, date_override=None):
    """Entry point del cron de "dato curioso" (cada 2h, 10:00-22:00 hora de
    España -> 7 al día, ver CLAUDE.md y STAT_ARTICLE_HOURS). Un artículo
    corto sobre un dato que el modelo/snapshot ya calcula pero que no
    aparece en ningún dashboard (ver STAT_KINDS en config.py). El kind base lo
    elige grounding.pick_stat_kind(hour, day), pero se evitan los kinds ya
    usados en la misma jornada de competición (season+jornada) para que los
    artículos de una jornada no repitan tipo. El registro de kinds usados se
    deriva de los artículos publicados (self-healing). Best-effort igual que el
    resto: si el grounding marca alguno de los 2 textos, no se publica y se
    avisa por email."""
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
    season = snap.get("season")
    jornada = snap.get("jornada")
    used = _stat_kinds_used_for_matchday(league_slug, season, jornada)
    kind = grounding.pick_stat_kind(hour, day=day, used=used)
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

    # Registrar el kind como usado para esta jornada, para que la siguiente
    # franja horaria de la misma jornada deportiva no repita el mismo tipo.
    if season is not None and jornada is not None:
        state = _load_stat_kinds_state()
        league_state = state.setdefault(league_slug, {})
        key = f"{season}|{jornada}"
        kinds_used = league_state.setdefault(key, [])
        if kind not in kinds_used:
            kinds_used.append(kind)
            _save_stat_kinds_state(state)

    flag_id = _stat_flag_id(league_slug, fecha, hour, kind)
    _notify_telegram(league_slug, headline, _pick_tweet_cta(flag_id), SITE + article_url)
    return 0


def _resumen_already_handled(league_slug, today):
    """Mismo criterio que _match_already_handled/_stat_already_handled: sin
    estado propio, mira si ya existe el HTML publicado o un registro de
    cuarentena para hoy (el cron ahora dispara cada hora, así que dos
    disparos dentro de la misma hora 23 Madrid no duplican ni gastan Gemini
    de más). Comprueba los kinds de cuarentena por su nombre exacto, no con
    un glob "*" — un "*" habría confundido la previa diaria (cuarentena
    "previa"/"previa-explicador" del mismo día) con el resumen."""
    slug = render.slug_for(league_slug, today)
    if (ARTICLES_OUT_DIR / f"{slug}.html").exists():
        return True
    return any((_FLAGGED_DIR / f"{league_slug}-{k}-{today}.json").exists()
               for k in ("resumen", "explicador"))


def _previa_already_handled(league_slug, today):
    """Mismo criterio que _resumen_already_handled, para la previa diaria."""
    slug = render.slug_for_previa(league_slug, today)
    if (ARTICLES_OUT_DIR / f"{slug}.html").exists():
        return True
    return any((_FLAGGED_DIR / f"{league_slug}-{k}-{today}.json").exists()
               for k in ("previa", "previa-explicador"))


def _pick_preview_team_id(partidos):
    """Equipo foco del explicador de la previa: el mayor favorito del día
    (el lado con el 1X2 más alto de cualquier partido) — sin Gemini, mismo
    criterio determinista que _pick_highlight_team_id (resumen diario) pero
    por favoritismo en vez de por cambio de probabilidad (aquí no hay
    'antes/después' porque el partido no se ha jugado)."""
    best_match = max(partidos, key=lambda m: max(m["p_local"], m["p_visita"]))
    if best_match["p_local"] >= best_match["p_visita"]:
        return best_match["local"]["id"]
    return best_match["visitante"]["id"]


def _run_previa(league_slug, dry_run, date_override=None):
    """Entry point de la previa diaria (cron cada hora en UTC, publica solo
    en la hora PREVIEW_LOCAL_HOUR de Madrid — mismo motivo/patrón que _run,
    ver CLAUDE.md): un artículo por liga con TODOS los partidos programados
    hoy y su 1X2 según el modelo, antes de que empiecen."""
    league = league_by_slug(league_slug)
    snap = grounding.load_snapshot(league_slug)
    if not snap:
        print(f"{league_slug}: sin snapshot (offseason o el cron SEO no ha corrido aún)")
        return 0

    now = datetime.now(_MADRID_TZ)
    if date_override is None and now.hour != PREVIEW_LOCAL_HOUR:
        return 0
    today = date_override or now.strftime("%Y-%m-%d")
    if _previa_already_handled(league_slug, today):
        return 0
    compact = today.replace("-", "")
    events = espn.fetch_scoreboard_range(league["espn_code"], compact, compact)
    scheduled = [e for e in events if e["state"] == "pre"]
    if not scheduled:
        print(f"{league_slug}: sin partidos programados hoy ({today})")
        return 0

    payload_preview = grounding.ground_previa_diaria(league, snap, scheduled)
    if not payload_preview["partidos"]:
        print(f"{league_slug}: partidos de hoy sin equipo resoluble en el snapshot")
        return 0

    team_id = _pick_preview_team_id(payload_preview["partidos"])
    team = grounding.team_by_id(snap, team_id)
    payload_explainer = grounding.ground_explainer(league, snap, team)

    if dry_run:
        print(f"{league_slug}: publicaría {render.slug_for_previa(league_slug, today)} "
              f"({len(payload_preview['partidos'])} partidos, explicador: {team['name']})")
        return 0

    preview = writer.write_article(payload_preview)
    explainer = writer.write_article(payload_explainer)

    if preview["status"] != "draft" or explainer["status"] != "draft":
        if preview["status"] != "draft":
            _save_flagged(league_slug, today, "previa", payload_preview, preview)
        if explainer["status"] != "draft":
            _save_flagged(league_slug, today, "previa-explicador", payload_explainer, explainer)
        bad = preview["flagged_values"] + explainer["flagged_values"]
        notify.send_alert(
            f"[PredictMotion] previa de {league['name']} sin publicar (grounding)",
            f"El texto generado por Gemini el {today} citaba cifras que no están en "
            f"los datos reales, así que no se publica: {bad}\n\n"
            f"Detalle en {_FLAGGED_DIR}/{league_slug}-previa*-{today}.json (en el servidor).",
            dedup_key=f"articles_previa_flagged_{league_slug}",
        )
        return 1

    catchy = writer.write_preview_headline(payload_preview)
    if catchy:
        headline, subtitle = catchy
    else:
        print(f"{league_slug}: titular llamativo no disponible, cae al determinista")
        headline = preview["title"].replace(" | PredictMotion", "")
        subtitle = preview["meta_description"]

    pairs = render._split_briefs(preview["body"], payload_preview["partidos"])
    has_side = pairs is not None and len(pairs) > 2
    widths = layout_estimate.column_widths(has_side)
    if pairs is not None:
        lead_paras = [t for _, t in pairs[:2]]
        side_paras_matches = [t for _, t in pairs[2:]]
    else:
        lead_paras, side_paras_matches = [preview["body"]], []

    ex_side_paras, ex_note_paras = writer.split_explainer_paragraphs(explainer["body"])
    ex_top_zona, ex_top_val = grounding.explainer_best_zone(payload_explainer)
    ex_headline_text = f'El modelo da al {team["name"]} un {pct(ex_top_val)} de {ex_top_zona.lower()}'

    exp_h = layout_estimate.explainer_height(ex_headline_text, ex_side_paras, widths["explainer"])
    main_h = layout_estimate.main_height(headline, subtitle, lead_paras, ex_note_paras, widths["main"])
    side_h = layout_estimate.side_height(side_paras_matches, widths["side"]) if has_side else 0
    fillers = layout_estimate.plan_fillers(exp_h, main_h, side_h, has_side)

    html = render.render_previa_broadsheet(
        payload_preview, preview["body"], payload_explainer, explainer["body"],
        league_slug=league_slug, fecha=today, league_logo=snap.get("league_logo"),
        headline=headline, subtitle=subtitle,
        explainer_filler_h=fillers.get("explainer"), side_filler_h=fillers.get("side"),
    )
    _write_atomic(ARTICLES_OUT_DIR / f"{render.slug_for_previa(league_slug, today)}.html", html)
    _write_sitemap()
    _write_articles_index()
    print(f"{league_slug}: publicado {render.url_for_previa(league_slug, today)}")

    _notify_telegram(league_slug, headline, _pick_tweet_cta(f"{league_slug}|previa|{today}"),
                      SITE + render.url_for_previa(league_slug, today))
    return 0


def _run(league_slug, dry_run, date_override=None):
    league = league_by_slug(league_slug)
    snap = grounding.load_snapshot(league_slug)
    if not snap:
        print(f"{league_slug}: sin snapshot (offseason o el cron SEO no ha corrido aún)")
        return 0

    # El cron dispara cada hora en UTC (CRON_TZ no se aplica en /etc/cron.d,
    # mismo gotcha que STAT_ARTICLE_HOURS): ejecuta solo en la hora 23 de
    # Madrid, para que "hoy" siga siendo el día natural de los partidos que
    # se acaban de jugar. Sin esto, a las 23:59 UTC son ya las 01:59 Madrid
    # del día siguiente y "hoy" rueda antes de que el día tenga partidos
    # terminados (incidente 2026-08-22: el resumen de Betis-Sociedad no
    # salió porque "hoy" ya era el día siguiente). --date bypassa la
    # guardia: es para relanzar a mano un día concreto.
    now = datetime.now(_MADRID_TZ)
    if date_override is None and now.hour != 23:
        return 0
    today = date_override or now.strftime("%Y-%m-%d")
    if _resumen_already_handled(league_slug, today):
        return 0
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
                     help="Solo el dato curioso de la franja (cron cada hora UTC, filtra 10-22h Madrid); sin resumen ni crónicas")
    ap.add_argument("--previa-only", action="store_true",
                     help="Solo la previa diaria (cron cada hora UTC, filtra la hora PREVIEW_LOCAL_HOUR de Madrid); sin resumen ni crónicas")
    ap.add_argument("--league", choices=ARTICLE_LEAGUES, help="Solo esta liga (por defecto, todas ARTICLE_LEAGUES)")
    args = ap.parse_args(argv)
    rc = 0
    for league_slug in ([args.league] if args.league else ARTICLE_LEAGUES):
        try:
            if args.matches_only:
                rc |= _run_matches_only(league_slug, args.dry_run, date_override=args.date)
            elif args.stat_only:
                rc |= _run_stat(league_slug, args.dry_run, date_override=args.date)
            elif args.previa_only:
                rc |= _run_previa(league_slug, args.dry_run, date_override=args.date)
            else:
                rc |= _run(league_slug, args.dry_run, date_override=args.date)
        except Exception as e:
            # Timeout / 429 / corte de red: el artículo de esta pasada no sale,
            # pero el cron vuelve en 5 min (crónicas) o en 1 h (dato y previa) y
            # lo reintenta. No es una incidencia: al log y a la siguiente liga,
            # sin email. Antes esto abortaba la liga Y mandaba alerta.
            if isinstance(e, GeminiError) and e.transient:
                print(f"[SKIP] {league_slug}: {e}", file=sys.stderr)
                continue
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
