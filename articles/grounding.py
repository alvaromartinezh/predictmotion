"""Payload de hechos reales para el prompt de cada tipo de artículo.

Lee data/<slug>/latest.json (mismo contrato que leen los dashboards) y, para
comparar con la jornada anterior, el histórico particionado por temporada que
ya persiste seo/snapshots.py. Nada se inventa aquí: si un dato no está en el
snapshot, no entra en el payload (y por tanto Gemini no puede citarlo).
"""

import json

from seo import sim_table
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


def _team_by_id(snap, team_id):
    for t in snap["teams"]:
        if str(t["id"]) == str(team_id):
            return t
    return None


def _prior_snapshot(slug, season, before_date):
    """Snapshot diario más reciente con fecha ANTERIOR a `before_date`
    (YYYY-MM-DD), o None. Reusa seo.snapshots.load_all — sin persistencia
    nueva: el histórico diario que el cron ya escribe basta para el
    antes/después de una crónica de partido."""
    prior = None
    for s in load_all(slug, season):
        if s["date"] < before_date:
            prior = s
    return prior


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
                "nombre": t["name"], "id": t["id"], "logo": t["logo"],
                "posicion": t["rank"], "posicion_anterior": pt["rank"],
                "prob_actual": t["prob"].get(primary["key"]),
                "prob_anterior": pt["prob"].get(primary["key"]),
                "variacion_puntos_porcentuales": d_prob,
            })
    movers.sort(key=lambda m: -m["variacion_puntos_porcentuales"])

    return {
        "tipo": "recap_jornada",
        "liga": league["name"], "temporada": snap["season"], "jornada": snap["jornada"],
        "zona_principal": primary["label"], "zona_principal_color": primary.get("color"),
        "lider": {"nombre": leader["name"], "id": leader["id"], "logo": leader["logo"],
                  "puntos": leader["pts"], "pj": leader["gp"],
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
        "zona_colores": {b["label"]: b.get("color") for b in bands if prob.get(b["key"]) is not None},
        "vecinos_en_la_tabla": neighbors,
    }


def ground_title_race(league, snap, prev_snap, top_n=4):
    bands = snap["bands"]
    key = "first" if any("first" in t["prob"] for t in snap["teams"]) else bands[0]["key"]
    ranked = sorted(snap["teams"], key=lambda t: -(t["prob"].get(key) or 0))[:top_n]

    candidatos = []
    prev_by_id = {t["id"]: t for t in (prev_snap or {}).get("teams", [])}
    for t in ranked:
        c = {"nombre": t["name"], "id": t["id"], "logo": t["logo"],
             "puntos": t["pts"], "pj": t["gp"], "prob_titulo": t["prob"].get(key)}
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


def _best_band(bands, prob):
    """Banda con la probabilidad más alta para este equipo. El porcentaje que
    se enseña en los artículos es SIEMPRE el mejor de cada equipo, no el de
    una banda elegida por posición actual o cercanía a un corte — eso sería
    mostrar un número que no es el más favorable/relevante que tiene el
    equipo según el modelo."""
    return max(bands, key=lambda b: prob.get(b["key"]) or 0)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _match_stats_and_events(league_slug, event_id):
    """Estadísticas de caja (posesión, tiros...) + eventos relevantes (goles,
    rojas, cambios) de un partido YA JUGADO — misma fuente/parseo que
    /partido (live_tracker.providers.espn.EspnProvider.get_match, un fetch a
    ESPN + parseo puro, SIN depender de que el servicio live_tracker esté
    corriendo ni de sus datos persistidos). Best-effort: si ESPN falla o
    tarda, la crónica sigue sin esto (nada se inventa). Sin distinción de
    "roja/cambio por lesión": el feed de ESPN no la marca (confirmado sobre
    un partido real — el texto del evento es genérico, "Substitution at
    66'", sin motivo), así que no se etiqueta ninguna como forzada por
    lesión para no adivinar.

    Los valores de estadística se guardan como número (no el string
    formateado de ESPN) para que numeric_facts() los cubra igual que el
    resto de cifras del payload — si no, el validador de grounding no
    podría contrastar un "59,2%" de posesión que citara el redactor."""
    try:
        from live_tracker.models import EventType
        from live_tracker.providers.espn import EspnProvider
        detail = EspnProvider().get_match(league_slug, str(event_id))
    except Exception:
        return [], []

    stats = []
    for s in detail.stats:
        vl, vv = _num(s.home), _num(s.away)
        if vl is None and vv is None:
            continue
        stats.append({"etiqueta": s.label, "local": vl, "visitante": vv})

    relevant = {EventType.GOAL, EventType.RED, EventType.SUB}
    events = [{"tipo": e.type.value, "minuto": e.minute, "equipo": e.team_side,
              "jugadores": [p.name for p in e.players if p.name]}
             for e in detail.events if e.type in relevant]
    return stats, events


def _match_side_summary(snap, bands, prior_by_id, team_id):
    """Nombre/zona/prob antes-y-después de UN equipo en UN partido — el
    bloque que se repite tanto en una crónica (1 partido) como en un
    resumen diario (varios partidos del mismo día)."""
    t = _team_by_id(snap, team_id)
    if not t:
        return None
    zone = _best_band(bands, t["prob"])
    pt = prior_by_id.get(str(t["id"]))
    return {
        "nombre": t["name"], "id": t["id"], "logo": t["logo"], "posicion": t["rank"],
        "zona": zone["label"], "zona_color": zone.get("color"),
        "prob_zona_actual": t["prob"].get(zone["key"]),
        "prob_zona_antes_del_partido": pt["prob"].get(zone["key"]) if pt else None,
    }


def ground_cronica_partido(league, snap, match):
    """payload de un partido de Hypermotion recién finalizado: marcador +
    cómo cambia la probabilidad de zona de cada equipo respecto al snapshot
    diario más reciente ANTERIOR al día del partido + estadísticas/eventos
    del propio partido. `match`: un evento de espn.fetch_scoreboard_range
    (event_id, date, home/away{id,name}, scores)."""
    bands = snap["bands"]
    prior = _prior_snapshot(league["slug"], snap["season"], match["date"])
    prior_by_id = {str(t["id"]): t for t in (prior or {}).get("teams", [])}

    estadisticas, eventos = _match_stats_and_events(league["slug"], match["event_id"])
    return {
        "tipo": "cronica_partido",
        "liga": league["name"], "temporada": snap["season"], "jornada": snap["jornada"],
        "fecha": match["date"], "event_id": match["event_id"],
        "local": _match_side_summary(snap, bands, prior_by_id, match["home"]["id"]),
        "visitante": _match_side_summary(snap, bands, prior_by_id, match["away"]["id"]),
        "resultado": {"local": match["home_score"], "visitante": match["away_score"]},
        "estadisticas": estadisticas, "eventos": eventos,
    }


def ground_resumen_diario(league, snap, matches):
    """payload de TODOS los partidos de esta liga terminados en un día
    natural concreto (uno por liga, una vez al día a las 00:00 hora local —
    ver PREVIEW_LOCAL_HOUR/generate.py). `matches`: eventos de
    espn.fetch_scoreboard_range ya filtrados a esa fecha y state=='post'."""
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


def _team_headline(snap, team, radius=1):
    """Banda a enseñar de este equipo: SIEMPRE la de mayor probabilidad (ver
    _best_band). `cerca_de_corte` es independiente de eso — solo dice si el
    equipo está a `radius` posiciones de un corte real (misma definición que
    teams_near_boundary), y sirve para elegir QUÉ EQUIPO de un partido
    destacar en render.py:_match_pick, no qué banda mostrar."""
    near = None
    for b in snap["bands"]:
        if abs(team["rank"] - b["lo"]) <= radius or abs(team["rank"] - b["hi"]) <= radius:
            near = b
            break
    band = _best_band(snap["bands"], team["prob"])
    return {
        "nombre": team["name"], "id": team["id"], "logo": team["logo"], "posicion": team["rank"],
        "zona": band["label"], "zona_color": band.get("color"),
        "prob_zona": team["prob"].get(band["key"]),
        "cerca_de_corte": near is not None,
    }


def _match_win_prob(league, snap, home_id, away_id):
    """1X2 pre-partido (pHome/pDraw/pAway, 0-100) con el MISMO modelo de fuerza
    que las ligas y /partido — reutiliza sim_table.snapshot_context/_match_ph_pd
    (igual que live_tracker/strength.py:pre_match_probs) en vez de reimplementar
    la fórmula. None si el snapshot no trae fuerza real de ambos equipos (liga
    uniforme tipo UEFA, o equipo sin rating): el llamador entonces no pinta la
    raya 1X2 en vez de inventar una probabilidad plana."""
    p_home, p_draw = league.get("p_home"), league.get("p_draw")
    if not p_home or not p_draw:
        return None
    sc = sim_table.snapshot_context(snap, float(p_home), float(p_draw))
    hid, aid = str(home_id), str(away_id)
    if sc is None or hid not in sc["strength"] or aid not in sc["strength"]:
        return None
    ph, pd = sim_table._match_ph_pd(sc, hid, aid, float(p_draw), sc["w"])
    pa = max(0.0, 1.0 - ph - pd)
    return {"home": ph * 100, "draw": pd * 100, "away": pa * 100}


def ground_previa_diaria(league, snap, fixtures):
    """payload de los partidos programados HOY para esta liga (una vez al
    día, solo si hay partidos). `fixtures`: eventos de
    espn.fetch_scoreboard_range ya filtrados a la fecha de hoy."""
    partidos = []
    for ev in fixtures:
        home = _team_by_id(snap, ev["home"]["id"])
        away = _team_by_id(snap, ev["away"]["id"])
        if not home or not away:
            continue
        partidos.append({
            "local": _team_headline(snap, home), "visitante": _team_headline(snap, away),
            "hora": ev["kickoff"], "event_id": ev.get("event_id"),
            "win_prob": _match_win_prob(league, snap, home["id"], away["id"]),
        })
    return {
        "tipo": "previa_diaria",
        "liga": league["name"], "temporada": snap["season"], "jornada": snap["jornada"],
        "fecha": fixtures[0]["date"] if fixtures else None,
        "partidos": partidos,
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
