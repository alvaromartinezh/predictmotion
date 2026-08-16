"""Configuración del generador de artículos. Todo lo que varía vive aquí."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ARTICLES_DATA_DIR = DATA_DIR / "articles"          # metadata + cuerpo (gitignored)
ARTICLES_PREVIEW_DIR = DATA_DIR / "articles_preview"  # salida sin --publish (gitignored)
ARTICLES_STATE_FILE = DATA_DIR / "articles_state.json"
ARTICLES_OUT_DIR = ROOT / "articulos"              # HTML publicado (gitignored, como equipos/)

# Ligas activas para el generador de artículos (independiente de TWEET_LEAGUES
# en seo/tweets.py, mismo patrón: allowlist simple, no una limitación
# estructural — ampliar cuando el tráfico lo justifique).
ARTICLE_LEAGUES = ["laliga", "hypermotion"]

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

# ── Grounding con Google Search (solo previa_diaria) ─────────────────────────
# Confirmado con una llamada real (2026-08-16): gemini-2.5-flash +
# tools:[{"google_search":{}}] SÍ ejecuta búsquedas reales (groundingMetadata
# con searchEntryPoint + citas de fuentes reales).
#
# CONFIRMADO (2026-08-16, prueba aislada — 3 llamadas SOLO con grounding, sin
# mezclar con nada más): el grounding consume el RPD normal de generateContent
# (20/día medido), NO el cupo separado de "Fundamentación de la búsqueda" que
# el panel de AI Studio muestra para Gemini 2.5 (1,5K/día). Evidencia: el pico
# del gráfico de RPD de generateContent creció visiblemente entre el antes y
# el después de las 3 llamadas (sin haber hecho ninguna otra llamada en medio,
# por diseño de la prueba), mientras que el contador de "Fundamentación de la
# búsqueda" se quedó exactamente en 0 en ambas capturas — ninguna señal ahí,
# toda la señal en el RPD normal. Por eso generate.py NO distingue: cada
# llamada grounded de previa_diaria cuenta como una más contra
# ARTICLES_MAX_PER_DAY, igual que las demás — esto ya no es una asunción
# conservadora a la espera de confirmación, es el comportamiento real medido.
#
# SEGUNDA CONFIRMACIÓN independiente (mismo día): el panel de RPD normal
# tarda en reflejar el uso real (mismo retraso que ya se vio en el panel de
# grounding, que tardó horas en pasar de 0 a 5) — una lectura a media tarde
# lo mostró en 10/20 cuando ya se sabía con certeza que había 15 llamadas
# reales ese día; horas después, con 20 llamadas reales acumuladas (7 de
# ellas grounded, contadas a mano por fuera del panel), el panel marcó
# 21/20 — encaja con "cada llamada cuenta" (≈20) y no con "solo cuentan las
# no-grounded" (≈13, la otra hipótesis, que habría quedado muy lejos).

# Los artículos previa_diaria que citan fuentes externas (lesiones/noticias
# vía Google Search) no se publican solos hasta esta fecha: se guardan con
# status "pending_review" (misma mecánica que "flagged" — auditados en
# data/articles/, nunca renderizados) para un vistazo humano antes de salir,
# porque un dato externo puede estar desactualizado o ser contradictorio
# (visto en la prueba real: dos fuentes discrepaban en la fecha de vuelta de
# un jugador). Pasada esta fecha, se publican solas como cualquier otro tipo
# — con una alerta de aviso (no de aprobación) por email. Fecha = 7 días
# desde que se implementó esto (2026-08-16); si el sitio queda desatendido,
# NO se rompe nada: esos artículos concretos simplemente no salen hasta que
# alguien los revise o pase la fecha.
PREVIA_NEWS_REVIEW_UNTIL = "2026-08-23"
