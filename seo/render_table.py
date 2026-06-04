"""Renderizado de páginas para ligas regulares (Hypermotion, LaLiga).

Devuelve {ruta_fichero: html} y la lista de URLs para el sitemap. Todo el texto
sale de variables reales; si un dato no existe, la frase no se incluye.
"""

from . import links as L
from .chrome import (page, esc, crumbs, avatar, prob_cell, stat_card, sparkline,
                     COLOR_PALETTE)
from .config import SITE
from .snapshots import per_period_series
from .textutil import pct, signed, ordinal, de_league, en_league

_SPARK_HEX = {"green": "#00c97a", "blue": "#3d8ef5", "violet": "#9b6bff", "red": "#f53050"}


def _by_slug(snap, slug):
    for t in snap["teams"]:
        if t["slug"] == slug:
            return t
    return None


def _prev_jornada_snap(series, jornada):
    prev = None
    for j, s in series:
        if j < jornada:
            prev = s
    return prev


def _zone_color(bands, rank):
    for b in bands:
        if b["lo"] <= rank <= b["hi"]:
            return b["color"]
    return None


def _av(team, size=32):
    color = COLOR_PALETTE[(team["rank"] - 1) % len(COLOR_PALETTE)]
    return avatar(team.get("logo"), team["name"], color, size=size)


def _delta_span(d, unit="pp"):
    cls = "delta-up" if d > 0.05 else "delta-down" if d < -0.05 else "delta-eq"
    return f'<span class="{cls}">{signed(d)} {unit}</span>'


# ── Página de equipo ────────────────────────────────────────────────────────

def _team_page(league, snap, series, team, extras, logo):
    slug = league["slug"]
    bands = snap["bands"]
    primary = bands[0]
    prob = team["prob"]
    pv = prob[primary["key"]]
    j = snap["jornada"]
    zcolor = _zone_color(bands, team["rank"]) or "gray"

    prev = _prev_jornada_snap(series, j)
    prev_team = _by_slug(prev, team["slug"]) if prev else None

    # Hero
    hero = (
        f'<div class="hero"><div class="hero-av">{_av(team, 64)}</div>'
        f'<div class="hero-meta"><div class="h">{esc(team["name"])}</div>'
        f'<div class="s"><span class="poschip {zcolor}">{ordinal(team["rank"])} de {snap["num_teams"]}</span>'
        f'<span>{team["pts"]} pts</span><span class="muted">·</span>'
        f'<span>{team["gp"]} PJ</span><span class="muted">·</span>'
        f'<span>{team["wins"]}G {team["draws"]}E {team["losses"]}P</span></div></div></div>'
    )

    # Frase principal
    lede = (f'El <strong>{esc(team["name"])}</strong> es {ordinal(team["rank"])} '
            f'{esc(en_league(league))} con <strong>{team["pts"]} puntos</strong> '
            f'tras la jornada {j}. Probabilidad de <strong>{esc(primary["label"].lower())}</strong>: '
            f'<strong>{pct(pv)}</strong>')
    if prev_team is not None:
        d = pv - prev_team["prob"][primary["key"]]
        lede += f' ({_delta_span(d)} respecto a la jornada {prev["jornada"]})'
    lede += "."

    # Stat cards
    stats = "".join(stat_card(prob[b["key"]], b["label"], b["color"]) for b in bands)
    if snap["has_playoff"] and "pWin" in prob:
        stats += stat_card(prob["pWin"], "Gana el play-off", "accent")

    body = (
        crumbs([("Inicio", league["dashboard"]), ("Datos", L.datos_url()),
                (f'Equipos · {league["name"]}', L.teams_hub_url(slug)),
                (team["name"], None)])
        + f'<div class="card">{hero}<div class="card-pad"><p class="lede">{lede}</p></div>'
        + f'<div class="stat-grid">{stats}</div></div>'
    )

    # Evolución
    vals, lbls = [], []
    for jj, s in series:
        tt = _by_slug(s, team["slug"])
        vals.append(tt["prob"][primary["key"]] if tt else 0)
        lbls.append(jj)
    spark = sparkline(vals, color=_SPARK_HEX.get(primary["color"], "#3d8ef5"))
    if spark:
        d = vals[-1] - vals[0]
        body += (f'<div class="card"><div class="card-pad">'
                 f'<div class="section-label">Evolución · {esc(primary["label"])}</div>{spark}'
                 f'<p class="muted" style="margin-top:8px">De la jornada {lbls[0]} ({pct(vals[0])}) '
                 f'a la {lbls[-1]} ({pct(vals[-1])}): {_delta_span(d)}.</p></div></div>')
    else:
        body += ('<div class="card"><div class="card-pad">'
                 '<div class="section-label">Evolución</div>'
                 '<p class="muted">Aún no hay histórico suficiente: hace falta al menos otra '
                 'jornada registrada para mostrar la evolución.</p></div></div>')

    # Calendario restante
    sched = (extras or {}).get(team["id"]) or []
    if sched:
        rows = ""
        for m in sched:
            loc = "Local" if m["home"] else "Visitante"
            rows += (f'<tr><td class="muted" style="font-family:Inconsolata,monospace;font-size:.8rem">{esc(m["date"])}</td>'
                     f'<td><a class="tname" href="{L.team_url(slug, _opp_slug(m["opponent"]))}">{esc(m["opponent"])}</a></td>'
                     f'<td class="muted">{loc}</td></tr>')
        body += (f'<div class="card"><div class="card-pad"><div class="section-label">Calendario restante</div></div>'
                 f'<div class="table-scroll"><table><thead><tr><th>Fecha</th><th>Rival</th><th>Condición</th>'
                 f'</tr></thead><tbody>{rows}</tbody></table></div></div>')

    # Enlaces internos (chips con mini-avatar)
    other = sorted((t for t in snap["teams"] if t["slug"] != team["slug"]), key=lambda x: x["rank"])
    chips = "".join(f'<a href="{L.team_url(slug, t["slug"])}">{_av(t, 20)}{esc(t["name"])}</a>'
                    for t in other[:8])
    chips += (f'<a href="{L.teams_hub_url(slug)}">Todos los equipos</a>'
              f'<a href="{L.jornada_url(slug, j)}">Jornada {j}</a>'
              f'<a href="{L.historico_url(slug)}">Histórico</a>')
    body += (f'<div class="card"><div class="card-pad">'
             f'<div class="section-label">Más datos {esc(de_league(league))}</div>'
             f'<div class="chips">{chips}</div></div></div>')

    title = f'{team["name"]} — Probabilidad de {primary["label"].lower()} · {league["name"]}'
    desc = (f'{team["name"]}: {pct(pv)} de {primary["label"].lower()} {en_league(league)} '
            f'tras la jornada {j} ({team["pts"]} pts, {ordinal(team["rank"])}). '
            f'Simulación Monte Carlo actualizada.')
    ld = {
        "@context": "https://schema.org", "@type": "SportsTeam",
        "name": team["name"], "sport": "Soccer",
        "url": SITE + L.team_url(slug, team["slug"]),
        "memberOf": {"@type": "SportsOrganization", "name": league["name"]},
    }
    if team["logo"]:
        ld["logo"] = team["logo"]

    html = page(title, desc, L.team_url(slug, team["slug"]), body,
                heading=league["name"], logo=logo, badge=f"Jornada <strong>{j}</strong>",
                json_ld=[ld], active_nav=league["dashboard"])
    return L.team_file(slug, team["slug"]), html


def _opp_slug(name):
    from .textutil import slugify
    return slugify(name)


# ── Hub de equipos ──────────────────────────────────────────────────────────

def _teams_hub(league, snap, logo):
    slug = league["slug"]
    bands = snap["bands"]
    rows = ""
    for t in sorted(snap["teams"], key=lambda x: x["rank"]):
        zc = _zone_color(bands, t["rank"]) or "none"
        rowcls = f' class="zone-{zc}"' if zc != "none" else ""
        cells = "".join(f'<td>{prob_cell(t["prob"][b["key"]], b["color"])}</td>' for b in bands)
        rows += (f'<tr{rowcls}><td style="width:12px;padding-left:8px"><div class="zbar {zc}"></div></td>'
                 f'<td class="pos">{t["rank"]}</td>'
                 f'<td><div class="tcell">{_av(t)}<a class="tname" href="{L.team_url(slug, t["slug"])}">{esc(t["name"])}</a></div></td>'
                 f'<td class="ptsv">{t["pts"]}</td>{cells}</tr>')
    head = "".join(f'<th><span style="color:var(--{b["color"]})">{esc(b["label"])}</span></th>' for b in bands)
    table = (f'<div class="table-scroll"><table><thead><tr><th style="width:12px"></th>'
             f'<th class="pos">#</th><th>Equipo</th><th class="r">Pts</th>{head}</tr></thead>'
             f'<tbody>{rows}</tbody></table></div>')

    lede = (f'Probabilidades por equipo {esc(en_league(league))} tras la jornada '
            f'{snap["jornada"]}, por simulación Monte Carlo sobre los partidos restantes.')
    body = (
        crumbs([("Inicio", league["dashboard"]), ("Datos", L.datos_url()),
                (f'Equipos · {league["name"]}', None)])
        + f'<div class="card"><div class="card-pad"><p class="lede">{lede}</p></div>{table}</div>'
        + f'<div class="card"><div class="card-pad"><div class="section-label">Más</div><div class="chips">'
        + f'<a href="{L.jornadas_hub_url(slug)}">Jornadas</a>'
        + f'<a href="{L.historico_url(slug)}">Histórico</a>'
        + f'<a href="{league["dashboard"]}">Clasificación en vivo</a></div></div></div>'
    )
    title = f'Probabilidades por equipo · {league["name"]} {league["season"]}'
    desc = (f'Probabilidad de cada zona {de_league(league)} por equipo tras la jornada '
            f'{snap["jornada"]}. Datos generados por simulación Monte Carlo.')
    ld = {
        "@context": "https://schema.org", "@type": "ItemList", "name": title,
        "itemListElement": [
            {"@type": "ListItem", "position": t["rank"], "name": t["name"],
             "url": SITE + L.team_url(slug, t["slug"])}
            for t in sorted(snap["teams"], key=lambda x: x["rank"])],
    }
    return L.teams_hub_file(slug), page(title, desc, L.teams_hub_url(slug), body,
                                        heading=league["name"], logo=logo,
                                        badge=f'Jornada <strong>{snap["jornada"]}</strong>',
                                        json_ld=[ld], active_nav=league["dashboard"])


# ── Página de jornada ───────────────────────────────────────────────────────

def _jornada_page(league, after, before, logo):
    slug = league["slug"]
    bands = after["bands"]
    primary = bands[0]
    j = after["jornada"]

    rows, movers = "", []
    for t in sorted(after["teams"], key=lambda x: x["rank"]):
        zc = _zone_color(bands, t["rank"]) or "none"
        rowcls = f' class="zone-{zc}"' if zc != "none" else ""
        pv = t["prob"][primary["key"]]
        bt = _by_slug(before, t["slug"]) if before else None
        if bt is not None:
            d = pv - bt["prob"][primary["key"]]
            dcell = _delta_span(d, unit="")
            movers.append((d, t["name"], t["slug"]))
        else:
            dcell = '<span class="muted">—</span>'
        rows += (f'<tr{rowcls}><td style="width:12px;padding-left:8px"><div class="zbar {zc}"></div></td>'
                 f'<td class="pos">{t["rank"]}</td>'
                 f'<td><div class="tcell">{_av(t)}<a class="tname" href="{L.team_url(slug, t["slug"])}">{esc(t["name"])}</a></div></td>'
                 f'<td class="ptsv">{t["pts"]}</td><td>{prob_cell(pv, primary["color"])}</td>'
                 f'<td class="r">{dcell}</td></tr>')
    table = (f'<div class="table-scroll"><table><thead><tr><th style="width:12px"></th><th class="pos">#</th>'
             f'<th>Equipo</th><th class="r">Pts</th>'
             f'<th><span style="color:var(--{primary["color"]})">{esc(primary["label"])}</span></th>'
             f'<th class="r">Δ</th></tr></thead><tbody>{rows}</tbody></table></div>')

    mv = ""
    if movers:
        movers.sort(key=lambda x: x[0], reverse=True)
        up, down = movers[0], movers[-1]
        parts = []
        if up[0] > 0.05:
            parts.append(f'el <a class="tname" href="{L.team_url(slug, up[2])}">{esc(up[1])}</a> '
                         f'fue quien más subió ({signed(up[0])} pp)')
        if down[0] < -0.05:
            parts.append(f'el <a class="tname" href="{L.team_url(slug, down[2])}">{esc(down[1])}</a> '
                         f'fue quien más bajó ({signed(down[0])} pp)')
        if parts:
            mv = (f'<p class="lede" style="margin-top:10px">Respecto a la jornada {before["jornada"]}, '
                  + " y ".join(parts) + f' en probabilidad de {esc(primary["label"].lower())}.</p>')

    if before is None:
        intro = (f'Probabilidades {esc(de_league(league))} tras la jornada {j}. '
                 f'Cuando se registre la jornada {j+1} aparecerá aquí cuánto movió cada resultado.')
    else:
        intro = (f'Cómo cambiaron las probabilidades {esc(de_league(league))} '
                 f'entre la jornada {before["jornada"]} y la {j}.')

    nav = (f'<a href="{L.jornada_url(slug, j-1)}">← Jornada {j-1}</a>' if before else '')
    nav += (f'<a href="{L.jornadas_hub_url(slug)}">Todas las jornadas</a>'
            f'<a href="{L.teams_hub_url(slug)}">Equipos</a>')

    body = (
        crumbs([("Inicio", league["dashboard"]), ("Datos", L.datos_url()),
                (f'Jornadas · {league["name"]}', L.jornadas_hub_url(slug)),
                (f'Jornada {j}', None)])
        + f'<div class="card"><div class="card-pad"><p class="lede">{intro}</p>{mv}</div>{table}</div>'
        + f'<div class="card"><div class="card-pad"><div class="section-label">Navegar</div>'
        + f'<div class="chips">{nav}</div></div></div>'
    )
    title = f'Jornada {j} · Probabilidades de {league["name"]} {league["season"]}'
    desc = (f'Evolución de las probabilidades {de_league(league)} en la jornada {j}: '
            f'cuánto movió cada resultado la carrera por {primary["label"].lower()}.')
    return L.jornada_file(slug, j), page(title, desc, L.jornada_url(slug, j), body,
                                         heading=league["name"], logo=logo, badge=f"Jornada <strong>{j}</strong>",
                                         active_nav=league["dashboard"])


# ── Hub de jornadas ─────────────────────────────────────────────────────────

def _jornadas_hub(league, series, logo):
    slug = league["slug"]
    chips = "".join(f'<a href="{L.jornada_url(slug, j)}">Jornada {j} · {esc(s["date"])}</a>'
                    for j, s in sorted(series, reverse=True))
    if not chips:
        chips = '<span class="muted">Aún no hay jornadas registradas.</span>'
    body = (
        crumbs([("Inicio", league["dashboard"]), ("Datos", L.datos_url()),
                (f'Jornadas · {league["name"]}', None)])
        + f'<div class="card"><div class="card-pad"><p class="lede">Histórico de jornadas '
          f'{esc(de_league(league))} {league["season"]}.</p>'
          f'<div class="chips" style="margin-top:12px">{chips}</div></div></div>'
    )
    title = f'Jornadas · {league["name"]} {league["season"]}'
    desc = f'Todas las jornadas con probabilidades registradas {de_league(league)} {league["season"]}.'
    return L.jornadas_hub_file(slug), page(title, desc, L.jornadas_hub_url(slug), body,
                                           heading=league["name"], logo=logo, badge="Jornadas",
                                           active_nav=league["dashboard"])


# ── Histórico ───────────────────────────────────────────────────────────────

def _historico(league, snaps, series, logo):
    slug = league["slug"]
    rows = ""
    for s in sorted(snaps, key=lambda x: x["date"], reverse=True):
        leader = min(s["teams"], key=lambda t: t["rank"])
        primary = s["bands"][0]
        rows += (f'<tr><td class="muted" style="font-family:Inconsolata,monospace;font-size:.82rem">{esc(s["date"])}</td>'
                 f'<td>J{s["jornada"]}</td>'
                 f'<td><div class="tcell">{_av(leader, 24)}'
                 f'<a class="tname" href="{L.team_url(slug, leader["slug"])}">{esc(leader["name"])}</a></div></td>'
                 f'<td class="r ptsv">{pct(leader["prob"][primary["key"]])}</td>'
                 f'<td class="r"><a class="tname" href="{L.jornada_url(slug, s["jornada"])}">ver jornada →</a></td></tr>')
    table = (f'<div class="table-scroll"><table><thead><tr><th>Fecha</th><th>Jor.</th><th>Líder</th>'
             f'<th class="r">{esc(snaps[-1]["bands"][0]["label"])}</th><th></th></tr></thead>'
             f'<tbody>{rows}</tbody></table></div>')
    body = (
        crumbs([("Inicio", league["dashboard"]), ("Datos", L.datos_url()),
                (f'Histórico · {league["name"]}', None)])
        + f'<div class="card"><div class="card-pad"><p class="lede">Snapshots de probabilidades '
          f'{esc(de_league(league))} registrados por fecha.</p></div>{table}</div>'
    )
    title = f'Histórico de probabilidades · {league["name"]} {league["season"]}'
    desc = f'Evolución por fechas de las probabilidades {de_league(league)} {league["season"]}.'
    ld = {
        "@context": "https://schema.org", "@type": "Dataset", "name": title, "description": desc,
        "url": SITE + L.historico_url(slug),
        "creator": {"@type": "Organization", "name": "PredictMotion"},
        "temporalCoverage": f'{snaps[0]["date"]}/{snaps[-1]["date"]}',
    }
    return L.historico_file(slug), page(title, desc, L.historico_url(slug), body,
                                        heading=league["name"], logo=logo, badge="Histórico",
                                        json_ld=[ld], active_nav=league["dashboard"])


# ── Entrada principal ───────────────────────────────────────────────────────

def render(league, snaps, extras=None):
    current = snaps[-1]
    logo = current.get("league_logo")
    series = per_period_series(snaps, "jornada")
    files, urls = {}, []

    def add(pair, url):
        files[pair[0]] = pair[1]
        urls.append((url, current["date"]))

    for t in current["teams"]:
        add(_team_page(league, current, series, t, extras, logo), L.team_url(league["slug"], t["slug"]))
    add(_teams_hub(league, current, logo), L.teams_hub_url(league["slug"]))
    for j, s in series:
        add(_jornada_page(league, s, _prev_jornada_snap(series, j), logo), L.jornada_url(league["slug"], j))
    add(_jornadas_hub(league, series, logo), L.jornadas_hub_url(league["slug"]))
    add(_historico(league, snaps, series, logo), L.historico_url(league["slug"]))
    return files, urls
