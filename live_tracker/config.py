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

# Ligas seguidas (códigos ESPN). El provider es agnóstico de liga.
LEAGUES = {
    "hypermotion": "esp.2",
    "laliga":      "esp.1",
    "mundial":     "fifa.world",
}

# ── Probabilidad pre-partido por liga (base de calibración) ───────────────────
# Mismas constantes que el Monte Carlo del sitio, para coherencia. En el minuto 0
# la probabilidad estimada cae exactamente a estos valores.
#   (p_home, p_draw)  → p_away = 1 - p_home - p_draw
LEAGUE_BASE_PROBS = {
    "hypermotion": (0.42, 0.27),
    "laliga":      (0.46, 0.26),
    "mundial":     (0.40, 0.27),  # p_home se ignora en sedes neutrales (ver abajo)
}
DEFAULT_BASE_PROBS = (0.42, 0.27)

# Ligas SIN localía real (sedes neutrales): el "local" del fixture no juega en casa,
# así que el modelo no aplica ventaja de campo (victorias simétricas) y en su lugar
# sesga la probabilidad por el RANKING FIFA de cada selección.
NEUTRAL_VENUE_LEAGUES = {"mundial"}
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
WINPROB_SOURCE = "inplay-stats-v1"
