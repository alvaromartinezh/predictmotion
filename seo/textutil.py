"""Utilidades de texto: slugs y formato numérico en español."""

import re
import unicodedata


def slugify(name):
    """'RC Deportivo' -> 'rc-deportivo'. ASCII, minúsculas, guiones."""
    s = unicodedata.normalize("NFKD", name)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "equipo"


def pct(value):
    """64.2 -> '64,2%' (coma decimal española). 0 -> '0%'."""
    if value is None:
        return "—"
    if value == 0:
        return "0%"
    if value == 100:
        return "100%"
    return f"{value:.1f}".replace(".", ",") + "%"


def num(value, decimals=1):
    """Formatea un número con coma decimal española."""
    return f"{value:.{decimals}f}".replace(".", ",")


def signed(value, decimals=1):
    """Delta con signo explícito: +5,1 / -2,3 / =."""
    if abs(value) < 0.05:
        return "="
    sign = "+" if value > 0 else "−"  # menos tipográfico
    return sign + num(abs(value), decimals)


def ordinal(n, fem=False):
    """1 -> '1º' · ordinal(1, fem=True) -> '1ª'. El femenino hace falta para
    concordar con 'defensa' ("la 3ª mejor defensa"): sin él salía "el 3º mejor
    defensa"."""
    return f"{n}{'ª' if fem else 'º'}"


def de_league(league):
    """Concordancia: 'de la Liga Hypermotion', 'de LaLiga', 'de la Copa del Mundo'."""
    art = league.get("article", "")
    return f"de {art + ' ' if art else ''}{league['name']}"


def en_league(league):
    """Concordancia: 'en la Liga Hypermotion', 'en LaLiga', 'en la Copa del Mundo'."""
    art = league.get("article", "")
    return f"en {art + ' ' if art else ''}{league['name']}"


def zone_label(label):
    """Etiqueta de zona en minúsculas dentro de una frase ('probabilidad de
    descenso'), PERO respetando los nombres propios: las tres competiciones UEFA
    son marcas registradas y '…de champions league' se leía como una errata en el
    <title> de ~250 páginas de equipo. Todo lo demás ('Descenso', 'Ascenso
    directo', 'Play-off de ascenso') es sustantivo común y sí va en minúscula."""
    return label if label.endswith("League") else label.lower()


_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_es(iso):
    """'2026-09-06' -> '6 de septiembre'. Para prosa; en tablas se deja el ISO,
    que ordena. Devuelve el original si no es una fecha ISO (el calendario viene
    de ESPN y no se le exige formato)."""
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return f"{d} de {_MESES[m - 1]}"
    except (ValueError, IndexError):
        return iso


def plural(n, singular, plural_=None):
    """'1 punto' / '3 puntos'. Sin esto salía 'Está a 1 puntos'."""
    return f"{n} {singular if abs(n) == 1 else (plural_ or singular + 's')}"


if __name__ == "__main__":  # python3 -m seo.textutil
    assert zone_label("Champions League") == "Champions League"
    assert zone_label("Europa League") == "Europa League"
    assert zone_label("Conference League") == "Conference League"
    assert zone_label("Descenso") == "descenso"
    assert zone_label("Ascenso directo") == "ascenso directo"
    assert zone_label("Play-off de ascenso") == "play-off de ascenso"
    assert zone_label("Descenso a Segunda") == "descenso a segunda"
    assert ordinal(3) == "3º" and ordinal(3, fem=True) == "3ª"
    assert fecha_es("2026-09-06") == "6 de septiembre"
    assert fecha_es("mañana") == "mañana"          # no revienta con basura
    assert plural(1, "punto") == "1 punto"
    assert plural(0, "punto") == "0 puntos"
    assert plural(-1, "punto") == "-1 punto"
    print("ok")
