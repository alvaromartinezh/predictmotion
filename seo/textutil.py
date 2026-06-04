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


def ordinal(n):
    """1 -> '1º'."""
    return f"{n}º"


def de_league(league):
    """Concordancia: 'de la Liga Hypermotion', 'de LaLiga', 'de la Copa del Mundo'."""
    art = league.get("article", "")
    return f"de {art + ' ' if art else ''}{league['name']}"


def en_league(league):
    """Concordancia: 'en la Liga Hypermotion', 'en LaLiga', 'en la Copa del Mundo'."""
    art = league.get("article", "")
    return f"en {art + ' ' if art else ''}{league['name']}"
