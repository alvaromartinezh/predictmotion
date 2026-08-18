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


def gemini_endpoint(model):
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
