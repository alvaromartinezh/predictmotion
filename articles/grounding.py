"""Payload de hechos reales para el prompt de cada tipo de artículo.

Lee data/<slug>/latest.json (mismo contrato que leen los dashboards) y, para
comparar con la jornada anterior, el histórico particionado por temporada que
ya persiste seo/snapshots.py. Nada se inventa aquí: si un dato no está en el
snapshot, no entra en el payload (y por tanto Gemini no puede citarlo).
"""

import json

from seo.snapshots import load_all, per_period_series
from .config import DATA_DIR


def load_snapshot(slug):
    """data/<slug>/latest.json, o None si no existe / liga offseason sin equipos."""
    path = DATA_DIR / slug / "latest.json"
    if not path.exists():
        return None
    snap = json.loads(path.read_text(encoding="utf-8"))
    if not snap.get("teams"):
        return None
    return snap


def load_previous_jornada_snapshot(slug, snap):
    """Snapshot de la jornada anterior a la de `snap`, o None si no hay histórico
    suficiente. Mismo patrón que render_table.py:_prev_jornada_snap."""
    snaps = load_all(slug, snap["season"])
    series = per_period_series(snaps, "jornada")
    prev = None
    for j, s in series:
        if j < snap["jornada"]:
            prev = s
    return prev


def _team_by_rank(teams, rank):
    for t in teams:
        if t["rank"] == rank:
            return t
    return None


def teams_near_boundary(snap, radius=1):
    """Equipos a `radius` puestos de cualquier corte de banda (lo/hi) — los más
    interesantes para un explicador ("¿por qué X% y no más?"). Sin duplicados."""
    bands = snap.get("bands") or []
    ranks = set()
    for b in bands:
        for edge in (b["lo"], b["hi"]):
            for r in range(edge - radius, edge + radius + 1):
                ranks.add(r)
    teams = [t for t in snap["teams"] if t["rank"] in ranks]
    teams.sort(key=lambda t: t["rank"])
    return teams


# ── Payloads por tipo ─────────────────────────────────────────────────────

def ground_recap(league, snap, prev_snap):
    bands = snap["bands"]
    primary = bands[0]
    leader = min(snap["teams"], key=lambda t: t["rank"])

    movers = []
    if prev_snap:
        prev_by_id = {t["id"]: t for t in prev_snap["teams"]}
        for t in snap["teams"]:
            pt = prev_by_id.get(t["id"])
            if not pt:
                continue
            d_prob = round((t["prob"].get(primary["key"]) or 0)
                           - (pt["prob"].get(primary["key"]) or 0), 1)
            movers.append({
                "nombre": t["name"], "posicion": t["rank"], "posicion_anterior": pt["rank"],
                "prob_actual": t["prob"].get(primary["key"]),
                "prob_anterior": pt["prob"].get(primary["key"]),
                "variacion_puntos_porcentuales": d_prob,
            })
    movers.sort(key=lambda m: -m["variacion_puntos_porcentuales"])

    return {
        "tipo": "recap_jornada",
        "liga": league["name"], "temporada": snap["season"], "jornada": snap["jornada"],
        "zona_principal": primary["label"],
        "lider": {"nombre": leader["name"], "puntos": leader["pts"], "pj": leader["gp"],
                  "prob_zona_principal": leader["prob"].get(primary["key"])},
        "mayores_subidas_probabilidad": movers[:3],
        "mayores_bajadas_probabilidad": list(reversed(movers[-3:])) if movers else [],
    }


def ground_explainer(league, snap, team):
    bands = snap["bands"]
    prob = team["prob"]
    neighbors = []
    for r in (team["rank"] - 1, team["rank"] + 1):
        nt = _team_by_rank(snap["teams"], r)
        if nt:
            neighbors.append({"nombre": nt["name"], "posicion": nt["rank"], "puntos": nt["pts"]})

    return {
        "tipo": "explicador_probabilidad",
        "liga": league["name"], "temporada": snap["season"], "jornada": snap["jornada"],
        "equipo": team["name"], "posicion": team["rank"], "puntos": team["pts"],
        "pj": team["gp"], "victorias": team["wins"], "empates": team["draws"], "derrotas": team["losses"],
        "rating_fuerza": team.get("strength"),
        "probabilidades_por_zona": {b["label"]: prob.get(b["key"]) for b in bands if prob.get(b["key"]) is not None},
        "vecinos_en_la_tabla": neighbors,
    }


def ground_title_race(league, snap, prev_snap, top_n=4):
    bands = snap["bands"]
    key = "first" if any("first" in t["prob"] for t in snap["teams"]) else bands[0]["key"]
    ranked = sorted(snap["teams"], key=lambda t: -(t["prob"].get(key) or 0))[:top_n]

    candidatos = []
    prev_by_id = {t["id"]: t for t in (prev_snap or {}).get("teams", [])}
    for t in ranked:
        c = {"nombre": t["name"], "puntos": t["pts"], "pj": t["gp"], "prob_titulo": t["prob"].get(key)}
        pt = prev_by_id.get(t["id"])
        if pt:
            c["prob_titulo_jornada_anterior"] = pt["prob"].get(key)
        candidatos.append(c)

    return {
        "tipo": "carrera_titulo",
        "liga": league["name"], "temporada": snap["season"], "jornada": snap["jornada"],
        "candidatos": candidatos,
        "diferencia_puntos_1_2": (ranked[0]["pts"] - ranked[1]["pts"]) if len(ranked) > 1 else None,
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
