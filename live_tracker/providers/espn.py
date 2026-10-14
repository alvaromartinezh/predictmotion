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
from ..models import (Athlete, FormGame, H2HMeeting, HeadToHead, Lineup,
                      LineupPlayer, Match, MatchDetail, MatchEvent,
                      MatchStatus, StatPair, Team, EventType)
from ..normalize import cross_reference, build_match_state
from ..winprob import DEFAULT_MODEL
from .base import MatchDataProvider

_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# Competiciones de SELECCIONES: ESPN traduce los nombres de país con `lang=es`
# (France → Francia, Czechia → Chequia) y la web es en español. Los CLUBES no se
# traducen a propósito: el cron SEO guarda sus snapshots con el nombre por defecto
# de ESPN (y de ahí salen rows.html, artículos y tuits), así que traducirlos aquí
# los descuadraría. Espejo del `ES_LANG` de assets/espn-proxy.js, que hace lo mismo
# con las llamadas del navegador.
_SPANISH_LEAGUES = {
    "uefa.nations", "concacaf.nations.league", "caf.nations_qual", "fifa.friendly",
}


def _lang(code, sep="?"):
    return f"{sep}lang=es" if code in _SPANISH_LEAGUES else ""


# NO poner un User-Agent tipo navegador ("Mozilla/..."): ESPN/Cloudflare lo
# devuelve 403 desde IPs de datacenter. El UA por defecto de urllib sí pasa; por
# eso _HEADERS va vacío (mismo motivo que en seo/espn.py).
_HEADERS = {}

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
        data = _get_json(f"{_BASE}/{code}/scoreboard{_lang(code)}")
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
        data = _get_json(f"{_BASE}/{code}/summary?event={event_id}{_lang(code, '&')}")

        comp = (data.get("header", {}).get("competitions") or [{}])[0]
        comps = comp.get("competitors", [])
        home_c = next((c for c in comps if c.get("homeAway") == "home"), comps[0] if comps else {})
        away_c = next((c for c in comps if c.get("homeAway") == "away"), comps[-1] if comps else {})
        home = _team_from_competitor(home_c)
        away = _team_from_competitor(away_c)
        status = _status_from(comp.get("status", {}))
        kickoff = comp.get("date") or ""

        side_by_team = {home.id: "home", away.id: "away"}

        events = self._parse_events(data.get("keyEvents", []), side_by_team)
        lineups = self._parse_lineups(data.get("rosters", []))
        stats, numeric = self._parse_stats(data.get("boxscore", {}))

        # Cruce eventos × alineaciones (estado real sobre el campo).
        cross_reference(lineups, events)

        detail = MatchDetail(
            id=str(event_id), league=league, status=status,
            home=home, away=away, events=events, lineups=lineups, stats=stats,
            date=kickoff,
            form=self._parse_form(data.get("lastFiveGames"), home.id, away.id),
            h2h=self._parse_h2h(data.get("seasonseries"), home.id, away.id),
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

    def _parse_form(self, last_five_games, home_id, away_id):
        """`lastFiveGames` de ESPN -> {'home': [FormGame,...], 'away': [...]}.
        Ausente/vacío en ligas menores, copas o inicio de temporada -> dict
        vacío (ninguna clave), NUNCA una lista vacía bajo una clave: el
        frontend decide si pinta la sección mirando si la clave existe."""
        out = {}
        for g in (last_five_games or []):
            team = g.get("team") or {}
            tid = str(team.get("id", ""))
            if tid == home_id:
                side = "home"
            elif tid == away_id:
                side = "away"
            else:
                continue
            games = []
            for e in (g.get("events") or []):
                result = e.get("gameResult")
                if result not in ("W", "D", "L"):
                    continue
                try:
                    home_score = int(e.get("homeTeamScore"))
                    away_score = int(e.get("awayTeamScore"))
                except (TypeError, ValueError):
                    continue
                is_home = str(e.get("homeTeamId", "")) == tid
                team_score = home_score if is_home else away_score
                opp_score = away_score if is_home else home_score
                games.append(FormGame(
                    result=result, opponent=(e.get("opponent") or {}).get("displayName", ""),
                    team_score=team_score, opp_score=opp_score, home=is_home,
                ))
            if games:
                out[side] = games
        return out

    def _parse_h2h(self, seasonseries, home_id, away_id):
        """`seasonseries` de ESPN -> balance SIEMPRE relativo al home/away del
        partido actual (no al de cada enfrentamiento histórico, que puede
        venir invertido). None si no hay bloque de tipo 'head-to-head' o
        ningún enfrentamiento usable (copas/selecciones/primer cruce)."""
        entry = next((s for s in (seasonseries or []) if s.get("type") == "head-to-head"), None)
        if not entry:
            return None
        home_wins = draws = away_wins = 0
        meetings = []
        for ev in (entry.get("events") or []):
            competitors = ev.get("competitors") or []
            home_c = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away_c = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home_c or not away_c:
                continue
            try:
                hs = int(home_c.get("score"))
                aw = int(away_c.get("score"))
            except (TypeError, ValueError):
                continue
            h_tid = str((home_c.get("team") or {}).get("id", ""))
            if h_tid == home_id:
                cur_home, cur_away = hs, aw
            elif h_tid == away_id:
                cur_home, cur_away = aw, hs
            else:
                continue  # equipo inesperado: no es este cruce
            if cur_home > cur_away:
                home_wins += 1
            elif cur_away > cur_home:
                away_wins += 1
            else:
                draws += 1
            meetings.append(H2HMeeting(
                date=ev.get("date") or "",
                home=(home_c.get("team") or {}).get("displayName", ""),
                away=(away_c.get("team") or {}).get("displayName", ""),
                home_score=hs, away_score=aw,
            ))
        if not meetings:
            return None
        return HeadToHead(home_wins=home_wins, draws=draws, away_wins=away_wins, meetings=meetings)
