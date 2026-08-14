"""Prior de fuerza para /partido — MISMO modelo que las ligas (seo/sim_table).

El backend en vivo NO re-simula ni re-deriva fuerza: lee el MISMO precálculo que
leen los dashboards (`data/<slug>/latest.json`, que genera el cron SEO) y aplica la
misma fórmula 1X2 que la simulación por liga (`seo.sim_table._match_ph_pd` — modelo
v2 ACTIVO: rating absoluto por diferencia de goles/partido + encogido del empate +
desvanecimiento). Así la probabilidad pre-partido de /partido y las de la liga son
coherentes entre sí: un favorito (p. ej. Madrid–Osasuna) no sale con la media plana
de p_home (~47%) sino con su 1X2 de fuerza real.

Best-effort (Principio 2): si falta el snapshot, la fuerza, la liga o el import de
`seo` falla, devuelve None → `InPlayStatsModel` cae a las medias planas de siempre
(`LEAGUE_BASE_PROBS`). El servicio en vivo nunca se rompe por esto.
"""

import json
import logging
import math
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
    """
    snap = _load_snapshot(league)
    if not snap:
        return None
    strength = {}
    for t in snap.get("teams", []):
        s = t.get("strength")
        if s is not None:
            strength[str(t["id"])] = float(s)
    if not strength:
        return None
    hid, aid = str(home_id), str(away_id)
    if hid not in strength or aid not in strength:
        return None
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
    p_away = max(0.0, 1.0 - p_home - p_draw)
    m = p_home + p_away
    if m <= 0:
        return None
    s0 = min(1 - 1e-9, max(1e-9, p_home / m))
    total_md = int(snap.get("total_md", 0) or 0)
    jornada = int(snap.get("jornada", 0) or 0)
    w_md = sim_table.fade_weight(jornada, total_md) if total_md else 0.0
    sc = {
        "strength": strength,
        "m": m,
        "logit_s0": math.log(s0 / (1 - s0)),
        "w": w_md,
    }
    ph, pd = sim_table._match_ph_pd(sc, hid, aid, p_draw, w_md)
    return (ph, pd, max(0.0, 1.0 - ph - pd))
