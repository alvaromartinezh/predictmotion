"""Modelo de datos normalizado (propio, NO el JSON crudo de ESPN).

El frontend y el resto del backend solo conocen estos tipos. El provider mapea
el JSON de la fuente a esto; si la fuente cambia, solo cambia el provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    GOAL = "GOAL"
    YELLOW = "YELLOW"
    RED = "RED"
    SUB = "SUB"
    OTHER = "OTHER"


@dataclass
class Athlete:
    id: str
    name: str
    short_name: str = ""

    def to_dict(self):
        return {"id": self.id, "name": self.name, "shortName": self.short_name}


@dataclass
class Team:
    id: str
    abbr: str
    name: str
    logo: str | None
    side: str          # 'home' | 'away'
    score: int = 0
    color: str | None = None        # color característico del equipo (#rrggbb)

    def to_dict(self):
        return {"id": self.id, "abbr": self.abbr, "name": self.name,
                "logo": self.logo, "side": self.side, "score": self.score,
                "color": self.color}


@dataclass
class MatchStatus:
    state: str         # 'pre' | 'in' | 'post'
    minute: str        # etiqueta para mostrar: "75'", "HT", "FT"
    minute_num: int    # minuto numérico para el cálculo (0..120)
    completed: bool

    def to_dict(self):
        return {"state": self.state, "minute": self.minute,
                "minuteNum": self.minute_num, "completed": self.completed}


@dataclass
class MatchEvent:
    type: EventType
    minute: str            # clock.displayValue, p.ej. "30'"
    clock_value: float     # segundos, para ordenar
    period: int
    team_side: str | None  # 'home' | 'away' | None
    players: list[Athlete] # GOAL:[goleador,(asistente)] · SUB:[entra,sale] · card:[jugador]
    text: str
    scoring: bool = False

    def to_dict(self):
        return {"type": self.type.value, "minute": self.minute,
                "clockValue": self.clock_value, "period": self.period,
                "teamSide": self.team_side,
                "players": [p.to_dict() for p in self.players],
                "text": self.text, "scoring": self.scoring}


@dataclass
class LineupPlayer:
    athlete: Athlete
    jersey: str
    position: str
    formation_place: int | None
    starter: bool
    # Cruzado con los eventos (estado real sobre el campo):
    goals: int = 0
    yellow: bool = False
    red: bool = False
    subbed_in: str | None = None    # minuto en que entró (si suplente que entró)
    subbed_out: str | None = None   # minuto en que salió

    def to_dict(self):
        return {"athlete": self.athlete.to_dict(), "jersey": self.jersey,
                "position": self.position, "formationPlace": self.formation_place,
                "starter": self.starter, "goals": self.goals,
                "yellow": self.yellow, "red": self.red,
                "subbedIn": self.subbed_in, "subbedOut": self.subbed_out}


@dataclass
class Lineup:
    side: str          # 'home' | 'away'
    team_abbr: str
    formation: str
    starters: list[LineupPlayer] = field(default_factory=list)
    subs: list[LineupPlayer] = field(default_factory=list)

    def to_dict(self):
        return {"side": self.side, "teamAbbr": self.team_abbr,
                "formation": self.formation,
                "starters": [p.to_dict() for p in self.starters],
                "subs": [p.to_dict() for p in self.subs]}


@dataclass
class StatPair:
    key: str
    label: str
    home: str
    away: str

    def to_dict(self):
        return {"key": self.key, "label": self.label,
                "home": self.home, "away": self.away}


@dataclass
class WinProbability:
    p_home: float
    p_draw: float
    p_away: float
    source: str
    note: str = ""     # etiqueta visible: deja claro que es estimada

    def to_dict(self):
        return {"pHome": self.p_home, "pDraw": self.p_draw, "pAway": self.p_away,
                "source": self.source, "note": self.note}


@dataclass
class Match:
    """Versión ligera para el listado (/matches)."""
    id: str
    league: str
    status: MatchStatus
    home: Team
    away: Team

    def to_dict(self):
        return {"id": self.id, "league": self.league,
                "status": self.status.to_dict(),
                "home": self.home.to_dict(), "away": self.away.to_dict()}


@dataclass
class MatchDetail:
    id: str
    league: str
    status: MatchStatus
    home: Team
    away: Team
    events: list[MatchEvent] = field(default_factory=list)
    lineups: dict[str, Lineup] = field(default_factory=dict)   # {'home':Lineup,'away':Lineup}
    stats: list[StatPair] = field(default_factory=list)
    win_probability: WinProbability | None = None
    stale: bool = False

    def to_dict(self):
        return {
            "id": self.id, "league": self.league,
            "status": self.status.to_dict(),
            "home": self.home.to_dict(), "away": self.away.to_dict(),
            "events": [e.to_dict() for e in self.events],
            "lineups": {k: v.to_dict() for k, v in self.lineups.items()},
            "stats": [s.to_dict() for s in self.stats],
            "winProbability": self.win_probability.to_dict() if self.win_probability else None,
            "stale": self.stale,
        }
