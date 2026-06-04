"""
Configuración central del generador de páginas SEO de PredictMotion.

Todo lo que varía entre ligas vive en LEAGUES. Para añadir una liga nueva del
mundo basta con añadir una entrada aquí: ningún otro fichero necesita cambios
para las ligas de tipo "table". Las ligas tipo "cup" (Mundial) usan sim_cup.

No hay texto redactado a mano en ningún sitio: todas las frases de las páginas
se construyen con f-strings a partir de datos reales de la simulación.
"""

from pathlib import Path

# ── Rutas ──────────────────────────────────────────────────────────────────
# El paquete vive en <repo>/seo/ ; la web se sirve desde <repo>/.
ROOT      = Path(__file__).resolve().parent.parent
DATA_DIR  = ROOT / "data"            # snapshots persistidos (gitignored)

SITE      = "https://predictmotion.com"

# Tamaño del Monte Carlo del lado servidor. Es muestreo: los porcentajes son
# equivalentes (dentro del ruido) a los 40 000 del navegador. Más bajo aquí
# para que el cron termine rápido en la VM ARM.
SIM_N_TABLE = 20000
SIM_N_CUP   = 5000


def _table_bands(slots):
    """Devuelve una función bands(n) -> lista de bandas de zona ordenadas.

    `slots` es una lista de tuplas (key, label, color, lo_expr, hi_expr) donde
    lo_expr/hi_expr son callables (n) -> rank (1-based, inclusivo). Se calcula
    en runtime con el número real de equipos de la API.
    """
    def bands(n):
        out = []
        for key, label, color, lo, hi in slots:
            out.append({
                "key": key, "label": label, "color": color,
                "lo": lo(n), "hi": hi(n),
            })
        return out
    return bands


# ── Registro de ligas ──────────────────────────────────────────────────────
# slug        → identificador en URLs (/equipos/<slug>/...)
# espn_code   → código de liga en la API de ESPN
# kind        → "table" (liga regular) | "cup" (Mundial)
# name        → nombre mostrado
# dashboard   → URL limpia del dashboard existente (no se toca)
# p_home/p_draw → medias históricas usadas por el Monte Carlo (idénticas al JS)
# playoff_top → si existe, hay play-off de ascenso (top N incluye los directos)
# bands(n)    → bandas de zona para derivar probabilidades por posición

LEAGUES = [
    {
        "slug": "hypermotion",
        "espn_code": "esp.2",
        "kind": "table",
        "name": "Liga Hypermotion",
        "article": "la",          # "de la / en la Liga Hypermotion"
        "season": "2025-26",
        "dashboard": "/",
        "p_home": 0.42,
        "p_draw": 0.27,
        "playoff_top": 6,
        "bands": _table_bands([
            ("ascenso",  "Ascenso directo",     "green", lambda n: 1,     lambda n: 2),
            ("playoff",  "Play-off de ascenso", "blue",  lambda n: 3,     lambda n: 6),
            ("descenso", "Descenso",            "red",   lambda n: n - 3, lambda n: n),
        ]),
    },
    {
        "slug": "laliga",
        "espn_code": "esp.1",
        "kind": "table",
        "name": "LaLiga",
        "article": "",            # el nombre ya lleva artículo: "de / en LaLiga"
        "season": "2025-26",
        "dashboard": "/laliga",
        "p_home": 0.46,
        "p_draw": 0.26,
        "playoff_top": None,
        "bands": _table_bands([
            ("champions",  "Champions League",  "green",  lambda n: 1,     lambda n: 4),
            ("europa",     "Europa League",     "blue",   lambda n: 5,     lambda n: 5),
            ("conference", "Conference League", "violet", lambda n: 6,     lambda n: 6),
            ("descenso",   "Descenso a Segunda","red",    lambda n: n - 2, lambda n: n),
        ]),
    },
    {
        "slug": "mundial",
        "espn_code": "fifa.world",
        "kind": "cup",
        "name": "Copa del Mundo 2026",
        "article": "la",          # "de la / en la Copa del Mundo"
        "season": "2026",
        "dashboard": "/mundial",
        "p_home": 0.37,
        "p_draw": 0.27,
    },
]


def league_by_slug(slug):
    for lg in LEAGUES:
        if lg["slug"] == slug:
            return lg
    return None
