"""HTML estático de artículos, reutilizando el esqueleto de seo/chrome.py
(mismo look de las páginas /equipos, /jornadas, /historico). Rutas de fichero
al estilo seo/links.py: hoja `articulos/<slug>.html`, hub `articulos/index.html`
— servidas por el try_files genérico de Caddy, sin tocar el Caddyfile.

Visual: mismo patrón que seo/render_table.py:_team_page (hero + stat-grid
dentro de una única .card, luego cards de prosa/enlaces) — nada nuevo en
chrome.CSS, solo composición distinta de los mismos bloques.
"""

from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from seo.chrome import crumbs, esc, page, stat_card, team_avatar
from seo.config import SITE
from seo.textutil import pct

from .writer import cronica_slug

_MADRID_TZ = ZoneInfo("Europe/Madrid")

_CRUMB_LABEL = {
    "recap_jornada": "Recap de jornada",
    "explicador_probabilidad": "Explicador",
    "carrera_titulo": "Carrera por el título",
    "cronica_partido": "Crónica",
    "previa_diaria": "Previa del día",
    "resumen_diario": "Resumen del día",
}


def article_url(slug):  return f"/articulos/{slug}"
def article_file(slug): return f"articulos/{slug}.html"
def hub_url():           return "/articulos"
def hub_file():           return "articulos/index.html"

# Vista previa privada (gateada por basic_auth en Caddy, ver CLAUDE.md
# "Preview privado de artículos") de lo que el pipeline genera y AÚN NO es
# público — draft sin --publish (el modo normal del cron), pending_review,
# flagged. Mismo nombre de carpeta que la ruta URL (preview-articulos/) para
# que el try_files genérico de Caddy la sirva sin reglas nuevas de rewrite;
# solo necesita el bloque de auth+noindex, ver Caddyfile del servidor.
def preview_article_url(slug):  return f"/preview-articulos/{slug}"
def preview_article_file(slug): return f"preview-articulos/{slug}.html"
def preview_hub_url():           return "/preview-articulos"
def preview_hub_file():           return "preview-articulos/index.html"


def _color(c):
    return c or "accent"


def _seed(team_id):
    try:
        return int(team_id)
    except (TypeError, ValueError):
        return 0


def _body_html(text):
    return "".join(
        f'<p class="lede">{esc(p.strip())}</p>'
        for p in text.split("\n\n") if p.strip()
    )


def _kickoff_label(iso):
    """'2026-08-16T18:00:00Z' -> '18:00' en hora de Madrid, o None si no
    parsea (el marcador simplemente no se pinta, no rompe la cabecera)."""
    if not iso:
        return None
    try:
        return (datetime.fromisoformat(iso.replace("Z", "+00:00"))
                .astimezone(_MADRID_TZ).strftime("%H:%M"))
    except ValueError:
        return None


def _win_prob_bar(win_prob, home_name, away_name):
    """Raya 1X2 con porcentajes — mismo componente `.winbar` que la home
    (assets/shell.css, ver home.js:winbarHTML), portado a los tokens de esta
    página. `win_prob` viene de grounding.py:_match_win_prob (mismo modelo de
    fuerza que /partido, sim_table._match_ph_pd); None -> sin raya, no se
    inventa una probabilidad plana."""
    if not win_prob:
        return ""
    h, d, a = win_prob["home"], win_prob["draw"], win_prob["away"]
    return (
        '<div class="winbar">'
        f'<div class="winbar__track"><span class="winbar__seg h" style="width:{h:.1f}%"></span>'
        f'<span class="winbar__seg d" style="width:{d:.1f}%"></span>'
        f'<span class="winbar__seg a" style="width:{a:.1f}%"></span></div>'
        f'<div class="winbar__legend"><b>{esc(home_name)} {pct(h)}</b>'
        f'<span class="mid">Empate {pct(d)}</span><b>{esc(away_name)} {pct(a)}</b></div></div>'
    )


def _match_card_body(local, visitante, *, liga=None, hora=None, resultado=None, win_prob=None):
    """Núcleo visual del 'match-hero' compartido por los 3 tipos que hablan
    de un partido — escudos a los lados (mismo `.hero-av`+`team_avatar` que
    el resto del artículo), y en el centro hora+competición (`resultado` no
    dado, pre-partido, con raya 1X2 opcional) o el marcador final + 'Final'
    (`resultado` dado, post-partido — nunca lleva raya 1X2: esa probabilidad
    ya no aplica). Sin `.card` ni enlace propios: los añade cada llamante
    (`_match_card` para previa/resumen; la crónica de un partido la mete
    directo en su propia `.card` junto al stat-grid, sin enlace — ya estás
    en esa página)."""
    if resultado is not None:
        mid = (f'<span class="kick">{resultado["local"]}–{resultado["visitante"]}</span>'
               '<span class="s">Final</span>')
        winbar = ""
    else:
        kick = _kickoff_label(hora)
        mid = (f'<span class="kick">{esc(kick)}</span>' if kick else "") + (
            f'<span class="s">{esc(liga)}</span>' if liga else "")
        winbar = _win_prob_bar(win_prob, local["nombre"], visitante["nombre"])
    row = (
        '<div class="match-hero__row">'
        f'<div class="match-hero__team"><div class="hero-av">'
        f'{team_avatar(local.get("logo"), local["nombre"], _seed(local.get("id")), 64)}</div>'
        f'<span class="name">{esc(local["nombre"])}</span></div>'
        f'<div class="match-hero__vs">{mid}</div>'
        f'<div class="match-hero__team"><div class="hero-av">'
        f'{team_avatar(visitante.get("logo"), visitante["nombre"], _seed(visitante.get("id")), 64)}</div>'
        f'<span class="name">{esc(visitante["nombre"])}</span></div>'
        '</div>'
    )
    return f'<div class="match-hero">{row}{winbar}</div>'


def _match_card(local, visitante, league_slug, event_id, **kw):
    """`_match_card_body` en su propia `.card`, enlazada a la CRÓNICA de ese
    partido (`/articulos/<liga>-cronica-<event_id>`, mismo slug que
    writer._article_slug) — el destino canónico tanto si aún no existe
    (previa, antes de jugarse: el enlace empieza a funcionar solo en cuanto
    se publica la crónica) como si ya existe (resumen, partido ya
    reportado); nunca un enlace de usar-y-tirar a otra vista."""
    card = f'<div class="card">{_match_card_body(local, visitante, **kw)}</div>'
    if not event_id:
        return card
    href = article_url(cronica_slug(league_slug, event_id))
    return f'<a class="comp-link" href="{esc(href)}">{card}</a>'


def _matches_body_html(text, partidos, builder):
    """Igual que _body_html, pero antepone builder(m) (una _match_card) a
    cada párrafo — previa_diaria/resumen_diario redactan un párrafo por
    partido, en el mismo orden que DATOS (ver
    writer.py:_INSTRUCTIONS['previa_diaria'/'resumen_diario']). Si el
    recuento no cuadra (Gemini no respetó el 1-párrafo-por-partido), degrada
    a una única card de texto sin cabeceras en vez de emparejar mal."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paras) != len(partidos):
        return f'<div class="card"><div class="card-pad">{_body_html(text)}</div></div>'
    out = []
    for p, m in zip(paras, partidos):
        out.append(builder(m))
        out.append(f'<div class="card"><div class="card-pad"><p class="lede">{esc(p)}</p></div></div>')
    return "".join(out)


def _hero(crests, heading, sub):
    """crests: lista de (logo, name, team_id) — 1 (recap/explainer/carrera)
    o 2 (crónica de partido)."""
    avs = "".join(f'<div class="hero-av">{team_avatar(logo, name, _seed(tid), 64)}</div>'
                 for logo, name, tid in crests)
    return (f'<div class="hero">{avs}<div class="hero-meta">'
            f'<div class="h">{esc(heading)}</div><div class="s">{esc(sub)}</div></div></div>')


def _stat_grid(cards):
    """cards: lista de (value, label, color|None)."""
    return f'<div class="stat-grid">{"".join(stat_card(v, l, _color(c)) for v, l, c in cards)}</div>'


# ── Hero + stat cards por tipo (los hechos ya vienen del payload de grounding;
# aquí solo se elige qué mostrar, nada se calcula de nuevo) ──────────────────

def _recap_visual(payload):
    l = payload["lider"]
    hero = _hero([(l.get("logo"), l["nombre"], l.get("id"))],
                l["nombre"], f'Líder · {payload["zona_principal"]}')
    cards = [(l["prob_zona_principal"], f'{l["nombre"]} · {payload["zona_principal"]}',
             payload.get("zona_principal_color"))]
    subidas = payload.get("mayores_subidas_probabilidad") or []
    bajadas = payload.get("mayores_bajadas_probabilidad") or []
    if subidas:
        m = subidas[0]
        cards.append((m["prob_actual"], f'{m["nombre"]} · sube', "green"))
    if bajadas:
        m = bajadas[0]
        cards.append((m["prob_actual"], f'{m["nombre"]} · baja', "red"))
    return hero, cards


def _explainer_visual(payload):
    hero = _hero([(payload.get("equipo_logo"), payload["equipo"], payload.get("equipo_id"))],
                payload["equipo"], f'{payload["posicion"]}º · {payload["puntos"]} pts')
    colores = payload.get("zona_colores") or {}
    zonas = payload.get("probabilidades_por_zona") or {}
    cards = [(v, k, colores.get(k)) for k, v in zonas.items()]
    return hero, cards


def _title_race_visual(payload):
    cands = payload.get("candidatos") or []
    if not cands:
        return "", []
    c = cands[0]
    hero = _hero([(c.get("logo"), c["nombre"], c.get("id"))],
                c["nombre"], f'Líder de la carrera · {pct(c["prob_titulo"])}')
    cards = [(x["prob_titulo"], x["nombre"], None)
             for x in cands if x.get("prob_titulo") is not None]
    return hero, cards


def _cronica_visual(payload):
    """Mismo `_match_card_body` que previa/resumen, en modo post-partido —
    antes era un `_hero()` de una línea de texto ('Local 2-1 Visitante'), sin
    enlazar (era la propia página de la crónica: enlazarse a sí misma no
    tiene sentido, así que se queda sin `.comp-link`, a diferencia de
    _match_card)."""
    l, v, r = payload["local"], payload["visitante"], payload["resultado"]
    body = _match_card_body(l, v, resultado=r)
    cards = [(t["prob_zona_actual"], f'{t["nombre"]} · {t["zona"]}', t.get("zona_color"))
             for t in (l, v) if t.get("prob_zona_actual") is not None]
    return body, cards


_VISUAL_BUILDERS = {
    "recap_jornada": _recap_visual,
    "explicador_probabilidad": _explainer_visual,
    "carrera_titulo": _title_race_visual,
    "cronica_partido": _cronica_visual,
}


def _match_pick(l, v):
    """Equipo más "en juego" de un partido: el que está cerca de un corte de
    zona real (mismo radio que teams_near_boundary); si ninguno lo está, el
    de mayor probabilidad. Un stat card por partido — no se recorta a un
    número fijo, así una jornada con muchos partidos los muestra todos."""
    if l.get("cerca_de_corte"):
        return l
    if v.get("cerca_de_corte"):
        return v
    return l if (l.get("prob_zona") or 0) >= (v.get("prob_zona") or 0) else v


def _previa_visual(payload):
    partidos = payload.get("partidos") or []
    crests, cards = [], []
    for p in partidos:
        l, v = p["local"], p["visitante"]
        crests.append((l.get("logo"), l["nombre"], l.get("id")))
        crests.append((v.get("logo"), v["nombre"], v.get("id")))
        pick = _match_pick(l, v)
        if pick.get("prob_zona") is not None:
            cards.append((pick["prob_zona"], f'{pick["nombre"]} · {pick["zona"]}',
                         pick.get("zona_color")))
    return crests, cards


def _resumen_visual(payload):
    """Mismo patrón que _previa_visual (fila de escudos + un stat card por
    partido, sin hero — puede haber varios resultados el mismo día), pero
    con los campos de un resultado YA jugado (prob_zona_actual/zona, los
    mismos que usa _cronica_visual) en vez de los de un partido futuro."""
    partidos = payload.get("partidos") or []
    crests, cards = [], []
    for p in partidos:
        l, v = p["local"], p["visitante"]
        crests.append((l.get("logo"), l["nombre"], l.get("id")))
        crests.append((v.get("logo"), v["nombre"], v.get("id")))
        for t in (l, v):
            if t.get("prob_zona_actual") is not None:
                cards.append((t["prob_zona_actual"], f'{t["nombre"]} · {t["zona"]}', t.get("zona_color")))
    return crests, cards


_NO_HERO_VISUALS = {
    "previa_diaria": ("Partidos de hoy", _previa_visual),
    "resumen_diario": ("Resultados de hoy", _resumen_visual),
}


# ── Equipos mencionados en el artículo (para el carrusel de escudos de abajo) ─

def _mentioned_teams(tipo, payload):
    """(id, nombre, logo) de cada equipo citado en el payload, deduplicados
    por id — nada se recalcula, es la misma lista de hechos que ya redactó
    Gemini, solo se leen los campos id/logo que grounding.py ya adjunta."""
    seen, out = set(), []

    def add(d, name_key="nombre", logo_key="logo", id_key="id"):
        if not d or not d.get(id_key) or d[id_key] in seen:
            return
        seen.add(d[id_key])
        out.append((d[id_key], d.get(name_key), d.get(logo_key)))

    if tipo == "recap_jornada":
        add(payload.get("lider"))
        for m in (payload.get("mayores_subidas_probabilidad") or []):
            add(m)
        for m in (payload.get("mayores_bajadas_probabilidad") or []):
            add(m)
    elif tipo == "explicador_probabilidad":
        add({"id": payload.get("equipo_id"), "nombre": payload.get("equipo"),
            "logo": payload.get("equipo_logo")})
        for n in (payload.get("vecinos_en_la_tabla") or []):
            add(n)
    elif tipo == "carrera_titulo":
        for c in (payload.get("candidatos") or []):
            add(c)
    elif tipo == "cronica_partido":
        add(payload.get("local"))
        add(payload.get("visitante"))
    elif tipo in ("previa_diaria", "resumen_diario"):
        for p in (payload.get("partidos") or []):
            add(p.get("local"))
            add(p.get("visitante"))
    return out


def _mentions_chips(league, league_logo, teams):
    """Chips de enlace, mismo componente `.chips`/`.chips a` que usa el resto
    del sitio (clasificación del footer, enlaces cruzados de equipo.html) —
    no un carrusel: son pocos equipos (2-8) y no hace falta deslizar. Variante
    `.chips-lg` (tap-target más grande, crece aún más en móvil): esta fila es
    la principal forma de navegar desde el artículo, así que tiene que ser
    cómoda de tocar con el dedo, no solo de hacer clic."""
    items = [f'<a href="{esc(league["dashboard"])}">'
            f'{team_avatar(league_logo, league["name"], 0, 26)}{esc(league["name"])}</a>']
    for tid, name, logo in teams:
        url = f'/equipo?id={tid}&name={quote(str(name), safe="")}&league={league["slug"]}'
        items.append(f'<a href="{esc(url)}">{team_avatar(logo, name, _seed(tid), 26)}{esc(name)}</a>')
    return f'<div class="chips chips-lg">{"".join(items)}</div>'


# ── Artículos recientes (carrusel "Seguir viendo…") ──────────────────────────

def _article_card_html(a, carousel=False, url_fn=article_url):
    cls = "comp-link carousel-item" if carousel else "comp-link"
    # `status`: solo lo llevan las tarjetas del hub de preview (draft/
    # pending_review/flagged) — el hub público solo lista publicados, así
    # que ahí el campo no está y no se pinta nada de más.
    badge = f' <span class="poschip">{esc(a["status"])}</span>' if a.get("status") else ""
    return (f'<a class="{cls}" href="{url_fn(a["slug"])}"><div class="card">'
            f'<div class="card-pad"><div class="comp-head"><div class="t">{esc(a["title"])}'
            f'<small>{esc(a["league_name"])}</small></div>{badge}</div>'
            f'<p class="comp-meta">{esc(a["meta_description"])}</p></div></div></a>')


# Script mínimo, sin dependencias, compartido por todos los .carousel-wrap de
# la página: el scroll nativo (touch/trackpad) ya funciona sin él — solo
# añade el botón "siguiente" y esconde el degradado/botón al llegar al final.
_CAROUSEL_SCRIPT = """<script>
document.querySelectorAll('.carousel-wrap').forEach(function(w){
  var c = w.querySelector('.carousel'), btn = w.querySelector('.carousel-nav');
  function sync(){
    var atEnd = c.scrollWidth <= c.clientWidth + 4 || c.scrollLeft + c.clientWidth >= c.scrollWidth - 4;
    w.classList.toggle('at-end', atEnd);
  }
  if (btn) btn.addEventListener('click', function(){
    c.scrollBy({left: c.clientWidth * 0.8, behavior: 'smooth'});
  });
  c.addEventListener('scroll', sync, {passive: true});
  sync();
});
</script>"""


def _article_carousel(cards):
    if not cards:
        return ""
    items = "".join(_article_card_html(a, carousel=True) for a in cards)
    return (f'<div class="carousel-wrap"><div class="carousel">{items}</div>'
            f'<button class="carousel-nav" type="button" aria-label="Ver más artículos">›</button>'
            f'</div>{_CAROUSEL_SCRIPT}')


def _sources_card(sources):
    """Atribución visible de las fuentes de Grounding with Google Search —
    mismo principio que la del agregador de noticias (news/): un dato externo
    se presenta con su fuente citada, nunca como afirmación propia sin más."""
    if not sources:
        return ""
    links = "".join(
        f'<a href="{esc(s["uri"])}" target="_blank" rel="noopener noreferrer nofollow">'
        f'{esc(s["title"])}</a>'
        for s in sources
    )
    return (f'<div class="card"><div class="card-pad"><div class="section-label">Fuentes</div>'
            f'<div class="chips">{links}</div></div></div>')


def render_article(article, league, logo=None, recent=None, preview=False):
    """`recent`: hasta 6-7 artículos ya publicados (cualquier liga), más
    recientes primero, EXCLUYENDO este — construidos por generate.py con la
    misma forma que usa render_hub.

    `preview=True`: renderiza a /preview-articulos en vez de /articulos (URL
    propia, noindex, sin `show_nav`/hub público) — la vista privada gateada
    por basic_auth en Caddy de un artículo aún no publicado (draft sin
    --publish, pending_review o flagged). Nada del contenido cambia, solo el
    namespace de URLs y el meta robots."""
    url_fn, file_fn, hub = (preview_article_url, preview_article_file, preview_hub_url()) \
        if preview else (article_url, article_file, hub_url())
    slug = article["slug"]
    payload = article["grounding_data"]
    tipo = article["type"]
    jornada = payload.get("jornada")
    crumb_label = _CRUMB_LABEL.get(tipo, "Artículo")

    lead_card = ""
    if tipo in _NO_HERO_VISUALS:
        label, builder = _NO_HERO_VISUALS[tipo]
        crests, cards = builder(payload)
        if crests:
            avs = "".join(team_avatar(logo_, name, _seed(tid), 32) for logo_, name, tid in crests)
            lead_card = (f'<div class="card"><div class="card-pad">'
                        f'<div class="section-label">{esc(label)}</div>'
                        f'<div class="chips">{avs}</div></div>'
                        + (_stat_grid(cards) if cards else "") + '</div>')
    else:
        builder = _VISUAL_BUILDERS.get(tipo)
        if builder:
            hero, cards = builder(payload)
            if hero:
                lead_card = (f'<div class="card">{hero}'
                            + (_stat_grid(cards) if cards else "") + '</div>')

    mentioned = _mentioned_teams(tipo, payload)
    seguir = ""
    if recent:
        seguir += (
            '<div class="card"><div class="card-pad"><div class="section-label">Seguir viendo…</div>'
            + _article_carousel(recent[:7]) + '</div></div>'
        )
    if mentioned:
        seguir += (
            '<div class="card"><div class="card-pad"><div class="section-label">Equipos mencionados</div>'
            + _mentions_chips(league, logo, mentioned) + '</div></div>'
        )

    if tipo == "previa_diaria":
        body_html = _matches_body_html(
            article["body"], payload.get("partidos") or [],
            lambda m: _match_card(m["local"], m["visitante"], league["slug"], m.get("event_id"),
                                  liga=league["name"], hora=m.get("hora"), win_prob=m.get("win_prob")))
    elif tipo == "resumen_diario":
        body_html = _matches_body_html(
            article["body"], payload.get("partidos") or [],
            lambda m: _match_card(m["local"], m["visitante"], league["slug"], m.get("event_id"),
                                  resultado=m["resultado"]))
    else:
        body_html = f'<div class="card"><div class="card-pad">{_body_html(article["body"])}</div></div>'

    body = (
        crumbs([("Inicio", league["dashboard"]),
                ("Artículos" + (" (preview)" if preview else ""), hub),
                (crumb_label, None)])
        + lead_card
        + body_html
        + _sources_card(article.get("sources"))
        + seguir
    )
    json_ld = {
        "@context": "https://schema.org", "@type": "SportsArticle",
        "headline": article["title"], "description": article["meta_description"],
        "datePublished": article["generated_at"],
        "author": {"@type": "Organization", "name": "PredictMotion"},
        "publisher": {"@type": "Organization", "name": "PredictMotion",
                      "logo": {"@type": "ImageObject", "url": f"{SITE}/media/twitter_profile.png"}},
        "about": {"@type": "SportsOrganization", "name": league["name"]},
        "url": SITE + url_fn(slug),
    }

    fecha = article["generated_at"][:10]
    badge_bits = ([f"Jornada <strong>{jornada}</strong>"] if jornada else []) + [
        esc(crumb_label), f"Actualizado {esc(fecha)}"]
    if preview:
        badge_bits.append(f"<strong>{esc(article['status'])}</strong>")
    badge = " · ".join(badge_bits)

    html = page(article["title"], article["meta_description"], url_fn(slug), body,
                heading=league["name"], logo=logo, badge=badge,
                json_ld=[json_ld], active_nav=league["dashboard"], og_type="article",
                show_nav=False, noindex=preview)
    return file_fn(slug), html


def render_hub(articles_meta):
    """articles_meta: [{slug, title, meta_description, league_name, generated_at}, ...]
    ya ordenados por fecha desc por el llamador (generate.py)."""
    cards = "".join(_article_card_html(a) for a in articles_meta)
    body = (crumbs([("Inicio", "/"), ("Artículos", None)])
            + f'<div class="comp-grid">{cards}</div>')
    title = "Artículos y análisis · PredictMotion"
    desc = ("Recaps de jornada, explicadores del modelo y análisis de la carrera por "
            "el título, generados a partir de las probabilidades reales de PredictMotion.")
    return hub_file(), page(title, desc, hub_url(), body, heading="Artículos")


def render_preview_hub(articles_meta):
    """Como render_hub, pero para /preview-articulos (gateada por basic_auth
    en Caddy — ver CLAUDE.md): TODO lo que el pipeline ha generado y aún no
    es público — draft sin --publish (el modo normal del cron), pending_review,
    flagged —, con su `status` como badge y enlazando a la vista preview de
    cada uno (no a la pública, que puede no existir todavía). `articles_meta`
    ya trae `status` (a diferencia de las del hub público, que solo lista
    publicados y no lo necesita)."""
    cards = "".join(_article_card_html(a, url_fn=preview_article_url) for a in articles_meta)
    empty = '<div class="card"><div class="card-pad">Nada en preview ahora mismo.</div></div>'
    body = (crumbs([("Inicio", "/"), ("Artículos (preview)", None)])
            + (f'<div class="comp-grid">{cards}</div>' if cards else empty))
    title = "Preview de artículos · PredictMotion"
    desc = "Vista privada de los artículos que el pipeline ha generado, pendientes de revisión o publicación."
    return preview_hub_file(), page(title, desc, preview_hub_url(), body,
                                    heading="Artículos (preview)", noindex=True)
