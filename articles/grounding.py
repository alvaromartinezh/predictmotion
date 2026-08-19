"""Payload de hechos reales para el prompt de Gemini.

Lee data/<slug>/latest.json (mismo contrato que leen los dashboards) y, para
comparar antes/después de un partido, el histórico particionado por
temporada que ya persiste seo/snapshots.py. Nada se inventa aquí: si un dato
no está en el snapshot, no entra en el payload (y por tanto Gemini no puede
citarlo).
"""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from seo import espn
from seo.poisson import cdf as poisson_cdf
from seo.sim_table import match_1x2, match_rates
from seo.snapshots import load_all
from seo.textutil import pct
from .config import DATA_DIR, ASCENSO_TOTAL_SEASON_FRACTION, STAT_KINDS

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


def pick_stat_kind(hour, day=0):
    """Alterna entre los STAT_KINDS por franja horaria + día — determinista (sin
    estado que mantener): dos ejecuciones a la misma hora del mismo día eligen lo
    mismo. `day` es un entero arbitrario (p. ej. el YYYYMMDD de la fecha del
    artículo) que desplaza la rotación: con 7 kinds y 6 franjas por día, sin el
    offset el ciclo de franjas dejaba siempre el mismo kind fuera."""
    keys = list(STAT_KINDS)
    return keys[(hour // 2 + day) % len(keys)]


def _dato_label(kind, n):
    info = STAT_KINDS[kind]
    if kind == "colista":
        return f"Probabilidad de ser {n}º"
    return info["dato_label"]


def format_val(kind, v):
    """'64,2%' para probabilidades; '−0,50 goles/partido' para el blend (fmt
    "goles"). Formateo ÚNICO del valor de un kind — lo usan render.py (box de
    ranking, columna lateral) y el titular determinista de writer.py."""
    if v is None:
        return "—"
    if STAT_KINDS[kind].get("fmt") == "goles":
        return f"{v:+.2f}".replace(".", ",") + " goles/partido"
    return pct(v)


def _stat_payload(league, snap, kind, fecha, hour, n, ranking_sides, shape="team"):
    info = STAT_KINDS[kind]
    return {
        "tipo": f"dato_{kind}", "kind": kind, "shape": shape,
        "liga": league["name"], "temporada": snap["season"], "jornada": snap["jornada"],
        "fecha": fecha, "hour": hour, "num_equipos": n,
        "dato_label": _dato_label(kind, n), "dato_verbo": info["verbo"],
        "protagonista": ranking_sides[0],
        "perseguidores": ranking_sides[1:4],
        "ranking": ranking_sides,
    }


def _ground_posicion(league, snap, kind, fecha, hour):
    """Posición final exacta (colista/líder): prob.first/last, ya persistida
    por el cron en cada equipo del snapshot. Ninguna simulación nueva."""
    info = STAT_KINDS[kind]
    key = info["prob_key"]
    n = snap.get("num_teams") or len(snap["teams"])
    bands = snap["bands"]
    candidates = [t for t in snap["teams"] if t["prob"].get(key) is not None]
    if len(candidates) < 4:
        return None
    ranking = sorted(candidates, key=lambda t: t["prob"][key], reverse=True)[:6]

    prior = _prior_snapshot(league["slug"], snap["season"], fecha)
    prior_by_id = {str(t["id"]): t for t in (prior or {}).get("teams", [])}

    def side(t):
        pt = prior_by_id.get(str(t["id"]))
        zone = _best_band(_effective_bands(snap, bands), t["prob"])
        return {
            "nombre": t["name"], "id": t["id"], "logo": t["logo"], "posicion": t["rank"],
            "puntos": t["pts"], "pj": t.get("gp"), "rating_fuerza": t.get("strength"),
            "valor": t["prob"][key],
            "valor_antes": (pt["prob"].get(key) if pt else None),
            "zona": zone["label"], "prob_zona": t["prob"].get(zone["key"]),
        }

    return _stat_payload(league, snap, kind, fecha, hour, n,
                         [side(t) for t in ranking])


def _ground_equipo(league, snap, kind, fecha, hour):
    """Fuerza del blend v3 (att/def del snapshot, muro/ataque): leer una
    desviación que el cron YA persiste por equipo — sin simular nada nuevo."""
    info = STAT_KINDS[kind]
    campo = info["campo"]
    descend = info.get("sort", "max") == "max"
    candidates = [t for t in snap["teams"] if t.get(campo) is not None]
    if len(candidates) < 4:
        return None
    ranking = sorted(candidates, key=lambda t: t[campo], reverse=descend)[:6]
    n = snap.get("num_teams") or len(snap["teams"])
    bands = snap["bands"]

    prior = _prior_snapshot(league["slug"], snap["season"], fecha)
    prior_by_id = {str(t["id"]): t for t in (prior or {}).get("teams", [])}

    def side(t):
        pt = prior_by_id.get(str(t["id"]))
        zone = _best_band(_effective_bands(snap, bands), t["prob"])
        return {
            "nombre": t["name"], "id": t["id"], "logo": t["logo"], "posicion": t["rank"],
            "puntos": t["pts"], "pj": t.get("gp"), "rating_fuerza": t.get("strength"),
            "valor": round(t[campo], 2),
            "valor_antes": (round(pt[campo], 2) if pt and pt.get(campo) is not None else None),
            "zona": zone["label"], "prob_zona": t["prob"].get(zone["key"]),
        }

    return _stat_payload(league, snap, kind, fecha, hour, n,
                         [side(t) for t in ranking])


def _next_matchday(league, snap, today):
    """Partidos `pre` de la PRÓXIMA jornada: los primeros num_teams//2 eventos
    pre de ESPN ordenados por saque a partir de mañana. [] si el scoreboard
    falla o no hay fixtures futuros (→ el kind de jornada no se publica; sin
    grounding no hay artículo)."""
    n = snap.get("num_teams") or len(snap["teams"])
    start = (datetime.fromisoformat(today) + timedelta(days=1)).strftime("%Y%m%d")
    end = (datetime.fromisoformat(today) + timedelta(days=14)).strftime("%Y%m%d")
    try:
        events = espn.fetch_scoreboard_range(league["espn_code"], start, end)
    except Exception:
        return []
    pre = [e for e in events if e.get("state") == "pre"]
    pre.sort(key=lambda e: e.get("kickoff") or e.get("date") or "")
    return pre[: max(1, n // 2)]


def _match_item(snap, bands, prior_by_id, th, ta, valor, ph, pd, pa, kickoff):
    """Side del "dato curioso" cuando el protagonista es un PARTIDO (shape
    'partido'): trae los dos equipos, sus posiciones y el 1X2 del modelo (en %)
    para que Gemini cite números reales y render.py pinte local vs visitante."""
    zone = _best_band(_effective_bands(snap, bands), th["prob"])
    return {
        "tipo": "partido",
        "nombre": f'{th["name"]} vs {ta["name"]}',
        "local": {"nombre": th["name"], "id": th["id"], "logo": th["logo"]},
        "visitante": {"nombre": ta["name"], "id": ta["id"], "logo": ta["logo"]},
        "kickoff": kickoff,
        "valor": round(valor, 1), "valor_antes": None,
        "p_local": round(ph * 100, 1), "p_empate": round(pd * 100, 1),
        "p_visita": round(pa * 100, 1),
        "zona": zone["label"], "prob_zona": th["prob"].get(zone["key"]),
        "posicion": None, "puntos": None, "rating_fuerza": None, "pj": None,
    }


def _ground_jornada(league, snap, kind, fecha, hour):
    """Próxima jornada resuelta con el MISMO modelo v3 del snapshot
    (match_rates/match_1x2): goleado (P encajar ≥3, de la λ que concede el
    rival), favorito_jornada (P de ganar) o nivel_jornada (partido con más
    fuerza combinada att−def, shape 'partido' con 1X2)."""
    info = STAT_KINDS[kind]
    bands = snap["bands"]
    n = snap.get("num_teams") or len(snap["teams"])
    matches = _next_matchday(league, snap, fecha)
    if len(matches) < 2:
        return None
    prior = _prior_snapshot(league["slug"], snap["season"], fecha)
    prior_by_id = {str(t["id"]): t for t in (prior or {}).get("teams", [])}
    p_home = league.get("p_home", 0.45)
    p_draw = league.get("p_draw", 0.26)

    if info.get("shape") == "partido":
        items = []
        for m in matches:
            th, ta = team_by_id(snap, m["home"]["id"]), team_by_id(snap, m["away"]["id"])
            if not th or not ta:
                continue
            nivel = ((th.get("att") or 0) - (th.get("def") or 0)
                     + (ta.get("att") or 0) - (ta.get("def") or 0))
            probs = match_1x2(snap, th["id"], ta["id"], p_home, p_draw)
            if probs is None:
                continue
            items.append(_match_item(snap, bands, prior_by_id, th, ta, nivel,
                                     probs[0], probs[1], probs[2], m.get("kickoff")))
        if len(items) < 2:
            return None
        items.sort(key=lambda it: it["valor"], reverse=True)
        return _stat_payload(league, snap, kind, fecha, hour, n,
                             items[:6], shape="partido")

    per_team = {}
    for m in matches:
        th, ta = team_by_id(snap, m["home"]["id"]), team_by_id(snap, m["away"]["id"])
        if not th or not ta:
            continue
        if kind == "goleado":
            rates = match_rates(snap, th["id"], ta["id"])
            if rates is None:
                continue
            lam_h, lam_a, max_goals = rates
            per_team.setdefault(str(th["id"]), 100.0 * (1 - poisson_cdf(lam_a, max_goals)[2]))
            per_team.setdefault(str(ta["id"]), 100.0 * (1 - poisson_cdf(lam_h, max_goals)[2]))
        else:  # favorito_jornada
            probs = match_1x2(snap, th["id"], ta["id"], p_home, p_draw)
            if probs is None:
                continue
            per_team.setdefault(str(th["id"]), 100.0 * probs[0])
            per_team.setdefault(str(ta["id"]), 100.0 * probs[2])
    if len(per_team) < 4:
        return None

    ranking = sorted([t for t in snap["teams"] if str(t["id"]) in per_team],
                     key=lambda t: per_team[str(t["id"])], reverse=True)[:6]
    if len(ranking) < 4:
        return None

    def side(t):
        zone = _best_band(_effective_bands(snap, bands), t["prob"])
        return {
            "nombre": t["name"], "id": t["id"], "logo": t["logo"], "posicion": t["rank"],
            "puntos": t["pts"], "pj": t.get("gp"), "rating_fuerza": t.get("strength"),
            "valor": round(per_team[str(t["id"])], 1),
            "valor_antes": None,
            "zona": zone["label"], "prob_zona": t["prob"].get(zone["key"]),
        }

    return _stat_payload(league, snap, kind, fecha, hour, n,
                         [side(t) for t in ranking])


def ground_stat(league, snap, kind, fecha, hour):
    """payload de hechos del "dato curioso" según `kind` (ver STAT_KINDS):
    qué equipo —o qué partido, en shape 'partido'— manda en ese dato según la
    simulación YA calculada. None si la liga no tiene datos suficientes
    (offseason, snapshot sin prob/blend, o sin fixtures de la próxima jornada;
    sin grounding no hay artículo)."""
    info = STAT_KINDS[kind]
    tipo = info["tipo"]
    if tipo == "posicion":
        return _ground_posicion(league, snap, kind, fecha, hour)
    if tipo == "equipo":
        return _ground_equipo(league, snap, kind, fecha, hour)
    if tipo == "jornada":
        return _ground_jornada(league, snap, kind, fecha, hour)
    return None


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
