"""Snapshots: construcción, persistencia y series históricas.

Un snapshot = estado de probabilidades de una liga en una fecha. Se guarda uno
por día (se sobreescribe el del mismo día). El histórico crece de forma
orgánica jornada a jornada; no se inventa nada del pasado.
"""

import json
from datetime import datetime, timezone

from .config import DATA_DIR
from .sim_table import zone_prob
from .textutil import slugify


# ── Construcción ────────────────────────────────────────────────────────────

def build_table_snapshot(league, rows, sim, sim_n, today, league_logo=None):
    n = len(rows)
    bands = league["bands"](n)
    jornada = max(r["gp"] for r in rows)
    total_md = 2 * (n - 1)

    teams = []
    for r in rows:
        res = sim[r["name"]]
        prob = {}
        for b in bands:
            prob[b["key"]] = zone_prob(res["pos_hist"], b["lo"], b["hi"], sim_n)
        if league.get("playoff_top"):
            prob["pSemi"] = res["pSemi"]
            prob["pFinal"] = res["pFinal"]
            prob["pWin"] = res["pWin"]
        teams.append({
            "slug":   slugify(r["name"]),
            "rank":   r["rank"],
            "id":     r["id"],
            "name":   r["name"],
            "logo":   r["logo"],
            "gp":     r["gp"], "pts": r["pts"],
            "gf":     r["gf"], "gc": r["gc"],
            "wins":   r["wins"], "draws": r["draws"], "losses": r["losses"],
            "prob":   prob,
        })

    return {
        "league":   league["slug"],
        "kind":     "table",
        "name":     league["name"],
        "season":   league["season"],
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


def build_cup_snapshot(league, groups, sim, today, league_logo=None):
    num_groups = len(groups)
    best3 = 0 if num_groups <= 8 else min(8, num_groups)
    advancing = num_groups * 2 + best3
    matchday = max((t["gp"] for g in groups for t in g["entries"]), default=0)

    out_groups = []
    for g in groups:
        entries = []
        for t in g["entries"]:
            prob = sim.get(t["id"], {"p1st": 0, "p2nd": 0, "p3rd": 0, "pOut": 0, "pAdv": 0})
            entries.append({
                "slug": slugify(t["name"]),
                "rank": t["rank"], "id": t["id"], "name": t["name"],
                "abbr": t["abbr"], "logo": t["logo"],
                "gp": t["gp"], "pts": t["pts"], "gf": t["gf"], "gc": t["gc"],
                "wins": t["wins"], "draws": t["draws"], "losses": t["losses"],
                "prob": prob,
            })
        out_groups.append({"name": g["name"], "entries": entries})

    return {
        "league":   league["slug"],
        "kind":     "cup",
        "name":     league["name"],
        "season":   league["season"],
        "date":     today,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "league_logo": league_logo,
        "matchday": matchday,
        "num_groups": num_groups,
        "advancing": advancing,
        "groups":   out_groups,
    }


# ── Persistencia ────────────────────────────────────────────────────────────

def _league_dir(slug):
    d = DATA_DIR / slug
    (d / "snapshots").mkdir(parents=True, exist_ok=True)
    return d


def save_snapshot(snap):
    d = _league_dir(snap["league"])
    path = d / "snapshots" / f"{snap['date']}.json"
    payload = json.dumps(snap, ensure_ascii=False, indent=1)
    path.write_text(payload, encoding="utf-8")
    (d / "latest.json").write_text(payload, encoding="utf-8")
    return path


def load_all(slug):
    """Todos los snapshots de una liga, ordenados por fecha ascendente."""
    d = DATA_DIR / slug / "snapshots"
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
