"""Snapshots: construcción, persistencia y series históricas.

Un snapshot = estado de probabilidades de una liga en una fecha. Se guarda uno
por día (se sobreescribe el del mismo día). El histórico crece de forma
orgánica jornada a jornada; no se inventa nada del pasado.
"""

import json
from datetime import datetime, timezone

from .config import DATA_DIR, STRENGTH_SCALE, STRENGTH_FADE_FRACTION
from .sim_table import zone_prob, resolve_strengths
from .textutil import slugify


# ── Construcción ────────────────────────────────────────────────────────────

def derive_bands_from_notes(bands, rows):
    """Deriva lo/hi de cada banda desde las notas de zona de ESPN, replicando
    deriveSlots() del dashboard: caminata CONTIGUA desde la cabeza para las zonas
    de arriba (una plaza no contigua —p. ej. la de Copa del Rey que ESPN marca a
    media tabla— no ensancha el rango) y desde el fondo para el descenso. Cada
    banda se empareja por su `zone`. Si una zona no tiene notas (inicio de
    temporada), la banda conserva su lo/hi de fallback. Muta `bands` y lo devuelve.
    """
    by_rank = sorted(rows, key=lambda r: r["rank"])
    n = len(by_rank)
    zone_of = [r.get("zone", "none") for r in by_rank]   # índice 0 = rank 1
    cursor = 0
    for b in bands:                                        # zonas de arriba, en orden
        if not b.get("zone") or b["zone"] == "relega":
            continue
        start = cursor
        while cursor < n and zone_of[cursor] == b["zone"]:
            cursor += 1
        if cursor > start:                                # hubo notas para esta zona
            b["lo"], b["hi"] = start + 1, cursor
    releg = next((b for b in bands if b.get("zone") == "relega"), None)
    if releg is not None:
        cnt, j = 0, n - 1
        while j >= 0 and zone_of[j] == "relega":
            cnt += 1; j -= 1
        if cnt > 0:
            releg["lo"], releg["hi"] = n - cnt + 1, n
    return bands


def build_table_snapshot(league, rows, sim, sim_n, today, league_logo=None,
                         season=None, ratings=None):
    n = len(rows)
    bands = league["bands"](n)
    if league.get("bands_from_notes"):
        bands = derive_bands_from_notes(bands, rows)
    jornada = max(r["gp"] for r in rows)
    # matches_per_team: formatos que no son round-robin (fase de liga UEFA: 36
    # equipos, 8 partidos). None → doble vuelta de siempre.
    total_md = league.get("matches_per_team") or 2 * (n - 1)

    # Fuerza por equipo (misma resolución que la sim) para que el fallback JS de
    # los dashboards aplique el mismo prior sin re-derivarlo. None → no se guarda.
    strengths = resolve_strengths(rows, ratings)

    teams = []
    for r in rows:
        res = sim[r["name"]]
        prob = {}
        for b in bands:
            prob[b["key"]] = zone_prob(res["pos_hist"], b["lo"], b["hi"], sim_n)
        # Prob. de título (acabar 1º): la pinta el dashboard de LaLiga (píldora
        # "Título") y no coincide con ninguna banda (Champions es 1-4). Inofensiva
        # para las ligas que no la muestran.
        prob["first"] = zone_prob(res["pos_hist"], 1, 1, sim_n)
        if league.get("playoff_top"):
            prob["pSemi"] = res["pSemi"]
            prob["pFinal"] = res["pFinal"]
            prob["pWin"] = res["pWin"]
        team = {
            "slug":   slugify(r["name"]),
            "rank":   r["rank"],
            "id":     r["id"],
            "name":   r["name"],
            "logo":   r["logo"],
            "gp":     r["gp"], "pts": r["pts"],
            "gf":     r["gf"], "gc": r["gc"],
            "wins":   r["wins"], "draws": r["draws"], "losses": r["losses"],
            "prob":   prob,
        }
        if strengths is not None:
            team["strength"] = round(strengths[r["id"]], 4)
        teams.append(team)

    snap = {
        "league":   league["slug"],
        "kind":     "table",
        "name":     league["name"],
        "season":   season or league["season"],
        "date":     today,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "league_logo": league_logo,
        "jornada":  jornada,
        "total_md": total_md,
        "num_teams": n,
        "finished": all(sim[r["name"]]["finished"] for r in rows),
        "bands":    bands,
        "has_playoff": bool(league.get("playoff_top")),
        "teams":    teams,
    }
    # Parámetros del prior de fuerza para que el fallback JS aplique la MISMA
    # fórmula (solo si hay fuerzas; si no, el fallback usa el modelo uniforme).
    if strengths is not None:
        snap["strength_scale"] = STRENGTH_SCALE
        snap["strength_fade_fraction"] = STRENGTH_FADE_FRACTION
    return snap


# ── Persistencia ────────────────────────────────────────────────────────────
# Los snapshots se PARTICIONAN por temporada: data/<slug>/<season>/snapshots/.
# Así el histórico/evolución de una temporada no se mezcla con el de otra (2025-26
# jornada 38 vs 2026-27 jornada 0). El `latest.json` de la temporada viva se
# mantiene ADEMÁS en la raíz data/<slug>/latest.json — ese es el contrato que leen
# los dashboards (/data/<slug>/latest.json), no se toca.

def _season_dir(slug, season):
    d = DATA_DIR / slug / season
    (d / "snapshots").mkdir(parents=True, exist_ok=True)
    return d


def save_snapshot(snap):
    d = _season_dir(snap["league"], snap["season"])
    path = d / "snapshots" / f"{snap['date']}.json"
    payload = json.dumps(snap, ensure_ascii=False, indent=1)
    path.write_text(payload, encoding="utf-8")
    (d / "latest.json").write_text(payload, encoding="utf-8")          # latest de la temporada
    (DATA_DIR / snap["league"] / "latest.json").write_text(payload, encoding="utf-8")  # latest vivo (dashboards)
    return path


def load_all(slug, season):
    """Snapshots de UNA temporada de una liga, ordenados por fecha ascendente."""
    d = DATA_DIR / slug / season / "snapshots"
    if not d.exists():
        return []
    snaps = []
    for f in sorted(d.glob("*.json")):
        try:
            snaps.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return snaps


def per_period_series(snaps, key):
    """Un snapshot por periodo (jornada/matchday): el último de cada valor.

    Devuelve lista [(periodo, snapshot)] ordenada por periodo ascendente.
    """
    by_period = {}
    for s in snaps:
        by_period[s[key]] = s  # el último visto (orden por fecha) gana
    return [(p, by_period[p]) for p in sorted(by_period)]
