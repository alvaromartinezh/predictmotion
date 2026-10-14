"""Tarjetas sociales 1200×630 para los artículos (`og:image`).

Por qué existe: los ~600 artículos publicados servían todos
`media/logo.jpeg` (cuadrado, 230 KB) con `twitter:card: summary`. Dos
consecuencias: al compartir un artículo en Bluesky/Telegram/WhatsApp salía una
miniatura del logo en vez de nada que invitase a entrar, y Google Discover
exige imagen de **1200 px de ancho mínimo** para dar la tarjeta grande, así que
los artículos no eran elegibles. `media/og-default.png` (1200×630) ya existía
en el repo pero no lo usaba nadie.

Reusa el compositor que ya estaba montado en `seo/tweets.py` (fuentes DejaVu,
escudo circular con caché, paleta de acentos por liga): aquí solo cambia el
lienzo (1200×630 en vez de 1080×1350) y el contenido (el titular, no el top-6).

Las tarjetas van a `media/og/<slug>.png`, gitignored igual que `articulos/`:
se generan en el servidor, dentro del cron de artículos que ya corre. La
generación es **idempotente** (si el PNG existe, no se repite) y la llama
`articles.generate._write_articles_index`, que ya escanea `articulos/*.html`
en cada publicación — así los artículos viejos se rellenan solos sin script de
backfill, mismo patrón self-healing que el índice y el sitemap.

Ver [[docs/articulos]].
"""

import io
import sys
from pathlib import Path

from .config import SITE
from .tweets import ACCENTS, _crest_image, _font, _load_snapshot

W, H = 1200, 630
OG_DIR = Path(__file__).resolve().parent.parent / "media" / "og"
DEFAULT_URL = SITE + "/media/og-default.png"  # fallback, ver ensure()


def url_for(slug):
    """URL pública de la tarjeta de un artículo (exista o no todavía)."""
    return f"{SITE}/media/og/{slug}.png"


def _wrap(d, text, font, max_w, max_lines):
    """Parte el titular en líneas que caben en `max_w` px, midiendo con la
    fuente real (textwrap por ancho de caracteres desborda con mayúsculas)."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        probe = f"{cur} {w}".strip()
        if cur and d.textlength(probe, font=font) > max_w:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
        else:
            cur = probe
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and len(" ".join(lines)) < len(text):
        # La "…" también ocupa: si la última línea iba justa, se suelta una
        # palabra hasta que quepa (si no, desborda el lienzo por la derecha).
        tail = lines[-1].rstrip(",.;:").split()
        while tail and d.textlength(" ".join(tail) + "…", font=font) > max_w:
            tail.pop()
        lines[-1] = " ".join(tail) + "…"
    return lines


def render(slug, league_slug, title):
    """Bytes PNG de la tarjeta, o None si falta PIL o las fuentes."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    f_title = _font(62, bold=True)
    f_league = _font(34, bold=True)
    f_foot = _font(30, bold=True)
    if not f_title:
        return None

    accent = ACCENTS.get(league_slug, (240, 169, 42))
    card = Image.new("RGB", (W, H), (11, 14, 20))
    d = ImageDraw.Draw(card)
    d.rectangle((0, 0, W, 12), fill=accent)

    snap = _load_snapshot(league_slug) or {}
    league_name = snap.get("name") or league_slug
    crest = _crest_image(league_name, snap.get("league_logo"), r=42)
    card.paste(crest, (80 - 42, 110 - 42), crest)
    d.text((148, 110), league_name.upper(), font=f_league, fill=(140, 148, 165),
           anchor="lm")
    d.text((W - 80, 110), "PREDICTMOTION", font=f_league, fill=accent, anchor="rm")

    lines = _wrap(d, title, f_title, W - 160, 4)
    y = 320 - (len(lines) - 1) * 42
    for ln in lines:
        d.text((80, y), ln, font=f_title, fill=(245, 246, 250), anchor="lm")
        y += 84

    d.rectangle((80, H - 112, 80 + 90, H - 106), fill=accent)
    d.text((80, H - 62), "predictmotion.com", font=f_foot, fill=(160, 168, 185),
           anchor="lm")

    buf = io.BytesIO()
    card.save(buf, "PNG")
    return buf.getvalue()


def ensure(slug, league_slug, title):
    """Genera `media/og/<slug>.png` si no existe. Idempotente.

    Si no se puede dibujar (sin PIL o sin fuentes) **copia `og-default.png`** en
    su sitio en vez de rendirse: el HTML apunta a esta ruta siempre, así que
    dejarla vacía sería un 404 en el `og:image` de todos los artículos — peor
    que el logo cuadrado que había antes. Devuelve la URL pública."""
    path = OG_DIR / f"{slug}.png"
    if path.exists():
        return url_for(slug)
    png = render(slug, league_slug, title) or _default_png()
    if png:
        try:
            OG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".png.tmp")
            tmp.write_bytes(png)
            tmp.replace(path)
        except OSError as e:
            print(f"[ogcard] no se pudo escribir {path}: {e}", file=sys.stderr)
    return url_for(slug)


def _default_png():
    try:
        return (OG_DIR.parent / "og-default.png").read_bytes()
    except OSError:
        return None


def read(slug):
    """Bytes de la tarjeta ya generada (para adjuntarla a un post), o None."""
    try:
        return (OG_DIR / f"{slug}.png").read_bytes()
    except OSError:
        return None


def _self_check():
    """Lo no trivial es el ajuste del titular: ni desborda el lienzo ni se come
    palabras cuando hay más texto que líneas."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (W, H)))
    f = _font(62, bold=True)
    assert f, "sin fuentes DejaVu: la tarjeta no se puede comprobar"

    corto = "El Alavés roza el descenso"
    assert _wrap(d, corto, f, W - 160, 4) == [corto]

    largo = ("El Villarreal dispara sus probabilidades de Champions tras ganar al "
             "Betis y el Real Madrid pierde el liderato por primera vez en la "
             "temporada después de una jornada de resultados inesperados")
    lines = _wrap(d, largo, f, W - 160, 4)
    assert len(lines) == 4, lines
    assert lines[-1].endswith("…"), lines[-1]
    assert all(d.textlength(l, font=f) <= W - 160 for l in lines), \
        [d.textlength(l, font=f) for l in lines]

    png = render("laliga-prueba", "laliga", largo)
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) < 1_000_000, f"{len(png)} B pasa del límite de blob de Bluesky"
    assert Image.open(io.BytesIO(png)).size == (1200, 630)
    print(f"ok: wrap + render ({len(png)} B)")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    elif len(sys.argv) > 3:
        out = OG_DIR / f"{sys.argv[1]}.png"
        png = render(sys.argv[1], sys.argv[2], " ".join(sys.argv[3:]))
        OG_DIR.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png)
        print("escrito", out, len(png), "B")
    else:
        print("uso: python3 -m seo.ogcard <slug> <liga> <titular...> | --self-check")
