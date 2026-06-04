"""Renderizado de páginas del Mundial (selecciones, grupos, histórico).

La probabilidad principal de una selección es pAdv: pasar a la fase
eliminatoria. Todo el texto sale de variables reales.
"""

from . import links as L
from .chrome import (page, esc, crumbs, avatar, prob_cell, stat_card, sparkline,
                     COLOR_PALETTE)
from .config import SITE
from .snapshots import per_period_series
from .textutil import pct, signed, ordinal, de_league, en_league


def _all_entries(snap):
    for g in snap["groups"]:
        for t in g["entries"]:
            yield g, t


def _find(snap, slug):
    for g, t in _all_entries(snap):
        if t["slug"] == slug:
            return g, t
    return None, None


def _prev_snap(series, matchday):
    prev = None
    for m, s in series:
        if m < matchday:
            prev = s
    return prev


def _av(team, size=32):
    color = COLOR_PALETTE[(team["rank"] - 1) % len(COLOR_PALETTE)]
    return avatar(team.get("logo"), team["name"], color, size=size)


def _poschip(rank):
    return {1: "green", 2: "green", 3: "violet"}.get(rank, "red")


def _delta_span(d, unit="pp"):
    cls = "delta-up" if d > 0.05 else "delta-down" if d < -0.05 else "delta-eq"
    return f'<span class="{cls}">{signed(d)} {unit}</span>'


# ── Selección ───────────────────────────────────────────────────────────────

def _team_page(league, snap, series, group, team, logo):
    slug = league["slug"]
    prob = team["prob"]
    md = snap["matchday"]
    prev = _prev_snap(series, md)
    _, prev_team = _find(prev, team["slug"]) if prev else (None, None)

    hero = (
        f'<div class="hero"><div class="hero-av">{_av(team, 64)}</div>'
        f'<div class="hero-meta"><div class="h">{esc(team["name"])}</div>'
        f'<div class="s"><span class="poschip {_poschip(team["rank"])}">Grupo {esc(group["name"])} · {ordinal(team["rank"])}</span>'
        f'<span>{team["pts"]} pts</span><span class="muted">·</span>'
        f'<span>{team["gp"]} PJ</span><span class="muted">·</span>'
        f'<span>{team["gf"]}:{team["gc"]}</span></div></div></div>'
    )

    lede = (f'<strong>{esc(team["name"])}</strong> está en el <strong>Grupo {esc(group["name"])}</strong> '
            f'{esc(de_league(league))} con <strong>{team["pts"]} puntos</strong> '
            f'({ordinal(team["rank"])} de grupo, {team["gp"]} partidos jugados). '
            f'Probabilidad de pasar a la fase eliminatoria: <strong>{pct(prob["pAdv"])}</strong>')
    if prev_team is not None:
        d = prob["pAdv"] - prev_team["prob"]["pAdv"]
        lede += f' ({_delta_span(d)} respecto al corte anterior)'
    lede += "."

    stats = (stat_card(prob["pAdv"], "Pasa de ronda", "green")
             + stat_card(prob["p1st"], "1º de grupo", "blue")
             + stat_card(prob["p2nd"], "2º de grupo", "violet")
             + stat_card(prob["pOut"], "Eliminada en grupos", "red"))

    body = (
        crumbs([("Mundial", league["dashboard"]), ("Datos", L.datos_url()),
                ("Selecciones", L.teams_hub_url(slug)),
                (f'Grupo {group["name"]}', L.grupo_url(slug, group["name"])),
                (team["name"], None)])
        + f'<div class="card">{hero}<div class="card-pad"><p class="lede">{lede}</p></div>'
        + f'<div class="stat-grid">{stats}</div></div>'
    )

    vals, lbls = [], []
    for m, s in series:
        _, tt = _find(s, team["slug"])
        vals.append(tt["prob"]["pAdv"] if tt else 0)
        lbls.append(m)
    spark = sparkline(vals, color="#00c97a")
    if spark:
        d = vals[-1] - vals[0]
        body += (f'<div class="card"><div class="card-pad"><div class="section-label">Evolución · Pasa de ronda</div>'
                 f'{spark}<p class="muted" style="margin-top:8px">{_delta_span(d)} desde el primer corte '
                 f'registrado.</p></div></div>')
    else:
        body += ('<div class="card"><div class="card-pad"><div class="section-label">Evolución</div>'
                 '<p class="muted">Aún no hay histórico suficiente para mostrar la evolución.</p></div></div>')

    rivals = [t for t in group["entries"] if t["slug"] != team["slug"]]
    chips = "".join(f'<a href="{L.team_url(slug, t["slug"])}">{_av(t, 20)}{esc(t["name"])}</a>' for t in rivals)
    chips += (f'<a href="{L.grupo_url(slug, group["name"])}">Grupo {esc(group["name"])}</a>'
              f'<a href="{L.teams_hub_url(slug)}">Todas las selecciones</a>'
              f'<a href="{L.historico_url(slug)}">Histórico</a>')
    body += (f'<div class="card"><div class="card-pad"><div class="section-label">Más {esc(de_league(league))}</div>'
             f'<div class="chips">{chips}</div></div></div>')

    title = f'{team["name"]} — Probabilidad de pasar de ronda · {league["name"]}'
    desc = (f'{team["name"]}: {pct(prob["pAdv"])} de pasar a la fase eliminatoria '
            f'{de_league(league)} (Grupo {group["name"]}, {team["pts"]} pts). Simulación Monte Carlo.')
    ld = {
        "@context": "https://schema.org", "@type": "SportsTeam", "name": team["name"], "sport": "Soccer",
        "url": SITE + L.team_url(slug, team["slug"]),
        "memberOf": {"@type": "SportsOrganization", "name": league["name"]},
    }
    if team["logo"]:
        ld["logo"] = team["logo"]
    return L.team_file(slug, team["slug"]), page(
        title, desc, L.team_url(slug, team["slug"]), body,
        heading=league["name"], logo=logo, badge=f'Grupo <strong>{esc(group["name"])}</strong>',
        json_ld=[ld], active_nav=league["dashboard"])


# ── Grupo ───────────────────────────────────────────────────────────────────

def _group_page(league, snap, group, logo):
    slug = league["slug"]
    rows = ""
    for t in sorted(group["entries"], key=lambda x: x["rank"]):
        zc = "green" if t["rank"] <= 2 else "violet" if t["rank"] == 3 else "none"
        rowcls = f' class="zone-{zc}"' if zc != "none" else ""
        rows += (f'<tr{rowcls}><td style="width:12px;padding-left:8px"><div class="zbar {zc}"></div></td>'
                 f'<td class="pos">{t["rank"]}</td>'
                 f'<td><div class="tcell">{_av(t)}<a class="tname" href="{L.team_url(slug, t["slug"])}">{esc(t["name"])}</a></div></td>'
                 f'<td class="ptsv">{t["pts"]}</td>'
                 f'<td>{prob_cell(t["prob"]["pAdv"], "green")}</td>'
                 f'<td>{prob_cell(t["prob"]["p1st"], "blue")}</td></tr>')
    table = (f'<div class="table-scroll"><table><thead><tr><th style="width:12px"></th><th class="pos">#</th>'
             f'<th>Selección</th><th class="r">Pts</th>'
             f'<th><span style="color:var(--green)">Pasa de ronda</span></th>'
             f'<th><span style="color:var(--blue)">1º de grupo</span></th></tr></thead>'
             f'<tbody>{rows}</tbody></table></div>')

    chips = "".join(f'<a href="{L.grupo_url(slug, g["name"])}">Grupo {esc(g["name"])}</a>'
                    for g in snap["groups"] if g["name"] != group["name"])
    chips += f'<a href="{L.teams_hub_url(slug)}">Selecciones</a>'

    lede = (f'Probabilidades del <strong>Grupo {esc(group["name"])}</strong> '
            f'{esc(de_league(league))} tras {snap["matchday"]} jornada(s). '
            f'Pasan {snap["advancing"]} selecciones de {snap["num_groups"]*4} a la fase eliminatoria.')
    body = (
        crumbs([("Mundial", league["dashboard"]), ("Datos", L.datos_url()),
                ("Grupos", L.grupos_hub_url(slug)), (f'Grupo {group["name"]}', None)])
        + f'<div class="card"><div class="card-pad"><p class="lede">{lede}</p></div>{table}</div>'
        + f'<div class="card"><div class="card-pad"><div class="section-label">Otros grupos</div>'
        + f'<div class="chips">{chips}</div></div></div>'
    )
    title = f'Grupo {group["name"]} · Probabilidades del {league["name"]}'
    desc = (f'Probabilidad de cada selección del Grupo {group["name"]} de pasar de ronda '
            f'{en_league(league)}. Simulación Monte Carlo.')
    return L.grupo_file(slug, group["name"]), page(
        title, desc, L.grupo_url(slug, group["name"]), body,
        heading=league["name"], logo=logo, badge=f'Grupo <strong>{esc(group["name"])}</strong>',
        active_nav=league["dashboard"])


# ── Hubs e histórico ────────────────────────────────────────────────────────

def _teams_hub(league, snap, logo):
    slug = league["slug"]
    allt = sorted((t for _, t in _all_entries(snap)), key=lambda x: -x["prob"]["pAdv"])
    rows = ""
    for i, t in enumerate(allt, 1):
        rows += (f'<tr><td class="pos">{i}</td>'
                 f'<td><div class="tcell">{_av(t)}<a class="tname" href="{L.team_url(slug, t["slug"])}">{esc(t["name"])}</a></div></td>'
                 f'<td class="ptsv">{t["pts"]}</td>'
                 f'<td>{prob_cell(t["prob"]["pAdv"], "green")}</td></tr>')
    table = (f'<div class="table-scroll"><table><thead><tr><th class="pos">#</th><th>Selección</th>'
             f'<th class="r">Pts</th><th><span style="color:var(--green)">Pasa de ronda</span></th>'
             f'</tr></thead><tbody>{rows}</tbody></table></div>')
    body = (
        crumbs([("Mundial", league["dashboard"]), ("Datos", L.datos_url()), ("Selecciones", None)])
        + f'<div class="card"><div class="card-pad"><p class="lede">Probabilidad de cada selección de '
          f'pasar a la fase eliminatoria {esc(de_league(league))}, por simulación Monte Carlo.</p></div>{table}</div>'
        + f'<div class="card"><div class="card-pad"><div class="section-label">Más</div><div class="chips">'
        + f'<a href="{L.grupos_hub_url(slug)}">Grupos</a>'
        + f'<a href="{L.historico_url(slug)}">Histórico</a>'
        + f'<a href="{league["dashboard"]}">Cuadro y partidos</a></div></div></div>'
    )
    title = f'Selecciones · Probabilidades del {league["name"]}'
    desc = f'Probabilidad de cada selección de pasar de ronda {en_league(league)}. Monte Carlo.'
    return L.teams_hub_file(slug), page(title, desc, L.teams_hub_url(slug), body,
                                        heading=league["name"], logo=logo, badge="Selecciones",
                                        active_nav=league["dashboard"])


def _groups_hub(league, snap, logo):
    slug = league["slug"]
    chips = "".join(f'<a href="{L.grupo_url(slug, g["name"])}">Grupo {esc(g["name"])}</a>'
                    for g in snap["groups"])
    body = (
        crumbs([("Mundial", league["dashboard"]), ("Datos", L.datos_url()), ("Grupos", None)])
        + f'<div class="card"><div class="card-pad"><p class="lede">Los {snap["num_groups"]} grupos '
          f'{esc(de_league(league))} con probabilidades por selección.</p>'
          f'<div class="chips" style="margin-top:12px">{chips}</div></div></div>'
    )
    title = f'Grupos · {league["name"]}'
    desc = f'Todos los grupos {de_league(league)} con probabilidades de clasificación.'
    return L.grupos_hub_file(slug), page(title, desc, L.grupos_hub_url(slug), body,
                                         heading=league["name"], logo=logo, badge="Grupos",
                                         active_nav=league["dashboard"])


def _historico(league, snaps, logo):
    slug = league["slug"]
    rows = ""
    for s in sorted(snaps, key=lambda x: x["date"], reverse=True):
        rows += (f'<tr><td class="muted" style="font-family:Inconsolata,monospace;font-size:.82rem">{esc(s["date"])}</td>'
                 f'<td>{s["matchday"]} jor.</td>'
                 f'<td>{s["num_groups"]} grupos · pasan {s["advancing"]}</td></tr>')
    table = (f'<div class="table-scroll"><table><thead><tr><th>Fecha</th><th>Jugado</th><th>Formato</th>'
             f'</tr></thead><tbody>{rows}</tbody></table></div>')
    body = (
        crumbs([("Mundial", league["dashboard"]), ("Datos", L.datos_url()), ("Histórico", None)])
        + f'<div class="card"><div class="card-pad"><p class="lede">Snapshots de probabilidades '
          f'{esc(de_league(league))} registrados por fecha.</p></div>{table}</div>'
    )
    title = f'Histórico de probabilidades · {league["name"]}'
    desc = f'Evolución por fechas de las probabilidades {de_league(league)}.'
    ld = {
        "@context": "https://schema.org", "@type": "Dataset", "name": title, "description": desc,
        "url": SITE + L.historico_url(slug),
        "creator": {"@type": "Organization", "name": "PredictMotion"},
        "temporalCoverage": f'{snaps[0]["date"]}/{snaps[-1]["date"]}',
    }
    return L.historico_file(slug), page(title, desc, L.historico_url(slug), body,
                                        heading=league["name"], logo=logo, badge="Histórico",
                                        json_ld=[ld], active_nav=league["dashboard"])


def render(league, snaps, extras=None):
    current = snaps[-1]
    logo = current.get("league_logo")
    series = per_period_series(snaps, "matchday")
    files, urls = {}, []

    def add(pair, url):
        files[pair[0]] = pair[1]
        urls.append((url, current["date"]))

    for g in current["groups"]:
        for t in g["entries"]:
            add(_team_page(league, current, series, g, t, logo), L.team_url(league["slug"], t["slug"]))
        add(_group_page(league, current, g, logo), L.grupo_url(league["slug"], g["name"]))
    add(_teams_hub(league, current, logo), L.teams_hub_url(league["slug"]))
    add(_groups_hub(league, current, logo), L.grupos_hub_url(league["slug"]))
    add(_historico(league, snaps, logo), L.historico_url(league["slug"]))
    return files, urls
