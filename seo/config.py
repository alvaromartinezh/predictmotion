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

# TEAM_LOGOS: sobreescrituras de escudo por id de equipo ESPN (clave) cuando el
# escudo oficial de ESPN es un 404 o no se sirve. Excepción puntual y curada a
# mano (lo normal es "nada hardcodeado": logos en vivo). Futuro club B de Celta
# usa el mismo escudo que el primer equipo (id 85).
TEAM_LOGOS = {
    "131858": "https://a.espncdn.com/i/teamlogos/soccer/500/85.png",  # Celta Fortuna → Celta Vigo
}


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
# STRENGTH_LADDERS: escaleras de ascenso/descenso POR PAÍS, cada una de la
#   división más fuerte a la más débil. El offset de nivel entre divisiones
#   consecutivas de una misma escalera es STRENGTH_LEVEL_GAP (en unidades z), lo
#   que hunde a la 2ª para que su cabeza caiga en el tercio bajo de la 1ª. Los ids
#   de ESPN son globales, así que build_strength_ratings fusiona todas las
#   escaleras en un único {team_id: R}. Solo se descargan las escaleras que
#   contienen alguna liga activa (ver active_codes), sin peticiones de más.
STRENGTH_LADDERS = [
    ["esp.1", "esp.2"],   # España
    ["eng.1", "eng.2"],   # Inglaterra
    ["ita.1", "ita.2"],   # Italia
    ["ger.1", "ger.2"],   # Alemania
    ["fra.1", "fra.2"],   # Francia
    ["por.1"],            # Portugal (solo 1ª cubierta)
    ["ned.1"],            # Países Bajos (solo 1ª cubierta)
]
STRENGTH_LEVEL_GAP   = 2.5    # separación entre divisiones, en unidades z de puntos
STRENGTH_SCALE       = 0.28   # cuánto sesga el partido una diferencia de 1 unidad
                              # (0.28: Barça ~38% título/~79% top-4; equilibra
                              #  LaLiga top-heavy con la Segunda más caótica)
STRENGTH_FADE_FRACTION = 0.5  # fracción de temporada sobre la que se desvanece


# ── Modelo de calibración v2 (Fase 4) — ACTIVO (validado 2026-08-10) ──────────
# Validado OFFLINE (seo/backtest.py) contra RESULTADOS reales de 4 temporadas: mejora
# Brier/LogLoss/ECE por-partido y la predicción del campeón real, y cuadra el mercado
# de los favoritos dominantes (arregla el bug "Bayern 38%"). Tres piezas:
#   1. rating ABSOLUTO por diferencia de goles/partido (NO z-score → conserva la
#      escala de dominancia que el z-score aplasta),
#   2. encogido del EMPATE al crecer |Δfuerza| (el empate ya no es fijo),
#   3. desvanecimiento del prior DENTRO de la proyección (el frozen-w del modelo vivo
#      sobre-confía al componer 34 partidos; decaer sobre la temporada proyectada
#      predice MEJOR el campeón real).
# Shadow-compare de las 15 ligas revisado antes de activar (OFF era bit-idéntico al
# modelo vivo; verificado). Las 3 UEFA no cambian (use_strength=False → uniforme).
#
# LÍMITE CONOCIDO Y DOCUMENTADO — infra-predicción de favoritos MUY dominantes (p. ej.
# PSG ~50% modelo vs ~90% mercado 2026-27). Es el TECHO de un modelo SOLO-RESULTADOS:
# el mercado incorpora valor de plantilla/fichajes que ESPN NO expone (roster sin
# métrica de calidad ni histórico que diferenciar; sin market value ni xG). NO se
# persigue con más hiperparámetros. Se probó explícitamente ponderar por RECENCIA el
# prior por partido (half-life sobre los partidos de la temporada previa, `--recency`
# en backtest.py): empeora Brier/LogLoss y el backtest de campeón de forma monótona,
# y NO acerca a PSG (los dominantes bajan su ritmo a final de liga → su forma reciente
# es MENOR que su nivel real). Rechazado; vive solo en el harness offline. v2 con
# rating de tabla agregada es la mejor versión validada. Cerrar el hueco requeriría
# una fuente externa de valor de plantilla que hoy no tenemos.
USE_ABSOLUTE_RATING     = True    # master flag del modelo v2 (ACTIVO desde 2026-08-10)
STRENGTH_SCALE_ABS      = 1.5     # escala sobre la dif. de goles/partido (v2)
STRENGTH_LEVEL_GAP_ABS  = 1.5     # offset de nivel entre divisiones, en goles/partido
DRAW_SHRINK_KAPPA       = 0.15    # encoge el empate: p_draw·exp(-kappa·|Δlogit|)
PROJECTION_HORIZON_FADE = 1.0     # el prior decae a 0 en N·temporada proyectada (None=frozen)

# ── Prior MULTI-TEMPORADA (H1) — validado 2026-08-10 (seo/backtest.py --multi) ──
# El prior de UNA sola temporada previa es de alta varianza: un dominante perenne
# que tuvo un año flojo sale infravalorado (Barça ~2× Madrid, PSG bajo). Mezclar las
# últimas PRIOR_SEASONS temporadas (media de goles/partido ponderada por PRIOR_DECAY**k,
# offset de nivel por división de CADA temporada, keyed por id de ESPN) estabiliza el
# nivel real. Validado OFFLINE vs. resultados reales de 4 temporadas × 7 ligas: bate al
# prior de 1 temporada en Brier/LogLoss y sobre todo en la predicción del campeón real
# (champLogLoss 1.45→1.20), mejora 6/7 ligas (sin overfit a los casos famosos), y acerca
# a PSG (49→60%) y al ratio Barça/Madrid (2.3×→1.7×). n=3/d=0.6 = mejor equilibrio del
# barrido (n=4 apenas mejora). Solo muerde el rating ABSOLUTO; el z-score (ruta OFF) usa
# 1 temporada. PRIOR_SEASONS=1 reproduce la salida previa BIT A BIT (ancla verificada).
# Descartado extender el histórico vía datasets externos (football-data.co.uk): licencia
# ambigua para un sitio monetizado y, con este decaimiento rápido, upside marginal
# (el peso cae <10% pasada la 5ª temporada; el barrido ya satura en 3-4).
PRIOR_SEASONS           = 3       # nº de temporadas previas a mezclar (1 = comportamiento antiguo)
PRIOR_DECAY             = 0.6     # peso geométrico de cada temporada más antigua (decay**k)


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


# ── Plantillas de banda reutilizables (por tipo de liga) ─────────────────────
# Los lo/hi son solo FALLBACK; con bands_from_notes=True los cortes reales se
# derivan en vivo de las notas de ESPN (derive_bands_from_notes), que son
# pan-europeas. Así una liga nueva reusa la plantilla de su nivel sin números
# hardcodeados por país.
def euro_top1_bands():
    """1ª división europea: Champions / Europa / Conference / descenso."""
    return _table_bands([
        ("champions",  "Champions League",  "green",  lambda n: 1,     lambda n: 4, "promo"),
        ("europa",     "Europa League",     "blue",   lambda n: 5,     lambda n: 6, "europa"),
        ("conference", "Conference League", "violet", lambda n: 7,     lambda n: 7, "conf"),
        ("descenso",   "Descenso",          "red",    lambda n: n - 2, lambda n: n, "relega"),
    ])


def euro_top2_bands():
    """2ª división europea: ascenso directo / play-off de ascenso / descenso."""
    return _table_bands([
        ("ascenso",  "Ascenso directo",     "green", lambda n: 1,     lambda n: 2, "promo"),
        ("playoff",  "Play-off de ascenso", "blue",  lambda n: 3,     lambda n: 6, "playoff"),
        ("descenso", "Descenso",            "red",   lambda n: n - 2, lambda n: n, "relega"),
    ])


def euro_league_phase_bands():
    """Fase de liga UEFA (36 equipos, 8 partidos): octavos directos (1º–8º) /
    play-off de eliminatorias (9º–24º) / eliminado (25º–36º). Reusa las mismas
    zonas internas que el resto (promo/playoff/relega) para que
    derive_bands_from_notes derive los cortes de las notas de ESPN sin lógica
    nueva. Los lo/hi son fallback (inicio de fase, sin notas)."""
    return _table_bands([
        ("octavos",   "Octavos de final",          "green", lambda n: 1,      lambda n: 8,      "promo"),
        ("playoff",   "Play-off de eliminatorias", "blue",  lambda n: 9,      lambda n: n - 12, "playoff"),
        ("eliminado", "Eliminado",                 "red",   lambda n: n - 11, lambda n: n,      "relega"),
    ])


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
        # Generación del dashboard estático (render_dashboard): plantilla + tokens.
        "dashboard_template": "top2",
        "subtitle": "Segunda División",
        "shortname": "Hypermotion",
        "releg_to": "Primera RFEF",
        "country": "España",
        "about": "La Liga Hypermotion, segunda categoría del fútbol español, reúne cada temporada a 22 clubes que pelean por el ascenso a LaLiga. Los dos primeros clasifican directos; del tercero al sexto se juegan el ascenso en un play-off a doble partido, mientras los cuatro últimos pierden la categoría. En PredictMotion se simula la temporada completa para estimar la probabilidad real de cada equipo de ascender, jugar el play-off o descender.",
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
        "dashboard_template": "top1",
        "subtitle": "Primera División",
        "country": "España",
        "about": "LaLiga, la máxima categoría del fútbol español, reúne a 20 clubes que luchan cada temporada por el título, las plazas europeas y la permanencia. Los puestos de cabeza se juegan la Champions League, la Europa League y la Conference League, mientras los tres últimos descienden a Segunda División. En PredictMotion se simula el resto de la temporada para estimar la probabilidad de cada equipo de acabar campeón, clasificarse para Europa o descender.",
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

    # ── Fase 1: 1ª división europea (plantilla top1, zonas por notas de ESPN) ──
    # p_home/p_draw HEURÍSTICOS (medias aproximadas por liga), PENDIENTES DE
    # CALIBRAR con el registro de predicciones. Las 2as (eng.2, ita.2, …) irán con
    # una variante top2 (slots por notas, sin bracket), aún por añadir.
    {
        "slug": "premier", "espn_code": "eng.1", "kind": "table",
        "name": "Premier League", "article": "la", "season": "2025-26",
        "country": "Inglaterra", "dashboard": "/premier",
        "dashboard_template": "top1", "subtitle": "Inglaterra",
        "about": "La Premier League, primera división del fútbol inglés, es una de las competiciones más seguidas del mundo con 20 clubes. El título, las plazas de Champions League, Europa League y Conference League, y la permanencia se deciden jornada a jornada; los tres últimos descienden al Championship. En PredictMotion se simula el resto de la temporada para estimar la probabilidad de cada equipo de clasificarse para Europa o descender.",
        "p_home": 0.45, "p_draw": 0.24, "playoff_top": None,
        "bands_from_notes": True, "bands": euro_top1_bands(),
    },
    {
        "slug": "seriea", "espn_code": "ita.1", "kind": "table",
        "name": "Serie A", "article": "la", "season": "2025-26",
        "country": "Italia", "dashboard": "/seriea",
        "dashboard_template": "top1", "subtitle": "Italia",
        "about": "La Serie A, máxima categoría del fútbol italiano, enfrenta a 20 clubes por el scudetto y las plazas europeas. Los puestos de cabeza dan acceso a Champions League, Europa League y Conference League, mientras los tres últimos descienden a la Serie B. En PredictMotion se simula el resto de la temporada para estimar la probabilidad de cada equipo de clasificarse para Europa o descender.",
        "p_home": 0.45, "p_draw": 0.27, "playoff_top": None,
        "bands_from_notes": True, "bands": euro_top1_bands(),
    },
    {
        "slug": "bundesliga", "espn_code": "ger.1", "kind": "table",
        "name": "Bundesliga", "article": "la", "season": "2025-26",
        "country": "Alemania", "dashboard": "/bundesliga",
        "dashboard_template": "top1", "subtitle": "Alemania",
        "about": "La Bundesliga, primera división del fútbol alemán, cuenta con 18 clubes en lugar de los 20 habituales en otras grandes ligas. Cada temporada se disputan el título, las plazas de Champions League, Europa League y Conference League, y la permanencia; los dos últimos descienden y el antepenúltimo juega una promoción. En PredictMotion se simula el resto de la temporada para estimar la probabilidad de cada equipo de clasificarse para Europa o descender.",
        "p_home": 0.44, "p_draw": 0.24, "playoff_top": None,
        "bands_from_notes": True, "bands": euro_top1_bands(),
    },
    {
        "slug": "ligue1", "espn_code": "fra.1", "kind": "table",
        "name": "Ligue 1", "article": "la", "season": "2025-26",
        "country": "Francia", "dashboard": "/ligue1",
        "dashboard_template": "top1", "subtitle": "Francia",
        "about": "La Ligue 1, máxima categoría del fútbol francés, reúne a 18 clubes que pelean por el título, las plazas de Champions League, Europa League y Conference League, y la permanencia. Los equipos que terminan en las últimas posiciones descienden a la Ligue 2. En PredictMotion se simula el resto de la temporada para estimar la probabilidad de cada equipo de clasificarse para Europa o descender.",
        "p_home": 0.45, "p_draw": 0.27, "playoff_top": None,
        "bands_from_notes": True, "bands": euro_top1_bands(),
    },
    {
        "slug": "primeira", "espn_code": "por.1", "kind": "table",
        "name": "Primeira Liga", "article": "la", "season": "2025-26",
        "country": "Portugal", "dashboard": "/primeira",
        "dashboard_template": "top1", "subtitle": "Portugal",
        "about": "La Primeira Liga, primera división del fútbol portugués, la disputan 18 clubes cada temporada. Además del título, los puestos de cabeza dan acceso a la Champions League y a la Europa League, mientras los tres últimos descienden a la segunda categoría. En PredictMotion se simula el resto de la temporada para estimar la probabilidad de cada equipo de clasificarse para Europa o descender.",
        "p_home": 0.46, "p_draw": 0.27, "playoff_top": None,
        "bands_from_notes": True, "bands": euro_top1_bands(),
    },
    {
        "slug": "eredivisie", "espn_code": "ned.1", "kind": "table",
        "name": "Eredivisie", "article": "la", "season": "2025-26",
        "country": "Países Bajos", "dashboard": "/eredivisie",
        "dashboard_template": "top1", "subtitle": "Países Bajos",
        "about": "La Eredivisie, máxima categoría del fútbol neerlandés, enfrenta cada temporada a 18 clubes por el título y las plazas europeas de Champions League y Europa League. Los tres últimos descienden, mientras el penúltimo juega una promoción por la permanencia. En PredictMotion se simula el resto de la temporada para estimar la probabilidad de cada equipo de clasificarse para Europa o descender.",
        "p_home": 0.46, "p_draw": 0.24, "playoff_top": None,
        "bands_from_notes": True, "bands": euro_top1_bands(),
    },

    # ── Fase 1b: 2ª división europea (plantilla tier2, slots por notas, SIN
    #    bracket). playoff_top=None → sin simulación de eliminatoria; la zona
    #    "play-off de ascenso" se muestra por posición (cortes de las notas).
    {
        "slug": "championship", "espn_code": "eng.2", "kind": "table",
        "name": "Championship", "article": "la", "season": "2025-26",
        "country": "Inglaterra", "dashboard": "/championship",
        "dashboard_template": "tier2", "subtitle": "Inglaterra",
        "shortname": "Championship", "releg_to": "League One",
        "about": "El Championship es la segunda división del fútbol inglés y una de las ligas más igualadas de Europa, con 24 clubes. Los dos primeros ascienden directos a la Premier League; del tercero al sexto juegan un play-off por la última plaza de ascenso, mientras los tres últimos descienden a la League One. En PredictMotion se simula la temporada completa para estimar la probabilidad real de cada equipo de ascender, jugar el play-off o descender.",
        "p_home": 0.45, "p_draw": 0.26, "playoff_top": None,
        "bands_from_notes": True, "bands": euro_top2_bands(),
    },
    {
        "slug": "serieb", "espn_code": "ita.2", "kind": "table",
        "name": "Serie B", "article": "la", "season": "2025-26",
        "country": "Italia", "dashboard": "/serieb",
        "dashboard_template": "tier2", "subtitle": "Italia",
        "shortname": "Serie B", "releg_to": "Serie C",
        "about": "La Serie B, segunda categoría del fútbol italiano, la disputan 20 clubes cada temporada. Los dos primeros ascienden directos a la Serie A; del tercero al octavo se juegan el ascenso en un play-off, mientras los tres últimos descienden a la Serie C. En PredictMotion se simula la temporada completa para estimar la probabilidad real de cada equipo de ascender, jugar el play-off o descender.",
        "p_home": 0.45, "p_draw": 0.28, "playoff_top": None,
        "bands_from_notes": True, "bands": euro_top2_bands(),
    },
    {
        "slug": "bundesliga2", "espn_code": "ger.2", "kind": "table",
        "name": "2. Bundesliga", "article": "la", "season": "2025-26",
        "country": "Alemania", "dashboard": "/bundesliga2",
        "dashboard_template": "tier2", "subtitle": "Alemania",
        "shortname": "2. Bundesliga", "releg_to": "3. Liga",
        "about": "La 2. Bundesliga, segunda división del fútbol alemán, la disputan 18 clubes cada temporada. Los dos primeros ascienden directos a la Bundesliga y el tercero juega una promoción de ascenso, mientras los dos últimos descienden a la 3. Liga y el antepenúltimo se juega la permanencia. En PredictMotion se simula la temporada completa para estimar la probabilidad real de cada equipo de ascender, jugar la promoción o descender.",
        "p_home": 0.44, "p_draw": 0.26, "playoff_top": None,
        "bands_from_notes": True, "bands": euro_top2_bands(),
    },
    {
        "slug": "ligue2", "espn_code": "fra.2", "kind": "table",
        "name": "Ligue 2", "article": "la", "season": "2025-26",
        "country": "Francia", "dashboard": "/ligue2",
        "dashboard_template": "tier2", "subtitle": "Francia",
        "shortname": "Ligue 2", "releg_to": "National",
        "about": "La Ligue 2, segunda categoría del fútbol francés, la disputan 18 clubes cada temporada. Los dos primeros ascienden directos a la Ligue 1 y del tercero al sexto se juegan el ascenso en un play-off, mientras los dos últimos descienden al National. En PredictMotion se simula la temporada completa para estimar la probabilidad real de cada equipo de ascender, jugar el play-off o descender.",
        "p_home": 0.45, "p_draw": 0.28, "playoff_top": None,
        "bands_from_notes": True, "bands": euro_top2_bands(),
    },

    # ── Fase 2: competiciones UEFA (fase de liga, plantilla `uefa`) ─────────────
    # NO son round-robin: 36 equipos, 8 partidos cada uno → `matches_per_team: 8`
    # (el motor lo usa en vez de 2·(n−1)). Zonas por notas de ESPN: octavos
    # directos (1º–8º) / play-off de eliminatorias (9º–24º) / eliminado (25º–36º).
    # `use_strength: False` → modelo UNIFORME, SIN prior de fuerza: el prior actual
    # es por país (z-score dentro de cada escalera) y NO es comparable entre países,
    # así que para 36 clubes de ~15 ligas no daría una fuerza válida. PENDIENTE
    # FASE 4: prior cross-country con dato real (coeficiente UEFA / regresión), no
    # una heurística improvisada. En pretemporada, por tanto, los 36 salen con % casi
    # iguales hasta que se juegan jornadas. p_home/p_draw heurísticos.
    # La fase eliminatoria (bracket) es la Fase 3, aparte.
    {
        "slug": "champions", "espn_code": "uefa.champions", "kind": "table",
        "name": "Champions League", "article": "la", "season": "2025-26",
        "country": "Europa", "dashboard": "/champions",
        "dashboard_template": "uefa", "subtitle": "Fase de liga",
        "about": "La Champions League estrena formato de fase de liga: 36 clubes, cada uno contra 8 rivales distintos, en una tabla única en lugar de grupos. Los ocho primeros clasifican directos a octavos de final; del noveno al vigésimo cuarto juegan un play-off de eliminatorias y el resto queda eliminado. En PredictMotion se simula la fase de liga completa para estimar la probabilidad real de cada club de clasificarse para octavos, jugar el play-off o quedar eliminado.",
        "p_home": 0.45, "p_draw": 0.25, "playoff_top": None,
        "matches_per_team": 8, "use_strength": False,
        "bands_from_notes": True, "bands": euro_league_phase_bands(),
    },
    {
        "slug": "europa", "espn_code": "uefa.europa", "kind": "table",
        "name": "Europa League", "article": "la", "season": "2025-26",
        "country": "Europa", "dashboard": "/europa",
        "dashboard_template": "uefa", "subtitle": "Fase de liga",
        "about": "La Europa League usa también el nuevo formato de fase de liga con 36 clubes, cada uno contra 8 rivales distintos en una tabla única. Los ocho primeros clasifican directos a octavos de final; del noveno al vigésimo cuarto juegan un play-off de eliminatorias y el resto queda eliminado. En PredictMotion se simula la fase de liga completa para estimar la probabilidad real de cada club de clasificarse para octavos, jugar el play-off o quedar eliminado.",
        "p_home": 0.45, "p_draw": 0.25, "playoff_top": None,
        "matches_per_team": 8, "use_strength": False,
        "bands_from_notes": True, "bands": euro_league_phase_bands(),
    },
    {
        "slug": "conference", "espn_code": "uefa.europa.conf", "kind": "table",
        "name": "Conference League", "article": "la", "season": "2025-26",
        "country": "Europa", "dashboard": "/conference",
        "dashboard_template": "uefa", "subtitle": "Fase de liga",
        "about": "La Conference League, tercera competición europea de clubes, adopta el mismo formato de fase de liga que las demás: 36 equipos, cada uno contra 8 rivales distintos, en una tabla única. Los ocho primeros clasifican directos a octavos de final; del noveno al vigésimo cuarto juegan un play-off de eliminatorias y el resto queda eliminado. En PredictMotion se simula la fase de liga completa para estimar la probabilidad real de cada club de clasificarse para octavos, jugar el play-off o quedar eliminado.",
        "p_home": 0.45, "p_draw": 0.25, "playoff_top": None,
        "matches_per_team": 8, "use_strength": False,
        "bands_from_notes": True, "bands": euro_league_phase_bands(),
    },
]


def league_by_slug(slug):
    for lg in LEAGUES:
        if lg["slug"] == slug:
            return lg
    return None
