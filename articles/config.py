"""Config del generador de artículos (broadsheet diario + crónicas de
partido, ver articles/generate.py) y del cliente Gemini que usa
(articles/gemini_client.py)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ARTICLES_OUT_DIR = ROOT / "articulos"  # HTML publicado (gitignored, como equipos/)

# Ligas para las que se generan artículos. Mismo patrón que
# seo/tweets.py:TWEET_LEAGUES — añadir un slug aquí (con dashboard_template
# top1/top2/tier2, ver seo/config.py:LEAGUES) es lo único que hace falta para
# activar una liga nueva; generate.py itera esta lista, aislando fallos por
# liga (una excepción o un grounding fallido en una no bloquea a las demás).
ARTICLE_LEAGUES = ["hypermotion", "laliga"]

# Tolerancia del validador de grounding: una cifra "%" generada por Gemini se
# acepta si cae a ±1 punto de algún valor real del payload de hechos
# (redondeos: textutil.pct() usa 1 decimal con coma española, Gemini puede
# redondear distinto).
GROUNDING_TOLERANCE_PP = 1.0

# Primera mitad de temporada (jornada/total_md): ascenso directo y play-off se
# funden en un único "ascenso total" para el número que citan los artículos
# (posiciones aún muy volátiles — separarlos sería ruido, no señal). Pasada
# esta fracción, se listan por separado. Ver articles/grounding.py:_effective_bands.
ASCENSO_TOTAL_SEASON_FRACTION = 0.5

GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_MODEL_GROUNDED = "gemini-2.5-flash"

# "Dato curioso": artículo corto sobre una estadística que el modelo/snapshot YA
# calcula pero que ningún dashboard muestra. Registro único
# (grounding.py/writer.py/render.py lo comparten) — añadir un kind aquí es lo
# único que hace falta para sumar un dato nuevo.
#
# Cada kind declara:
#   - `tipo` (obligatorio), la familia de datos que usa:
#       * "posicion": prob exacta de posición final (prob.first/last, ya en el
#         snapshot). El protagonista es el equipo con mayor prob[prob_key].
#       * "equipo": fuerza del blend v3 (att/def del snapshot) — sin simular
#         nada nuevo, solo leer una desviación que el cron ya persiste.
#       * "jornada": la próxima jornada (fixtures `pre` de ESPN) resuelta con el
#         MISMO modelo v3 del snapshot (match_rates/match_1x2) — quién encaja
#         más goles, quién es favorito, qué partido tiene más nivel. Todo
#         grounding: si no hay fixtures o el snapshot no es v3, no se publica.
#   - `shape` (opcional): "partido" si el protagonista es un PARTIDO (X vs Y) en
#     vez de un equipo (por defecto "team"). La maquetación y los prompts se
#     adaptan solos (ver grounding._match_item/render.py).
#   - `eyebrow`/`verbo`/`verbo_largo` (prosa) y `dato_label` (cabecera del box de
#     ranking). `fmt` (opcional): "goles" para valores en goles/partido con signo
#     (los % por defecto van con pct()).
STAT_KINDS = {
    "colista": {
        "tipo": "posicion", "prob_key": "last", "eyebrow": "Farolillo rojo",
        "verbo": "acabar colista", "verbo_largo": "acabar colista (la última posición de la tabla)",
        "dato_label": "Probabilidad de ser el último",
    },
    "lider": {
        "tipo": "posicion", "prob_key": "first", "eyebrow": "Máximo favorito",
        "verbo": "acabar líder", "verbo_largo": "acabar líder (la primera posición de la tabla)",
        "dato_label": "Probabilidad de acabar 1º",
    },
    "muro": {
        "tipo": "equipo", "campo": "def", "sort": "min", "fmt": "goles",
        "eyebrow": "Muro de la liga", "verbo": "tener la defensa más sólida de la liga",
        "verbo_largo": "tener la defensa más sólida de la liga (menos goles en contra por partido)",
        "dato_label": "Goles en contra por partido (desv. de la media)",
    },
    "ataque": {
        "tipo": "equipo", "campo": "att", "sort": "max", "fmt": "goles",
        "eyebrow": "Ataque más potente", "verbo": "tener el ataque más potente de la liga",
        "verbo_largo": "tener el ataque más potente de la liga (más goles a favor por partido)",
        "dato_label": "Goles a favor por partido (desv. de la media)",
    },
    "goleado": {
        "tipo": "jornada", "eyebrow": "Goleada anunciada",
        "verbo": "ser el más propenso a encajar una goleada en la próxima jornada",
        "verbo_largo": "ser el más propenso a encajar una goleada (3 o más goles) en la próxima jornada",
        "dato_label": "Probabilidad de encajar 3+ goles en su próximo partido",
    },
    "porteria_cero": {
        "tipo": "jornada", "eyebrow": "Muro de la jornada",
        "verbo": "dejar su portería a cero en la próxima jornada",
        "verbo_largo": "dejar su portería a cero en la próxima jornada",
        "dato_label": "Probabilidad de dejar su portería a cero en su próximo partido",
    },
    "favorito_jornada": {
        "tipo": "jornada", "eyebrow": "Favorito de la jornada",
        "verbo": "ser el favorito para ganar su partido de la próxima jornada",
        "verbo_largo": "ser el favorito para ganar su partido de la próxima jornada",
        "dato_label": "Probabilidad de ganar su próximo partido",
    },
    "nivel_jornada": {
        "tipo": "jornada", "shape": "partido", "eyebrow": "Partido de la jornada",
        "verbo": "protagonizar el partido de mayor nivel de la próxima jornada",
        "verbo_largo": "protagonizar el partido de mayor nivel de la próxima jornada (la mayor suma de fuerza de ataque y defensa de ambos equipos)",
        "dato_label": "Nivel del partido (fuerza combinada del blend)",
    },
    "empate_jornada": {
        "tipo": "jornada", "shape": "partido", "eyebrow": "Empate cantado",
        "verbo": "terminar en empate según el modelo de la próxima jornada",
        "verbo_largo": "terminar en empate en la próxima jornada (la mayor probabilidad de empate del modelo)",
        "dato_label": "Probabilidad de empate (1X2 del modelo)",
    },
    "goles_jornada": {
        "tipo": "jornada", "shape": "partido", "fmt": "goles_abs",
        "eyebrow": "Gol esperado", "verbo": "acumular más goles esperados en la próxima jornada",
        "verbo_largo": "acumular más goles esperados en la próxima jornada (la mayor suma de goles esperados de ambos equipos)",
        "dato_label": "Goles esperados del partido (λ local + λ visitante)",
    },
    # ── Tipos de partido de la próxima jornada (shape 'partido') — los 4
    # salen del MISMO modelo v3 (match_rates/match_1x2) que ya usan los de
    # arriba: over_25 = P(total ≥ 3 goles) de la bivariada Poisson, ambos_marcan
    # = P(gol del local Y gol del visitante), sorpresa_jornada = el cruce con
    # más P de victoria del menos favorito (min(p_local, p_visita)), y
    # marcador_jornada = el marcador exacto más probable (la celda máxima de la
    # matriz de marcadores). ──
    "over_25": {
        "tipo": "jornada", "shape": "partido",
        "eyebrow": "Lluvia de goles", "verbo": "superar los 2,5 goles en la próxima jornada",
        "verbo_largo": "superar los 2,5 goles en la próxima jornada (la mayor probabilidad de 3 o más goles según el modelo)",
        "dato_label": "Probabilidad de más de 2,5 goles",
    },
    "ambos_marcan": {
        "tipo": "jornada", "shape": "partido",
        "eyebrow": "Sin porterías a cero", "verbo": "terminar con gol de ambos equipos en la próxima jornada",
        "verbo_largo": "terminar con gol de ambos equipos en la próxima jornada (la mayor probabilidad de 'ambos marcan' según el modelo)",
        "dato_label": "Probabilidad de que marquen los dos",
    },
    "sorpresa_jornada": {
        "tipo": "jornada", "shape": "partido",
        "eyebrow": "Sorpresa a la vista", "verbo": "ser el partido con más opciones de sorpresa de la próxima jornada",
        "verbo_largo": "ser el partido con más opciones de sorpresa de la próxima jornada (la mayor probabilidad de victoria del menos favorito según el modelo)",
        "dato_label": "Probabilidad de sorpresa (victoria del menos favorito)",
    },
    "marcador_jornada": {
        "tipo": "jornada", "shape": "partido",
        "eyebrow": "Marcador más probable", "verbo": "acabar con el marcador más probable de la próxima jornada",
        "verbo_largo": "acabar con el marcador más probable de la próxima jornada (la combinación de goles que el modelo ve más factible)",
        "dato_label": "Probabilidad del marcador exacto",
    },
    # ── Tipos de equipo de la próxima jornada (shape 'team') — complementan a
    # los de arriba con la cara positiva/negativa del mismo 1X2: goleador = P
    # de marcar 3+ goles, invicto_jornada = P de no perder (ganar o empatar) y
    # derrota_jornada = P de perder. ──
    "goleador": {
        "tipo": "jornada",
        "eyebrow": "Pólvora de la jornada", "verbo": "marcar 3 o más goles en la próxima jornada",
        "verbo_largo": "marcar 3 o más goles en la próxima jornada (la mayor probabilidad de golear según el modelo)",
        "dato_label": "Probabilidad de marcar 3+ goles",
    },
    "invicto_jornada": {
        "tipo": "jornada",
        "eyebrow": "A prueba de derrotas", "verbo": "no perder su partido de la próxima jornada",
        "verbo_largo": "no perder en la próxima jornada (la mayor probabilidad de ganar o empatar según el modelo)",
        "dato_label": "Probabilidad de no perder (ganar o empatar)",
    },
    "derrota_jornada": {
        "tipo": "jornada",
        "eyebrow": "En la cuerda floja", "verbo": "perder su partido de la próxima jornada",
        "verbo_largo": "perder su partido de la próxima jornada (la mayor probabilidad de derrota según el modelo)",
        "dato_label": "Probabilidad de perder su próximo partido",
    },
    # ── Tipos de zona: la PROBABILIDAD de moverse de zona, no de una posición
    # concreta. subida_zona = P de acabar en una banda MEJOR que la actual (suma
    # de las bandas por encima); caida_zona = P de acabar en una banda PEOR
    # (suma de las bandas por debajo). Usan las bandas del snapshot (las mismas
    # que pintan los dashboards) y la posición actual del equipo para saber cuál
    # es "su" zona. ──
    "subida_zona": {
        "tipo": "zona", "sort": "desc",
        "eyebrow": "Con hambre de subir", "verbo": "subir de zona en la tabla",
        "verbo_largo": "acabar la temporada en una zona superior a la actual (la mayor probabilidad de ascenso acumulado según el modelo)",
        "dato_label": "Probabilidad de acabar en una zona superior",
    },
    "caida_zona": {
        "tipo": "zona", "sort": "desc",
        "eyebrow": "En la cuerda floja", "verbo": "caer de zona en la tabla",
        "verbo_largo": "acabar la temporada en una zona inferior a la actual (la mayor probabilidad de descenso acumulado según el modelo)",
        "dato_label": "Probabilidad de acabar en una zona inferior",
    },
    # ── La revelación de la temporada: el equipo que más ha MEJORADO la
    # probabilidad de su mejor zona desde el PRIMER snapshot de la temporada
    # hasta hoy. `fmt: "pp"` → el valor se muestra como puntos porcentuales con
    # signo (+15,0 pp), no como un % (es una diferencia, no una probabilidad). ──
    "sorpresa_temporada": {
        "tipo": "temporada", "fmt": "pp",
        "eyebrow": "La revelación del curso", "verbo": "ser la revelación de la temporada",
        "verbo_largo": "ser la revelación de la temporada (el equipo que más ha mejorado su probabilidad de zona desde el arranque)",
        "dato_label": "Mejora de probabilidad de zona desde el arranque",
    },
    # ── El tapado: la mayor probabilidad de acabar 1º entre los que NO lideran
    # hoy (el 'lider' de siempre es el que más prob de 1º tiene, y casi siempre
    # es el propio líder actual; este kind se salta al líder para enseñar al
    # perseguidor con más opciones reales de título). ──
    "tapado": {
        "tipo": "posicion", "prob_key": "first", "exclude_rank_1": True,
        "eyebrow": "El tapado", "verbo": "amenazar el título sin ser líder",
        "verbo_largo": "amenazar el título sin ser el líder actual (la mayor probabilidad de acabar 1º entre los que no mandan)",
        "dato_label": "Probabilidad de acabar 1º (sin ser líder)",
    },
    # ═══════════════════════════════════════════════════════════════════════
    # NUEVOS KINDS (segunda tanda): duplican el catálogo a 42 tipos.
    # Todos derivan de datos que ya persiste el snapshot o del modelo v3 de
    # la próxima jornada; no requieren nuevos endpoints ni simulaciones.
    # ═══════════════════════════════════════════════════════════════════════
    # ── Zonas específicas ──
    "descenso": {
        "tipo": "zona_especifica", "zone_type": "relega",
        "eyebrow": "Cuesta abajo", "verbo": "descender de categoría",
        "verbo_largo": "descender de categoría al final de la temporada",
        "dato_label": "Probabilidad de descenso",
    },
    "ascenso_directo": {
        "tipo": "zona_especifica", "zone_type": "promo",
        "eyebrow": "Ascenso en puerta", "verbo": "ascender de categoría de forma directa",
        "verbo_largo": "ascender de categoría de forma directa (sin playoff)",
        "dato_label": "Probabilidad de ascenso directo",
    },
    "playoff": {
        "tipo": "zona_especifica", "zone_type": "playoff",
        "eyebrow": "Play-off a la vista", "verbo": "jugar el playoff de ascenso",
        "verbo_largo": "jugar el playoff de ascenso al final de la temporada",
        "dato_label": "Probabilidad de jugar el playoff",
    },
    "champions": {
        "tipo": "zona_especifica", "zone_type": "champions",
        "eyebrow": "Aroma a Champions", "verbo": "clasificarse para la Champions League",
        "verbo_largo": "clasificarse para la Champions League al final de la temporada",
        "dato_label": "Probabilidad de jugar la Champions League",
    },
    "europa": {
        "tipo": "zona_especifica", "zone_type": "europa",
        "eyebrow": "Rumbo a Europa", "verbo": "clasificarse para la Europa League",
        "verbo_largo": "clasificarse para la Europa League al final de la temporada",
        "dato_label": "Probabilidad de jugar la Europa League",
    },
    # ── Fuerza del blend v3 (cara B) ──
    "coladero": {
        "tipo": "equipo", "campo": "def", "sort": "max", "fmt": "goles",
        "eyebrow": "Coladero de la liga", "verbo": "tener la defensa más permeable de la liga",
        "verbo_largo": "tener la defensa más permeable de la liga (más goles en contra por partido)",
        "dato_label": "Goles en contra por partido (desv. de la media)",
    },
    "peor_ataque": {
        "tipo": "equipo", "campo": "att", "sort": "min", "fmt": "goles",
        "eyebrow": "Ataque más apagado", "verbo": "tener el ataque más apagado de la liga",
        "verbo_largo": "tener el ataque más apagado de la liga (menos goles a favor por partido)",
        "dato_label": "Goles a favor por partido (desv. de la media)",
    },
    "equilibrio": {
        "tipo": "equipo", "campo": "balance", "sort": "max", "fmt": "goles",
        "eyebrow": "Equipo más equilibrado", "verbo": "tener el balance ataque-defensa más sólido de la liga",
        "verbo_largo": "tener el balance ataque-defensa más sólido (la mayor diferencia a favor del blend)",
        "dato_label": "Balance ataque-defensa (goles/partido)",
    },
    "desequilibrio": {
        "tipo": "equipo", "campo": "imbalance", "sort": "max", "fmt": "goles",
        "eyebrow": "Equipo más irregular", "verbo": "tener el ataque y la defensa más descompensados de la liga",
        "verbo_largo": "tener el ataque y la defensa más descompensados (la mayor diferencia absoluta entre att y def)",
        "dato_label": "Desequilibrio ataque-defensa (goles/partido)",
    },
    # ── Goles reales ya anotados ──
    "goleador_real": {
        "tipo": "goles", "campo": "gf_por_partido", "sort": "max", "fmt": "goles_abs",
        "eyebrow": "Máximo goleador real", "verbo": "marcar más goles por partido de lo que dice la media",
        "verbo_largo": "marcar más goles por partido (dato real de la temporada, no el modelo)",
        "dato_label": "Goles a favor por partido (real)",
    },
    "coladero_real": {
        "tipo": "goles", "campo": "gc_por_partido", "sort": "max", "fmt": "goles_abs",
        "eyebrow": "Coladero real", "verbo": "encajar más goles por partido de lo que dice la media",
        "verbo_largo": "encajar más goles por partido (dato real de la temporada, no el modelo)",
        "dato_label": "Goles en contra por partido (real)",
    },
    "efectividad": {
        "tipo": "goles", "campo": "efectividad", "sort": "max", "fmt": "goles_abs",
        "eyebrow": "Equipo más efectivo", "verbo": "sacar más puntos por gol marcado",
        "verbo_largo": "sacar más puntos por gol marcado (la mayor ratio puntos/goles a favor)",
        "dato_label": "Puntos por gol a favor",
    },
    # ── Próxima jornada: cara B del 1X2/goles ──
    "menos_favorito_jornada": {
        "tipo": "jornada",
        "eyebrow": "En apuros", "verbo": "ser el menos favorito para ganar en la próxima jornada",
        "verbo_largo": "ser el menos favorito para ganar su partido de la próxima jornada",
        "dato_label": "Probabilidad de ganar su próximo partido",
    },
    "under_jornada": {
        "tipo": "jornada",
        "eyebrow": "Partido de pocos goles", "verbo": "ser el equipo con menos opciones de ver +2,5 goles en su próximo partido",
        "verbo_largo": "ser el equipo con menos opciones de ver más de 2,5 goles en su próximo partido",
        "dato_label": "Probabilidad de menos de 2,5 goles en su próximo partido",
    },
    "sin_gol_jornada": {
        "tipo": "jornada",
        "eyebrow": "Sin gol a la vista", "verbo": "tener más opciones de no marcar en la próxima jornada",
        "verbo_largo": "tener más opciones de no marcar en su próximo partido",
        "dato_label": "Probabilidad de no marcar en su próximo partido",
    },
    # ── Próxima jornada: por partido, cara B ──
    "under_25": {
        "tipo": "jornada", "shape": "partido",
        "eyebrow": "Partido de pocos goles", "verbo": "tener menos opciones de superar los 2,5 goles en la próxima jornada",
        "verbo_largo": "tener menos opciones de superar los 2,5 goles en la próxima jornada (la mayor probabilidad de 2 goles o menos)",
        "dato_label": "Probabilidad de menos de 2,5 goles",
    },
    "local_claro": {
        "tipo": "jornada", "shape": "partido",
        "eyebrow": "Local sólido", "verbo": "tener al local más favorito de la próxima jornada",
        "verbo_largo": "tener al local más favorito de la próxima jornada (la mayor probabilidad de victoria local según el modelo)",
        "dato_label": "Probabilidad de victoria local",
    },
    "visitante_claro": {
        "tipo": "jornada", "shape": "partido",
        "eyebrow": "Visitante sólido", "verbo": "tener al visitante más favorito de la próxima jornada",
        "verbo_largo": "tener al visitante más favorito de la próxima jornada (la mayor probabilidad de victoria visitante según el modelo)",
        "dato_label": "Probabilidad de victoria visitante",
    },
    # ── Tendencia / estabilidad a lo largo de la temporada ──
    "decepcion_temporada": {
        "tipo": "temporada", "fmt": "pp", "direction": "worse",
        "eyebrow": "La decepción del curso", "verbo": "ser la decepción de la temporada",
        "verbo_largo": "ser la decepción de la temporada (el equipo que más ha empeorado su probabilidad de zona desde el arranque)",
        "dato_label": "Empeoramiento de probabilidad de zona desde el arranque",
    },
    "estabilidad_temporada": {
        "tipo": "temporada", "fmt": "pp", "direction": "stable",
        "eyebrow": "El más fiel a sí mismo", "verbo": "ser el equipo más estable de la temporada",
        "verbo_largo": "ser el equipo más estable de la temporada (el que menos ha movido su probabilidad de zona desde el arranque)",
        "dato_label": "Cambio absoluto de probabilidad de zona desde el arranque",
    },
    "subrepresentado": {
        "tipo": "ranking_vs_prob", "sort": "max", "fmt": "pos",
        "eyebrow": "Equipo infravalorado", "verbo": "estar más bajo en la tabla de lo que su probabilidad merece",
        "verbo_largo": "estar más bajo en la tabla de lo que su probabilidad de zona merece (mayor diferencia entre posición real y esperada)",
        "dato_label": "Diferencia posición real vs esperada por el modelo",
    },
}

# Cron dedicado (ver CLAUDE.md): un dato curioso cada 2h, de 10:00 a 22:00
# hora de España -> 7 al día. `_run_stat` repite esta guarda en tiempo de
# ejecución (defensa en profundidad si el cron se lanza fuera de horario).
# ⚠️ El cron del servidor dispara CADA HORA en UTC (CRON_TZ no se aplica en ese
# cron; ver CLAUDE.md) y el script filtra por hora de Madrid — así sobrevive al
# cambio de hora de verano/invierno sin tocar el cron a mano.
STAT_ARTICLE_HOURS = range(10, 23, 2)


def gemini_endpoint(model):
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
