"""Cliente de la API pública de ESPN — solo stdlib (urllib).

Mismos endpoints y mismo parseo que el JS del navegador, para que los datos de
partida sean idénticos a los que ve el usuario en el dashboard.
"""

import json
import re
import urllib.request

_BASE_V2   = "https://site.api.espn.com/apis/v2/sports/soccer"
_BASE_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
_HEADERS   = {"User-Agent": "Mozilla/5.0 (PredictMotion SEO generator)"}
_TIMEOUT   = 25


def _get_json(url):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _stat(entry, name):
    for s in entry.get("stats", []):
        if s.get("name") == name:
            return s.get("value") or 0
    return 0


def fetch_table(espn_code):
    """Clasificación de una liga regular. Port de fetchStandings()."""
    data = _get_json(f"{_BASE_V2}/{espn_code}/standings")
    entries = data["children"][0]["standings"]["entries"]
    rows = []
    for i, e in enumerate(entries):
        team = e["team"]
        logos = team.get("logos") or []
        rows.append({
            "rank":   i + 1,
            "id":     str(team["id"]),
            "name":   team["displayName"],
            "abbr":   team.get("abbreviation", ""),
            "logo":   logos[0]["href"] if logos else None,
            "gp":     int(_stat(e, "gamesPlayed")),
            "pts":    int(_stat(e, "points")),
            "gf":     int(_stat(e, "pointsFor")),
            "gc":     int(_stat(e, "pointsAgainst")),
            "wins":   int(_stat(e, "wins")),
            "draws":  int(_stat(e, "ties")),
            "losses": int(_stat(e, "losses")),
        })
    return rows


def fetch_groups(espn_code):
    """Grupos del Mundial. Port de fetchGroups()."""
    data = _get_json(f"{_BASE_V2}/{espn_code}/standings")
    children = data.get("children") or []
    groups = []
    for child in children:
        raw = (child.get("abbreviation") or child.get("name") or "")
        name = raw.replace("Group", "").replace("Grupo", "").strip() or child.get("name")
        entries = []
        for i, e in enumerate(child.get("standings", {}).get("entries", [])):
            team = e["team"]
            logos = team.get("logos") or []
            entries.append({
                "rank":   i + 1,
                "id":     str(team["id"]),
                "name":   team["displayName"],
                "abbr":   team.get("abbreviation", ""),
                "logo":   logos[0]["href"] if logos else None,
                "gp":     int(_stat(e, "gamesPlayed")),
                "pts":    int(_stat(e, "points")),
                "gf":     int(_stat(e, "pointsFor")),
                "gc":     int(_stat(e, "pointsAgainst")),
                "wins":   int(_stat(e, "wins")),
                "draws":  int(_stat(e, "ties")),
                "losses": int(_stat(e, "losses")),
            })
        if entries:
            groups.append({"name": name, "entries": entries})
    return groups


def fetch_league_meta(espn_code):
    """Metadatos vivos de la competición desde ESPN (nada hardcodeado).

    Devuelve {'logo':..., 'season':...} (best-effort, valores None si falla).
    - logo: de `leagues[0].logos`, preferida la variante 'dark' (logo claro para
      fondo oscuro); si no, la 'default'.
    - season: de `leagues[0].season.displayName`, extraído como 'YYYY-YY'.
    """
    out = {"logo": None, "season": None}
    try:
        data = _get_json(f"{_BASE_SITE}/{espn_code}/scoreboard")
    except Exception:
        return out
    lg = (data.get("leagues") or [{}])[0]
    logos = lg.get("logos") or []
    if logos:
        dark = next((l for l in logos if "dark" in (l.get("rel") or [])), None)
        href = (dark or logos[0]).get("href")
        if href and href.startswith("http://"):
            href = "https://" + href[len("http://"):]
        out["logo"] = href
    dn = (lg.get("season") or {}).get("displayName") or ""
    m = re.search(r"\d{4}-\d{2}", dn)
    if m:
        out["season"] = m.group(0)
    return out


def fetch_remaining_schedule(espn_code, team_id):
    """Próximos partidos de un equipo (estado 'pre').

    Best-effort: si falla o no hay datos, devuelve []. Nunca inventa partidos.
    """
    try:
        data = _get_json(f"{_BASE_SITE}/{espn_code}/teams/{team_id}/schedule")
    except Exception:
        return []
    out = []
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        status = (comp.get("status") or ev.get("status") or {}).get("type", {})
        if status.get("state") != "pre":
            continue
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        is_home = str(home["team"]["id"]) == str(team_id)
        opp = away if is_home else home
        out.append({
            "date":     ev.get("date", "")[:10],
            "opponent": opp["team"].get("displayName", ""),
            "opp_id":   str(opp["team"].get("id", "")),
            "home":     is_home,
        })
    return out
