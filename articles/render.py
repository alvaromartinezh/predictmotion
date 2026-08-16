"""HTML estático de artículos, reutilizando el esqueleto de seo/chrome.py
(mismo look de las páginas /equipos, /jornadas, /historico). Rutas de fichero
al estilo seo/links.py: hoja `articulos/<slug>.html`, hub `articulos/index.html`
— servidas por el try_files genérico de Caddy, sin tocar el Caddyfile.
"""

from seo.chrome import crumbs, esc, page
from seo.config import SITE

_CRUMB_LABEL = {
    "recap_jornada": "Recap de jornada",
    "explicador_probabilidad": "Explicador",
    "carrera_titulo": "Carrera por el título",
}


def article_url(slug):  return f"/articulos/{slug}"
def article_file(slug): return f"articulos/{slug}.html"
def hub_url():           return "/articulos"
def hub_file():           return "articulos/index.html"


def _body_html(text):
    return "".join(
        f'<p class="lede">{esc(p.strip())}</p>'
        for p in text.split("\n\n") if p.strip()
    )


def render_article(article, league, logo=None):
    slug = article["slug"]
    payload = article["grounding_data"]
    jornada = payload.get("jornada")
    crumb_label = _CRUMB_LABEL.get(article["type"], "Artículo")

    body = (
        crumbs([("Inicio", league["dashboard"]),
                ("Artículos", hub_url()),
                (crumb_label, None)])
        + f'<div class="card"><div class="card-pad">{_body_html(article["body"])}</div></div>'
        + '<div class="card"><div class="card-pad"><div class="section-label">Más</div>'
        + f'<div class="chips"><a href="{league["dashboard"]}">Clasificación en vivo de '
        + f'{esc(league["name"])}</a><a href="{hub_url()}">Más artículos</a></div></div></div>'
    )
    json_ld = {
        "@context": "https://schema.org", "@type": "SportsArticle",
        "headline": article["title"], "description": article["meta_description"],
        "datePublished": article["generated_at"],
        "author": {"@type": "Organization", "name": "PredictMotion"},
        "publisher": {"@type": "Organization", "name": "PredictMotion",
                      "logo": {"@type": "ImageObject", "url": f"{SITE}/media/twitter_profile.png"}},
        "about": {"@type": "SportsOrganization", "name": league["name"]},
        "url": SITE + article_url(slug),
    }
    badge = f"Jornada <strong>{jornada}</strong>" if jornada else None
    html = page(article["title"], article["meta_description"], article_url(slug), body,
                heading=league["name"], logo=logo, badge=badge,
                json_ld=[json_ld], active_nav=league["dashboard"], og_type="article")
    return article_file(slug), html


def render_hub(articles_meta):
    """articles_meta: [{slug, title, meta_description, league_name, generated_at}, ...]
    ya ordenados por fecha desc por el llamador (generate.py)."""
    cards = ""
    for a in articles_meta:
        cards += (
            f'<a class="comp-link" href="{article_url(a["slug"])}"><div class="card">'
            f'<div class="card-pad"><div class="comp-head"><div class="t">{esc(a["title"])}'
            f'<small>{esc(a["league_name"])}</small></div></div>'
            f'<p class="comp-meta">{esc(a["meta_description"])}</p></div></div></a>'
        )
    body = (crumbs([("Inicio", "/"), ("Artículos", None)])
            + f'<div class="comp-grid">{cards}</div>')
    title = "Artículos y análisis · PredictMotion"
    desc = ("Recaps de jornada, explicadores del modelo y análisis de la carrera por "
            "el título, generados a partir de las probabilidades reales de PredictMotion.")
    return hub_file(), page(title, desc, hub_url(), body, heading="Artículos")
