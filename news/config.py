"""Configuración del agregador de noticias.

Todo lo que varía (feeds, límites, alias coloquiales) vive aquí. Añadir un medio
nuevo = una entrada en FEEDS; añadir un mote de equipo = una entrada en
COLLOQUIAL_ALIASES. Ningún otro fichero cambia.
"""

from pathlib import Path

# ── Rutas ───────────────────────────────────────────────────────────────────
# El paquete vive en <repo>/news/ ; la web se sirve desde <repo>/.
ROOT     = Path(__file__).resolve().parent.parent
NEWS_DIR = ROOT / "data" / "news"        # salida (gitignored, como el resto de data/)

# ── Feeds RSS ────────────────────────────────────────────────────────────────
# source      → nombre visible de la fuente (atribución en la tarjeta)
# home        → home del medio (por si hace falta enlazar la marca)
# url         → feed RSS
# league_hint → liga por defecto del feed si el ítem no revela equipo:
#               "laliga" / "hypermotion" / None (feed general → sin pista)
#
# Verificados (2026-08): los tres devuelven HTTP 200 con el UA por defecto de
# urllib y traen <category> con nombre de equipo, resumen corto en <description>
# (o <media:description>) y `content:encoded` con el CUERPO COMPLETO — que NO se
# usa. Marca tiene feed POR liga; AS y MD son de fútbol general.
FEEDS = [
    {
        "source": "Marca",
        "home": "https://www.marca.com/",
        "url": "https://e00-marca.uecdn.es/rss/futbol/primera-division.xml",
        "league_hint": "laliga",
    },
    {
        "source": "Marca",
        "home": "https://www.marca.com/",
        "url": "https://e00-marca.uecdn.es/rss/futbol/segunda-division.xml",
        "league_hint": "hypermotion",
    },
    {
        "source": "AS",
        "home": "https://as.com/",
        "url": "https://feeds.as.com/mrss-s/pages/as/site/as.com/section/futbol/portada/",
        "league_hint": None,
    },
    {
        "source": "Mundo Deportivo",
        "home": "https://www.mundodeportivo.com/",
        "url": "https://www.mundodeportivo.com/feed/rss/futbol",
        "league_hint": None,
    },
]

# Ligas que interesan (slug → espn_code) para construir la tabla de alias de
# equipos EN VIVO desde ESPN (sin hardcode; se actualiza con ascensos/descensos).
LEAGUES = {
    "laliga":      "esp.1",
    "hypermotion": "esp.2",
}

# ── Límites ──────────────────────────────────────────────────────────────────
SUMMARY_MAXLEN = 220     # resumen CORTO: se trunca aquí pase lo que pase (legal)
PER_FEED_LIMIT = 40      # tope de ítems por feed (MD sirve ~100; no lo dejamos dominar)
MAX_ITEMS      = 90      # tope global tras ordenar por fecha desc
MAX_AGE_DAYS   = 12      # se descartan noticias más viejas (esto son "noticias")

HTTP_TIMEOUT   = 20      # s por feed
# NO poner UA de navegador (mismo gotcha 403 que ESPN, ver CLAUDE.md). El UA por
# defecto de urllib pasa en Marca/AS/MD (verificado). _HEADERS vacío = urllib
# añade su propio "Python-urllib/x.y".
HTTP_HEADERS   = {}

# ── Alias coloquiales de equipo (SOLO inequívocos) ───────────────────────────
# Clave = subcadena normalizada que aparece en el displayName de ESPN del equipo
# (minúsculas, sin acentos, sin puntos). Valor = motes/formas cortas.
# HEURÍSTICO y AMPLIABLE. Se omiten a propósito motes ambiguos entre clubes
# (p. ej. "rojiblanco" = Athletic/Atlético/Sevilla/Rayo…). Además, cualquier alias
# que acabe apuntando a >1 equipo se descarta automáticamente en tagging.py, así
# que las colisiones no generan falsos positivos.
COLLOQUIAL_ALIASES = {
    "barcelona":     ["barça", "barsa", "culé", "cule", "azulgrana", "blaugrana"],
    "real madrid":   ["madrid", "merengue", "merengues", "blancos"],
    "atletico de madrid": ["atleti", "atletico", "colchonero", "colchoneros"],
    "athletic":      ["athletic", "leones"],
    "valencia":      ["che"],
    "villarreal":    ["submarino", "groguet"],
    "real sociedad": ["la real", "erreala", "txuri"],
    "espanyol":      ["perico", "periquito", "periquitos"],
    "real betis":    ["betis", "verdiblanco", "betico"],
    "sevilla":       ["nervionense"],
    "getafe":        ["azulon"],
    "osasuna":       ["rojillo", "rojillos"],
}
