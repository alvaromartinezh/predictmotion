"""Prior de fuerza para /partido — MISMO modelo que las ligas (seo/sim_table).

El backend en vivo NO re-simula ni re-deriva fuerza: lee el MISMO precálculo que
leen los dashboards (`data/<slug>/latest.json`, que genera el cron SEO) y aplica el
mismo 1X2 que la simulación por liga vía `seo.sim_table.match_1x2` — el dispatcher
central que despacha según `strength_model` del snapshot: v3 (marginal Poisson con
att/def), v2 (rating absoluto + encogido del empate + desvanecimiento) o uniforme.
Así la probabilidad pre-partido de /partido y las de la liga son coherentes entre
sí: un favorito (p. ej. Madrid–Osasuna) no sale con la media plana de p_home (~47%)
sino con su 1X2 real.

Best-effort (Principio 2): si falta el snapshot, la fuerza, la liga o el import de
`seo` falla, devuelve None → `InPlayStatsModel` cae a las medias planas de siempre
(`LEAGUE_BASE_PROBS`). El servicio en vivo nunca se rompe por esto.
"""

import json
import logging
import threading
import time

from . import config

log = logging.getLogger("live_tracker.strength")

_snap_cache: dict[str, tuple[float, dict | None]] = {}
_snap_lock = threading.Lock()


def _load_snapshot(league: str):
    """latest.json de la liga (data/<slug>/latest.json), con caché corta."""
    now = time.time()
    with _snap_lock:
        hit = _snap_cache.get(league)
        if hit and now - hit[0] < config.WINPROB_SNAPSHOT_TTL:
            return hit[1]
    snap = None
    try:
        from seo.config import DATA_DIR
        path = DATA_DIR / league / "latest.json"
        snap = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        snap = None
    with _snap_lock:
        _snap_cache[league] = (now, snap)
    return snap


def pre_match_probs(league: str, home_id, away_id):
    """1X2 pre-partido con el modelo de fuerza de las ligas, o None si no aplica.

    La fuerza de cada equipo sale del snapshot del cron SEO (el mismo que leen los
    dashboards) y el 1X2 se calcula con la MISMA función que usa la simulación por
    liga (`seo.sim_table._match_ph_pd`). None → el modelo usa las medias planas.

    `snapshot_context` incluye el guard de `strength_model`: si el snapshot en disco
    lo declara distinto del modelo compilado aquí (deploy/rollback con el snapshot
    del cron aún sin regenerar, hasta 3 h), devuelve None y caemos a las medias
    planas en vez de multiplicar ratings de una escala por la constante de otra.
    """
    snap = _load_snapshot(league)
    if not snap:
        return None
    hid, aid = str(home_id), str(away_id)
    try:
        from seo import sim_table
        from seo.config import league_by_slug
    except Exception:
        return None
    # Base por liga: fuente única seo/config (p_home/p_draw); fallback local.
    lg = league_by_slug(league)
    p_home, p_draw = config.LEAGUE_BASE_PROBS.get(league, config.DEFAULT_BASE_PROBS)
    if lg:
        p_home = float(lg.get("p_home") or p_home)
        p_draw = float(lg.get("p_draw") or p_draw)
    # Dispatcher central del 1X2 (v3/v2/uniforme): misma función que usan la
    # simulación y el registro de predicciones. None → el snapshot no permite
    # este partido (modelo desconocido, o v3 sin att/def) → medias planas.
    return sim_table.match_1x2(snap, hid, aid, p_home, p_draw)
