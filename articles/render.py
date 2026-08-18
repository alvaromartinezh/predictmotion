"""HTML del broadsheet diario de Hypermotion.

Página autónoma (no usa seo/chrome.py:page() — paleta/tipografía distintas,
ver assets/articles-broadsheet.css) que combina dos piezas generadas por
writer.py: el resumen de los partidos del día (un brief por partido) y un
explicador del equipo más destacado de la jornada.
"""

import json
from datetime import date, datetime, timezone

from seo.chrome import COLOR_PALETTE, GTM_BODY, GTM_HEAD, avatar, esc, team_avatar
from seo.config import SITE
from seo.textutil import pct, signed

from . import illustration

_CSS_V = "5"
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
ZONE_HEX = {"ascenso": "#2ec98a", "playoff": "#f3b23f", "descenso": "#ff556b"}


def slug_for(fecha):
    return f"hypermotion-resumen-{fecha}"


def url_for(fecha):
    return f"/articulos/{slug_for(fecha)}"


def file_for(fecha):
    return f"articulos/{slug_for(fecha)}.html"


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


def _delta(actual, antes):
    if actual is None or antes is None:
        return "", ""
    d = actual - antes
    if abs(d) < 0.05:
        return "sin cambio", "bs-delta-eq"
    return signed(d) + " pp", ("bs-delta-up" if d > 0 else "bs-delta-down")


def _zone_block(t, size_cls=""):
    if t is None or t.get("prob_zona_actual") is None:
        return ""
    color = ZONE_HEX.get(t.get("zona_key"), "#66789c")
    delta_txt, delta_cls = _delta(t["prob_zona_actual"], t.get("prob_zona_antes_del_partido"))
    delta_html = f'<span class="{delta_cls}">{esc(delta_txt)}</span>' if delta_txt else ""
    cls = "bs-zone" + (f" {size_cls}" if size_cls else "")
    return (f'<div class="{cls}" style="border-left-color:{color}">'
            f'<div class="bs-zone__row">'
            f'<span class="bs-zone__team">{esc(t["nombre"])}</span>'
            f'<b class="bs-zone__val">{pct(t["prob_zona_actual"])}</b>'
            f'{delta_html}</div>'
            f'<div class="bs-zone__label">{esc(t["zona"])}</div></div>')


def _match_head(m, size=20):
    l, v, r = m["local"], m["visitante"], m["resultado"]
    inner = (
        f'{team_avatar(l.get("logo"), l["nombre"], _seed(l.get("id")), size)}'
        f'<span class="bs-brief__name">{esc(l["nombre"])}</span>'
        f'<b class="bs-brief__score">{r["local"]}–{r["visitante"]}</b>'
        f'<span class="bs-brief__name bs-brief__name--away">{esc(v["nombre"])}</span>'
        f'{team_avatar(v.get("logo"), v["nombre"], _seed(v.get("id")), size)}'
    )
    if m.get("event_id"):
        href = f'/partido?league=hypermotion&id={m["event_id"]}'
        return f'<a class="bs-brief__head" href="{esc(href)}">{inner}</a>'
    return f'<div class="bs-brief__head">{inner}</div>'


def _brief_html(m, text):
    zones = _zone_block(m["local"]) + _zone_block(m["visitante"])
    return f'<div class="bs-brief">{_match_head(m)}<p>{esc(text)}</p>{zones}</div>'


def _side_brief_html(m, text):
    l, v, r = m["local"], m["visitante"], m["resultado"]
    href = f'/partido?league=hypermotion&id={m["event_id"]}' if m.get("event_id") else None
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


def _illo_html(fecha, variant, cls, caption_cls):
    ill = illustration.pick(fecha, variant)
    return (f'<figure class="{cls}">'
            f'<img src="{illustration.url(ill)}" alt="" loading="lazy">'
            f'<figcaption class="{caption_cls}">{esc(ill["credit"])} · {esc(ill["source"])}</figcaption>'
            f'</figure>')


def _mentions_html(payload_resumen, league_name, league_logo):
    seen, chips = set(), []
    chips.append(f'<a href="/hypermotion">{avatar(league_logo, league_name, "#e11d48", 20)}{esc(league_name)}</a>')
    for m in payload_resumen["partidos"]:
        for t in (m["local"], m["visitante"]):
            if t["id"] in seen:
                continue
            seen.add(t["id"])
            color = COLOR_PALETTE[_seed(t["id"]) % len(COLOR_PALETTE)]
            href = f'/equipo?id={t["id"]}&name={esc(t["nombre"])}&league=hypermotion'
            chips.append(f'<a href="{href}">{avatar(t.get("logo"), t["nombre"], color, 20)}{esc(t["nombre"])}</a>')
    return (
        '<div class="bs-mentions"><div class="bs-mentions__label">Equipos mencionados</div>'
        f'<div class="bs-mentions__list">{"".join(chips)}</div></div>'
    )


def render_broadsheet(payload_resumen, resumen_body, payload_explainer, explainer_body,
                       *, fecha, league_logo, status_label="Publicado"):
    partidos = payload_resumen["partidos"]
    n = len(partidos)
    title = f'Resumen del día en {payload_resumen["liga"]}: {n} {"partido" if n == 1 else "partidos"} | PredictMotion'
    description = (f'Cómo han quedado hoy los {n} {"partido" if n == 1 else "partidos"} de '
                    f'{payload_resumen["liga"]} y cómo cambian las probabilidades de zona según el modelo de PredictMotion.')
    canonical = SITE + url_for(fecha)
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
    ex_paras = [p.strip() for p in explainer_body.split("\n\n") if p.strip()]
    side_paras, note_paras = (ex_paras[:2], ex_paras[2:]) if len(ex_paras) >= 3 else (ex_paras, [])
    zonas = payload_explainer["probabilidades_por_zona"]
    top_zona, top_val = max(zonas.items(), key=lambda kv: kv[1] or 0)
    ex_headline = f'El modelo da al {esc(payload_explainer["equipo"])} un <span>{pct(top_val)}</span> de {esc(top_zona.lower())}'

    ZONE_ORDER = [("Ascenso directo", "#2ec98a"), ("Play-off de ascenso", "#f3b23f"), ("Descenso", "#ff556b")]
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
        _illo_html(fecha, "explainer", "bs-illo bs-illo--sm", "bs-illo__caption") +
        '</div>'
    )

    # ── Resumen del día (columna central) ──
    pairs = _split_briefs(resumen_body, partidos)
    if pairs is None:
        lead_html, side_html = _prose_html(resumen_body), ""
    else:
        lead_pairs, side_pairs = pairs[:2], pairs[2:]
        lead_html = "".join(_brief_html(m, t) for m, t in lead_pairs)
        side_html = "".join(_side_brief_html(m, t) for m, t in side_pairs)

    note_html = ""
    if note_paras:
        note_html = ('<div class="bs-note"><div class="bs-note__label">Nota del modelo</div>'
                     f'<p>{esc(" ".join(note_paras))}</p></div>')

    main_col = (
        '<div class="bs-col-main">'
        + _illo_html(fecha, "cover", "bs-cover", "bs-cover__caption") +
        '<div class="bs-main-label">Resumen del día</div>'
        f'<h2>Resumen del día en {esc(payload_resumen["liga"])}: <span>{n} {"partido" if n == 1 else "partidos"}</span></h2>'
        f'<div class="bs-teaser"><p>{esc(_teaser(partidos))}</p></div>'
        + lead_html + note_html +
        '</div>'
    )

    side_col = ""
    if side_html:
        side_col = (
            '<div class="bs-col-side">'
            '<div class="bs-section-label">Más resultados</div>'
            + side_html +
            _illo_html(fecha, "footer", "bs-illo bs-illo--footer", "bs-illo__caption") +
            '</div>'
        )

    grid = f'<div class="bs-grid">{explainer_col}{main_col}{side_col}</div>'
    mentions = _mentions_html(payload_resumen, payload_resumen["liga"], league_logo)

    body = f"""<div class="bs-page">
<a class="bs-back" href="/hypermotion">← Volver a la clasificación</a>
<div class="bs-sheet">
<div class="bs-masthead">
<div class="bs-masthead__kicker"><span>Simulación Monte Carlo</span><span>Datos oficiales · ESPN</span></div>
<div class="bs-masthead__title"><span class="bs-masthead__dot"></span>
<h1>Predict<span>Motion</span></h1></div>
<div class="bs-masthead__tagline">{esc(payload_resumen["liga"])} · El diario de las probabilidades</div>
</div>
<div class="bs-edition">
<span class="bs-edition__item">Edición diaria</span>
<span class="bs-edition__item bs-edition__item--muted">{_fecha_label(fecha)}</span>
<span class="bs-edition__item">Jornada {payload_resumen["jornada"]}</span>
<span class="bs-edition__item">{n} {"partido" if n == 1 else "partidos"}</span>
<span class="bs-edition__item bs-edition__item--status">{esc(status_label)}</span>
</div>
{grid}
{mentions}
<div class="bs-footer">
<span>© 2025 PredictMotion · Todos los derechos reservados</span>
<a href="/privacy">Privacidad</a>
</div>
</div></div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=1180">
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
