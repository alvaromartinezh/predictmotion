"""Genera las fichas de jugador: data/players/<id>.json y el índice data/players/index.json.

Se invoca desde generate_site (dentro del cron) y también directamente:
    python3 -m seo.players [--league <slug>] [--dry-run]

Cada ficha contiene los datos biográficos del roster de ESPN + stats de la temporada
EN CURSO embebidas en el roster (vacías hasta que se jueguen partidos).

Reglas de consistencia:
- Un jugador aparece en el roster de su liga doméstica Y en el de sus competiciones
  UEFA. El `seen` es GLOBAL y LEAGUES ordena las domésticas primero → gana la ficha
  doméstica (más rica: equipo correcto, stats de la liga en curso).
- Los rosters UEFA embeben stats de la edición ANTERIOR hasta que empieza la nueva
  (verificado 2026-08: 9 PJ de UCL 2025-26 en agosto) → se IGNORAN sus stats.
- El nombre/id del equipo sale de la RAÍZ del roster (`team`), no del athlete
  (`defaultTeam` es solo un $ref).
- Foto: headshot de ESPN si lo trae; si no, el cutout de TheSportsDB cacheado por
  el cron en data/player_cuts.json ({id: {u: url}}).
"""

import json, os, re, sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA   = os.path.join(ROOT, "data", "players")
CUTS   = os.path.join(ROOT, "data", "player_cuts.json")

sys.path.insert(0, str(ROOT))
from seo import config, espn

MAX_WORKERS = 16
UEFA_SLUGS = {"champions", "europa", "conference"}


def _norm(s: str) -> str:
    import unicodedata
    s = (s or "").lower().strip()
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()


def _season_label() -> str:
    today = datetime.now(timezone.utc)
    y = today.year if today.month >= 8 else today.year - 1
    return f"{y}-{(y + 1) % 100:02d}"     # "2026-27", estilo ESPN


def _load_cuts() -> dict:
    """data/player_cuts.json → {id_espn: url_cutout} (solo los que tienen url)."""
    try:
        with open(CUTS, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return {}
    return {k: v["u"] for k, v in raw.items() if isinstance(v, dict) and v.get("u")}


def _player_data(athlete: dict, team: dict, league_slug: str, season: str,
                 cuts: dict) -> dict | None:
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

    # Stats embebidas en el roster = temporada en curso. EXCEPTO en rosters UEFA,
    # que traen la edición anterior hasta que empieza la nueva → se ignoran.
    stat_map = {}
    if league_slug not in UEFA_SLUGS:
        st = athlete.get("statistics") or {}
        splits = st.get("splits") or {}
        for cat in (splits.get("categories") or []):
            for s in (cat.get("stats") or []):
                name = s.get("name", "")
                val = s.get("value")
                if name and val is not None:
                    if isinstance(val, float) and val.is_integer():
                        val = int(val)
                    stat_map[name] = val
    def _g(k): return stat_map.get(k) if k in stat_map else '--'

    # Foto: headshot ESPN (vía combiner, redimensionado) o cutout TheSportsDB.
    aid = str(athlete.get("id", ""))
    href = head.get("href") if isinstance(head, dict) else None
    headshot = None
    if href:
        m = re.match(r"^https?://[^/]+/(.*)$", href)
        headshot = (f"https://a.espncdn.com/combiner/i?img={quote('/' + m[1])}&w=320&h=320"
                    if m else href)
    elif aid in cuts:
        headshot = cuts[aid]

    name = athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or "—"
    return {
        "id":           aid,
        "name":         name,
        "team":         team.get("name") or "",
        "team_id":      team.get("id") or "",
        "team_logo":    team.get("logo") or "",
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


def _fetch_roster(espn_code: str, team_row: dict, league_slug: str,
                  season: str, cuts: dict) -> list[dict]:
    url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/{espn_code}"
            f"/teams/{team_row['id']}/roster")
    try:
        data = espn._get_json(url)
    except Exception:
        return []
    athletes = (data.get("athletes") or [])
    if not athletes and data.get("children"):
        athletes = data["children"][0].get("athletes") or []
    # El equipo: raíz del roster (fiable) → fallback al row de la clasificación.
    t = data.get("team") or {}
    team = {
        "id":   str(t.get("id") or team_row["id"]),
        "name": t.get("displayName") or team_row.get("name") or "",
        "logo": ((t.get("logos") or [{}])[0].get("href")
                 if isinstance(t.get("logos"), list) else None) or team_row.get("logo") or "",
    }
    players = []
    for a in athletes:
        p = _player_data(a, team, league_slug, season, cuts)
        if p:
            players.append(p)
    return players


def run(league_slugs: list[str] | None = None, dry_run: bool = False,
        limit: int = 0) -> dict:
    from seo.config import LEAGUES

    season = _season_label()
    leagues = [lg for lg in LEAGUES if not league_slugs or lg["slug"] in league_slugs]
    errors = []
    os.makedirs(DATA, exist_ok=True)

    cuts = _load_cuts()
    all_players = []
    seen = set()          # GLOBAL: la primera liga que ficha al jugador gana
                          # (LEAGUES ordena domésticas antes que UEFA).

    for league in leagues:
        slug = league["slug"]
        espn_code = league["espn_code"]
        try:
            rows = espn.fetch_table(espn_code)
        except Exception as e:
            errors.append(f"{slug}: standings error: {e}")
            continue
        league_players = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {}
            for row in rows:
                future = ex.submit(_fetch_roster, espn_code, row, slug, season, cuts)
                futures[future] = slug
            for future in as_completed(futures):
                lg_s = futures[future]
                try:
                    pls = future.result()
                except Exception as e:
                    errors.append(f"{lg_s}: {e}")
                    continue
                for p in pls:
                    if p["id"] and p["id"] not in seen:
                        seen.add(p["id"])
                        league_players.append(p)
        if limit:
            league_players = league_players[:limit]
        all_players.extend(league_players)
        print(f"  [{slug}] {len(league_players)} fichas")

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
            "team_id":   p["team_id"],
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
    run(slugs, args.dry_run, args.limit)
    sys.exit(0)
