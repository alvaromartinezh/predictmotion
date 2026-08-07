"""Descarga y parseo de feeds RSS — solo stdlib (urllib + xml.etree).

Cada ítem se normaliza a un dict estable. Del feed se toma SOLO: título, resumen
CORTO (truncado), enlace, fecha, fuente y categorías. `content:encoded` (cuerpo
completo del artículo) se IGNORA por diseño (requisito legal de sindicación).
"""

import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .config import HTTP_HEADERS, HTTP_TIMEOUT, PER_FEED_LIMIT, SUMMARY_MAXLEN

# Media RSS (Yahoo) — Marca/AS/MD lo usan para media:content / media:description.
_MEDIA = "{http://search.yahoo.com/mrss/}"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def _strip_html(s):
    """Quita etiquetas HTML (incluye el píxel de tracking de Marca), decodifica
    entidades y colapsa espacios. Devuelve texto plano."""
    s = _TAG_RE.sub(" ", s or "")
    s = html.unescape(s)
    return _WS_RE.sub(" ", s).strip()


def _truncate(s, maxlen=SUMMARY_MAXLEN):
    """Corta a `maxlen` en el último espacio y añade elipsis. Salvaguarda legal:
    garantiza 'resumen corto' aunque el feed sirva un texto largo (p. ej. MD)."""
    if len(s) <= maxlen:
        return s
    cut = s[:maxlen].rsplit(" ", 1)[0].rstrip(" ,.;:—-")
    return (cut or s[:maxlen]).rstrip() + "…"


def _summary(item):
    """Resumen corto en texto plano. Prioriza media:description (Marca lo trae
    limpio) y cae a <description>. NUNCA usa content:encoded."""
    for tag in (f"{_MEDIA}description", "description"):
        raw = _text(item.find(tag))
        if raw:
            clean = _strip_html(raw)
            if clean:
                return _truncate(clean)
    return ""


def _parse_date(item):
    """pubDate (RFC-822) → (iso, epoch). Best-effort; (None, 0) si no parsea.
    Tolera variantes vistas: 'Fri, 07 Aug 2026 11:55:50 GMT' y '07 Aug 2026
    17:28:45 +0200' (sin día de la semana)."""
    raw = _text(item.find("pubDate"))
    if not raw:
        return None, 0
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(), int(dt.timestamp())
    except (TypeError, ValueError, IndexError):
        return None, 0


def _categories(item):
    out = []
    for c in item.findall("category"):
        t = _text(c)
        if t:
            out.append(t)
    return out


def fetch_feed(feed):
    """Descarga y parsea un feed. Devuelve lista de ítems normalizados.

    Best-effort: cualquier fallo (red, HTTP, XML) se propaga como excepción para
    que el orquestador lo registre por-feed y siga con los demás.
    """
    req = urllib.request.Request(feed["url"], headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)

    items = []
    for item in root.findall(".//item")[:PER_FEED_LIMIT]:
        link = _text(item.find("link"))
        title = _strip_html(_text(item.find("title")))
        if not link or not title:
            continue
        iso, ts = _parse_date(item)
        items.append({
            "title":      title,
            "summary":    _summary(item),
            "link":       link,
            "source":     feed["source"],
            "home":       feed["home"],
            "published":  iso,
            "ts":         ts,
            "categories": _categories(item),
            "league_hint": feed["league_hint"],
        })
    return items
