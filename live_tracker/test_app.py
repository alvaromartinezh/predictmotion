"""_cache_ttl debe distinguir el scoreboard de temporada completa (`dates=AÑO`
suelto, ~4-5 MB, TTL largo) del resto de llamadas ESPN (standings, roster,
scoreboard en vivo sin `dates`, `dates=INICIO-FIN`...) que necesitan quedarse
en el TTL corto de siempre.

    python3 -m live_tracker.test_app
"""

from __future__ import annotations

from . import config
from .app import _cache_ttl


def demo():
    season = "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/scoreboard?dates=2026&limit=700"
    assert _cache_ttl(season) == config.ESPN_PROXY_SEASON_CACHE_TTL

    live = "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/scoreboard"
    assert _cache_ttl(live) == config.ESPN_PROXY_CACHE_TTL

    standings = "https://site.api.espn.com/apis/v2/sports/soccer/esp.1/standings"
    assert _cache_ttl(standings) == config.ESPN_PROXY_CACHE_TTL

    roster = "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/teams/86/roster"
    assert _cache_ttl(roster) == config.ESPN_PROXY_CACHE_TTL

    # dates=AÑO como PRIMER año de un rango legado no debe colarse por el año
    # que sigue al guion.
    old_range = "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/scoreboard?dates=20260926-20261226"
    assert _cache_ttl(old_range) == config.ESPN_PROXY_CACHE_TTL

    print("ok")


if __name__ == "__main__":
    demo()
