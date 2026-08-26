"""Renderizado de páginas para ligas regulares (Hypermotion, LaLiga).

Devuelve {ruta_fichero: html} y la lista de URLs para el sitemap. Todo el texto
sale de variables reales; si un dato no existe, la frase no se incluye.
"""

from . import links as L
from .chrome import (page, esc, crumbs, avatar, prob_cell, stat_card, sparkline,
                     COLOR_PALETTE, team_avatar, delta_span)
from .config import SITE
from .snapshots import per_period_series
from .textutil import (pct, num, signed, ordinal, de_league, en_league,
                       zone_label, fecha_es, plural)

_SPARK_HEX = {"green": "#00c97a", "blue": "#3d8ef5", "violet": "#9b6bff", "red": "#f53050"}


def _by_slug(snap, slug):
    for t in snap["teams"]:
        if t["slug"] == slug:
            return t
    return None


def _by_rank(snap, rank):
    for t in snap["teams"]:
        if t["rank"] == rank:
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
    return team_avatar(team.get("logo"), team["name"], team["rank"] - 1, size=size)


_delta_span = delta_span


# ── Página de equipo ────────────────────────────────────────────────────────

def _rank_of(teams, team, key, best="max"):
    """Puesto de `team` por `key` entre `teams` (1 = mejor). Empates comparten
    puesto: 1 + cuántos son ESTRICTAMENTE mejores."""
    v = team.get(key)
    if v is None:
        return None
    better = sum(1 for t in teams
                 if t.get(key) is not None
                 and (t[key] > v if best == "max" else t[key] < v))
    return better + 1


def _team_analysis(league, snap, series, team, extras):
    """Párrafo de análisis propio de ESTE equipo, solo con lo que el snapshot ya
    trae. Sin IA a propósito: no gasta cuota de Gemini, es determinista (misma
    tabla → mismo texto) y se rehace solo en el cron de generate_site.

    Existe por SEO. Hasta 2026-08-26 una página de equipo tenía ~35 palabras
    propias sobre 157, y dos equipos de la misma liga eran 85 % idénticos palabra
    por palabra: Google se dejó 262 URLs en «Descubierta: actualmente sin indexar»
    (ver [[docs/seo]]).

    **La clave no es añadir texto, es que sea distinto.** Un primer intento metió
    100 palabras por equipo y la similitud entre páginas bajó solo del 85 % al
    81 %: las mismas cinco frases en el mismo orden con otros números siguen
    siendo una plantilla. Así que aquí cada frase se PUNTÚA por lo llamativa que
    es para ESE equipo (lo lejos que está de lo normal en su liga) y solo salen
    las mejores, en ese orden. El líder abre hablando de su ataque, el colista de
    su defensa y el de media tabla de su calendario: distinto orden, distinto
    subconjunto y distintas cifras. No es *spinning* — es la misma jerarquía
    editorial que usaría un redactor.

    Una frase solo se genera si sus datos existen: en pretemporada (gp == 0), sin
    calendario de ESPN o sin histórico, sencillamente hay menos frases. Nunca se
    inventa un dato para rellenar.
    """
    played = [t for t in snap["teams"] if (t.get("gp") or 0) > 0]
    gp = team.get("gp") or 0
    n = snap.get("num_teams") or len(snap["teams"])
    banda = snap["bands"][0]
    etiqueta = zone_label(banda["label"])
    cand = []   # (score, frase) — score alto = más digno de abrir el párrafo

    def extremo(puesto, total):
        """1.0 si es el primero o el último de la liga, ~0 si es de media tabla.
        Es la medida de "esto merece contarse" para un puesto."""
        if not puesto or total < 2:
            return 0.0
        return abs((puesto - 1) / (total - 1) - 0.5) * 2

    # ── Goles ────────────────────────────────────────────────────────────────
    if gp and len(played) >= 4:
        gf, gc = team.get("gf") or 0, team.get("gc") or 0
        r_gf = _rank_of(played, team, "gf", "max")
        r_gc = _rank_of(played, team, "gc", "min")
        dif = gf - gc
        saldo = "un saldo neutro" if dif == 0 else f"una diferencia de {signed(dif, 0)}"
        cand.append((
            max(extremo(r_gf, len(played)), extremo(r_gc, len(played))),
            f'Ha marcado <strong>{plural(gf, "gol", "goles")}</strong> '
            f'({ordinal(r_gf)} de la categoría) y encajado <strong>{gc}</strong> '
            f'({ordinal(r_gc)} menos batido), para {saldo}.'))

    # ── Ritmo de puntos ──────────────────────────────────────────────────────
    total_md = snap.get("total_md")
    if gp and played:
        ppp = team["pts"] / gp
        media = sum(t["pts"] for t in played) / sum(t["gp"] for t in played)
        comp = "por encima de" if ppp > media else ("por debajo de" if ppp < media else "en")
        f = (f'Suma <strong>{num(ppp, 2)} puntos por partido</strong>, {comp} la media '
             f'de la competición ({num(media, 2)})')
        # Extrapolar 38 jornadas desde 1-2 partidos da titulares absurdos (un 3-0
        # en la J1 "proyecta" 114 puntos). A partir de 5 ya dice algo.
        if gp >= 5 and total_md:
            # "acabaría la liga" chirría en las UEFA, que no son una liga sino
            # una fase de liga a 8 jornadas. Sin sujeto vale para las 15.
            f += (f'; a ese ritmo terminaría con unos '
                  f'<strong>{round(ppp * total_md)} puntos</strong>')
        cand.append((min(abs(ppp - media) / 1.5, 1.0), f + "."))

    # ── Distancia al corte de su zona principal ──────────────────────────────
    corte = _by_rank(snap, banda["hi"])
    fuera = _by_rank(snap, banda["hi"] + 1)
    if gp and corte and team["rank"] > banda["hi"]:
        d = abs(team["pts"] - corte["pts"])
        # Cuanto más cerca del corte, más interesa: a 0-2 puntos es la noticia.
        cand.append((max(0.0, 1.0 - d / 8),
                     f'Está a <strong>{plural(d, "punto")}</strong> del '
                     f'{ordinal(corte["rank"])} ({esc(corte["name"])}), que hoy marca '
                     f'el corte de {etiqueta}.'))
    elif gp and fuera and team["rank"] <= banda["hi"]:
        d = team["pts"] - fuera["pts"]
        # signed() da "=" para 0, que vale en una tabla pero no en una frase.
        colchon = (f'empatado a puntos con el {ordinal(fuera["rank"])}' if d == 0
                   else f'con <strong>{plural(d, "punto")}</strong> sobre el '
                        f'{ordinal(fuera["rank"])}')
        cand.append((max(0.0, 1.0 - abs(d) / 8),
                     f'Ocupa plaza de {etiqueta} {colchon} ({esc(fuera["name"])}), '
                     f'primero fuera del corte.'))

    # ── Ataque y defensa según el modelo (no la tabla) ───────────────────────
    if team.get("att") is not None and team.get("def") is not None and len(snap["teams"]) >= 6:
        r_att = _rank_of(snap["teams"], team, "att", "max")
        r_def = _rank_of(snap["teams"], team, "def", "min")
        s_att, s_def = extremo(r_att, n), extremo(r_def, n)
        # Solo se cuenta el lado que destaca: decir "12º en ataque y 11º en
        # defensa" no aporta nada y es justo lo que hace que todas las páginas
        # se parezcan.
        if max(s_att, s_def) >= 0.5:
            cual, puesto = ("ataque", r_att) if s_att >= s_def else ("defensa", r_def)
            fem = cual == "defensa"          # "la mejor defensa", "el mejor ataque"
            # Contar desde arriba solo si está arriba: "el 22º mejor ataque" de 22
            # equipos era, literalmente, el peor de la liga.
            if puesto <= n / 2:
                pos, grado = puesto, "mejor"
            else:
                pos, grado = n - puesto + 1, "peor"
            art = "la" if fem else "el"
            cual_txt = (f'{art} {grado} {cual}' if pos == 1
                        else f'{art} {ordinal(pos, fem=fem)} {grado} {cual}')
            cand.append((max(s_att, s_def) * 0.9,
                         f'Para el modelo tiene <strong>{cual_txt}</strong> '
                         f'{esc(de_league(league))}, y de ahí sale su probabilidad, '
                         f'no de la clasificación actual.'))

    # ── Calendario restante ──────────────────────────────────────────────────
    sched = (extras or {}).get(team["id"]) or []
    if sched:
        casa = sum(1 for m in sched if m["home"])
        por_slug = {t["slug"]: t for t in snap["teams"]}
        rivales = [(m, por_slug.get(_opp_slug(m["opponent"]))) for m in sched]
        rivales = [(m, t) for m, t in rivales if t and t.get("strength") is not None]
        f = (f'Le quedan <strong>{plural(len(sched), "partido")}</strong>, {casa} en casa '
             f'y {len(sched) - casa} a domicilio')
        if rivales:
            m, duro = max(rivales, key=lambda r: r[1]["strength"])
            donde = "recibe" if m["home"] else "visita"
            # "de más entidad" según el rating del modelo, que puede no coincidir
            # con la clasificación (sobre todo en las primeras jornadas): se dice
            # de dónde sale el criterio para que no parezca una errata.
            f += (f'; el rival de más nivel que le queda —por rating del modelo, no '
                  f'por tabla— es el <strong>{esc(duro["name"])}</strong> '
                  f'({ordinal(duro["rank"])} hoy), al que {donde} el '
                  f'{esc(fecha_es(m["date"]))}')
        # Desequilibrio casa/fuera: si le quedan casi todos fuera, es noticia.
        cand.append((extremo(casa + 1, len(sched) + 1) * 0.6, f + "."))

    # ── La jornada que más le movió la probabilidad ──────────────────────────
    puntos = [(jj, tt["prob"][banda["key"]]) for jj, s in series
              for tt in [_by_slug(s, team["slug"])] if tt]
    if len(puntos) >= 3:
        saltos = [(puntos[i][0], puntos[i][1] - puntos[i - 1][1])
                  for i in range(1, len(puntos))]
        jmax, dmax = max(saltos, key=lambda x: abs(x[1]))
        if abs(dmax) >= 0.1:
            verbo = "ganó" if dmax > 0 else "perdió"
            cand.append((min(abs(dmax) / 25, 1.0),
                         f'Su jornada más movida fue la <strong>{jmax}</strong>, en la que '
                         f'{verbo} {num(abs(dmax), 1)} puntos porcentuales de {etiqueta}.'))

    if len(cand) < 2:
        return ""
    cand.sort(key=lambda x: -x[0])
    frases = [f for _, f in cand[:4]]
    return (f'<div class="card"><div class="card-pad">'
            f'<div class="section-label">El {esc(team["name"])}, en detalle</div>'
            f'<p class="lede">{" ".join(frases)}</p></div></div>')


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
            f'tras la jornada {j}. Probabilidad de <strong>{esc(zone_label(primary["label"]))}</strong>: '
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
        crumbs([("Inicio", league["dashboard"]),
                (f'Equipos · {league["name"]}', L.teams_hub_url(slug)),
                (team["name"], None)])
        + f'<div class="card">{hero}<div class="card-pad"><p class="lede">{lede}</p></div>'
        + f'<div class="stat-grid">{stats}</div></div>'
    )

    # Análisis propio del equipo — es lo que diferencia esta página de las otras
    # 245 de equipo (ver _team_analysis).
    body += _team_analysis(league, snap, series, team, extras)

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

    title = f'{team["name"]} — Probabilidad de {zone_label(primary["label"])} · {league["name"]}'
    desc = (f'{team["name"]}: {pct(pv)} de {zone_label(primary["label"])} {en_league(league)} '
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

    # og:image/favicon del equipo: su propio escudo es más específico para una
    # vista previa social que el de la competición (fallback si ESPN no lo trae).
    html = page(title, desc, L.team_url(slug, team["slug"]), body,
                heading=league["name"], logo=team["logo"] or logo,
                badge=f"Jornada <strong>{j}</strong>",
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
        crumbs([("Inicio", league["dashboard"]),
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
                  + " y ".join(parts) + f' en probabilidad de {esc(zone_label(primary["label"]))}.</p>')

    if before is None:
        intro = (f'Probabilidades {esc(de_league(league))} tras la jornada {j}. '
                 f'Cuando se registre la jornada {j+1} aparecerá aquí cuánto movió cada resultado.')
    else:
        intro = (f'Cómo cambiaron las probabilidades {esc(de_league(league))} '
                 f'entre la jornada {before["jornada"]} y la {j}.')

    # `before` es el snapshot anterior que EXISTE, no forzosamente el de j-1: si el
    # cron se salta una liga un día (403, caída), la serie salta de la 20 a la 22 y
    # /jornadas/<liga>/21 nunca se generó ni está en el sitemap. Enlazar j-1 le daba
    # un 404 interno al crawler; la prosa de arriba ya usa before["jornada"].
    # La jornada 0 es el snapshot de PRETEMPORADA: no tiene página generada, así
    # que no se enlaza atrás cuando el snapshot previo es la 0 (sería un 404).
    nav = (f'<a href="{L.jornada_url(slug, before["jornada"])}">'
           f'← Jornada {before["jornada"]}</a>' if before and before["jornada"] > 0 else '')
    nav += (f'<a href="{L.jornadas_hub_url(slug)}">Todas las jornadas</a>'
            f'<a href="{L.teams_hub_url(slug)}">Equipos</a>')

    body = (
        crumbs([("Inicio", league["dashboard"]),
                (f'Jornadas · {league["name"]}', L.jornadas_hub_url(slug)),
                (f'Jornada {j}', None)])
        + f'<div class="card"><div class="card-pad"><p class="lede">{intro}</p>{mv}</div>{table}</div>'
        + f'<div class="card"><div class="card-pad"><div class="section-label">Navegar</div>'
        + f'<div class="chips">{nav}</div></div></div>'
    )
    title = f'Jornada {j} · Probabilidades de {league["name"]} {league["season"]}'
    desc = (f'Evolución de las probabilidades {de_league(league)} en la jornada {j}: '
            f'cuánto movió cada resultado la carrera por {zone_label(primary["label"])}.')
    ld = {
        "@context": "https://schema.org", "@type": "ItemList", "name": title,
        "itemListElement": [
            {"@type": "ListItem", "position": t["rank"], "name": t["name"],
             "url": SITE + L.team_url(slug, t["slug"])}
            for t in sorted(after["teams"], key=lambda x: x["rank"])],
    }
    return L.jornada_file(slug, j), page(title, desc, L.jornada_url(slug, j), body,
                                         heading=league["name"], logo=logo, badge=f"Jornada <strong>{j}</strong>",
                                         json_ld=[ld],
                                         active_nav=league["dashboard"])


# ── Hub de jornadas ─────────────────────────────────────────────────────────

def _jornadas_hub(league, series, logo):
    slug = league["slug"]
    chips = "".join(f'<a href="{L.jornada_url(slug, j)}">Jornada {j} · {esc(s["date"])}</a>'
                    for j, s in sorted(series, reverse=True) if j > 0)
    if not chips:
        chips = '<span class="muted">Aún no hay jornadas registradas.</span>'
    body = (
        crumbs([("Inicio", league["dashboard"]),
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
        jn = s["jornada"]
        # La jornada 0 (pretemporada) no tiene página: sin enlace "ver jornada".
        ver = (f'<a class="tname" href="{L.jornada_url(slug, jn)}">ver jornada →</a>'
               if jn > 0 else '<span class="muted">—</span>')
        rows += (f'<tr><td class="muted" style="font-family:Inconsolata,monospace;font-size:.82rem">{esc(s["date"])}</td>'
                 f'<td>J{jn}</td>'
                 f'<td><div class="tcell">{_av(leader, 24)}'
                 f'<a class="tname" href="{L.team_url(slug, leader["slug"])}">{esc(leader["name"])}</a></div></td>'
                 f'<td class="r ptsv">{pct(leader["prob"][primary["key"]])}</td>'
                 f'<td class="r">{ver}</td></tr>')
    table = (f'<div class="table-scroll"><table><thead><tr><th>Fecha</th><th>Jor.</th><th>Líder</th>'
             f'<th class="r">{esc(snaps[-1]["bands"][0]["label"])}</th><th></th></tr></thead>'
             f'<tbody>{rows}</tbody></table></div>')
    body = (
        crumbs([("Inicio", league["dashboard"]),
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
    # Temporada VIVA del snapshot (no el valor fijo de config.py): todas las
    # referencias league["season"] de abajo la heredan por esta copia.
    league = {**league, "season": current["season"]}
    logo = current.get("league_logo")
    series = per_period_series(snaps, "jornada")
    files, urls = {}, []

    def add(pair, url):
        files[pair[0]] = pair[1]
        urls.append((url, current["date"]))

    for t in current["teams"]:
        add(_team_page(league, current, series, t, extras, logo), L.team_url(league["slug"], t["slug"]))
    add(_teams_hub(league, current, logo), L.teams_hub_url(league["slug"]))
    # La jornada 0 (pretemporada, estado previo a cualquier partido) no se genera:
    # ni fichero ni URL de sitemap — sin valor informativo ni SEO.
    for j, s in series:
        if j == 0:
            continue
        add(_jornada_page(league, s, _prev_jornada_snap(series, j), logo), L.jornada_url(league["slug"], j))
    add(_jornadas_hub(league, series, logo), L.jornadas_hub_url(league["slug"]))
    add(_historico(league, snaps, series, logo), L.historico_url(league["slug"]))
    return files, urls


# ── Autocomprobación de _team_analysis ──────────────────────────────────────
# python3 -m seo.render_table
# Sin red ni ficheros: una tabla de juguete basta para fijar las trampas que ya
# mordieron una vez (concordancia, singulares, "22º mejor" siendo el peor).

def _demo_snap(gp=2):
    bands = [{"key": "champions", "label": "Champions League", "color": "green",
              "lo": 1, "hi": 2, "zone": "promo"},
             {"key": "descenso", "label": "Descenso", "color": "red",
              "lo": 4, "hi": 4, "zone": "relega"}]
    teams = []
    for i in range(4):
        teams.append({
            "slug": f"eq{i}", "id": str(i), "name": f"Equipo {i}", "logo": None,
            "rank": i + 1, "pts": (3 - i) * gp, "gp": gp,
            "gf": 6 - i, "gc": i * 2, "wins": 0, "draws": 0, "losses": 0,
            "strength": 1.0 - i * 0.4, "att": 1.0 - i * 0.5, "def": i * 0.5 - 0.5,
            "prob": {"champions": 80.0 - i * 20, "descenso": i * 15.0},
        })
    return {"teams": teams, "bands": bands, "jornada": gp, "num_teams": 4,
            "total_md": 38, "has_playoff": False, "season": "2026-27",
            "date": "2026-08-26", "league_logo": None}


def _demo():
    league = {"slug": "test", "name": "Liga Test", "article": "la",
              "season": "2026-27", "dashboard": "/test"}
    snap = _demo_snap()
    series = [(1, _demo_snap(1)), (2, snap)]

    textos = [_team_analysis(league, snap, series, t, {}) for t in snap["teams"]]
    assert all(textos), "con partidos jugados todos los equipos deben tener análisis"

    junto = " ".join(textos)
    # Concordancia y singulares: los cuatro fallos que salieron en la 1ª pasada.
    assert "= puntos" not in junto, "signed(0) se coló en la prosa"
    assert " 1 puntos" not in junto, "falta el singular 'punto'"
    assert "1º mejor" not in junto, "'1º mejor' debe ser 'el/la mejor'"
    assert "el 4ª" not in junto and "la 4º" not in junto, "concordancia de género rota"
    # El peor de la liga no puede describirse como "4º mejor" de 4 equipos.
    assert "4º mejor" not in junto and "4ª mejor" not in junto

    # Lo que justifica todo esto: las páginas tienen que ser DISTINTAS.
    assert len(set(textos)) == len(textos), "dos equipos con el mismo texto"

    # Pretemporada: sin partidos no se inventa nada.
    pre = _demo_snap(gp=0)
    for t in pre["teams"]:
        t["gf"] = t["gc"] = t["pts"] = 0
    assert _team_analysis(league, pre, [(0, pre)], pre["teams"][0], {}) == ""

    # Un equipo sin calendario de ESPN no puede romper la generación.
    assert _team_analysis(league, snap, series, snap["teams"][0], None)
    print("seo.render_table: OK")


if __name__ == "__main__":
    _demo()
