"""get_detail no debe servir para siempre un snapshot persistido sin alineaciones
(caso real: Albacete-Real Sociedad II 2026-08-22, ESPN tardó en consolidar y el
partido ya había salido del scoreboard de hoy cuando se detectó).

    python3 -m live_tracker.test_cache
"""

from __future__ import annotations

from . import persist
from .cache import LiveStore
from .models import MatchDetail, MatchStatus, Team, Lineup, LineupPlayer, Athlete
from .providers.base import MatchDataProvider


def _team(side: str) -> Team:
    return Team(id=side, abbr=side[:3].upper(), name=side, logo=None, side=side)


def _detail(with_lineups: bool) -> MatchDetail:
    lineups = {}
    if with_lineups:
        p = LineupPlayer(athlete=Athlete(id="1", name="Fulano"), jersey="9",
                          position="FW", formation_place=9, starter=True)
        lineups = {"home": Lineup(side="home", team_abbr="HOM", formation="4-4-2", starters=[p]),
                   "away": Lineup(side="away", team_abbr="AWY", formation="4-4-2", starters=[p])}
    return MatchDetail(
        id="e1", league="hypermotion",
        status=MatchStatus(state="post", minute="FT", minute_num=90, completed=True),
        home=_team("home"), away=_team("away"), lineups=lineups,
    )


class _FakeProvider(MatchDataProvider):
    def __init__(self, detail: MatchDetail):
        self.detail = detail
        self.calls = 0

    def list_matches(self, league):
        return []

    def get_match(self, league, event_id):
        self.calls += 1
        return self.detail


def demo():
    league, event_id = "hypermotion", "e1"

    persist.save(_detail(with_lineups=False))
    assert persist.exists(league, event_id)

    provider = _FakeProvider(_detail(with_lineups=True))
    store = LiveStore(provider)

    out = store.get_detail(league, event_id)
    assert out is not None
    assert out["lineups"]["home"]["starters"], "debía rellenar alineaciones desde el fetch"
    assert provider.calls == 1, "el disco sin alineaciones debe disparar un re-fetch"

    persist.save(_detail(with_lineups=True))
    store2 = LiveStore(_FakeProvider(_detail(with_lineups=False)))
    out2 = store2.get_detail(league, event_id)
    assert out2["lineups"]["home"]["starters"], "el disco con alineaciones no debe tocarse"

    print("ok")


if __name__ == "__main__":
    import os
    path = persist._path("hypermotion", "e1")
    demo()
    os.remove(path)
