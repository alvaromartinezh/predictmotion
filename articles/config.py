"""Configuración del generador de artículos. Todo lo que varía vive aquí."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ARTICLES_DATA_DIR = DATA_DIR / "articles"          # metadata + cuerpo (gitignored)
ARTICLES_PREVIEW_DIR = DATA_DIR / "articles_preview"  # salida sin --publish (gitignored)
ARTICLES_STATE_FILE = DATA_DIR / "articles_state.json"
ARTICLES_OUT_DIR = ROOT / "articulos"              # HTML publicado (gitignored, como equipos/)

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)

# ── Tope diario de llamadas a Gemini ─────────────────────────────────────────
# Cuota REAL de la key de este proyecto, verificada en aistudio.google.com/
# rate-limit el 2026-08-16 (gemini-2.5-flash, nivel gratuito): RPD 20 / RPM 5 /
# TPM 250K. 15 = 75% de los 20 RPD reales — margen del 25% para reintentos y
# para no depender de que Google no cambie la cuota sin aviso (ya ha pasado
# con los límites de ESPN, ver CLAUDE.md). El RPM (5) no es cuello de botella:
# los artículos se generan secuenciales y best-effort, no en ráfaga. NO es una
# cifra sacada de terceros (que reportan entre 250 y 1500 RPD, cifras que no
# corresponden a la cuenta real de este proyecto): es la cuota medida.
ARTICLES_MAX_PER_DAY = 15

# ── Ventanas de dedupe/cadencia por tipo (días) ──────────────────────────────
EXPLAINER_COOLDOWN_DAYS = 14   # no repetir el mismo equipo en un explicador
TITLE_RACE_MIN_GAP_DAYS = 7    # frecuencia mínima entre artículos de carrera por el título
# Umbral heurístico (puntos porcentuales) de cambio en la probabilidad del
# líder desde el último artículo de carrera por el título para adelantar el
# hueco semanal — PENDIENTE DE CALIBRAR con datos reales, como el resto de
# parámetros heurísticos del modelo (ver seo/config.py).
TITLE_RACE_PROB_SWING_TRIGGER_PP = 8.0

# Tolerancia del validador de grounding: una cifra "%" generada por Gemini se
# acepta si cae a ±1 punto de algún valor del payload de hechos (redondeos:
# textutil.pct() usa 1 decimal con coma española, Gemini puede redondear distinto).
GROUNDING_TOLERANCE_PP = 1.0
