"""Adapter sobre la API pública de ESPN para el Mundial (fifa.world)."""

from __future__ import annotations
from typing import Optional
import requests

_ESPN_V2   = "https://site.api.espn.com/apis/v2/sports/soccer"
_ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"


def _stat(stats: list[dict], name: str, default: int = 0) -> int:
    for s in stats:
        if s.get("name") == name:
            return int(s.get("value", default))
    return default


class DataSource:
    def __init__(self, espn_code: str = "fifa.world"):
        self.code = espn_code
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "PredictMotion/1.0"

    def _get(self, url: str, **params) -> dict:
        r = self._session.get(url, params=params or None, timeout=10)
        r.raise_for_status()
        return r.json()

    # ── Grupos ────────────────────────────────────────────────────────────────

    def get_all_groups(self) -> list[dict]:
        """Lista de grupos. Cada grupo: {name, entries: [equipo, ...]}.
        Equipo: {id, name, abbr, logo, pts, gp, gf, gc, w, d, l, rank}."""
        data = self._get(f"{_ESPN_V2}/{self.code}/standings")
        groups = []
        for child in data.get("children", []):
            name    = child.get("name") or child.get("abbreviation", "?")
            raw     = child.get("standings", {}).get("entries", [])
            entries = []
            for e in raw:
                stats = e.get("stats", [])
                team  = e.get("team", {})
                logos = team.get("logos", [])
                entries.append({
                    "id":   team.get("id", ""),
                    "name": team.get("displayName", "?"),
                    "abbr": team.get("abbreviation", ""),
                    "logo": logos[0]["href"] if logos else None,
                    "pts":  _stat(stats, "points"),
                    "gp":   _stat(stats, "gamesPlayed"),
                    "gf":   _stat(stats, "pointsFor"),
                    "gc":   _stat(stats, "pointsAgainst"),
                    "w":    _stat(stats, "wins"),
                    "d":    _stat(stats, "ties"),
                    "l":    _stat(stats, "losses"),
                })
            entries.sort(key=lambda t: (-t["pts"], -(t["gf"] - t["gc"]), -t["gf"]))
            for i, t in enumerate(entries):
                t["rank"] = i + 1
            groups.append({"name": name, "entries": entries})
        return groups

    def get_group_standings(self, group_name: str) -> Optional[dict]:
        for g in self.get_all_groups():
            if g["name"].upper() == group_name.upper():
                return g
        return None

    def get_best_third_placed(self) -> list[dict]:
        """Mejores terceros de cada grupo, ordenados por criterio FIFA (pts, DG, GF)."""
        groups = self.get_all_groups()
        thirds = []
        for g in groups:
            if len(g["entries"]) >= 3:
                thirds.append({**g["entries"][2], "group": g["name"]})
        thirds.sort(key=lambda t: (-t["pts"], -(t["gf"] - t["gc"]), -t["gf"]))
        for i, t in enumerate(thirds):
            t["third_rank"] = i + 1
        return thirds

    # ── Scoreboard ────────────────────────────────────────────────────────────

    def get_live_matches(self) -> list[dict]:
        """Partidos de hoy (pre/in/post). Incluye detección de grupo."""
        data = self._get(f"{_ESPN_SITE}/{self.code}/scoreboard")
        matches = []
        for event in data.get("events", []):
            comp   = event["competitions"][0]
            comps  = comp["competitors"]
            try:
                home = next(c for c in comps if c["homeAway"] == "home")
                away = next(c for c in comps if c["homeAway"] == "away")
            except StopIteration:
                continue

            group = self._extract_group(event, comp)

            matches.append({
                "id":        event["id"],
                "name":      event.get("shortName", event.get("name", "")),
                "state":     event["status"]["type"]["state"],      # pre|in|post
                "clock":     event["status"].get("displayClock", ""),
                "completed": event["status"]["type"].get("completed", False),
                "home_id":   home["team"]["id"],
                "home_name": home["team"]["displayName"],
                "home_abbr": home["team"].get("abbreviation", ""),
                "home_score": int(home.get("score") or 0),
                "away_id":   away["team"]["id"],
                "away_name": away["team"]["displayName"],
                "away_abbr": away["team"].get("abbreviation", ""),
                "away_score": int(away.get("score") or 0),
                "is_group":  group is not None,
                "group":     group,
                "date":      event.get("date", ""),
            })
        return matches

    @staticmethod
    def _extract_group(event: dict, comp: dict) -> Optional[str]:
        """Intenta extraer la letra del grupo desde las notas o el nombre del evento."""
        for note in comp.get("notes", []):
            h = note.get("headline", "")
            for prefix in ("Grupo ", "Group "):
                if h.startswith(prefix):
                    return h[len(prefix):].strip().split()[0]
        for label in [event.get("shortName", ""), event.get("name", "")]:
            for prefix in ("Grupo ", "Group "):
                if prefix in label:
                    after = label.split(prefix, 1)[1].strip()
                    return after.split()[0] if after else None
        return None

    # ── Eventos de partido ────────────────────────────────────────────────────

    def get_match_events(self, match_id: str) -> list[dict]:
        """Jugadas clave (goles). Devuelve [] si el endpoint no está disponible."""
        try:
            data = self._get(f"{_ESPN_SITE}/{self.code}/summary", event=match_id)
            plays = data.get("scoringPlays") or data.get("keyEvents") or []
            result = []
            for p in plays:
                result.append({
                    "clock": p.get("clock", {}).get("displayValue", ""),
                    "team":  p.get("team", {}).get("displayName", ""),
                    "text":  p.get("text", ""),
                    "type":  p.get("type", {}).get("text", ""),
                })
            return result
        except Exception:
            return []
