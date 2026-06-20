"""Normalización transversal: cruza eventos con alineaciones y construye el estado
de entrada del modelo de probabilidad. Opera sobre modelos normalizados, así que
es independiente del provider.
"""

from __future__ import annotations

from .models import EventType, Lineup, MatchEvent, MatchStatus, Team
from .winprob import MatchState


def cross_reference(lineups: dict[str, Lineup], events: list[MatchEvent]) -> None:
    """Marca sobre cada jugador goles/tarjetas/cambios a partir de los eventos.

    Modifica `lineups` in-place: tras esto, la pestaña Alineación solo pinta el
    estado real (⚽ goleador, 🟨/🟥, entró/salió)."""
    by_id = {}
    for lu in lineups.values():
        for p in list(lu.starters) + list(lu.subs):
            if p.athlete.id:
                by_id[p.athlete.id] = p

    for ev in events:
        if not ev.players:
            continue
        if ev.type == EventType.GOAL:
            scorer = by_id.get(ev.players[0].id)
            if scorer:
                scorer.goals += 1
        elif ev.type == EventType.YELLOW:
            p = by_id.get(ev.players[0].id)
            if p:
                p.yellow = True
        elif ev.type == EventType.RED:
            p = by_id.get(ev.players[0].id)
            if p:
                p.red = True
        elif ev.type == EventType.SUB:
            pin = by_id.get(ev.players[0].id)
            if pin:
                pin.subbed_in = ev.minute
            if len(ev.players) > 1:
                pout = by_id.get(ev.players[1].id)
                if pout:
                    pout.subbed_out = ev.minute


def build_match_state(league: str, status: MatchStatus, home: Team, away: Team,
                      events: list[MatchEvent], numeric_stats: dict) -> MatchState:
    """Estado normalizado de entrada para WinProbabilityModel."""
    # Hombres en el campo: 11 - rojas. Preferimos la stat redCards; si falta,
    # contamos eventos RED por lado.
    red_pair = numeric_stats.get("redCards")
    if red_pair:
        red_home, red_away = int(red_pair[0]), int(red_pair[1])
    else:
        red_home = sum(1 for e in events if e.type == EventType.RED and e.team_side == "home")
        red_away = sum(1 for e in events if e.type == EventType.RED and e.team_side == "away")

    return MatchState(
        league=league,
        state=status.state,
        minute_num=status.minute_num,
        home_score=home.score,
        away_score=away.score,
        men_home=max(7, 11 - red_home),   # nunca por debajo de 7 (regla real)
        men_away=max(7, 11 - red_away),
        stats=numeric_stats,
    )
