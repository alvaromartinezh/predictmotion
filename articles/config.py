"""Config del generador de artículos (broadsheet diario de Hypermotion, ver
articles/generate.py) y del cliente Gemini que usa (articles/gemini_client.py)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ARTICLES_OUT_DIR = ROOT / "articulos"  # HTML publicado (gitignored, como equipos/)

# Tolerancia del validador de grounding: una cifra "%" generada por Gemini se
# acepta si cae a ±1 punto de algún valor real del payload de hechos
# (redondeos: textutil.pct() usa 1 decimal con coma española, Gemini puede
# redondear distinto).
GROUNDING_TOLERANCE_PP = 1.0

GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_MODEL_GROUNDED = "gemini-2.5-flash"


def gemini_endpoint(model):
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
