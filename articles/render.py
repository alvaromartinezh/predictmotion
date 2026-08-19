"""HTML de los broadsheets de artículos (resumen diario + crónica de
partido), uno por liga en articles.config.ARTICLE_LEAGUES.

Página autónoma (no usa seo/chrome.py:page() — paleta/tipografía distintas,
ver assets/articles-broadsheet.css) que combina dos piezas generadas por
writer.py: el resumen de los partidos del día (un brief por partido) y un
explicador del equipo más destacado de la jornada.
"""

import json
import re
from datetime import date, datetime, timezone

from seo.chrome import COLOR_PALETTE, GTM_BODY, GTM_HEAD, avatar, esc, team_avatar
from seo.config import SIM_N_TABLE, SITE
from seo.textutil import pct, signed, slugify

from . import grounding, illustration, writer
from .config import STAT_KINDS

_CSS_V = "12"
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
ZONE_HEX = {"ascenso": "#2ec98a", "ascenso_total": "#2ec98a", "playoff": "#f3b23f", "descenso": "#ff556b"}
STAT_HEX = {"colista": "#ff556b", "lider": "#2ec98a", "tapado": "#7c5cff",
            "muro": "#2ec98a", "ataque": "#f3b23f",
            "goleado": "#ff556b", "porteria_cero": "#2ec98a", "favorito_jornada": "#2ec98a",
            "goleador": "#f3b23f", "invicto_jornada": "#2ec98a", "derrota_jornada": "#ff556b",
            "nivel_jornada": "#7c5cff", "empate_jornada": "#7c5cff", "goles_jornada": "#f3b23f",
            "over_25": "#f3b23f", "ambos_marcan": "#f3b23f", "sorpresa_jornada": "#7c5cff",
            "marcador_jornada": "#7c5cff",
            "subida_zona": "#2ec98a", "caida_zona": "#ff556b", "sorpresa_temporada": "#7c5cff"}


def slug_for(league_slug, fecha):
    return f"{league_slug}-resumen-{fecha}"


def url_for(league_slug, fecha):
    return f"/articulos/{slug_for(league_slug, fecha)}"


def file_for(league_slug, fecha):
    return f"articulos/{slug_for(league_slug, fecha)}.html"


def slug_for_stat(league_slug, fecha, hour, kind):
    return f"{league_slug}-dato-{kind}-{fecha}-{hour:02d}"


def url_for_stat(league_slug, fecha, hour, kind):
    return f"/articulos/{slug_for_stat(league_slug, fecha, hour, kind)}"


def slug_for_match(league_slug, fecha, local_nombre, visitante_nombre):
    return f"{league_slug}-{slugify(local_nombre)}-{slugify(visitante_nombre)}-{fecha}"


def url_for_match(league_slug, fecha, local_nombre, visitante_nombre):
    return f"/articulos/{slug_for_match(league_slug, fecha, local_nombre, visitante_nombre)}"


def _seed(team_id):
    try:
        return int(team_id)
    except (TypeError, ValueError):
        return 0


def _fecha_label(fecha):
    d = date.fromisoformat(fecha)
    dia = _DIAS[d.weekday()].capitalize()
    mes = _MESES[d.month - 1]
    return f"{dia} {d.day} {mes} {d.year}"


def _teaser(partidos):
    """Frase-resumen de la jornada, derivada de los resultados (sin LLM: es
    prosa sintética a partir de datos cerrados, cero riesgo de invención)."""
    if not partidos:
        return ""
    bits, used = [], set()

    def margin(m):
        return abs(m["resultado"]["local"] - m["resultado"]["visitante"])

    biggest = max(partidos, key=margin)
    if margin(biggest) >= 2:
        bl, bv = biggest["resultado"]["local"], biggest["resultado"]["visitante"]
        winner, loser = (biggest["local"], biggest["visitante"]) if bl > bv else (biggest["visitante"], biggest["local"])
        bits.append(f'el {winner["nombre"]} golea al {loser["nombre"]}')
        used.add(id(biggest))

    draw = next((m for m in partidos if margin(m) == 0 and id(m) not in used), None)
    if draw:
        bits.append(f'el {draw["local"]["nombre"]} y el {draw["visitante"]["nombre"]} firman tablas')
        used.add(id(draw))

    close = next((m for m in partidos if margin(m) == 1 and id(m) not in used), None)
    if close:
        cl, cv = close["resultado"]["local"], close["resultado"]["visitante"]
        winner, loser = (close["local"], close["visitante"]) if cl > cv else (close["visitante"], close["local"])
        bits.append(f'el {winner["nombre"]} gana por la mínima al {loser["nombre"]}')
        used.add(id(close))

    if not bits:
        bits = [f'{m["local"]["nombre"]} {m["resultado"]["local"]}-{m["resultado"]["visitante"]} {m["visitante"]["nombre"]}'
                for m in partidos[:3]]

    bits = bits[:3]
    sentence = bits[0] if len(bits) == 1 else ", ".join(bits[:-1]) + " y " + bits[-1]
    return sentence[0].upper() + sentence[1:] + "."


def _highlight_teams(text, team_names):
    """Titular llamativo (texto libre de Gemini) con los nombres de equipo
    que aparezcan resaltados en acento — mismo hueco visual que antes cubría
    el <span> del titular determinista ("N partidos"), que desapareció al
    pasar a un titular generado. Nombres más largos primero para que un
    nombre corto no se coma parte de uno más largo que lo contiene."""
    out = esc(text)
    for name in sorted(set(team_names), key=len, reverse=True):
        pattern = re.compile(r'\b' + re.escape(esc(name)) + r'\b')
        out = pattern.sub(lambda m: f'<span>{m.group(0)}</span>', out, count=1)
    return out


def _delta(actual, antes):
    if actual is None or antes is None:
        return "", ""
    d = actual - antes
    if abs(d) < 0.05:
        return "sin cambio", "bs-delta-eq"
    return signed(d) + " pp", ("bs-delta-up" if d > 0 else "bs-delta-down")


def _zone_block(t, size_cls="", show_before=False):
    if t is None or t.get("prob_zona_actual") is None:
        return ""
    color = ZONE_HEX.get(t.get("zona_key"), "#66789c")
    delta_txt, delta_cls = _delta(t["prob_zona_actual"], t.get("prob_zona_antes_del_partido"))
    delta_html = f'<span class="{delta_cls}">{esc(delta_txt)}</span>' if delta_txt else ""
    before_html = ""
    if show_before and t.get("prob_zona_antes_del_partido") is not None:
        before_html = f'<span class="bs-zone__before">{pct(t["prob_zona_antes_del_partido"])} →</span>'
    cls = "bs-zone" + (f" {size_cls}" if size_cls else "")
    return (f'<div class="{cls}" style="border-left-color:{color}">'
            f'<div class="bs-zone__row">'
            f'<span class="bs-zone__team">{esc(t["nombre"])}</span>'
            f'{before_html}'
            f'<b class="bs-zone__val">{pct(t["prob_zona_actual"])}</b>'
            f'{delta_html}</div>'
            f'<div class="bs-zone__label">{esc(t["zona"])}</div></div>')


def _match_head(m, league_slug, size=20):
    l, v, r = m["local"], m["visitante"], m["resultado"]
    inner = (
        f'{team_avatar(l.get("logo"), l["nombre"], _seed(l.get("id")), size)}'
        f'<span class="bs-brief__name">{esc(l["nombre"])}</span>'
        f'<b class="bs-brief__score">{r["local"]}–{r["visitante"]}</b>'
        f'<span class="bs-brief__name bs-brief__name--away">{esc(v["nombre"])}</span>'
        f'{team_avatar(v.get("logo"), v["nombre"], _seed(v.get("id")), size)}'
    )
    if m.get("event_id"):
        href = f'/partido?league={league_slug}&id={m["event_id"]}'
        return f'<a class="bs-brief__head" href="{esc(href)}">{inner}</a>'
    return f'<div class="bs-brief__head">{inner}</div>'


def _brief_html(m, text, league_slug):
    zones = _zone_block(m["local"]) + _zone_block(m["visitante"])
    return f'<div class="bs-brief">{_match_head(m, league_slug)}<p>{esc(text)}</p>{zones}</div>'


def _side_brief_html(m, text, league_slug):
    l, v, r = m["local"], m["visitante"], m["resultado"]
    href = f'/partido?league={league_slug}&id={m["event_id"]}' if m.get("event_id") else None
    cronica = f'<a class="bs-side-brief__cronica" href="{esc(href)}">Crónica</a>' if href else ""
    zones = _zone_block(l, "bs-zone--sm") + _zone_block(v, "bs-zone--sm")
    return (
        f'<div class="bs-side-brief">'
        f'<h3>{esc(l["nombre"])} <span>{r["local"]}–{r["visitante"]}</span> {esc(v["nombre"])}</h3>'
        f'<div class="bs-side-brief__row">'
        f'{team_avatar(l.get("logo"), l["nombre"], _seed(l.get("id")), 22)}'
        f'{team_avatar(v.get("logo"), v["nombre"], _seed(v.get("id")), 22)}'
        f'{cronica}</div>'
        f'<p>{esc(text)}</p>{zones}</div>'
    )


def _split_briefs(text, partidos):
    """1 párrafo por partido, en orden (contrato de writer.py). Si el
    recuento no cuadra, degrada a None (el llamante cae a prosa suelta)."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paras) != len(partidos):
        return None
    return list(zip(partidos, paras))


def _prose_html(text):
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    return '<div class="bs-prose">' + "".join(f"<p>{esc(p)}</p>" for p in paras) + "</div>"


def _illo_html(ill, cls, img_style="", caption_cls=None):
    style_attr = f' style="{img_style}"' if img_style else ""
    caption = ""
    if caption_cls:
        caption = f'<figcaption class="{caption_cls}">{esc(ill["credit"])} · {esc(ill["source"])}</figcaption>'
    return (f'<figure class="{cls}">'
            f'<img src="{illustration.url(ill)}" alt="" loading="lazy"{style_attr}>'
            f'{caption}'
            f'</figure>')


def _mentions_html(payload_resumen, league_name, league_logo, league_slug):
    seen, chips = set(), []
    chips.append(f'<a href="/{league_slug}">{avatar(league_logo, league_name, "#e11d48", 20)}{esc(league_name)}</a>')
    for m in payload_resumen["partidos"]:
        for t in (m["local"], m["visitante"]):
            if t["id"] in seen:
                continue
            seen.add(t["id"])
            color = COLOR_PALETTE[_seed(t["id"]) % len(COLOR_PALETTE)]
            href = f'/equipo?id={t["id"]}&name={esc(t["nombre"])}&league={league_slug}'
            chips.append(f'<a href="{href}">{avatar(t.get("logo"), t["nombre"], color, 20)}{esc(t["nombre"])}</a>')
    return (
        '<div class="bs-mentions"><div class="bs-mentions__label">Equipos mencionados</div>'
        f'<div class="bs-mentions__list">{"".join(chips)}</div></div>'
    )


def _masthead_html(tagline):
    """Cabecera compartida por el broadsheet diario y el de partido — único
    sitio que la define, para no tener dos copias del mismo marcado."""
    return f"""<div class="bs-masthead">
<div class="bs-masthead__kicker"><span>Simulación Monte Carlo</span><span>Datos oficiales · ESPN</span></div>
<div class="bs-masthead__title"><span class="bs-masthead__dot"></span>
<h1>Predict<span>Motion</span></h1></div>
<div class="bs-masthead__tagline">{esc(tagline)}</div>
</div>"""


def _footer_html():
    return """<div class="bs-footer">
<span>© 2025 PredictMotion · Todos los derechos reservados</span>
<a href="/privacy">Privacidad</a>
</div>"""


def _page_html(title, description, canonical, league_logo, json_ld, body):
    """Documento HTML completo (head+body) compartido por el broadsheet
    diario y el de partido — solo cambian título/meta/JSON-LD/cuerpo."""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">
<meta name="theme-color" content="#060916">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{esc(league_logo or '')}">
<meta property="og:locale" content="es_ES">
<meta property="og:site_name" content="PredictMotion">
<meta name="twitter:card" content="summary">
<link rel="icon" type="image/png" href="{esc(league_logo or '')}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="dns-prefetch" href="https://a.espncdn.com">
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&family=Saira+Condensed:wght@500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/articles-broadsheet.css?v={_CSS_V}">
<script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
</head>
<body>
{GTM_BODY}
{body}
</body>
</html>"""


def render_broadsheet(payload_resumen, resumen_body, payload_explainer, explainer_body,
                       *, league_slug, fecha, league_logo, headline, subtitle, status_label="Publicado",
                       explainer_filler_h=None, side_filler_h=None):
    partidos = payload_resumen["partidos"]
    n = len(partidos)
    picked_files = set()

    def pick_illo(variant):
        ill = illustration.pick(league_slug, fecha, variant, avoid=picked_files)
        picked_files.add(ill["file"])
        return ill
    title = f'{headline} | PredictMotion'
    description = subtitle
    canonical = SITE + url_for(league_slug, fecha)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    json_ld = {
        "@context": "https://schema.org", "@type": "SportsArticle", "headline": title,
        "description": description, "datePublished": generated_at,
        "author": {"@type": "Organization", "name": "PredictMotion"},
        "publisher": {"@type": "Organization", "name": "PredictMotion",
                      "logo": {"@type": "ImageObject", "url": "https://predictmotion.com/media/twitter_profile.png"}},
        "about": {"@type": "SportsOrganization", "name": payload_resumen["liga"]},
        "url": canonical,
    }

    # ── Explicador (columna izquierda + nota del modelo) ──
    side_paras, note_paras = writer.split_explainer_paragraphs(explainer_body)
    zonas = payload_explainer["probabilidades_por_zona"]
    top_zona, top_val = grounding.explainer_best_zone(payload_explainer)
    ex_headline = f'El modelo da al {esc(payload_explainer["equipo"])} un <span>{pct(top_val)}</span> de {esc(top_zona.lower())}'

    ZONE_ORDER = [("Ascenso total", "#2ec98a"), ("Ascenso directo", "#2ec98a"),
                  ("Play-off de ascenso", "#f3b23f"), ("Descenso", "#ff556b")]
    stats_html = "".join(
        f'<div class="bs-stats__row"><span class="bs-stats__value" style="color:{color}">{pct(zonas[label])}</span>'
        f'<span class="bs-stats__label">{esc(label)}</span></div>'
        for label, color in ZONE_ORDER if label in zonas
    )

    explainer_col = (
        '<div class="bs-col-explainer">'
        '<div class="bs-section-label">Explicador</div>'
        f'<h2>{ex_headline}</h2>'
        f'<div class="bs-team-row">{team_avatar(payload_explainer["equipo_logo"], payload_explainer["equipo"], _seed(payload_explainer["equipo_id"]), 26)}'
        f'<span class="bs-team-row__name">{esc(payload_explainer["equipo"])}</span>'
        f'<span class="bs-team-row__meta">{payload_explainer["posicion"]}º · {payload_explainer["puntos"]} pts</span></div>'
        f'<div class="bs-stats">{stats_html}</div>'
        + _prose_html("\n\n".join(side_paras)) +
        _illo_html(pick_illo("explainer"), "bs-illo bs-illo--sm")
    )
    if explainer_filler_h:
        explainer_col += _illo_html(pick_illo("explainer_filler"), "bs-illo bs-illo--filler",
                                     img_style=f"height:{explainer_filler_h:.0f}px")
    explainer_col += '</div>'

    # ── Resumen del día (columna central) ──
    pairs = _split_briefs(resumen_body, partidos)
    if pairs is None:
        lead_html, side_html = _prose_html(resumen_body), ""
    else:
        lead_pairs, side_pairs = pairs[:2], pairs[2:]
        lead_html = "".join(_brief_html(m, t, league_slug) for m, t in lead_pairs)
        side_html = "".join(_side_brief_html(m, t, league_slug) for m, t in side_pairs)

    note_html = ""
    if note_paras:
        note_html = ('<div class="bs-note"><div class="bs-note__label">Nota del modelo</div>'
                     f'<p>{esc(" ".join(note_paras))}</p></div>')

    main_col = (
        '<div class="bs-col-main">'
        + _illo_html(pick_illo("cover"), "bs-cover") +
        '<div class="bs-main-label">Resumen del día</div>'
        f'<h2>{_highlight_teams(headline, [t["nombre"] for m in partidos for t in (m["local"], m["visitante"])])}</h2>'
        f'<div class="bs-teaser"><p>{esc(subtitle)}</p></div>'
        + lead_html + note_html +
        '</div>'
    )

    side_col = ""
    if side_html:
        side_col = (
            '<div class="bs-col-side">'
            '<div class="bs-section-label">Más resultados</div>'
            + side_html +
            _illo_html(pick_illo("footer"), "bs-illo bs-illo--footer")
        )
        if side_filler_h:
            side_col += _illo_html(pick_illo("side_filler"), "bs-illo bs-illo--filler",
                                    img_style=f"height:{side_filler_h:.0f}px")
        side_col += '</div>'

    grid = f'<div class="bs-grid">{explainer_col}{main_col}{side_col}</div>'
    mentions = _mentions_html(payload_resumen, payload_resumen["liga"], league_logo, league_slug)

    body = f"""<div class="bs-page">
<a class="bs-back" href="/{league_slug}">← Volver a la clasificación</a>
<div class="bs-sheet">
{_masthead_html(f'{payload_resumen["liga"]} · El diario de las probabilidades')}
<div class="bs-edition">
<span class="bs-edition__item">Edición diaria</span>
<span class="bs-edition__item bs-edition__item--muted">{_fecha_label(fecha)}</span>
<span class="bs-edition__item">Jornada {payload_resumen["jornada"]}</span>
<span class="bs-edition__item">{n} {"partido" if n == 1 else "partidos"}</span>
<span class="bs-edition__item bs-edition__item--status">{esc(status_label)}</span>
</div>
{grid}
{mentions}
{_footer_html()}
</div></div>"""

    return _page_html(title, description, canonical, league_logo, json_ld, body)


# ── Broadsheet de PARTIDO ────────────────────────────────────────────────

def _team_headline(team):
    """H2 de la columna del equipo: 'Su <zona> <verbo> <valor>' — determinista
    (mismo criterio que el titular del explicador diario: la cifra la compone
    Python a partir del payload, nunca Gemini)."""
    actual = team.get("prob_zona_actual")
    zona = esc(team["zona"])
    if actual is None:
        return zona
    antes = team.get("prob_zona_antes_del_partido")
    val = pct(actual)
    if antes is None:
        return f'Su {zona.lower()} queda en el <span>{val}</span>'
    d = actual - antes
    verb = "se mantiene en" if abs(d) < 0.05 else ("sube al" if d > 0 else "cae al")
    return f'Su {zona.lower()} {verb} <span>{val}</span>'


def _match_stats_html(team):
    rows = []
    for z in team["zonas"]:
        if z["actual"] is None:
            continue
        color = ZONE_HEX.get(z["key"], "#66789c")
        delta_txt, delta_cls = _delta(z["actual"], z["antes"])
        delta_html = f'<span class="bs-stats__delta {delta_cls}">{esc(delta_txt)}</span>' if delta_txt else ""
        rows.append(
            f'<div class="bs-stats__row">'
            f'<span class="bs-stats__value" style="color:{color}">{pct(z["actual"])}</span>'
            f'<span class="bs-stats__label">{esc(z["label"])}</span>'
            f'{delta_html}</div>'
        )
    return f'<div class="bs-stats">{"".join(rows)}</div>'


def _match_side_html(cls, label, team, body_text, illo, extra_html="", illo_extra_cls="", illo_caption_cls=None):
    illo_cls = "bs-illo bs-illo--fill" + (f" {illo_extra_cls}" if illo_extra_cls else "")
    return (
        f'<div class="{cls}">'
        f'<div class="bs-section-label">{esc(label)}</div>'
        f'<div class="bs-match-team">'
        f'{team_avatar(team.get("logo"), team["nombre"], _seed(team.get("id")), 30)}'
        f'<span class="bs-match-team__name">{esc(team["nombre"])}</span>'
        f'<span class="bs-match-team__meta">{team["posicion"]}º · {team["puntos"]} pts</span>'
        f'</div>'
        f'<h2>{_team_headline(team)}</h2>'
        f'{_match_stats_html(team)}'
        f'{_prose_html(body_text)}'
        f'{extra_html}'
        f'{_illo_html(illo, illo_cls, caption_cls=illo_caption_cls)}'
        f'</div>'
    )


def _scoreline_html(local, visitante, resultado):
    return (
        '<div class="bs-scoreline">'
        '<div class="bs-scoreline__side">'
        f'{team_avatar(local.get("logo"), local["nombre"], _seed(local.get("id")), 46)}'
        f'<span class="bs-scoreline__name">{esc(local["nombre"])}</span>'
        '<span class="bs-scoreline__tag">Local</span></div>'
        '<div class="bs-scoreline__mid">'
        f'<span class="bs-scoreline__score">{resultado["local"]}–{resultado["visitante"]}</span>'
        '<span class="bs-scoreline__status">Final</span></div>'
        '<div class="bs-scoreline__side">'
        f'{team_avatar(visitante.get("logo"), visitante["nombre"], _seed(visitante.get("id")), 46)}'
        f'<span class="bs-scoreline__name">{esc(visitante["nombre"])}</span>'
        '<span class="bs-scoreline__tag">Visitante</span></div>'
        '</div>'
    )


def _facts_html(payload):
    l, v, r = payload["local"], payload["visitante"], payload["resultado"]
    sim_n = f"{SIM_N_TABLE:,}".replace(",", ".")
    rows = [
        ("Competición", payload["liga"]),
        ("Jornada", str(payload["jornada"])),
        ("Fecha", _fecha_label(payload["fecha"])),
        ("Estadio", payload.get("estadio") or "—"),
        ("Marcador", f'{l["nombre"]} {r["local"]} – {r["visitante"]} {v["nombre"]}'),
        ("Modelo", f"Monte Carlo · {sim_n} sim."),
    ]
    rows_html = "".join(f'<div class="bs-facts__row"><span>{esc(k)}</span><span>{esc(val)}</span></div>'
                         for k, val in rows)
    return f'<div class="bs-facts"><div class="bs-facts__label">Ficha del partido</div>{rows_html}</div>'


def _model_reading(jornada):
    """'Lectura del modelo' — determinista (sin Gemini): la fiabilidad del
    prior de fuerza depende de cuántas jornadas reales se han acumulado, un
    hecho ya conocido por jornada, no algo que necesite redactarse por IA."""
    if jornada <= 3:
        plural = "s" if jornada != 1 else ""
        return (
            f"Con solo {jornada} jornada{plural} disputada{plural}, el simulador trabaja todavía sobre una base "
            "de información mínima, de modo que cada partido mueve las probabilidades mucho más de lo que lo "
            "hará en primavera. Conviene leer estos porcentajes como una fotografía del momento y no como una "
            "tendencia consolidada: el rating de fuerza de cada plantilla sigue pesando más que el resultado "
            "puntual hasta que se acumulen suficientes jornadas."
        )
    return (
        f"Con la jornada {jornada} ya disputada, el simulador combina los resultados reales de la temporada con "
        "el rating de fuerza de cada plantilla, que va perdiendo peso a medida que se acumulan partidos. Un "
        "resultado aislado mueve ya menos las probabilidades que al principio de la competición, pero sigue "
        "siendo una señal real para el modelo."
    )


def _match_mentions_html(payload, league_name, league_logo, league_slug):
    chips = [f'<a href="/{league_slug}">{avatar(league_logo, league_name, "#e11d48", 20)}{esc(league_name)}</a>']
    for t in (payload["local"], payload["visitante"]):
        color = COLOR_PALETTE[_seed(t.get("id")) % len(COLOR_PALETTE)]
        href = f'/equipo?id={t["id"]}&name={esc(t["nombre"])}&league={league_slug}'
        chips.append(f'<a href="{href}">{avatar(t.get("logo"), t["nombre"], color, 20)}{esc(t["nombre"])}</a>')
    return (
        '<div class="bs-mentions"><div class="bs-mentions__label">Equipos mencionados</div>'
        f'<div class="bs-mentions__list">{"".join(chips)}</div></div>'
    )


def render_match_broadsheet(payload, local_body, visitante_body, cronica_body,
                             *, league_slug, headline, teaser, league_logo, status_label="Finalizado"):
    local, visitante, resultado = payload["local"], payload["visitante"], payload["resultado"]
    fecha = payload["fecha"]
    picked_files = set()

    def pick_illo(variant):
        ill = illustration.pick(league_slug, fecha, f'match-{payload.get("event_id")}-{variant}', avoid=picked_files)
        picked_files.add(ill["file"])
        return ill

    title = f'{headline} | PredictMotion'
    description = teaser
    canonical = SITE + url_for_match(league_slug, fecha, local["nombre"], visitante["nombre"])
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    json_ld = {
        "@context": "https://schema.org", "@type": "SportsArticle", "headline": title,
        "description": description, "datePublished": generated_at,
        "author": {"@type": "Organization", "name": "PredictMotion"},
        "publisher": {"@type": "Organization", "name": "PredictMotion",
                      "logo": {"@type": "ImageObject", "url": "https://predictmotion.com/media/twitter_profile.png"}},
        "about": {"@type": "SportsEvent", "name": f'{local["nombre"]} - {visitante["nombre"]}',
                  "homeTeam": {"@type": "SportsTeam", "name": local["nombre"]},
                  "awayTeam": {"@type": "SportsTeam", "name": visitante["nombre"]}},
        "url": canonical,
    }

    home_col = _match_side_html("bs-match-home", "El local", local, local_body, pick_illo("home"),
                                 illo_extra_cls="bs-illo--fill-lg", illo_caption_cls="bs-illo__caption")
    away_col = _match_side_html("bs-match-away", "El visitante", visitante, visitante_body, pick_illo("away"),
                                 extra_html=_facts_html(payload))

    moves_html = (
        '<div class="bs-note"><div class="bs-note__label">Movimientos del modelo</div>'
        + _zone_block(local, show_before=True) + _zone_block(visitante, show_before=True) +
        '</div>'
    )
    reading_html = (
        '<div class="bs-note"><div class="bs-note__label">Lectura del modelo</div>'
        f'<p>{esc(_model_reading(payload["jornada"]))}</p></div>'
    )
    center_col = (
        '<div class="bs-match-center">'
        + _illo_html(pick_illo("cover"), "bs-cover", caption_cls="bs-cover__caption") +
        f'<div class="bs-main-label">Crónica de la jornada {payload["jornada"]}</div>'
        f'<h2>{_highlight_teams(headline, [local["nombre"], visitante["nombre"]])}</h2>'
        f'<div class="bs-teaser"><p>{esc(teaser)}</p></div>'
        + _scoreline_html(local, visitante, resultado) +
        _prose_html(cronica_body) + moves_html + reading_html +
        '</div>'
    )

    grid = f'<div class="bs-grid">{home_col}{center_col}{away_col}</div>'
    mentions = _match_mentions_html(payload, payload["liga"], league_logo, league_slug)

    venue_bits = [b for b in (payload.get("estadio"), payload.get("hora")) if b]
    venue_txt = " · ".join(venue_bits) if venue_bits else "—"

    body = f"""<div class="bs-page">
<a class="bs-back" href="/{league_slug}">← Volver a la clasificación</a>
<div class="bs-sheet">
{_masthead_html(f'{payload["liga"]} · El diario de las probabilidades')}
<div class="bs-edition">
<span class="bs-edition__item">Crónica de partido</span>
<span class="bs-edition__item bs-edition__item--muted">{_fecha_label(fecha)}</span>
<span class="bs-edition__item">Jornada {payload["jornada"]}</span>
<span class="bs-edition__item">{esc(venue_txt)}</span>
<span class="bs-edition__item bs-edition__item--status">{esc(status_label)}</span>
</div>
{grid}
{mentions}
{_footer_html()}
</div></div>"""

    return _page_html(title, description, canonical, league_logo, json_ld, body)


# ── Broadsheet de DATO CURIOSO (articles/generate.py:_run_stat) ────────────

def _stat_side_headline(protagonista, kind):
    """H2 de la columna del protagonista — determinista (mismo criterio que
    _team_headline: la cifra la compone Python, nunca Gemini). Adaptado al
    shape del kind: partido (1X2), blend en goles, delta en pp o probabilidad."""
    verb = STAT_KINDS[kind]["verbo"]
    if protagonista.get("tipo") == "partido":
        marc = protagonista.get("marcador")
        if marc:
            return (f'El modelo señala este <span>{protagonista["nombre"]}</span> como el '
                    f'que {verb}, con <span>{esc(marc)}</span> y un '
                    f'<span>{pct(protagonista["valor"])}</span> de probabilidad exacta')
        return (f'El modelo señala este <span>{protagonista["nombre"]}</span> como el '
                f'que {verb}, con <span>{pct(protagonista["p_local"])}</span> de victoria local, '
                f'<span>{pct(protagonista["p_empate"])}</span> de empate y '
                f'<span>{pct(protagonista["p_visita"])}</span> de victoria visitante')
    if STAT_KINDS[kind].get("fmt") in ("goles", "pp"):
        return (f'{protagonista["posicion"]}º en la tabla real, con '
                f'<span>{grounding.format_val(kind, protagonista["valor"])}</span> de {verb}')
    return (f'{protagonista["posicion"]}º en la tabla real, con el '
            f'<span>{pct(protagonista["valor"])}</span> de {verb}')


def _stat_rank_html(ranking, kind, dato_label):
    color = STAT_HEX.get(kind, "#f3b23f")
    base = max((abs(r["valor"] or 0) for r in ranking), default=0) or 1
    rows = []
    for i, r in enumerate(ranking, start=1):
        width = max(4, round(abs(r["valor"] or 0) / base * 100))
        logo = r.get("logo") or (r["local"].get("logo") if r.get("tipo") == "partido" else None)
        val = grounding.format_val(kind, r["valor"])
        if r.get("marcador"):
            val = f'{esc(r["marcador"])} · {val}'
        rows.append(
            '<div class="bs-rank__row">'
            f'<span class="bs-rank__pos">{i}.</span>'
            f'{team_avatar(logo, r["nombre"], _seed(r.get("id") or (r["local"].get("id") if r.get("tipo") == "partido" else None)), 22)}'
            f'<span class="bs-rank__name">{esc(r["nombre"])}</span>'
            f'<span class="bs-rank__bar"><span class="bs-rank__fill" style="width:{width}%;background:{color}"></span></span>'
            f'<b class="bs-rank__val">{val}</b></div>'
        )
    sim_n = f"{SIM_N_TABLE:,}".replace(",", ".")
    return (
        '<div class="bs-rankbox"><div class="bs-rankbox__head">'
        f'<span>{esc(dato_label)}</span><span class="bs-rankbox__n">{sim_n} simulaciones</span></div>'
        + "".join(rows) + '</div>'
    )


def _stat_methodology_html(payload):
    sim_n = f"{SIM_N_TABLE:,}".replace(",", ".")
    kind = payload["kind"]
    tipo = STAT_KINDS[kind]["tipo"]
    if tipo == "equipo":
        text = (
            f"El rating de fuerza de cada plantilla sale del blend de ataque y defensa de la "
            "temporada (goles a favor y en contra por partido, desviados de la media de la "
            f"liga) que el modelo ya usa para simular los {sim_n} escenarios de la temporada "
            "completa. Este dato no es una predicción de un resultado: es la lectura de una "
            "fuerza que el modelo calcula y aplica en cada partido que simula."
        )
    elif tipo == "jornada":
        text = (
            f"El modelo resuelve cada partido de la próxima jornada con el mismo rating de "
            "fuerza de ataque y defensa de cada plantilla con el que simula la temporada "
            f"completa ({sim_n} repeticiones). Este dato sale de la probabilidad de marcador "
            "(distribución de Poisson) que el modelo ya calcula para cada partido, no de una "
            "simulación extra."
        )
    elif tipo == "zona":
        up = kind == "subida_zona"
        direction = "subir" if up else "caer"
        above_below = "por encima" if up else "por debajo"
        text = (
            f"El modelo juega {sim_n} veces la temporada completa y en cada repetición ordena la "
            "tabla final. La banda actual de cada equipo es la que ocupa por su posición real "
            f"hoy; la probabilidad de {direction} de zona es la suma de las "
            f"frecuencias de todas las bandas {above_below} de la "
            "suya, dividida entre el total. No es una predicción de un partido: es la lectura "
            "de la tabla proyectada por el modelo."
        )
    elif tipo == "temporada":
        text = (
            f"El modelo juega {sim_n} veces la temporada completa y guarda la probabilidad de "
            "la mejor zona de cada equipo en el primer snapshot del curso. Este dato compara "
            "esa probabilidad inicial con la de hoy: la diferencia es la mejora acumulada, en "
            "puntos porcentuales, del equipo que más ha progresado según el modelo."
        )
    else:
        text = (
            f"El modelo juega {sim_n} veces la temporada completa. En cada repetición resuelve los "
            "partidos que quedan a partir del rating de fuerza de cada plantilla, suma los puntos y "
            "ordena la tabla final. La probabilidad de este dato es simplemente el recuento de "
            "repeticiones en las que un equipo termina en esa posición exacta de las "
            f"{payload['num_equipos']} que forman la tabla, dividido entre el total. No es una predicción "
            "sobre un partido concreto, sino la frecuencia con la que un escenario aparece cuando "
            "se repite la competición miles de veces."
        )
    return f'<div class="bs-note"><div class="bs-note__label">Cómo se calcula</div><p>{esc(text)}</p></div>'


def _split_chasers(text, perseguidores):
    """1 párrafo por perseguidor, en orden (contrato de writer._STAT_CHASERS_INSTR,
    mismo patrón que _split_briefs). Degrada a None si el recuento no cuadra."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paras) != len(perseguidores):
        return None
    return list(zip(perseguidores, paras))


def _chaser_html(t, text, kind):
    logo = t.get("logo") or (t["local"].get("logo") if t.get("tipo") == "partido" else None)
    seed = t.get("id") or (t["local"].get("id") if t.get("tipo") == "partido" else None)
    return (
        '<div class="bs-chaser">'
        f'<div class="bs-chaser__row">{team_avatar(logo, t["nombre"], _seed(seed), 24)}'
        f'<span class="bs-chaser__name">{esc(t["nombre"])}</span>'
        f'<b class="bs-chaser__val">{grounding.format_val(kind, t["valor"])}</b></div>'
        f'<p>{esc(text)}</p></div>'
    )


def _stat_facts_html(payload):
    p = payload["protagonista"]
    sim_n = f"{SIM_N_TABLE:,}".replace(",", ".")
    rows = [
        ("Dato", payload["dato_label"]),
    ]
    if p.get("tipo") == "partido":
        rows += [
            ("Partido", p["nombre"]),
            ("1X2", f'{pct(p["p_local"])} · {pct(p["p_empate"])} · {pct(p["p_visita"])}'),
        ]
        if p.get("marcador"):
            rows += [("Marcador", p["marcador"])]
    else:
        rows += [("Equipo", p["nombre"])]
    rows += [
        ("Valor", grounding.format_val(payload["kind"], p["valor"])),
        ("Anterior", grounding.format_val(payload["kind"], p["valor_antes"]) if p.get("valor_antes") is not None else "—"),
        ("Corte", payload["jornada_txt"]),
        ("Modelo", f"Monte Carlo · {sim_n} sim."),
    ]
    rows_html = "".join(f'<div class="bs-facts__row"><span>{esc(k)}</span><span>{esc(v)}</span></div>' for k, v in rows)
    return f'<div class="bs-facts"><div class="bs-facts__label">Ficha del dato</div>{rows_html}</div>'


def _stat_mentions_html(payload, league_logo, league_slug):
    chips = [f'<a href="/{league_slug}">{avatar(league_logo, payload["liga"], "#e11d48", 20)}{esc(payload["liga"])}</a>']
    refs = []
    for t in [payload["protagonista"]] + payload["perseguidores"]:
        if t.get("tipo") == "partido":
            refs += [t["local"], t["visitante"]]
        else:
            refs.append(t)
    for t in refs:
        color = COLOR_PALETTE[_seed(t.get("id")) % len(COLOR_PALETTE)]
        href = f'/equipo?id={t["id"]}&name={esc(t["nombre"])}&league={league_slug}'
        chips.append(f'<a href="{href}">{avatar(t.get("logo"), t["nombre"], color, 20)}{esc(t["nombre"])}</a>')
    return (
        '<div class="bs-mentions"><div class="bs-mentions__label">Equipos mencionados</div>'
        f'<div class="bs-mentions__list">{"".join(chips)}</div></div>'
    )


def render_stat_broadsheet(payload, protagonist_body, perseguidores_body, *,
                            league_slug, headline, teaser, league_logo, status_label="Publicado"):
    kind = payload["kind"]
    info = STAT_KINDS[kind]
    payload["jornada_txt"] = ("Próxima jornada" if info["tipo"] == "jornada"
                              else f'Jornada {payload["jornada"]}')
    protagonista, perseguidores = payload["protagonista"], payload["perseguidores"]
    fecha, hour = payload["fecha"], payload["hour"]
    picked_files = set()

    def pick_illo(variant):
        ill = illustration.pick(league_slug, fecha, f'stat-{kind}-{hour}-{variant}', avoid=picked_files)
        picked_files.add(ill["file"])
        return ill

    title = f'{headline} | PredictMotion'
    description = teaser
    canonical = SITE + url_for_stat(league_slug, fecha, hour, kind)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    json_ld = {
        "@context": "https://schema.org", "@type": "SportsArticle", "headline": title,
        "description": description, "datePublished": generated_at,
        "author": {"@type": "Organization", "name": "PredictMotion"},
        "publisher": {"@type": "Organization", "name": "PredictMotion",
                      "logo": {"@type": "ImageObject", "url": "https://predictmotion.com/media/twitter_profile.png"}},
        "about": {"@type": "SportsOrganization", "name": payload["liga"]},
        "url": canonical,
    }

    # split_explainer_paragraphs() es genérico (>=3 párrafos -> 2 + resto);
    # aquí reparte los 4 párrafos del protagonista en 2 para la columna
    # lateral y 2 para el cuerpo de la columna central.
    side_paras, body_paras = writer.split_explainer_paragraphs(protagonist_body)

    color = STAT_HEX.get(kind, "#f3b23f")
    if protagonista.get("tipo") == "partido":
        stats_rows = [
            (grounding.format_val(kind, protagonista["valor"]), payload["dato_label"]),
            (pct(protagonista["p_local"]), f'Victoria de {protagonista["local"]["nombre"]}'),
            (pct(protagonista["p_empate"]), "Empate"),
            (pct(protagonista["p_visita"]), f'Victoria de {protagonista["visitante"]["nombre"]}'),
        ]
    else:
        stats_rows = [(grounding.format_val(kind, protagonista["valor"]), payload["dato_label"])]
        if protagonista.get("prob_zona") is not None:
            stats_rows.append((pct(protagonista["prob_zona"]), protagonista["zona"]))
        if protagonista.get("rating_fuerza") is not None:
            stats_rows.append((signed(protagonista["rating_fuerza"]), "Rating de fuerza"))
    stats_html = "".join(
        f'<div class="bs-stats__row"><span class="bs-stats__value" style="color:{color}">{v}</span>'
        f'<span class="bs-stats__label">{esc(lbl)}</span></div>'
        for v, lbl in stats_rows
    )

    if protagonista.get("tipo") == "partido":
        team_block = (
            '<div class="bs-match-team bs-match-team--pair">'
            f'<span class="bs-match-team__side">{team_avatar(protagonista["local"].get("logo"), protagonista["local"]["nombre"], _seed(protagonista["local"].get("id")), 30)}'
            f'<span class="bs-match-team__name">{esc(protagonista["local"]["nombre"])}</span></span>'
            f'<span class="bs-match-team__vs">vs</span>'
            f'<span class="bs-match-team__side">{team_avatar(protagonista["visitante"].get("logo"), protagonista["visitante"]["nombre"], _seed(protagonista["visitante"].get("id")), 30)}'
            f'<span class="bs-match-team__name">{esc(protagonista["visitante"]["nombre"])}</span></span></div>'
        )
    else:
        team_block = (
            '<div class="bs-match-team">'
            f'{team_avatar(protagonista.get("logo"), protagonista["nombre"], _seed(protagonista.get("id")), 30)}'
            f'<span class="bs-match-team__name">{esc(protagonista["nombre"])}</span>'
            f'<span class="bs-match-team__meta">{protagonista["posicion"]}º · {protagonista["puntos"]} pts</span></div>'
        )

    left_col = (
        '<div class="bs-stat-side">'
        f'<div class="bs-section-label">{esc(info["eyebrow"])}</div>'
        + team_block +
        f'<h2>{_stat_side_headline(protagonista, kind)}</h2>'
        f'<div class="bs-stats">{stats_html}</div>'
        + _prose_html("\n\n".join(side_paras))
        + _illo_html(pick_illo("side"), "bs-illo bs-illo--fill", caption_cls="bs-illo__caption")
        + '</div>'
    )

    center_col = (
        '<div class="bs-col-main">'
        + _illo_html(pick_illo("cover"), "bs-cover", caption_cls="bs-cover__caption") +
        f'<div class="bs-main-label">{esc(info["eyebrow"])} · el dato del día</div>'
        f'<h2>{_highlight_teams(headline, [t["nombre"] for t in payload["ranking"]])}</h2>'
        f'<div class="bs-teaser"><p>{esc(teaser)}</p></div>'
        + _stat_rank_html(payload["ranking"], kind, payload["dato_label"])
        + _prose_html("\n\n".join(body_paras))
        + _stat_methodology_html(payload)
        + '</div>'
    )

    chasers_pairs = _split_chasers(perseguidores_body, perseguidores)
    chasers_html = ("".join(_chaser_html(t, txt, kind) for t, txt in chasers_pairs)
                     if chasers_pairs is not None else _prose_html(perseguidores_body))

    right_col = (
        '<div class="bs-stat-chasers">'
        '<div class="bs-section-label">Los perseguidores</div>'
        + chasers_html
        + _stat_facts_html(payload)
        + _illo_html(pick_illo("footer"), "bs-illo bs-illo--fill")
        + '</div>'
    )

    grid = f'<div class="bs-grid">{left_col}{center_col}{right_col}</div>'
    mentions = _stat_mentions_html(payload, league_logo, league_slug)

    body = f"""<div class="bs-page">
<a class="bs-back" href="/{league_slug}">← Volver a la clasificación</a>
<div class="bs-sheet">
{_masthead_html(f'{payload["liga"]} · El diario de las probabilidades')}
<div class="bs-edition">
<span class="bs-edition__item">Estadística</span>
<span class="bs-edition__item bs-edition__item--muted">{_fecha_label(fecha)}</span>
<span class="bs-edition__item">{esc(payload["jornada_txt"])}</span>
<span class="bs-edition__item">{esc(info["eyebrow"])}</span>
<span class="bs-edition__item bs-edition__item--status">{esc(status_label)}</span>
</div>
{grid}
{mentions}
{_footer_html()}
</div></div>"""

    return _page_html(title, description, canonical, league_logo, json_ld, body)
