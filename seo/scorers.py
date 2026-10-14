"""`/goleadores/<liga>` — el pichichi de cada competición.

Por qué existe: `seo/players.py` ya descarga y guarda ~14 000 fichas de
jugador con `stats.goals` y `stats.assists`, y hasta ahora solo alimentaban el
buscador. "pichichi laliga" (y su equivalente en cada liga) es volumen de
búsqueda puro que el sitio no cubría pese a tener el dato en disco.

**Cero llamadas nuevas a ESPN**: el ranking lo calcula `players._write_scorers`
con las fichas que ya tiene en memoria, y aquí solo se lee
`data/players/scorers.json`.

Principio 1 de [[CLAUDE]] (competición terminada se elimina): la página se
genera por liga ACTIVA, desde `LEAGUES`. Cuando una liga sale de ahí, deja de
generarse sin tocar este fichero.

Ver [[docs/seo]].
"""

import json

from .chrome import crumbs, esc, page, team_avatar
from .config import DATA_DIR, SITE
from .textutil import de_league

MIN_PLAYERS = 3   # con uno o dos goleadores la página no es un ranking
_POS = {"F": "Delantero", "M": "Centrocampista", "D": "Defensa", "G": "Portero"}


def _seed(player_id):
    """`chrome.team_avatar` indexa la paleta con `seed % len(...)`: necesita un
    int y los ids de ESPN llegan como str."""
    try:
        return int(player_id)
    except (TypeError, ValueError):
        return 0


def url_for(slug):
    return f"/goleadores/{slug}"


def file_for(slug):
    return f"goleadores/{slug}.html"


def load():
    """(temporada, {liga: [jugador, ...]}) del fichero que escribe
    seo/players.py. ("", {}) si aún no existe (primer arranque) o está
    corrupto — la página simplemente no se genera ese run."""
    try:
        with open(DATA_DIR / "players" / "scorers.json", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return "", {}
    if not isinstance(data, dict):
        return "", {}
    leagues = data.get("leagues")
    return data.get("season") or "", leagues if isinstance(leagues, dict) else {}


def _row(i, p):
    pos = _POS.get(p.get("pos"), "")
    goles = p["goals"]
    asis = p.get("assists")
    pj = p.get("matches")
    extra = []
    if isinstance(asis, (int, float)):
        extra.append(f'{asis} asist.')
    if isinstance(pj, (int, float)) and pj:
        extra.append(f'{pj} PJ')
    sub = " · ".join([x for x in [pos] + extra if x])
    return (f'<tr><td class="r muted">{i}</td>'
            f'<td><div class="tcell">{team_avatar(p.get("team_logo"), p["team"], _seed(p["id"]), 28)}'
            f'<div><a class="tname" href="/jugador?id={esc(p["id"])}">{esc(p["name"])}</a>'
            f'<div class="muted" style="font-size:.74rem">{esc(p["team"])}'
            + (f' · {esc(sub)}' if sub else "") + '</div></div></div></td>'
            f'<td class="r ptsv">{goles}</td></tr>')


def render(league, rows, season=None):
    """(ruta, html) del pichichi de una liga. None si no hay ranking que contar.

    `season` pisa la de `config.LEAGUES`, congelada a mano y desfasada (decía
    "2025-26" con ESPN ya en 2026-27). Mismo apaño que `render_table.render`."""
    if len(rows) < MIN_PLAYERS:
        return None
    if season:
        league = {**league, "season": season}
    slug = league["slug"]
    top = rows[0]
    body_rows = "".join(_row(i + 1, p) for i, p in enumerate(rows))
    lede = (f'<p class="lede"><b>{esc(top["name"])}</b> ({esc(top["team"])}) es el máximo '
            f'goleador {esc(de_league(league))} con <b>{top["goals"]}</b> '
            f'{"goles" if top["goals"] != 1 else "gol"} esta temporada.</p>')
    table = ('<div class="table-scroll"><table><thead><tr><th class="r">#</th>'
             '<th>Jugador</th><th class="r">Goles</th></tr></thead><tbody>'
             + body_rows + '</tbody></table></div>')
    body = (
        crumbs([("Inicio", league["dashboard"]),
                (f'Goleadores · {league["name"]}', None)])
        + f'<div class="card"><div class="card-pad">{lede}</div>{table}</div>'
    )
    title = f'Máximos goleadores {league["name"]} {league["season"]} · Pichichi'
    desc = (f'Tabla de goleadores {de_league(league)} {league["season"]}: '
            f'{esc(top["name"])} lidera con {top["goals"]} goles. '
            f'Los {len(rows)} jugadores más goleadores, con asistencias y partidos.')
    ld = {
        "@context": "https://schema.org", "@type": "ItemList",
        "name": title, "url": SITE + url_for(slug),
        "numberOfItems": len(rows),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": p["name"]}
            for i, p in enumerate(rows[:10])
        ],
    }
    return file_for(slug), page(title, desc, url_for(slug), body,
                                heading=league["name"],
                                logo=league.get("logo"), badge="Goleadores",
                                json_ld=[ld], active_nav=league["dashboard"])


def render_all(leagues):
    """{ruta: html}, [(url, None)] de todas las ligas activas con ranking."""
    season, data = load()
    files, urls = {}, []
    for league in leagues:
        out = render(league, data.get(league["slug"]) or [], season)
        if out:
            files[out[0]] = out[1]
            urls.append(url_for(league["slug"]))
    return files, urls


def _self_check():
    """Lo no trivial es el umbral y el texto derivado del dato (concordancia de
    singular/plural y la liga sin ranking)."""
    # season "2025-26" a propósito: es el valor congelado a mano en config.py,
    # el que la temporada del dato tiene que pisar.
    league = {"slug": "laliga", "name": "LaLiga", "season": "2025-26",
              "dashboard": "/laliga", "pais": "España"}

    def p(name, goals, assists=2, pos="F"):
        return {"id": "1", "name": name, "team": "Equipo", "team_logo": None,
                "headshot": None, "pos": pos, "goals": goals, "assists": assists,
                "matches": 9}

    assert render(league, []) is None
    assert render(league, [p("A", 5), p("B", 4)]) is None       # por debajo del mínimo
    rows_ok = [p("A", 5), p("B", 4), p("C", 3)]
    out = render(league, rows_ok)
    assert out and out[0] == "goleadores/laliga.html"
    assert "<b>5</b> goles" in out[1], "plural"
    out1 = render(league, [p("A", 1), p("B", 1), p("C", 1)])
    assert "<b>1</b> gol esta temporada" in out1[1], "singular"

    # La temporada del dato pisa la de config (congelada a mano).
    assert "2026-27" in render(league, rows_ok, "2026-27")[1]
    assert "2025-26" in render(league, rows_ok)[1]

    # Un fichero inexistente no debe lanzar: ese run simplemente no genera nada.
    s, d = load()
    assert isinstance(s, str) and isinstance(d, dict)

    # Orden y filtrado los hace players._write_scorers; aquí se comprueba que el
    # render respeta el orden recibido y no reordena por su cuenta.
    rows = [p("Primero", 9), p("Segundo", 7), p("Tercero", 6)]
    html = render(league, rows)[1]
    assert html.index("Primero") < html.index("Segundo") < html.index("Tercero")
    print("ok: umbral, concordancia y orden")


if __name__ == "__main__":
    import sys
    if "--self-check" in sys.argv:
        _self_check()
    else:
        season, d = load()
        print("temporada:", season or "(sin scorers.json)")
        for slug, rows in sorted(d.items()):
            top = rows[0] if rows else None
            print(f"{slug:14s} {len(rows):3d} jugadores"
                  + (f"  · líder {top['name']} ({top['goals']})" if top else ""))
