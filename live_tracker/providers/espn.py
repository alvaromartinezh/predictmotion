"""EspnProvider — ÚNICO punto con URLs y parseo del JSON de ESPN.

Reverse-engineered y frágil a propósito: cada acceso al JSON es defensivo (.get
con defaults) para que un cambio de estructura degrade en datos vacíos, no en una
excepción que tire la web. Rutas confirmadas contra el JSON real (ver CLAUDE.md).
"""

from __future__ import annotations

import json
import re
import urllib.request

from .. import config
from ..models import (Athlete, Lineup, LineupPlayer, Match, MatchDetail,
                      MatchEvent, MatchStatus, StatPair, Team, EventType)
from ..normalize import cross_reference, build_match_state
from ..winprob import DEFAULT_MODEL
from .base import MatchDataProvider

_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
_HEADERS = {"User-Agent": "Mozilla/5.0 (PredictMotion live tracker)"}

# Stats que mostramos en la pestaña Datos (clave ESPN -> etiqueta ES), en orden.
_STAT_DISPLAY = [
    ("possessionPct",  "Posesión %"),
    ("totalShots",     "Tiros"),
    ("shotsOnTarget",  "Tiros a puerta"),
    ("wonCorners",     "Córners"),
    ("foulsCommitted", "Faltas"),
    ("yellowCards",    "Amarillas"),
    ("redCards",       "Rojas"),
    ("offsides",       "Fueras de juego"),
    ("saves",          "Paradas"),
    ("totalPasses",    "Pases"),
    ("passPct",        "Precisión de pase %"),
]


# Stats que ESPN da como fracción 0-1 y deben mostrarse como porcentaje 0-100.
_RATIO_STATS = {"passPct", "shotPct", "crossPct", "longballPct", "tacklePct"}


def _fmt_stat(key, val):
    """Texto a mostrar de una estadística. Convierte las fracciones (passPct…) a %."""
    if val is None:
        return "—"
    if key in _RATIO_STATS:
        try:
            return str(round(float(val) * 100)) + "%"
        except (TypeError, ValueError):
            return str(val)
    return str(val)


def _get_json(url):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _clock_to_num(display, state, completed):
    """Minuto numérico para el cálculo. '90'+3'' -> 93, 'HT' -> 45, etc."""
    if state == "pre":
        return 0
    if completed or state == "post":
        return config.WINPROB_FULL_TIME
    if not display:
        return 0
    if "HT" in display.upper():
        return 45
    nums = re.findall(r"\d+", display)
    if not nums:
        return 0
    return sum(int(n) for n in nums)


def _status_from(status):
    typ = (status or {}).get("type", {}) or {}
    state = typ.get("state", "pre")
    completed = bool(typ.get("completed"))
    # Minuto a mostrar: reloj en vivo o detalle corto (FT/HT).
    minute = status.get("displayClock") or typ.get("shortDetail") or ""
    return MatchStatus(state=state, minute=minute,
                       minute_num=_clock_to_num(minute, state, completed),
                       completed=completed)


def _color(t):
    """Color característico del equipo (#rrggbb) desde ESPN; None si no hay o es
    casi blanco/negro (poco distintivo)."""
    raw = (t.get("color") or "").strip().lstrip("#")
    if len(raw) != 6:
        return None
    if raw.lower() in ("ffffff", "000000"):
        alt = (t.get("alternateColor") or "").strip().lstrip("#")
        if len(alt) == 6 and alt.lower() not in ("ffffff", "000000"):
            return "#" + alt
    return "#" + raw


def _team_from_competitor(c):
    t = c.get("team", {}) or {}
    logos = t.get("logos") or []
    logo = t.get("logo") or (logos[0].get("href") if logos else None)
    try:
        score = int(c.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    return Team(id=str(t.get("id", "")), abbr=t.get("abbreviation", ""),
                name=t.get("displayName", ""), logo=logo,
                side=c.get("homeAway", ""), score=score, color=_color(t))


def _event_type(slug, scoring):
    if scoring:
        return EventType.GOAL
    s = (slug or "").lower()
    if "red" in s:
        return EventType.RED
    if "yellow" in s:
        return EventType.YELLOW
    if s == "substitution":
        return EventType.SUB
    return EventType.OTHER


def _to_num(v):
    try:
        return float(str(v).replace("%", ""))
    except (TypeError, ValueError):
        return 0.0


class EspnProvider(MatchDataProvider):

    def list_matches(self, league: str) -> list[Match]:
        code = config.LEAGUES.get(league)
        if not code:
            return []
        data = _get_json(f"{_BASE}/{code}/scoreboard")
        out = []
        for ev in data.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            comps = comp.get("competitors", [])
            home = next((c for c in comps if c.get("homeAway") == "home"), None)
            away = next((c for c in comps if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            out.append(Match(
                id=str(ev.get("id", "")), league=league,
                status=_status_from(ev.get("status", {})),
                home=_team_from_competitor(home),
                away=_team_from_competitor(away),
            ))
        return out

    def get_match(self, league: str, event_id: str) -> MatchDetail:
        code = config.LEAGUES.get(league)
        if not code:
            raise ValueError(f"liga desconocida: {league}")
        data = _get_json(f"{_BASE}/{code}/summary?event={event_id}")

        comp = (data.get("header", {}).get("competitions") or [{}])[0]
        comps = comp.get("competitors", [])
        home_c = next((c for c in comps if c.get("homeAway") == "home"), comps[0] if comps else {})
        away_c = next((c for c in comps if c.get("homeAway") == "away"), comps[-1] if comps else {})
        home = _team_from_competitor(home_c)
        away = _team_from_competitor(away_c)
        status = _status_from(comp.get("status", {}))

        side_by_team = {home.id: "home", away.id: "away"}

        events = self._parse_events(data.get("keyEvents", []), side_by_team)
        lineups = self._parse_lineups(data.get("rosters", []))
        stats, numeric = self._parse_stats(data.get("boxscore", {}))

        # Cruce eventos × alineaciones (estado real sobre el campo).
        cross_reference(lineups, events)

        detail = MatchDetail(
            id=str(event_id), league=league, status=status,
            home=home, away=away, events=events, lineups=lineups, stats=stats,
        )
        # Probabilidad estimada SOLO mientras no ha terminado: un partido
        # finalizado se muestra completo pero sin bloque de probabilidad.
        if status.state == "post":
            detail.win_probability = None
        else:
            try:
                state = build_match_state(league, status, home, away, events, numeric)
                detail.win_probability = DEFAULT_MODEL.estimate(state)
            except Exception:
                detail.win_probability = None  # degrada: sin bloque de probabilidad
        return detail

    # ── parseo interno ────────────────────────────────────────────────────────

    def _parse_events(self, key_events, side_by_team):
        out = []
        for ev in key_events:
            typ = ev.get("type", {}) or {}
            scoring = bool(ev.get("scoringPlay"))
            et = _event_type(typ.get("type"), scoring)
            clock = ev.get("clock", {}) or {}
            team = ev.get("team", {}) or {}
            players = [
                Athlete(id=str((p.get("athlete") or {}).get("id", "")),
                        name=(p.get("athlete") or {}).get("displayName", ""),
                        short_name=(p.get("athlete") or {}).get("shortName", ""))
                for p in (ev.get("participants") or [])
                if p.get("athlete")
            ]
            out.append(MatchEvent(
                type=et, minute=clock.get("displayValue", ""),
                clock_value=float(clock.get("value", 0) or 0),
                period=int((ev.get("period") or {}).get("number", 0) or 0),
                team_side=side_by_team.get(str(team.get("id", ""))),
                players=players, text=ev.get("text", ""), scoring=scoring,
            ))
        out.sort(key=lambda e: (e.period, e.clock_value))
        return out

    def _parse_lineups(self, rosters):
        lineups = {}
        for r in rosters:
            side = r.get("homeAway", "")
            if side not in ("home", "away"):
                continue
            starters, subs = [], []
            for p in r.get("roster", []):
                ath = p.get("athlete", {}) or {}
                pos = p.get("position", {}) or {}
                fp = p.get("formationPlace")
                player = LineupPlayer(
                    athlete=Athlete(id=str(ath.get("id", "")),
                                    name=ath.get("displayName", ""),
                                    short_name=ath.get("shortName", "")),
                    jersey=str(p.get("jersey", "")),
                    position=pos.get("abbreviation") or pos.get("name", ""),
                    formation_place=int(fp) if str(fp).isdigit() else None,
                    starter=bool(p.get("starter")),
                )
                (starters if player.starter else subs).append(player)
            lineups[side] = Lineup(
                side=side, team_abbr=(r.get("team", {}) or {}).get("abbreviation", ""),
                formation=r.get("formation", "") or "", starters=starters, subs=subs,
            )
        return lineups

    def _parse_stats(self, boxscore):
        teams = boxscore.get("teams", []) if isinstance(boxscore, dict) else []
        by_side = {}
        for t in teams:
            side = t.get("homeAway", "")
            by_side[side] = {s.get("name"): s.get("displayValue")
                             for s in t.get("statistics", [])}
        home = by_side.get("home", {})
        away = by_side.get("away", {})
        pairs = []
        for key, label in _STAT_DISPLAY:
            if key in home or key in away:
                pairs.append(StatPair(key=key, label=label,
                                      home=_fmt_stat(key, home.get(key)),
                                      away=_fmt_stat(key, away.get(key))))
        # Versión numérica para el modelo de probabilidad.
        numeric = {}
        for key in set(list(home.keys()) + list(away.keys())):
            numeric[key] = (_to_num(home.get(key, 0)), _to_num(away.get(key, 0)))
        return pairs, numeric
