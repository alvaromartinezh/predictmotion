"""Pieza satírica suelta: articulos/sancho-palmeiras.html.

NO la genera ningún cron. Es un artículo escrito a mano (la broma de internet
del fichaje de Jadon Sancho por el Palmeiras, contada como si fuera verdad,
con fuentes inventadas) que reusa el broadsheet de articles/render.py para no
tener una segunda plantilla. Se ejecuta a mano una vez:

    python3 -m articles.satira_sancho

articulos/ está gitignored, así que el HTML publicado no vive en git — este
fichero es su fuente. Ver docs/articulos.md para las decisiones (noindex,
fuera del kiosco, aviso de sátira en el cuerpo).
"""
import json

from seo.chrome import esc
from seo.config import SITE

from . import illustration
from .config import ARTICLES_OUT_DIR
from .render import _ads_html, _footer_html, _illo_html, _masthead_html, _page_html

SLUG = "sancho-palmeiras"
CANON = f"{SITE}/articulos/{SLUG}"
TITLE = "Jadon Sancho firma por el Palmeiras hasta 2039 y cobrará parte del sueldo en açaí"
DESC = ("Sátira. El fichaje no existe, las fuentes tampoco: la crónica del rumor de internet "
        "más persistente del mercado, contada como si hubiera pasado de verdad.")

seen = set()
def illo(v):
    i = illustration.pick("satira", "2026-09-01", v, avoid=seen)
    seen.add(i["file"])
    return i

def prose(*paras):
    return '<div class="bs-prose">' + "".join(f"<p>{p}</p>" for p in paras) + "</div>"

def note(label, *paras):
    # .bs-note p tiene margin:0 (pensado para un solo párrafo) — separación inline
    # en los intermedios, para no tocar el CSS compartido ni bumpear _CSS_V.
    body = "".join(
        f'<p{"" if i == len(paras) - 1 else chr(32)+chr(115)+"tyle=\"margin-bottom:12px\""}>{t}</p>'
        for i, t in enumerate(paras))
    return f'<div class="bs-note"><div class="bs-note__label">{esc(label)}</div>{body}</div>' 

DISCLAIMER = note(
    "Aviso: esto es sátira",
    "Nada de lo que vas a leer ha ocurrido. <strong>Jadon Sancho no ha fichado por el Palmeiras</strong>, "
    "no lo ha fichado nunca y no hay ninguna negociación. Es un meme de internet que lleva años "
    "resucitando cada mercado.",
    "Todas las fuentes citadas en esta página son <strong>inventadas</strong>. Los medios, las radios, "
    "los sindicatos y el veterinario no existen. Tampoco el perro. Ojalá el perro.")

# ── Columna izquierda: las fuentes ───────────────────────────────────────
fuentes = f"""<div class="bs-col-explainer">
<div class="bs-section-label">Las fuentes</div>
<h2>Cinco medios que <span>no existen</span></h2>
{_illo_html(illo("explainer"), "bs-illo bs-illo--sm", caption_cls="bs-illo__caption")}
{prose(
 "<strong>Rádio Verdão AM 1130.</strong> Emite desde un garaje de Barra Funda. Su lema, repetido cada "
 "hora en punto: «aquí no se confirma nada, aquí se siente». No ha acertado un fichaje desde 1997, pero "
 "tampoco ha fallado ninguno: nunca dice de quién habla.",
 "<strong>Boletim do Verdão Independente.</strong> Portal de dos personas y un plugin de comentarios. "
 "Publicó la exclusiva a las 04:11 de la madrugada, en mayúsculas, sin párrafos y con siete signos de "
 "exclamación. Doce minutos después la retiró. Cuarenta minutos después la volvió a publicar con nueve.",
 "<strong>Gazeta Municipal de Itaquaquecetuba.</strong> Cubría alcantarillado. Ahora cubre mercado de "
 "fichajes. En su portada del lunes conviven el titular del siglo y un aviso de corte de agua en la "
 "Rua das Palmeiras, que ellos juran que es una coincidencia.",
 "<strong>Sindicato dos Contadores Esportivos do Estado de São Paulo.</strong> Boletín interno número "
 "412, página 7, bajo el titular «SOCORRO». Describe la operación como «matemáticamente posible pero "
 "espiritualmente desaconsejable». Desde entonces no coge el teléfono.",
 "<strong>O Diário Estaiado.</strong> Único medio que ha visto el contrato. Dice que son 47 páginas y "
 "que la cláusula del puente está en la 31, escrita a mano.")}
{note("Verificación",
      "PredictMotion ha contrastado las cinco fuentes entre sí. Las cinco se citan mutuamente. "
      "Ninguna cita a nadie más. El círculo es perfecto y por eso es tan convincente.")}
</div>"""

# ── Columna central: la historia ─────────────────────────────────────────
centro = f"""<div class="bs-col-main">
{_illo_html(illo("cover"), "bs-cover", caption_cls="bs-cover__caption")}
<div class="bs-main-label">Mercado de fichajes · Exclusiva que no lo es</div>
<h2>Jadon <span>Sancho</span> firma por el <span>Palmeiras</span> hasta 2039 y cobrará parte del sueldo en açaí</h2>
<div class="bs-teaser"><p>Estaba escrito en las estrellas, en la pared de un baño de la Estação Barra
Funda y en un mensaje de WhatsApp reenviado cuatrocientas mil veces. Ha ocurrido. No ha ocurrido. Pero
ha ocurrido.</p></div>
{DISCLAIMER}
{prose(
 "La negociación no se cerró por videollamada ni con intermediarios en Mónaco. Se cerró, según "
 "<em>Rádio Verdão AM 1130</em>, en un Nokia 3310 con la batería al 4 %, propiedad de un socio "
 "identificado únicamente como Seu Nilton, que llevaba desde 2021 pidiendo el fichaje en los comentarios "
 "de Instagram y a quien la directiva acabó dando credenciales de negociador «para que parara».",
 "El acuerdo se firmó en una servilleta de una pastelaria de Perdizes. La servilleta ya está plastificada "
 "y expuesta en el museo del club, junto a una nota que aclara que la mancha de la esquina es de pastel "
 "de carne y no de tinta.",
 "El reconocimiento médico se realizó, por un error de agenda que nadie ha querido explicar, en una "
 "clínica veterinaria de Itaquaquecetuba. El informe confirma que el jugador está en perfecto estado, no "
 "presenta pulgas y que «el rabo se encuentra dentro de parámetros normales para su raza». El veterinario "
 "declaró a la <em>Gazeta Municipal</em> que fue el paciente más grande que ha atendido, «sin contar "
 "aquel caballo».",
 "La afición reaccionó como se esperaba: seis mil personas se congregaron en Guarulhos a esperar un vuelo "
 "que, según la propia radio que lo anunció, no existía y nunca existió. Sancho llegó tres días después en "
 "autobús desde Campinas, sin que nadie se diera cuenta, sentado al fondo, junto a una señora que le "
 "ofreció un caramelo de menta.",
 "El primer entrenamiento duró once minutos. Se suspendió porque un perro entró al campo, cogió el balón "
 "y se negó a devolverlo. El perro ya tiene nombre, cuenta abierta y noventa mil seguidores. Está en "
 "negociaciones para ser mascota oficial y exige la misma estructura salarial que Sancho, açaí incluido.",
 "El debut estaba previsto para el domingo. Sigue previsto para el domingo. El balón sigue con el perro.")}
{note("Lectura del modelo",
      "El modelo de PredictMotion no ha sido consultado para esta pieza y agradece que no se le "
      "involucre. Su única aportación al asunto es recordar que la probabilidad de este fichaje, "
      "calculada con cualquier método conocido, es exactamente cero — y que llevamos cuatro mercados "
      "explicándolo sin que sirva de nada.")}
</div>"""

# ── Columna derecha: cláusulas y dinero ──────────────────────────────────
lado = f"""<div class="bs-col-side">
<div class="bs-section-label">La estructura económica</div>
<div class="bs-stats">
<div class="bs-stats__row"><span class="bs-stats__value">60 %</span><span class="bs-stats__label">en reales, como una persona normal</span></div>
<div class="bs-stats__row"><span class="bs-stats__value">25 %</span><span class="bs-stats__label">en açaí, indexado al kilo en la Zona Cerealista</span></div>
<div class="bs-stats__row"><span class="bs-stats__value">15 %</span><span class="bs-stats__label">de un canal de YouTube que el club aún no ha creado</span></div>
<div class="bs-stats__row"><span class="bs-stats__value">13,5</span><span class="bs-stats__label">años de contrato (hasta junio de 2039)</span></div>
</div>
<div class="bs-side-brief">
<h3>Las <span>cláusulas</span></h3>
<p><strong>1.</strong> No podrá cruzar la Ponte Estaiada en dirección sur los martes. Ninguna de las
partes ha explicado por qué. Al preguntar, la directiva respondió: «usted ya sabe por qué».</p>
<p><strong>2.</strong> Rescisión: 900 millones de euros <em>o</em> un contenedor de guaraná, a elección
del club comprador.</p>
<p><strong>3.</strong> Obligación de aparecer una vez al mes en el programa de madrugada
<em>Papo de Boleiro com o Zezinho</em> a explicar qué es la Premier League.</p>
<p><strong>4.</strong> Si el Palmeiras gana la Libertadores, el jugador pasa a llamarse legalmente
<strong>Jadinho</strong>. El trámite ya está preaprobado en el registro civil.</p>
</div>
{_illo_html(illo("footer"), "bs-illo bs-illo--footer", caption_cls="bs-illo__caption")}
<div class="bs-side-brief">
<h3>Por qué <span>vuelve cada año</span></h3>
<p>El rumor no tiene origen conocido. No hay un tuit cero, no hay un periodista que lo lanzara, no hay
un audio filtrado. Simplemente existe, como el viento.</p>
<p>Cada ventana de fichajes alguien lo resucita, cada vez con un detalle nuevo, y cada vez hay alguien
que se lo cree lo justo para reenviarlo. Ese es el chiste entero: el rumor es más sólido que la mayoría
de fichajes reales porque nunca puede desmentirse del todo.</p>
<p>Esta página es, hasta donde sabemos, el desmentido más largo que se le ha dedicado. Tampoco servirá.</p>
</div>
</div>"""

body = f"""<div class="bs-page">
<a class="bs-back" href="/kiosco">← Volver al kiosco</a>
<div class="bs-sheet">
{_masthead_html('Mercado · El diario de las probabilidades')}
<div class="bs-edition">
<span class="bs-edition__item">Sátira</span>
<span class="bs-edition__item bs-edition__item--muted">1 de septiembre de 2026</span>
<span class="bs-edition__item">Fichaje inexistente</span>
<span class="bs-edition__item">Fuentes inventadas</span>
<span class="bs-edition__item bs-edition__item--status">FALSO</span>
</div>
<div class="bs-grid">{fuentes}{centro}{lado}</div>
{_ads_html()}
{_footer_html()}
</div></div>"""

json_ld = {
    "@context": "https://schema.org", "@type": "SatiricalArticle", "headline": TITLE,
    "description": DESC, "datePublished": "2026-09-01T12:00:00Z",
    "author": {"@type": "Organization", "name": "PredictMotion"},
    "publisher": {"@type": "Organization", "name": "PredictMotion",
                  "logo": {"@type": "ImageObject", "url": f"{SITE}/media/logo.jpeg"}},
    "url": CANON,
}

html = _page_html(TITLE + " | PredictMotion", DESC, CANON, None, json_ld, body)
html = html.replace('content="index, follow', 'content="noindex, follow')
out = ARTICLES_OUT_DIR / f"{SLUG}.html"
out.write_text(html, encoding="utf-8")
print("escrito", out, len(html), "bytes")
assert "noindex" in html and "esto es sátira" in html and "bs-grid" in html
