"""Configuración del seguimiento en vivo.

⚠️  PESOS Y FACTORES HEURÍSTICOS SIN VALIDAR  ⚠️
Todos los números del bloque WINPROB de abajo son una PRIMERA APROXIMACIÓN a ojo,
NO calibrada contra resultados reales. Están aquí, centralizados y comentados, para
ajustarlos viendo partidos en vivo y comparando la probabilidad estimada con cómo
acaban realmente. No son cuotas ni una predicción validada. Cambiar estos valores
NO requiere tocar código: el modelo (winprob.py) los lee de aquí.
"""

import os


def _flag(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ── Interruptor general de la feature ─────────────────────────────────────────
# Con False, el backend responde "desactivado" en todos los endpoints y el
# frontend oculta la UI de seguimiento en vivo.
LIVE_TRACKING_ENABLED = _flag("LIVE_TRACKING_ENABLED", True)

# ── Servidor ──────────────────────────────────────────────────────────────────
PORT = _int("LIVE_TRACKING_PORT", 8770)
HOST = os.environ.get("LIVE_TRACKING_HOST", "127.0.0.1")

# Directorio donde se guardan los partidos finalizados (gitignored, solo en el VM).
DATA_DIR = os.environ.get(
    "LIVE_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live_data"),
)

# ── Polling / caché ───────────────────────────────────────────────────────────
SCOREBOARD_POLL_SECONDS = _int("SCOREBOARD_POLL_SECONDS", 30)  # descubrir qué hay en vivo
LIVE_POLL_SECONDS       = _int("LIVE_POLL_SECONDS", 25)        # refrescar summary de partidos en vivo
DETAIL_TTL_SECONDS      = _int("DETAIL_TTL_SECONDS", 300)      # TTL de detalle de partidos NO en vivo
FINAL_REFRESH_SECONDS   = _int("FINAL_REFRESH_SECONDS", 300)   # re-guardar el snapshot N s tras el final (stats consolidadas)
HTTP_TIMEOUT_SECONDS    = _int("LIVE_HTTP_TIMEOUT", 12)

# ── Proxy ESPN (fix 2026-08-12) ───────────────────────────────────────────────
# ESPN devuelve 403 a los User-Agents de navegador (solo pasan curl/python-urllib).
# El frontend reescribe sus fetch a la API de ESPN a /api/espn/<host>/<path>; este
# backend los reenvía con el UA por defecto de urllib (sí pasa) y responde JSON con
# Access-Control-Allow-Origin: *. Cache corto en memoria para absorber el polling.
ESPN_PROXY_ENABLED   = _flag("ESPN_PROXY_ENABLED", True)
ESPN_PROXY_CACHE_TTL = _int("ESPN_PROXY_CACHE_TTL", 30)
ESPN_PROXY_TIMEOUT   = _int("ESPN_PROXY_TIMEOUT", 20)

# Ligas seguidas (códigos ESPN). El provider es agnóstico de liga. Las 15
# competiciones con dashboard (12 ligas + fase de liga UEFA); las copas no
# entran (sin seguimiento).
LEAGUES = {
    "hypermotion": "esp.2",
    "laliga":      "esp.1",
    "premier":     "eng.1",
    "championship":"eng.2",
    "seriea":      "ita.1",
    "serieb":      "ita.2",
    "bundesliga":  "ger.1",
    "bundesliga2": "ger.2",
    "ligue1":      "fra.1",
    "ligue2":      "fra.2",
    "primeira":    "por.1",
    "eredivisie":  "ned.1",
    "brasileirao": "bra.1",
    "champions":   "uefa.champions",
    "europa":      "uefa.europa",
    "conference":  "uefa.europa.conf",
}

# ── Probabilidad pre-partido por liga (base de calibración) ───────────────────
# FALLBACK cuando no hay prior de fuerza aplicable. La base REAL pre-partido de
# /partido sale ahora del MISMO modelo que las ligas: lee la fuerza por equipo del
# snapshot data/<slug>/latest.json (cron SEO) y aplica seo.sim_table._match_ph_pd
# (ver live_tracker/strength.py). Solo si ese prior no está disponible (sin
# snapshot, ids fuera, prior desvanecido a media temporada) se cae aquí.
#   (p_home, p_draw)  → p_away = 1 - p_home - p_draw
# Valores de seo/config.py → LEAGUES (fuente única; si cambian allá, actualizar
# aquí).
LEAGUE_BASE_PROBS = {
    "hypermotion": (0.42, 0.27),
    "laliga":      (0.46, 0.26),
    "premier":     (0.45, 0.24),
    "championship":(0.45, 0.26),
    "seriea":      (0.45, 0.27),
    "serieb":      (0.45, 0.28),
    "bundesliga":  (0.44, 0.24),
    "bundesliga2": (0.44, 0.26),
    "ligue1":      (0.45, 0.27),
    "ligue2":      (0.45, 0.28),
    "primeira":    (0.46, 0.27),
    "eredivisie":  (0.46, 0.24),
    "brasileirao": (0.49, 0.26),
    "champions":   (0.45, 0.25),
    "europa":      (0.45, 0.25),
    "conference":  (0.45, 0.25),
}
DEFAULT_BASE_PROBS = (0.42, 0.27)

# Ligas SIN localía real (sedes neutrales): el "local" del fixture no juega en casa,
# así que el modelo no aplica ventaja de campo (victorias simétricas) y en su lugar
# sesga la probabilidad por el RANKING FIFA de cada selección. Vacío ahora mismo:
# el modelo de sedes neutrales queda latente, listo para reutilizar en cualquier
# competición de sedes neutrales.
NEUTRAL_VENUE_LEAGUES = set()
# Peso del ranking FIFA sobre la tasa de gol (solo sedes neutrales). HEURÍSTICO.
WINPROB_RANK_WEIGHT = 1.2


# ══════════════════════════════════════════════════════════════════════════════
#  WINPROB — pesos y factores HEURÍSTICOS SIN VALIDAR (ajustar viendo partidos)
# ══════════════════════════════════════════════════════════════════════════════
#
# El modelo proyecta el resultado final = marcador actual + goles esperados en el
# tiempo restante. Las stats en vivo solo MODULAN ese esperado; el marcador y el
# tiempo restante pesan mucho más. Ver winprob.py para el detalle del cálculo.

# Pesos del log-multiplicador por stat. Cada uno multiplica la desviación de la
# "cuota del local" respecto a 0.5 (q_i = local/(local+visitante)). Más alto =
# más influye esa estadística. TODO: calibrar con partidos reales.
WINPROB_STAT_WEIGHTS = {
    "shotsOnTarget": 0.9,   # mejor proxy de peligro
    "totalShots":    0.5,
    "possessionPct": 0.6,
    "wonCorners":    0.4,
    "yellowCards":   0.1,   # señal débil de descontrol/expulsión cercana
    "foulsCommitted": 0.1,  # idem (se aplica al equipo que comete)
}

# Límites del multiplicador por stats, para que ninguna combinación se dispare.
WINPROB_MULT_MIN = 0.60
WINPROB_MULT_MAX = 1.70

# Ventaja por hombre de más/menos (rojas). HEURÍSTICO: por cada jugador de ventaja
# el equipo con más hombres ve su tasa de gol ×UP y el de menos ×DOWN.
WINPROB_MAN_ADV_UP   = 1.25
WINPROB_MAN_ADV_DOWN = 0.85

# Duración de referencia para el tiempo restante (min). El descuento se trata
# limitando la fracción restante a >= 0.
WINPROB_FULL_TIME = 90

# Nota visible en la UI: deja claro que es una estimación heurística, no una cuota.
WINPROB_UI_NOTE = "Probabilidad estimada (modelo heurístico, no validado)"
WINPROB_SOURCE = "inplay-stats-v2"

# TTL del snapshot de fuerza por liga (data/<slug>/latest.json) en el modelo en
# vivo: lectura en disco + re-derivación del 1X2, amortizada en el polling.
WINPROB_SNAPSHOT_TTL = _int("WINPROB_SNAPSHOT_TTL", 300)
