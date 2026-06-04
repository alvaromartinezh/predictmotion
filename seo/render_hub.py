"""Selector de competiciones (/datos) y página de cada competición (/datos/<slug>).

- /datos: índice ligero con una tarjeta por competición que enlaza a su página.
- /datos/<slug>: SOLO los datos de esa competición — selector para cambiar, logo,
  resumen honesto, favorito y los accesos existentes (Equipos / Jornadas o Grupos /
  Histórico / Dashboard). La clasificación completa por equipo NO se duplica aquí:
  vive en /equipos/<slug> (ya hecha) y se enlaza tal cual.

Todo sale de datos reales del snapshot; nada inventado.
"""

from . import links as L
from .chrome import page, esc, crumbs, avatar, COLOR_PALETTE
from .config import SITE
from .textutil import pct, de_league


# ── helpers ─────────────────────────────────────────────────────────────────

def _av(team, size=30):
    color = COLOR_PALETTE[(team["rank"] - 1) % len(COLOR_PALETTE)]
    return avatar(team.get("logo"), team["name"], color, size=size)


def _primary(snap):
    """(clave, etiqueta) de la probabilidad principal de la competición."""
    if snap["kind"] == "table":
        b = snap["bands"][0]
        return b["key"], b["label"]
    return "pAdv", "pasar de ronda"


def _all_teams(snap):
    if snap["kind"] == "table":
        return snap["teams"]
    return [t for g in snap["groups"] for t in g["entries"]]


def _favorite(snap):
    key, _ = _primary(snap)
    return max(_all_teams(snap), key=lambda t: t["prob"][key])


def _contested(snap):
    """Equipos con incertidumbre real en la zona principal (5% < p < 95%)."""
    key, _ = _primary(snap)
    teams = [t for t in _all_teams(snap) if 5 < t["prob"][key] < 95]
    return sorted(teams, key=lambda t: -t["prob"][key])


def _selector_pills(entries, active_slug):
    """Fila de píldoras (mismo estilo que league-nav) para cambiar de competición."""
    out = []
    for e in entries:
        lg = e["league"]
        if lg["slug"] == active_slug:
            out.append(f'<span class="league-btn active">{esc(lg["name"])}</span>')
        else:
            out.append(f'<a class="league-btn" href="{L.datos_league_url(lg["slug"])}">{esc(lg["name"])}</a>')
    return '<nav class="league-nav" style="margin-top:-6px">' + "".join(out) + "</nav>"


# ── /datos — selector ───────────────────────────────────────────────────────

def render_selector(entries):
    cards = ""
    for e in entries:
        lg, snap = e["league"], e["snap"]
        logo = snap.get("league_logo")
        logo_html = (f'<div class="comp-logo"><img src="{esc(logo)}" alt="{esc(lg["name"])}"></div>'
                     if logo else "")
        if snap["kind"] == "table":
            state = "Temporada finalizada" if snap.get("finished") else f'En juego · jornada {snap["jornada"]}'
        else:
            state = f'En juego · {snap["matchday"]} jornada(s)'
        cards += (
            f'<a class="comp-link" href="{L.datos_league_url(lg["slug"])}">'
            f'<div class="card"><div class="card-pad">'
            f'<div class="comp-head">{logo_html}'
            f'<div class="t">{esc(lg["name"])}<small>{esc(lg["season"])}</small></div></div>'
            f'<p class="comp-meta">{esc(state)} · actualizado {esc(snap["date"])}</p>'
            f'<span class="comp-cta">Ver datos y probabilidades →</span>'
            f'</div></div></a>'
        )
    body = (
        crumbs([("Inicio", "/"), ("Datos", None)])
        + '<div class="card"><div class="card-pad"><p class="lede">Elige una competición para ver '
          'sus probabilidades por equipo, evolución por jornada e histórico. Todo generado por '
          'simulación Monte Carlo a partir de resultados reales.</p></div></div>'
        + f'<div class="comp-grid">{cards}</div>'
    )
    title = "Datos y probabilidades · PredictMotion"
    desc = ("Selector de competiciones de PredictMotion: probabilidades de ascenso, descenso y "
            "clasificación por equipo y jornada, por simulación Monte Carlo.")
    ld = {"@context": "https://schema.org", "@type": "CollectionPage",
          "name": title, "description": desc, "url": SITE + L.datos_url(),
          "hasPart": [{"@type": "WebPage", "name": e["league"]["name"],
                       "url": SITE + L.datos_league_url(e["league"]["slug"])} for e in entries]}
    return L.datos_file(), page(title, desc, L.datos_url(), body,
                                heading="Datos y probabilidades", json_ld=[ld])


# ── /datos/<slug> — una competición ─────────────────────────────────────────

def render_competition(entry, entries):
    lg, snap = entry["league"], entry["snap"]
    slug = lg["slug"]
    logo = snap.get("league_logo")
    key, label = _primary(snap)
    fav = _favorite(snap)
    contested = _contested(snap)

    # Lede honesto
    if snap["kind"] == "table":
        badge = f'Jornada <strong>{snap["jornada"]}</strong>'
        if snap.get("finished"):
            lede = (f'La <strong>{esc(lg["name"])} {esc(snap["season"])}</strong> ya está decidida: '
                    f'todos los partidos se han jugado. Estas fueron las probabilidades finales.')
        elif contested:
            lede = (f'<strong>{len(contested)}</strong> equipos siguen en disputa por '
                    f'<strong>{esc(label.lower())}</strong> {esc(de_league(lg))} tras la jornada '
                    f'{snap["jornada"]}.')
        else:
            lede = (f'Probabilidades {esc(de_league(lg))} tras la jornada {snap["jornada"]}, '
                    f'por simulación Monte Carlo.')
        accesos = (f'<a href="{L.teams_hub_url(slug)}">Tabla por equipo</a>'
                   f'<a href="{L.jornadas_hub_url(slug)}">Jornadas</a>'
                   f'<a href="{L.historico_url(slug)}">Histórico</a>'
                   f'<a href="{lg["dashboard"]}">Dashboard en vivo</a>')
    else:
        badge = f'{snap["num_groups"]} grupos'
        if contested:
            lede = (f'<strong>{len(contested)}</strong> selecciones siguen en disputa por '
                    f'<strong>pasar de ronda</strong> {esc(de_league(lg))} tras {snap["matchday"]} '
                    f'jornada(s). Pasan {snap["advancing"]} de {snap["num_groups"]*4}.')
        else:
            lede = (f'Probabilidades {esc(de_league(lg))} tras {snap["matchday"]} jornada(s), '
                    f'por simulación Monte Carlo.')
        accesos = (f'<a href="{L.teams_hub_url(slug)}">Tabla por selección</a>'
                   f'<a href="{L.grupos_hub_url(slug)}">Grupos</a>'
                   f'<a href="{L.historico_url(slug)}">Histórico</a>'
                   f'<a href="{lg["dashboard"]}">Dashboard en vivo</a>')

    # Favorito
    fav_label = "Favorito" if snap["kind"] == "table" else "Favorita"
    hl = (f'<div class="hl">{_av(fav)}<div><div class="hl-l">{fav_label} · {esc(label)}</div>'
          f'<div class="hl-n">{esc(fav["name"])}</div></div>'
          f'<div class="hl-v">{pct(fav["prob"][key])}</div></div>')

    # En disputa (lista compacta, no es la clasificación: solo 5%–95%)
    race = ""
    if contested:
        items = "".join(
            f'<a href="{L.team_url(slug, t["slug"])}">{_av(t, 22)}{esc(t["name"])} '
            f'<strong style="color:var(--accent)">{pct(t["prob"][key])}</strong></a>'
            for t in contested[:8])
        race = (f'<div class="card"><div class="card-pad">'
                f'<div class="section-label">En disputa · {esc(label)}</div>'
                f'<div class="chips">{items}</div>'
                f'<p class="muted" style="margin-top:10px">Clasificación completa por equipo en '
                f'<a href="{L.teams_hub_url(slug)}" style="color:var(--accent)">la tabla de probabilidades</a>.</p>'
                f'</div></div>')

    body = (
        crumbs([("Inicio", "/"), ("Datos", L.datos_url()), (lg["name"], None)])
        + _selector_pills(entries, slug)
        + f'<div class="card"><div class="card-pad"><p class="lede">{lede}</p>{hl}</div></div>'
        + race
        + f'<div class="card"><div class="card-pad"><div class="section-label">Datos {esc(de_league(lg))}</div>'
        + f'<div class="chips">{accesos}</div></div></div>'
    )
    title = f'{lg["name"]} {lg["season"]} — Datos y probabilidades'
    desc = (f'Probabilidades {de_league(lg)} {lg["season"]} por equipo, jornada e histórico. '
            f'Favorito: {fav["name"]} ({pct(fav["prob"][key])} {label.lower()}). Simulación Monte Carlo.')
    ld = {"@context": "https://schema.org", "@type": "CollectionPage",
          "name": title, "description": desc, "url": SITE + L.datos_league_url(slug),
          "about": {"@type": "SportsOrganization", "name": lg["name"], "sport": "Soccer"}}
    return L.datos_league_file(slug), page(title, desc, L.datos_league_url(slug), body,
                                           heading=lg["name"], logo=logo, badge=badge,
                                           json_ld=[ld], active_nav=None)
