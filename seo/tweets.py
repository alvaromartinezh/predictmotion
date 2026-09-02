"""Tweets de inicio de jornada estilo solofichajes, vía Telegram.

Genera, al inicio de cada jornada, un tweet por zona de cada liga (top-6 con su
probabilidad + teaser + enlace al dashboard), acompañado de una "captura" PNG de
los datos, y lo manda al Telegram del dueño — que es quien lo sube a X/Twitter
manualmente (la API de X no se puede permitir: 0,20 €/tweet con enlace).

Ligas y zonas (de momento SOLO LaLiga y Hypermotion por decisión del dueño;
el resto de ligas del sitio está desactivado pero la infraestructura genérica
—zonas por plantilla, hashtags por liga, @ por equipo— queda lista para
reactivarlo en TWEET_LEAGUES):
  - laliga (LaLiga, 1ª): título, Champions, Europa League, Conference League,
    descenso.
  - hypermotion (Liga Hypermotion, 2ª): ascenso, ascenso directo,
    play-off de ascenso, descenso.

Datos: lee el precálculo del cron SEO `data/<slug>/latest.json` (NO simula).
Estado anti-duplicado (una vez por jornada y liga) en `data/tweets_state.json`.

Disparadores (todo dentro del cron, ver CLAUDE.md Principio 2):
  - Programado: lunes y jueves a las 23:59 (hora de España). Tuitea solo si la
    jornada está a punto de arrancar (hay partidos `pre` en los próximos 3 días)
    y esa (season, jornada) no se ha tuiteado ya.
  - Manual: comando `/tweet` (y `/tweet <liga>`) vía Telegram para jornadas
    partidas o reenvíos. `--poll` es el cron de comandos (getUpdates breve).
  - Botón inline: cada tweet enviado (y el mensaje de /start) lleva un teclado
    con un botón por liga activa ("⚽ Tweet <liga>"); al pulsarlo se regeneran
    los tuits de esa liga con las estadísticas del momento (callback_query que
    procesa el mismo `--poll`).

Robustez: best-effort. Sin credenciales de Telegram → no hace nada. Si algo
lanza, alerta por email (seo.notify) y no rompe el cron. Pillow es OPCIONAL
(solo para la imagen): sin él se manda el texto sin captura.

Credenciales (.env del servidor, gitignored): TELEGRAM_BOT_TOKEN,
TELEGRAM_CHAT_ID (el chat también se aprende solo en el primer /tweet).

Uso:
    python3 -m seo.tweets              # cron programado (lunes/jueves)
    python3 -m seo.tweets --poll       # cron de comandos (cada ~2 min)
    python3 -m seo.tweets --dry-run    # texto + imagen a data/tweets_preview/
    python3 -m seo.tweets --league laliga   # forzar una liga (manual)
"""

import argparse
import io
import json
import os
import re
import sys
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import espn, notify
from .config import DATA_DIR, SITE, league_by_slug

# Ligas sobre las que se tuitea. **Por decisión del dueño (2026-08-14) SOLO
# LaLiga y Hypermotion**: el resto de ligas del sitio quedan DESACTIVADAS de
# momento (la infraestructura genérica —zonas por plantilla, hashtags por liga,
# @ por equipo— ya está lista en este fichero para reactivarlas cuando se
# quiera: basta con volver a listarlas aquí).
TWEET_LEAGUES = ["hypermotion", "laliga"]

# Zonas por tipo de liga (claves de `prob` del snapshot, etiqueta corta del tweet):
#   top1 (1as europeas) → 5 tuits, igual que LaLiga.
#   top2/tier2 (2as)    → 4 tuits (ascenso + directo + play-off + descenso),
#                         igual que Hypermotion.
ZONES_TOP1 = [
    ("first", "Título"),
    ("champions", "Champions"),
    ("europa", "Europa League"),
    ("conference", "Conference League"),
    ("descenso", "Descenso"),
]
ZONES_TIER2 = [
    ("ascenso_total", "Ascenso"),
    ("ascenso", "Ascenso directo"),
    ("playoff", "Play-off de ascenso"),
    ("descenso", "Descenso"),
]


def _zones(slug):
    """Zonas a tuitear de una liga, según su plantilla de dashboard."""
    lg = league_by_slug(slug)
    if not lg:
        return []
    t = lg.get("dashboard_template")
    # `top1` la comparten las europeas y el Brasileirão, y `tier2` las 2as europeas
    # con Liga MX, MLS y Argentina, cada familia con SUS claves de zona. Si la liga
    # declara las suyas, las columnas salen de sus bandas (mismo motivo que
    # snapshots._pills_for: con las claves a fuego el tuit saldría a cero).
    etiquetas = lg.get("zone_labels")
    if etiquetas and t in ("top1", "tier2"):
        claves = [b["key"] for b in lg["bands"](20)]
        pares = list(zip(claves, etiquetas))
        if len(claves) > len(etiquetas):     # top1: la cola no va en zone_labels
            pares.append((claves[-1], "Descenso"))
        return ([("first", "Título")] if t == "top1" else []) + pares
    if t == "top1":
        return ZONES_TOP1
    if t in ("top2", "tier2"):
        return ZONES_TIER2
    return []                     # uefa y otras: sin tuits

# Acento de marca por liga (mismo que styles.css → .theme-*). Las ligas sin tema
# propio usan el oro global --brand (= mismo fallback del dashboard).
ACCENTS = {
    "hypermotion": (240, 169, 42),   # oro
    "laliga":      (255, 74, 90),    # rojo
}

_NUM = ["1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3",
        "4\ufe0f\u20e3", "5\ufe0f\u20e3", "6\ufe0f\u20e3"]

# Hashtags al final de cada tuit: el de la liga + 2 genéricos (X limita a 280
# chars; si el tuit se pasara, _tweet_text recorta hasta quedarse solo con el de
# la liga o sin hashtags).
HASHTAGS = {
    "hypermotion": ["#hypermotion", "#futbol", "#predicciones"],
    "laliga":      ["#LaLiga", "#futbol", "#predicciones"],
    "premier":     ["#PremierLeague", "#futbol", "#predicciones"],
    "seriea":      ["#SerieA", "#futbol", "#predicciones"],
    "bundesliga":  ["#Bundesliga", "#futbol", "#predicciones"],
    "ligue1":      ["#Ligue1", "#futbol", "#predicciones"],
    "primeira":    ["#LigaPortugal", "#futbol", "#predicciones"],
    "eredivisie":  ["#Eredivisie", "#futbol", "#predicciones"],
    "brasileirao": ["#Brasileirao", "#futbol", "#predicciones"],
    "ligamx":      ["#LigaMX", "#futbol", "#predicciones"],
    "mls-este":    ["#MLS", "#futbol", "#predicciones"],
    "mls-oeste":   ["#MLS", "#futbol", "#predicciones"],
    "argentina-a": ["#LigaProfesional", "#futbol", "#predicciones"],
    "argentina-b": ["#LigaProfesional", "#futbol", "#predicciones"],
    "championship": ["#Championship", "#futbol", "#predicciones"],
    "serieb":      ["#SerieB", "#futbol", "#predicciones"],
    "bundesliga2": ["#2Bundesliga", "#futbol", "#predicciones"],
    "ligue2":      ["#Ligue2", "#futbol", "#predicciones"],
}

STATE_FILE = DATA_DIR / "tweets_state.json"
PREVIEW_DIR = DATA_DIR / "tweets_preview"
HANDLES_FILE = DATA_DIR / "tweets_handles.json"

# TheSportsDB (misma API gratuita que seo/player_cuts.py): los equipos de ESPN no
# traen su @ de X, así que se resuelve por nombre aquí y se cachea por id ESPN.
_TSDB = "https://www.thesportsdb.com/api/v1/json/123/searchteams.php"

# Overrides de @ oficiales (datos de marca, como TEAM_LOGOS): TheSportsDB no los
# tiene, los tiene mal (p. ej. "Celta Vigo" → @rcceltaen, un fan) o el nombre no
# casa por exacto. Clave = nombre ESPN normalizado (_norm_team). Gana al match TSD.
HANDLE_OVERRIDES = {
    "athleticclub":     "@AthleticClub",
    "celtavigo":        "@RCCelta",
    "rcceltafortuna":   "@RCCelta",
    "deportivo":        "@RCDeportivo",
    "racingsantander":  "@RealRacing",
    "alaves":           "@Alaves",
    "realsociedadii":   "@RealSociedad",
    "cdsabadell":       "@CESabadell",
    "sportinggijon":    "@RealSporting",
    "tenerife":         "@CDTOficial",
    "albacete":         "@AlbaceteBPSAD",
    "ceuta":            "@ADCeutaFC",
    "cordoba":          "@cordobacfsad",
}

# Ventana para considerar que una jornada está a punto de arrancar (partidos pre).
UPCOMING_DAYS = 3

# Candidatos de fuentes DejaVu (Fedora: /usr/share/fonts/TTF · Ubuntu: truetype/dejavu).
_FONT_DIRS = [
    Path("/usr/share/fonts/TTF"),
    Path("/usr/share/fonts/truetype/dejavu"),
]

_PALETTE = [
    (240, 169, 42), (255, 74, 90), (36, 208, 138), (61, 142, 245),
    (155, 92, 255), (255, 122, 69), (79, 214, 200), (224, 123, 214),
]


# ---------------------------------------------------------------- estado ----

def _load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _update_state(**claves):
    """Relee el estado del disco y guarda SOLO las claves dadas.

    Guardar el dict entero pisaba lo que hubiera escrito otro tramo mientras tanto:
    `_poll_once` cargaba el estado, llamaba a `_process_league` (que anota su
    `{slug: {season, label}}` anti-duplicado) y al terminar reescribía su copia
    vieja con solo `offset`/`telegram_chat` — borrando la marca recién puesta, así
    que el cron de lunes/jueves reenviaba los mismos tuits de esa jornada."""
    state = _load_state()
    state.update(claves)
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except OSError as e:
        print(f"[tweets] no se pudo guardar el estado: {e}", file=sys.stderr)
    return state


def _load_snapshot(slug):
    path = DATA_DIR / slug / "latest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"[tweets] snapshot {path} no disponible: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------- texto -----

def _clip(name, limit=20):
    return name if len(name) <= limit else name[: limit - 1] + "…"


def _fmt_pct(p):
    if p <= 0:
        return "0%"
    if p < 1:
        return f"{p:.1f}".replace(".", ",") + "%"
    if p >= 100:
        return "100%"
    return f"{round(p)}%"


def _team_prob(t, zone):
    """Probabilidad de un equipo para una zona.

    `ascenso_total` no siempre está en el snapshot: Hypermotion lo persiste
    (ascenso directo + ganar el play-off). Para el resto de 2ªs se aproxima
    sumando ascenso directo + llegar al play-off."""
    prob = t.get("prob") or {}
    if zone == "ascenso_total":
        if "ascenso_total" in prob:
            return prob["ascenso_total"]
        return round(min(100.0, prob.get("ascenso", 0) + prob.get("playoff", 0)), 1)
    return prob.get(zone)


def _top_teams(snap, zone, k=6):
    rows = []
    for t in snap.get("teams", []):
        p = _team_prob(t, zone)
        if p is None:
            continue
        rows.append((t["name"], t.get("logo"), p))
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows[:k]


# ------------------------------------------------------- handles de X (@) -----

def _extract_handle(url_text):
    """'www.twitter.com/realmadrid' → '@realmadrid'. None si no es válido."""
    s = (url_text or "").strip().split("/")[-1].lstrip("@").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", s):
        return None
    return "@" + s


def _norm_team(name):
    """Normaliza un nombre para match conservador (sin acentos/mayús/signos)."""
    n = unicodedata.normalize("NFD", name or "").encode("ascii", "ignore").decode()
    return "".join(ch for ch in n.lower() if ch.isalnum())


def _fetch_handles(slug, teams):
    """{id_espm: '@handle' | None} por liga, cacheado en data/tweets_handles.json.

    Solo consulta a TheSportsDB los ids que faltan en la caché; best-effort: si un
    equipo no tiene @ o falla la consulta, se queda sin handle (se usa el nombre)."""
    cache = {}
    if HANDLES_FILE.exists():
        try:
            cache = json.loads(HANDLES_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
    sl = cache.setdefault(slug, {})
    for t in teams:                            # los overrides mandan siempre
        ov = HANDLE_OVERRIDES.get(_norm_team(t.get("name") or ""))
        if ov:
            sl[str(t.get("id"))] = ov
    missing = [t for t in teams if str(t.get("id")) not in sl]
    if missing:
        print(f"[tweets] {slug}: resolviendo @ de {len(missing)} equipos en TheSportsDB…")
    for t in missing:
        tid, name = str(t.get("id")), t.get("name")
        try:
            q = urllib.parse.quote(name or "")
            data = None
            for attempt in range(2):           # 1 reintento con backoff si hay 429
                try:
                    with urllib.request.urlopen(
                            urllib.request.Request(f"{_TSDB}?t={q}"), timeout=15) as r:
                        data = json.loads(r.read().decode())
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 429 and attempt == 0:
                        print(f"[tweets] {slug}: 429 de TheSportsDB, reintento en 10 s…")
                        time.sleep(10)
                        continue
                    raise
            results = (data or {}).get("teams") or []
            declared = [x for x in results if (x.get("strSport") or "").strip()]
            soccer = [x for x in results
                      if (x.get("strSport") or "").lower() == "soccer"]
            if soccer:
                candidates = soccer
            elif not declared:
                candidates = results          # sin deporte declarado → asumimos fútbol
            else:
                candidates = []               # hay deporte, pero no es fútbol
            want = _norm_team(name)
            hit = next((x for x in candidates
                        if _norm_team(x.get("strTeam") or "") == want), None)
            sl[tid] = HANDLE_OVERRIDES.get(want) or \
                (_extract_handle(hit.get("strTwitter")) if hit else None)
            print(f"[tweets] {slug}: {name} → {sl[tid] or 'sin @'}")
        except Exception as e:
            print(f"[tweets] {slug}: no se pudo resolver @ de {name}: {e}",
                  file=sys.stderr)
        time.sleep(0.8)
    if missing:
        try:
            tmp = HANDLES_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.rename(HANDLES_FILE)
        except OSError as e:
            print(f"[tweets] no se pudo guardar la caché de @: {e}", file=sys.stderr)
    return sl


def _tweet_text(league_name, label, zone_label, top, url, tags=None):
    lines = [f"📊 {league_name} · Jornada {label}",
             f"{zone_label} según PredictMotion ⚽"]
    for i, (name, pct) in enumerate(top[:6]):
        lines.append(f"{_NUM[i]} {_clip(name)} {pct}")
    lines.append("El resto, en la web 👇")
    lines.append(url)
    if tags:
        lines.append("")
        lines.append(" ".join(tags))
    text = "\n".join(lines)
    if len(text) > 280 and tags:
        lines[-1] = tags[0]                 # solo el hashtag de la liga
        text = "\n".join(lines)
    if len(text) > 280:
        lines = lines[:-2]                  # sin hashtags (caso límite)
        text = "\n".join(lines)
    if len(text) > 280:
        lines = [l for l in lines if not l.startswith("El resto")]
        text = "\n".join(lines)
    return text


def _intent_url(text):
    """Enlace directo al compositor de X con el texto del tuit precargado."""
    return "https://twitter.com/intent/tweet?text=" + urllib.parse.quote(text, safe="")


def _caption(text):
    """Mensaje de Telegram: el tuit + un enlace que lleva a X para publicarlo.

    Telegram limita el caption a 1024 chars; si el enlace se pasara de largo se
    manda el texto a secas (el enlace de la web sigue dentro del propio tuit)."""
    link = "👉 " + _intent_url(text)
    caption = text + "\n\n" + link
    if len(caption) > 1024:
        print(f"[tweets] caption con enlace demasiado largo ({len(caption)}); "
              f"se manda solo el texto", file=sys.stderr)
        return text
    return caption


# ---------------------------------------------------------------- imagen -----

def _font(size, bold=False):
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for d in _FONT_DIRS:
        f = d / name
        if f.exists():
            return ImageFont.truetype(str(f), size)
    return None


def _initials(name):
    parts = [w for w in name.replace(".", " ").split() if w and w[0].isalnum()]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _palette(name):
    return _PALETTE[abs(hash(name)) % len(_PALETTE)]


_IMG_CACHE = {}


def _fetch_image(url, timeout=6):
    if not url:
        return None
    if url in _IMG_CACHE:
        return _IMG_CACHE[url]
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except Exception:
        data = None
    _IMG_CACHE[url] = data
    return data


def _crest_image(name, logo_url, r=30):
    """Escudo circular (PIL RGBA) con el logo de ESPN o avatar de iniciales."""
    from PIL import Image, ImageDraw
    bytes_ = _fetch_image(logo_url)
    im = None
    if bytes_:
        try:
            im = Image.open(io.BytesIO(bytes_)).convert("RGBA")
            im = im.resize((2 * r, 2 * r), Image.LANCZOS)
        except Exception:
            im = None
    if im is None:
        im = Image.new("RGBA", (2 * r, 2 * r), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((0, 0, 2 * r - 1, 2 * r - 1), fill=_palette(name))
        font = _font(int(r * 1.0), bold=True)
        if font:
            d.text((r, r), _initials(name), font=font,
                   fill=(255, 255, 255), anchor="mm")
    mask = Image.new("L", (2 * r, 2 * r), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 2 * r - 1, 2 * r - 1), fill=255)
    im.putalpha(mask)
    return im


def _card_image(slug, snap, label, zone_label, top, handles=None):
    """Tarjeta PNG 1080×1350 con la 'captura' del top-6. None si no hay PIL/fuentes."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    W, H = 1080, 1350
    accent = ACCENTS.get(slug, (240, 169, 42))
    bg = (11, 14, 20)
    card = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(card)

    f_name = _font(46, bold=True)
    f_name_sm = _font(38, bold=True)
    f_sub = _font(28)
    f_sub_sm = _font(26)
    f_zone = _font(46, bold=True)
    f_rank = _font(34, bold=True)
    f_pct = _font(52, bold=True)
    f_foot = _font(36, bold=True)
    if not f_name:
        return None

    # Barra de acento superior.
    d.rectangle((0, 0, W, 14), fill=accent)

    # Marca arriba a la derecha.
    d.text((W - 60, 58), "PREDICTMOTION", font=_font(24, bold=True),
           fill=(140, 148, 165), anchor="ra")

    # Cabecera: escudo de la competición + nombre + jornada.
    crest = _crest_image(snap.get("name") or slug, snap.get("league_logo"), r=55)
    card.paste(crest, (110 - 55, 150 - 55), crest)
    d.ellipse((110 - 55, 150 - 55, 110 + 55, 150 + 55), outline=(40, 46, 62), width=3)

    league_name = snap.get("name") or slug
    d.text((200, 118), league_name, font=f_name, fill=(245, 246, 250), anchor="lm")
    season = snap.get("season", "")
    d.text((200, 176), f"Jornada {label} · {season}", font=f_sub,
           fill=(140, 148, 165), anchor="lm")

    # Tarjeta de la zona.
    d.rounded_rectangle((60, 250, 1020, 470), radius=28,
                        fill=(20, 25, 36), outline=accent, width=2)
    d.text((540, 330), zone_label, font=f_zone, fill=accent, anchor="mm")
    d.text((540, 392), "según el método PredictMotion", font=f_sub,
           fill=(160, 168, 185), anchor="mm")

    # Filas del top-6.
    row_h, gap, start_y = 104, 18, 540
    bar_max = 730
    max_pct = max((p for _, _, p in top), default=0.0) or 1.0
    for i, (name, logo_url, p) in enumerate(top[:6]):
        cy = start_y + i * (row_h + gap)
        d.ellipse((120 - 32, cy - 32, 120 + 32, cy + 32),
                  fill=(24, 30, 44), outline=(40, 46, 62), width=2)
        d.text((120, cy), str(i + 1), font=f_rank, fill=accent, anchor="mm")

        c = _crest_image(name, logo_url, r=30)
        card.paste(c, (200 - 30, cy - 30), c)
        d.ellipse((200 - 30, cy - 30, 200 + 30, cy + 30),
                  outline=(40, 46, 62), width=2)

        d.text((250, cy), (handles or {}).get(name) or _clip(name, 24),
               font=f_name_sm, fill=(245, 246, 250), anchor="lm")
        d.text((1020, cy), _fmt_pct(p), font=f_pct, fill=accent, anchor="rm")

        ybar = cy + 46
        d.rounded_rectangle((250, ybar, 250 + bar_max, ybar + 8), radius=4,
                            fill=(32, 38, 54))
        w = max(int(bar_max * min(p, max_pct) / max_pct), 8)
        d.rounded_rectangle((250, ybar, 250 + w, ybar + 8), radius=4, fill=accent)

    # Pie: enlace + atribución.
    url = SITE + (league_by_slug(slug) or {}).get("dashboard", f"/{slug}")
    d.text((540, 1245), url, font=f_foot, fill=(245, 246, 250), anchor="mm")
    d.text((540, 1300), "Pronóstico por Monte Carlo · 20 000 simulaciones",
           font=f_sub_sm, fill=(110, 118, 138), anchor="mm")

    buf = io.BytesIO()
    card.save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- telegram ---

def _tg_url(method):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    return f"https://api.telegram.org/bot{token}/{method}"


def _tg_keyboard():
    """Teclado inline: un botón por liga activa → regenera sus tuits al pulsarlo."""
    buttons = []
    for slug in TWEET_LEAGUES:
        lg = league_by_slug(slug)
        label = (lg or {}).get("name") or slug
        buttons.append({"text": f"⚽ Tweet {label}", "callback_data": f"tweet:{slug}"})
    return {"inline_keyboard": [buttons]}


def _tg_send_message(chat_id, text, reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        data = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(_tg_url("sendMessage"), data=data)
        with urllib.request.urlopen(req, timeout=30) as r:
            return bool((json.loads(r.read().decode()) or {}).get("ok"))
    except Exception as e:
        print(f"[tweets] sendMessage falló: {e}", file=sys.stderr)
        return False


def _tg_send_photo(chat_id, caption, png_bytes, reply_markup=None):
    try:
        boundary = "----PM" + uuid.uuid4().hex
        parts = []
        fields = [("chat_id", str(chat_id)), ("caption", caption)]
        if reply_markup:
            fields.append(("reply_markup", json.dumps(reply_markup)))
        for name, value in fields:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; '
                         f'name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; '
                     f'name="photo"; filename="captura.png"\r\n'
                     f'Content-Type: image/png\r\n\r\n'.encode())
        parts.append(png_bytes)
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        req = urllib.request.Request(
            _tg_url("sendPhoto"), data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return bool((json.loads(r.read().decode()) or {}).get("ok"))
    except Exception as e:
        print(f"[tweets] sendPhoto falló: {e}", file=sys.stderr)
        return False


def _tg_answer_callback(callback_query_id):
    """Confirma el callback para que el botón deje de girar en el chat."""
    try:
        data = urllib.parse.urlencode(
            {"callback_query_id": callback_query_id}).encode()
        req = urllib.request.Request(_tg_url("answerCallbackQuery"), data=data)
        with urllib.request.urlopen(req, timeout=30) as r:
            return bool((json.loads(r.read().decode()) or {}).get("ok"))
    except Exception as e:
        print(f"[tweets] answerCallbackQuery falló: {e}", file=sys.stderr)
        return False


def _tg_get_updates(token, offset):
    try:
        q = urllib.parse.urlencode({"timeout": 0, "offset": offset or ""})
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/getUpdates?{q}")
        with urllib.request.urlopen(req, timeout=30) as r:
            return (json.loads(r.read().decode()) or {}).get("result", [])
    except Exception as e:
        print(f"[tweets] getUpdates falló: {e}", file=sys.stderr)
        return []


# ---------------------------------------------------------------- lógica -----

def _imminent_round(espn_code):
    """True si hay algún partido `pre` en los próximos UPCOMING_DAYS días.

    Es la puerta de "la jornada está a punto de arrancar". Best-effort: si ESPN
    falla ([]), devuelve False y la pasada programada se salta (se puede pedir
    a mano con /tweet)."""
    today = datetime.now(timezone.utc).date()
    fmt = lambda dt: dt.strftime("%Y%m%d")
    events = espn.fetch_scoreboard_range(
        espn_code, fmt(today), fmt(today + timedelta(days=UPCOMING_DAYS)))
    return any(ev.get("state") == "pre" for ev in events)


def _send_tweet(chat_id, text, png, dry_run=False, slug=None, zone_label=None):
    """Manda (o guarda en preview) un tweet. Devuelve True si se consideró enviado."""
    if dry_run:
        print("\n" + "=" * 60)
        print(text)
        print("=" * 60)
        try:
            PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
            if png:
                safe = (slug or "x") + "-" + (zone_label or "x") \
                    .replace(" ", "-").replace("/", "-")
                (PREVIEW_DIR / f"{safe}.png").write_bytes(png)
                print(f"[tweets] imagen → data/tweets_preview/{safe}.png")
        except OSError as e:
            print(f"[tweets] no se pudo escribir preview: {e}", file=sys.stderr)
        return True
    if png:
        return _tg_send_photo(chat_id, text, png, reply_markup=_tg_keyboard())
    return _tg_send_message(chat_id, text, reply_markup=_tg_keyboard())


def _process_league(slug, *, force=False, chat_id=None, dry_run=False):
    """Genera y manda los tweets de una liga para la jornada que va a empezar.

    Sin `force` (cron programado): salta si la (season, jornada) ya se tuiteó o
    si no hay jornada inminente. Con `force` (manual /tweet): manda siempre.
    """
    league = league_by_slug(slug)
    if not league:
        print(f"[tweets] liga desconocida: {slug}", file=sys.stderr)
        return 0
    snap = _load_snapshot(slug)
    if not snap:
        return 0
    if snap.get("finished"):
        print(f"[tweets] {slug}: temporada acabada, sin tuits")
        return 0

    season = snap.get("season", "")
    label = int(snap.get("jornada", 0) or 0)
    state = _load_state()
    cur = state.get(slug) or {}

    if not force:
        if cur.get("season") == season and cur.get("label") == label:
            print(f"[tweets] {slug}: jornada {label} ({season}) ya tuiteada")
            return 0
        if not _imminent_round(league["espn_code"]):
            print(f"[tweets] {slug}: sin jornada inminente (≤{UPCOMING_DAYS} días)")
            return 0

    if not dry_run and chat_id is None:
        chat_id = os.environ.get("TELEGRAM_CHAT_ID") or _load_state().get("telegram_chat")
        if not chat_id:
            print("[tweets] sin chat_id de Telegram (TELEGRAM_CHAT_ID o --poll)",
                  file=sys.stderr)
            return 0

    url = SITE + league["dashboard"]
    handles = _fetch_handles(slug, snap.get("teams", []))
    by_name = {t.get("name"): handles.get(str(t.get("id")))
               for t in snap.get("teams", []) if t.get("name")}
    sent = 0
    for zone, zlabel in _zones(slug):
        top = _top_teams(snap, zone)
        if not top or top[0][2] <= 0:
            print(f"[tweets] {slug}/{zone}: sin datos (todas 0%), se omite")
            continue
        rows = [(by_name.get(n) or _clip(n), _fmt_pct(p)) for n, _, p in top]
        text = _tweet_text(snap.get("name") or slug, label, zlabel, rows, url,
                           tags=HASHTAGS.get(slug))
        caption = _caption(text)
        png = _card_image(slug, snap, label, zlabel, top, handles=by_name)
        if _send_tweet(chat_id, caption, png, dry_run=dry_run,
                       slug=slug, zone_label=zlabel):
            sent += 1
        time.sleep(1)

    if not dry_run:
        if sent == 0:
            notify.send_alert(
                f"[tweets] no se envió ningún tuit de {slug}",
                f"slug={slug} jornada={label} ({season})", dedup_key=f"tweets_send_{slug}")
        else:
            _update_state(**{slug: {"season": season, "label": label}})
    return sent


def _run_scheduled(dry_run=False):
    """Cron programado (lunes/jueves): todas las ligas, con detección de jornada."""
    notify._load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID") or _load_state().get("telegram_chat")
    if not dry_run and not (token and chat):
        notify.send_alert(
            "[tweets] sin configuración de Telegram",
            "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env",
            dedup_key="tweets_no_config")
        print("[tweets] sin TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID; nada que hacer",
              file=sys.stderr)
        return 0
    for slug in TWEET_LEAGUES:
        try:
            _process_league(slug, chat_id=chat, dry_run=dry_run)
        except Exception as e:
            print(f"[tweets] error en {slug}: {e}", file=sys.stderr)
    return 0


def _poll_once():
    """Una pasada de getUpdates para comandos manuales (/tweet)."""
    notify._load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("[tweets] sin TELEGRAM_BOT_TOKEN; --poll no hace nada", file=sys.stderr)
        return 0
    state = _load_state()
    updates = _tg_get_updates(token, state.get("offset") or 0)
    last = state.get("offset") or 0
    for u in updates:
        last = max(last, u.get("update_id", 0))
        cbq = u.get("callback_query") or {}
        if cbq:
            cid = cbq.get("id")
            data = (cbq.get("data") or "").strip()
            chat_id = ((cbq.get("message") or {}).get("chat") or {}).get("id")
            if chat_id:
                state["telegram_chat"] = chat_id
            if cid:
                _tg_answer_callback(cid)
            try:
                if data.startswith("tweet:"):
                    arg = data.split(":", 1)[1]
                    if arg and arg not in TWEET_LEAGUES:
                        _tg_send_message(chat_id, f"Liga desconocida: {arg}. "
                                                  f"Válidas: {', '.join(TWEET_LEAGUES)}")
                        continue
                    _tg_send_message(chat_id, "Generando tuits…")
                    _process_league(arg or "hypermotion", force=True, chat_id=chat_id)
            except Exception as e:
                print(f"[tweets] error procesando callback: {e}", file=sys.stderr)
            continue
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = (msg.get("chat") or {}).get("id")
        if chat_id:
            state["telegram_chat"] = chat_id
        if not text:
            continue
        try:
            if text.startswith("/tweet"):
                arg = text[len("/tweet"):].strip()
                if arg and arg not in TWEET_LEAGUES:
                    _tg_send_message(chat_id, f"Liga desconocida: {arg}. "
                                              f"Válidas: {', '.join(TWEET_LEAGUES)}")
                    continue
                _tg_send_message(chat_id, "Generando tuits…")
                for s in ([arg] if arg else TWEET_LEAGUES):
                    _process_league(s, force=True, chat_id=chat_id)
            elif text.startswith(("/start", "/help")):
                _tg_send_message(chat_id, "PredictMotion: pulsa el botón para "
                                          "generar los tuits de la jornada con los "
                                          "datos del momento (o /tweet <liga>). "
                                          "Ligas: " + ", ".join(TWEET_LEAGUES),
                                 reply_markup=_tg_keyboard())
        except Exception as e:
            print(f"[tweets] error procesando comando: {e}", file=sys.stderr)
    if updates:
        # Solo estas dos claves: entre medias `_process_league` ha podido anotar la
        # marca anti-duplicado de una liga, y guardar el dict entero la borraría.
        campos = {"offset": last + 1}
        if state.get("telegram_chat"):
            campos["telegram_chat"] = state["telegram_chat"]
        _update_state(**campos)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tweets de jornada vía Telegram")
    ap.add_argument("--poll", action="store_true",
                    help="cron de comandos: getUpdates breve para /tweet")
    ap.add_argument("--dry-run", action="store_true",
                    help="no envía: imprime texto y guarda la imagen en preview")
    ap.add_argument("--league", help="fuerza una liga (manual)")
    args = ap.parse_args(argv)

    try:
        if args.poll:
            return _poll_once()
        if args.league:
            notify._load_env()
            _process_league(args.league, force=True, dry_run=args.dry_run)
            return 0
        return _run_scheduled(dry_run=args.dry_run)
    except Exception:
        notify.send_alert("[tweets] error no capturado",
                          traceback.format_exc(), dedup_key="tweets_crash")
        print(traceback.format_exc(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
