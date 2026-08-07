"""
Configuración central del generador de páginas SEO de PredictMotion.

Todo lo que varía entre ligas vive en LEAGUES. Para añadir una liga nueva del
mundo basta con añadir una entrada aquí: ningún otro fichero necesita cambios
para las ligas de tipo "table".

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


# ── Prior de fuerza por equipo (Elo sin estado desde la temporada anterior) ──
# En pretemporada (0 partidos) el Monte Carlo, que solo usa p_home/p_draw
# constantes, daba a TODOS los equipos el mismo %. Este prior diferencia a los
# equipos usando la tabla FINAL de la temporada anterior (traída en vivo de ESPN
# con ?season=; sin estado, se recalcula cada run). El prior se DESVANECE a lo
# largo de la primera mitad de temporada, hasta que a media temporada el modelo
# vuelve a estar 100% dirigido por los resultados reales.
#
# ⚠️ PARÁMETROS HEURÍSTICOS — PENDIENTES DE CALIBRAR CON DATOS REALES.
# Los tres valores de abajo (LEVEL_GAP, SCALE, FADE_FRACTION) son estimaciones
# iniciales validadas solo "a ojo" contra la 2025-26. Cuando exista el registro
# histórico de predicciones (snapshots por jornada) se podrá medir la calibración
# real (Brier/reliability) y ajustarlos. NO tratarlos como definitivos.
#
# STRENGTH_DIVISIONS: divisiones ordenadas de más fuerte a más débil. El offset de
#   nivel entre divisiones consecutivas es STRENGTH_LEVEL_GAP (en unidades z), lo
#   que hunde a Segunda para que su cabeza caiga en el tercio bajo de Primera.
STRENGTH_DIVISIONS   = ["esp.1", "esp.2"]
STRENGTH_LEVEL_GAP   = 2.5    # separación entre divisiones, en unidades z de puntos
STRENGTH_SCALE       = 0.28   # cuánto sesga el partido una diferencia de 1 unidad
                              # (0.28: Barça ~38% título/~79% top-4; equilibra
                              #  LaLiga top-heavy con la Segunda más caótica)
STRENGTH_FADE_FRACTION = 0.5  # fracción de temporada sobre la que se desvanece


def _table_bands(slots):
    """Devuelve una función bands(n) -> lista de bandas de zona ordenadas.

    `slots` es una lista de tuplas (key, label, color, lo_expr, hi_expr[, zone])
    donde lo_expr/hi_expr son callables (n) -> rank (1-based, inclusivo). Se
    calcula en runtime con el número real de equipos de la API. El 6º elemento
    opcional `zone` ('promo'/'europa'/'conf'/'relega') asocia la banda con la
    zona que ESPN marca en sus notas, para derivar los cortes en vivo (ver
    `bands_from_notes` y `derive_bands_from_notes`); los lo/hi son el fallback.
    """
    def bands(n):
        out = []
        for slot in slots:
            key, label, color, lo, hi = slot[:5]
            zone = slot[5] if len(slot) > 5 else None
            out.append({
                "key": key, "label": label, "color": color,
                "lo": lo(n), "hi": hi(n), "zone": zone,
            })
        return out
    return bands


# ── Registro de ligas ──────────────────────────────────────────────────────
# slug        → identificador en URLs (/equipos/<slug>/...)
# espn_code   → código de liga en la API de ESPN
# kind        → "table" (liga regular)
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
        "dashboard": "/hypermotion",
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
        # Cortes europeos derivados EN VIVO de las notas de ESPN (España tiene 5
        # plazas de Champions desde 2024-25; nada hardcodeado). Los lo/hi de abajo
        # son solo fallback si ESPN no trae notas (inicio de temporada). Ver
        # `derive_bands_from_notes`, que replica el deriveSlots del dashboard.
        "bands_from_notes": True,
        "bands": _table_bands([
            ("champions",  "Champions League",  "green",  lambda n: 1,     lambda n: 5, "promo"),
            ("europa",     "Europa League",     "blue",   lambda n: 6,     lambda n: 6, "europa"),
            ("conference", "Conference League", "violet", lambda n: 7,     lambda n: 7, "conf"),
            ("descenso",   "Descenso a Segunda","red",    lambda n: n - 2, lambda n: n, "relega"),
        ]),
    },
]


def league_by_slug(slug):
    for lg in LEAGUES:
        if lg["slug"] == slug:
            return lg
    return None
