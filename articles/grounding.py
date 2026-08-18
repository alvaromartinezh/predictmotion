"""Payload de hechos reales para el prompt de Gemini.

Lee data/<slug>/latest.json (mismo contrato que leen los dashboards) y, para
comparar antes/después de un partido, el histórico particionado por
temporada que ya persiste seo/snapshots.py. Nada se inventa aquí: si un dato
no está en el snapshot, no entra en el payload (y por tanto Gemini no puede
citarlo).
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from seo.snapshots import load_all
from .config import DATA_DIR, ASCENSO_TOTAL_SEASON_FRACTION

_MADRID_TZ = ZoneInfo("Europe/Madrid")


def load_snapshot(slug):
    """data/<slug>/latest.json, o None si no existe / liga offseason sin equipos."""
    path = DATA_DIR / slug / "latest.json"
    if not path.exists():
        return None
    snap = json.loads(path.read_text(encoding="utf-8"))
    if not snap.get("teams"):
        return None
    return snap


def _team_by_rank(teams, rank):
    for t in teams:
        if t["rank"] == rank:
            return t
    return None


def team_by_id(snap, team_id):
    for t in snap["teams"]:
        if str(t["id"]) == str(team_id):
            return t
    return None


def _prior_snapshot(slug, season, before_date):
    """Snapshot diario más reciente con fecha ANTERIOR a `before_date`
    (YYYY-MM-DD), o None. Reusa seo.snapshots.load_all — sin persistencia
    nueva: el histórico diario que el cron ya escribe basta para el
    antes/después de un resultado."""
    prior = None
    for s in load_all(slug, season):
        if s["date"] < before_date:
            prior = s
    return prior


def _best_band(bands, prob):
    """Banda con la probabilidad más alta para este equipo. El porcentaje que
    se enseña es SIEMPRE el mejor de cada equipo, no el de una banda elegida
    por posición actual — eso sería mostrar un número que no es el más
    favorable/relevante que tiene el equipo según el modelo."""
    return max(bands, key=lambda b: prob.get(b["key"]) or 0)


def _effective_bands(snap, bands):
    """Bandas a comparar para elegir la "mejor zona" que citan los artículos.
    En la primera mitad de temporada (`ASCENSO_TOTAL_SEASON_FRACTION`),
    ascenso directo y play-off se funden en un único "ascenso total": las
    posiciones aún son muy volátiles y separar directo/play-off sería ruido,
    no señal. Pasada esa fracción, se listan por separado (`bands` tal cual).
    Solo aplica a ligas con play-off (`bands` trae 'ascenso' Y 'playoff' —
    hoy, solo Hypermotion; el resto de artículos no se ve afectado)."""
    keys = {b["key"] for b in bands}
    if not {"ascenso", "playoff"} <= keys:
        return bands
    total_md, jornada = snap.get("total_md") or 0, snap.get("jornada") or 0
    if total_md and jornada / total_md >= ASCENSO_TOTAL_SEASON_FRACTION:
        return bands
    merged = [b for b in bands if b["key"] not in ("ascenso", "playoff")]
    merged.insert(0, {"key": "ascenso_total", "label": "Ascenso total",
                       "color": "green", "zone": "promo"})
    return merged


def _match_side_summary(snap, bands, prior_by_id, team_id):
    """Nombre/zona/prob antes-y-después de UN equipo en UN partido, más el
    detalle de puntos/racha/fuerza y las 3 zonas completas (antes/actual) que
    necesita el broadsheet de partido (render.py:render_match_broadsheet) —
    el resumen diario solo usa el subconjunto zona-mejor de siempre, así que
    los campos de más no le rompen nada (nunca los lee). El campo "zonas"
    completo NUNCA se funde (detalle real siempre disponible); solo la zona
    "mejor" (zona/zona_key/prob_zona_*) pasa por `_effective_bands`."""
    t = team_by_id(snap, team_id)
    if not t:
        return None
    zone = _best_band(_effective_bands(snap, bands), t["prob"])
    pt = prior_by_id.get(str(t["id"]))
    return {
        "nombre": t["name"], "id": t["id"], "logo": t["logo"], "posicion": t["rank"],
        "puntos": t["pts"], "pj": t.get("gp"), "victorias": t.get("wins"),
        "empates": t.get("draws"), "derrotas": t.get("losses"), "rating_fuerza": t.get("strength"),
        "zona": zone["label"], "zona_key": zone["key"],
        "prob_zona_actual": t["prob"].get(zone["key"]),
        "prob_zona_antes_del_partido": pt["prob"].get(zone["key"]) if pt else None,
        "zonas": [
            {"label": b["label"], "key": b["key"],
             "actual": t["prob"].get(b["key"]),
             "antes": (pt["prob"].get(b["key"]) if pt else None)}
            for b in bands
        ],
    }


def ground_resumen_diario(league, snap, matches):
    """payload de TODOS los partidos de Hypermotion terminados en un día
    natural concreto. `matches`: eventos de espn.fetch_scoreboard_range ya
    filtrados a esa fecha y state=='post'."""
    bands = snap["bands"]
    fecha = matches[0]["date"] if matches else None
    prior = _prior_snapshot(league["slug"], snap["season"], fecha) if fecha else None
    prior_by_id = {str(t["id"]): t for t in (prior or {}).get("teams", [])}

    partidos = []
    for m in matches:
        local = _match_side_summary(snap, bands, prior_by_id, m["home"]["id"])
        visitante = _match_side_summary(snap, bands, prior_by_id, m["away"]["id"])
        if not local or not visitante:
            continue
        partidos.append({
            "local": local, "visitante": visitante, "event_id": m.get("event_id"),
            "resultado": {"local": m["home_score"], "visitante": m["away_score"]},
        })

    return {
        "tipo": "resumen_diario",
        "liga": league["name"], "temporada": snap["season"], "jornada": snap["jornada"],
        "fecha": fecha, "partidos": partidos,
    }


def ground_match(league, snap, match):
    """payload de hechos de UN partido de Hypermotion terminado hoy, para el
    broadsheet de partido (render.py:render_match_broadsheet). `match`: un
    evento de espn.fetch_scoreboard_range con state=='post'. None si alguno
    de los dos equipos no está en el snapshot (mismo criterio de
    ground_resumen_diario)."""
    bands = snap["bands"]
    prior = _prior_snapshot(league["slug"], snap["season"], match["date"])
    prior_by_id = {str(t["id"]): t for t in (prior or {}).get("teams", [])}

    local = _match_side_summary(snap, bands, prior_by_id, match["home"]["id"])
    visitante = _match_side_summary(snap, bands, prior_by_id, match["away"]["id"])
    if not local or not visitante:
        return None

    hora = None
    if match.get("kickoff"):
        try:
            dt = datetime.fromisoformat(match["kickoff"].replace("Z", "+00:00"))
            hora = dt.astimezone(_MADRID_TZ).strftime("%H:%M")
        except ValueError:
            hora = None

    return {
        "tipo": "match_cronica",
        "liga": league["name"], "temporada": snap["season"], "jornada": snap["jornada"],
        "fecha": match["date"], "event_id": match.get("event_id"),
        "estadio": match.get("venue"), "hora": hora,
        "local": local, "visitante": visitante,
        "resultado": {"local": match["home_score"], "visitante": match["away_score"]},
    }


def explainer_best_zone(payload):
    """(etiqueta, valor) de la zona con mayor probabilidad de un payload de
    explicador — el mismo criterio de "mejor zona" que _best_band, aplicado
    al payload ya aplanado (probabilidades_por_zona). Único sitio que lo
    calcula: lo usan tanto render.py (titular en pantalla) como
    layout_estimate.py (longitud del titular para estimar su altura)."""
    zonas = payload["probabilidades_por_zona"]
    return max(zonas.items(), key=lambda kv: kv[1] or 0)


def ground_explainer(league, snap, team):
    bands = _effective_bands(snap, snap["bands"])
    prob = team["prob"]
    neighbors = []
    for r in (team["rank"] - 1, team["rank"] + 1):
        nt = _team_by_rank(snap["teams"], r)
        if nt:
            neighbors.append({"nombre": nt["name"], "id": nt["id"], "logo": nt["logo"],
                              "posicion": nt["rank"], "puntos": nt["pts"]})

    return {
        "tipo": "explicador_probabilidad",
        "liga": league["name"], "temporada": snap["season"], "jornada": snap["jornada"],
        "equipo": team["name"], "equipo_id": team["id"], "equipo_logo": team["logo"],
        "posicion": team["rank"], "puntos": team["pts"],
        "pj": team["gp"], "victorias": team["wins"], "empates": team["draws"], "derrotas": team["losses"],
        "rating_fuerza": team.get("strength"),
        "probabilidades_por_zona": {b["label"]: prob.get(b["key"]) for b in bands if prob.get(b["key"]) is not None},
        "vecinos_en_la_tabla": neighbors,
    }


def numeric_facts(payload):
    """Todos los valores numéricos del payload (recursivo), para el validador de
    grounding: cualquier '%' que Gemini escriba debe caer cerca de uno de estos."""
    out = []

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            out.append(float(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(payload)
    return out


def to_prompt_json(payload):
    return json.dumps(payload, ensure_ascii=False, indent=1)
