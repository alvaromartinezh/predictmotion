"""Genera las fichas de jugador: data/players/<id>.json y el índice data/players/index.json.

Se invoca desde generate_site (dentro del cron) y también directamente:
    python3 -m seo.players [--league <slug>] [--dry-run]

Cada ficha contiene los datos biográficos que ofrece el roster de ESPN para un jugador.
Los stats de partido (goles/asistencias) habría que agregarlos match a match — por ahora
solo biographical + stats de la temporada si ESPN las incluye en el roster (normalmente
vacías para fútbol; se rellenan con el símbolo '--').
"""

import json, os, sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA   = os.path.join(ROOT, "data", "players")

sys.path.insert(0, str(ROOT))
from seo import config, espn

MAX_WORKERS = 16


def _norm(s: str) -> str:
    import unicodedata
    s = (s or "").lower().strip()
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()


def _player_data(athlete: dict, team_slug: str, league_slug: str, season: str) -> dict | None:
    pos  = athlete.get("position") or {}
    flag = athlete.get("flag") or {}
    head = athlete.get("headshot") or {}
    dob  = athlete.get("dateOfBirth") or athlete.get("birthDate")
    height_in = athlete.get("height")
    height_cm = round(height_in * 2.54) if height_in else None
    weight_lb = athlete.get("weight")
    weight_kg = round(weight_lb * 0.453592) if weight_lb else None
    citizens = athlete.get("citizenship") or []
    if isinstance(citizens, str):
        citizens = [citizens]
    age = athlete.get("age")
    injuries = athlete.get("injuries") or []
    injury_text = None
    if injuries:
        inj = injuries[0] if injuries else None
        if inj and inj.get("status") != "ACTIVE":
            injury_text = inj.get("description") or inj.get("type") or "Lesionado"
    stat_map = {}
    st = athlete.get("statistics") or {}
    splits = st.get("splits") or {}
    for cat in (splits.get("categories") or []):
        for s in (cat.get("stats") or []):
            name = s.get("name", "")
            val = s.get("value")
            if name and val is not None:
                # ESPN sirve los contadores como float (2.0) — normalizar a int.
                if isinstance(val, float) and val.is_integer():
                    val = int(val)
                stat_map[name] = val
    def _g(k): return stat_map.get(k) if k in stat_map else '--'
    href = head.get("href") if isinstance(head, dict) else None
    headshot = None
    if href:
        import re
        m = re.match(r"^https?://[^/]+/(.*)$", href)
        headshot = (f"https://a.espncdn.com/combiner/i?img=/{m[1]}&w=320&h=320"
                    if m else href)
    name = athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or "—"
    slug = (name.lower().replace(" ", "-").replace("'", "-").replace(".", "")
             + "-" + str(athlete.get("id", "")))
    return {
        "id":           str(athlete.get("id", "")),
        "name":         name,
        "slug":         slug,
        "team":         athlete.get("defaultTeam", {}).get("displayName") or "",
        "team_slug":    team_slug,
        "league_slug":  league_slug,
        "season":       season,
        "position":     pos.get("abbreviation") or "—",
        "posLabel":     pos.get("displayName") or "—",
        "jersey":       athlete.get("jersey") or None,
        "age":          age,
        "dob":          dob,
        "height_cm":    height_cm,
        "weight_kg":    weight_kg,
        "nationality":  citizens[0] if citizens else None,
        "flag":         flag.get("href") if isinstance(flag, dict) else None,
        "headshot":     headshot,
        "injury":       injury_text,
        "stats": {
            "matches":  _g("appearances") or _g("gamesPlayed"),
            "minutes": _g("minutes"),
            "goals":    _g("totalGoals") or _g("goals"),
            "assists":  _g("goalAssists") or _g("assists"),
            "yellow":   _g("yellowCards"),
            "red":      _g("redCards"),
        },
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _fetch_roster(espn_code: str, team_id: str, team_slug: str,
                   league_slug: str, season: str) -> list[dict]:
    url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/{espn_code}"
            f"/teams/{team_id}/roster")
    try:
        data = espn._get_json(url)
    except Exception:
        return []
    athletes = (data.get("athletes") or [])
    if not athletes and data.get("children"):
        athletes = data["children"][0].get("athletes") or []
    players = []
    for a in athletes:
        p = _player_data(a, team_slug, league_slug, season)
        if p:
            players.append(p)
    return players


def run(league_slugs: list[str] | None = None, dry_run: bool = False,
        limit: int = 0) -> dict:
    global SEASON
    from seo.config import LEAGUES

    today = datetime.now(timezone.utc)
    if today.month >= 8:
        SEASON = f"{today.year}-{today.year + 1}"
    else:
        SEASON = f"{today.year - 1}-{today.year}"

    leagues = [lg for lg in LEAGUES if not league_slugs or lg["slug"] in league_slugs]
    ok, errors, total = 0, [], 0
    os.makedirs(DATA, exist_ok=True)
    all_players = []

    for league in leagues:
        slug = league["slug"]
        espn_code = league["espn_code"]
        try:
            rows = espn.fetch_table(espn_code)
        except Exception as e:
            errors.append(f"{slug}: standings error: {e}")
            continue
        team_players = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {}
            for row in rows:
                tid = row["id"]
                future = ex.submit(_fetch_roster, espn_code, tid, slug, slug, SEASON)
                futures[future] = (slug, tid)
            for future in as_completed(futures):
                lg_s, tid = futures[future]
                try:
                    pls = future.result()
                except Exception as e:
                    errors.append(f"{lg_s}/{tid}: {e}")
                    continue
                if limit:
                    pls = pls[:limit]
                team_players.extend(pls)
        all_players.extend(team_players)
        print(f"  [{slug}] {len(team_players)} fichas")

    if not dry_run:
        for p in all_players:
            path = os.path.join(DATA, f"{p['id']}.json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(p, fh, ensure_ascii=False, indent=2)
            os.rename(tmp, path)
        index = [{
            "id":        p["id"],
            "name":      p["name"],
            "norm":      _norm(p["name"]),
            "team":      p["team"],
            "team_slug": p["team_slug"],
            "league":    p["league_slug"],
            "pos":       p["position"],
            "posLabel":  p["posLabel"],
            "headshot":  p["headshot"],
        } for p in all_players]
        idx_path = os.path.join(DATA, "index.json")
        tmp = idx_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(index, fh, ensure_ascii=False, indent=2)
        os.rename(tmp, idx_path)

    ok = len(all_players)
    print(f"\nplayers: {ok} fichas escritas, {len(errors)} errores.")
    return {"ok": ok, "errors": errors, "players": ok}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--league")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    slugs = [args.league] if args.league else None
    result = run(slugs, args.dry_run, args.limit)
    sys.exit(0)
