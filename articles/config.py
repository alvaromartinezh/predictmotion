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
}

# Cron dedicado (ver CLAUDE.md): un dato curioso cada 2h, solo 10:00-20:00
# hora de España -> 6 al día. `_run_stat` repite esta guarda en tiempo de
# ejecución (defensa en profundidad si el cron se lanza fuera de horario).
STAT_ARTICLE_HOURS = range(10, 21, 2)


def gemini_endpoint(model):
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
