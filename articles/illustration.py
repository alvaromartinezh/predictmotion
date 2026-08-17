"""Banco de ilustraciones SVG dibujadas a mano para las páginas de artículo.

18 SUJETOS × 4 FONDOS = 72 composiciones (71 tras la lista de exclusión), todas
trazo puro sin relleno, en un lienzo 400×300. Se compone fondo + sujeto y se
INCRUSTA el `<svg>` en el HTML del artículo (no es un data-URI en el CSS como
los iconos de assets/articles-editorial.css): 72 combinaciones en la hoja
serían ~144 KB en CADA página, y además un data-URI es un documento aparte que
no hereda el cascade — por eso los iconos tienen el color "horneado" y estas
ilustraciones sí pueden usar `currentColor`.

CONTRATO GEOMÉTRICO (romperlo descuadra las 72 de golpe):
  · El horizonte va SIEMPRE en y=155 en los 4 fondos. Lo que cambia por fondo
    es la arquitectura por encima (cubierta, grada, cielo, clima), nunca la
    altura del horizonte — así cualquier sujeto vale con cualquier fondo sin
    retocarlo.
  · El sujeto vive en la caja x[56,344] · y[158,278], apoyado en la base
    y=278. Puede sacar por encima del horizonte trazos FINOS y de poca
    opacidad (rayos, vientos, mástiles), nunca masa sólida.
  · Un sujeto llena el panel con DIAGONALES (patas abiertas, tirantes, brazos
    en voladizo), no estirándose hasta ser un rectángulo del tamaño del
    marco: un rectángulo a sangre choca con el borde del panel y además tapa
    la grada, con lo que los 4 fondos dejan de distinguirse.

SELECCIÓN: `pick()` es una función PURA de (slug, tipo, fecha DEL ARTÍCULO) y
usa `hashlib.md5` EXPLÍCITO. Nunca `hash()`: el hash de un str lleva sal
aleatoria por proceso (PYTHONHASHSEED), así que el cron de 3 h le cambiaría el
dibujo a cada artículo en cada pasada, en producción y sin que fallara nada.
Los porqués de cada pieza están en los docstrings de `_digest` y `pick` y en
los comentarios de FAMILIES / BLOCKED / TYPE_SALT.

AÑADIR UN SUJETO NUEVO:
  1. Dibujarlo respetando el contrato geométrico de arriba (los tres puntos,
     no solo la caja: el de las diagonales es el que más se olvida).
  2. Comprobarlo contra los 4 fondos Y contra los sujetos que ya existen — a
     tamaño miniatura los parecidos se ven y a tamaño hero no. Si sale un par
     que se confunde, anotarlo en FAMILIES (máximo 2 por familia).
  3. `python3 -m articles.test_illustration`.
  4. Ojo: al derivarse el índice de `sorted()`, un sujeto nuevo reordena y
     cambia la ilustración de los artículos YA generados. Es churn cosmético,
     no un fallo (ver la nota `ponytail:` sobre SUBJECT_NAMES).

DÓNDE SE PINTA: `render.render_article` lo mete entre el titular y el lead
card (titular -> grabado -> datos, orden de periódico). El CSS que lo limita
está en assets/articles-editorial.css (`.illo`), con su propio comentario
sobre por qué lleva max-width y por qué el 4:3 no se puede recortar.

Uso: `illustration.svg(slug, tipo, fecha_iso)` -> markup listo para incrustar.
"""

import hashlib
import math
from datetime import date

VIEWBOX = "0 0 400 300"

# ── FONDOS (capa 0) ─────────────────────────────────────────────────────
# catedral: tribuna de dos anillos + cercha alta · terraza: grada baja de pie,
# pueblo y colinas · lluvia: cubierta en voladizo curva + aguacero ·
# noche: dos torres de focos, luna, grada en sombra.
BACKDROPS = {
    "catedral":
        "<g stroke-width=\".8\" opacity=\".16\"><path d=\"M12 30h376M12 46h376M12 62h376\"/></g><path d"
        "=\"M12 92h376v14H12z\" stroke-width=\"2\"/><g stroke-width=\".9\" opacity=\".5\"><path d=\"M59 92"
        "v14M106 92v14M153 92v14M200 92v14M247 92v14M294 92v14M341 92v14\"/><path d=\"M12 92l47 14M"
        "59 92l47 14M106 92l47 14M153 92l47 14M200 92l47 14M247 92l47 14M294 92l47 14M341 92l47 1"
        "4\"/></g><path d=\"M12 106h376v26H12z\" stroke-width=\"1.7\"/><g stroke-width=\".7\" opacity=\"."
        "4\"><path d=\"M12 114h376M12 122h376\"/><path d=\"M36 106v26M60 106v26M84 106v26M108 106v26M"
        "132 106v26M156 106v26M180 106v26M204 106v26M228 106v26M252 106v26M276 106v26M300 106v26M"
        "324 106v26M348 106v26M372 106v26\"/></g><path d=\"M12 132h376v23H12z\" stroke-width=\"1.7\"/>"
        "<g stroke-width=\".7\" opacity=\".4\"><path d=\"M12 140h376M12 148h376\"/><path d=\"M48 132v23M"
        "96 132v23M144 132v23M192 132v23M240 132v23M288 132v23M336 132v23\"/></g><path d=\"M12 155h"
        "376v133H12z\" stroke-width=\"1.7\"/><g stroke-width=\".75\" opacity=\".26\"><path d=\"M12 196h37"
        "6M12 236h376M12 268h376\"/><path d=\"M80 288l40-133M180 288l14-133M260 288l-14-133M330 288"
        "l-40-133\"/></g>",
    "lluvia":
        "<g stroke-width=\".8\" opacity=\".28\"><path d=\"M30 18l-9 26M70 12l-9 26M110 24l-9 26M150 14"
        "l-9 26M190 26l-9 26M230 16l-9 26M270 22l-9 26M310 12l-9 26M350 24l-9 26M50 50l-9 26M90 5"
        "6l-9 26M130 46l-9 26M170 58l-9 26M210 48l-9 26M250 60l-9 26M290 50l-9 26M330 56l-9 26M37"
        "0 46l-9 26M24 156l-9 26M64 168l-9 26M104 158l-9 26M144 170l-9 26M184 160l-9 26M224 172l-"
        "9 26M264 162l-9 26M304 174l-9 26M344 164l-9 26M44 214l-9 26M124 216l-9 26M204 218l-9 26M"
        "284 220l-9 26M364 214l-9 26\"/></g><path d=\"M12 128q188-76 376 0\" stroke-width=\"2.2\"/><pa"
        "th d=\"M12 140q188-76 376 0\" stroke-width=\"1.3\" opacity=\".7\"/><g stroke-width=\".9\" opacit"
        "y=\".5\"><path d=\"M60 111v12M110 99v12M160 92v12M210 90v12M260 94v12M310 103v12M360 118v12"
        "\"/></g><g stroke-width=\".85\" opacity=\".45\"><path d=\"M12 128l48 24M60 111l50 20M110 99l50"
        " 16M160 92l50 12M210 90l50 14M260 94l50 18M310 103l50 24\"/></g><path d=\"M12 140h376v15H1"
        "2z\" stroke-width=\"1.7\"/><g stroke-width=\".7\" opacity=\".38\"><path d=\"M12 148h376\"/><path "
        "d=\"M44 140v15M76 140v15M108 140v15M140 140v15M172 140v15M204 140v15M236 140v15M268 140v1"
        "5M300 140v15M332 140v15M364 140v15\"/></g><path d=\"M12 155h376v133H12z\" stroke-width=\"1.7"
        "\"/><g stroke-width=\".75\" opacity=\".22\"><path d=\"M12 186h376M12 216h376M12 246h376M12 274"
        "h376\"/></g><g stroke-width=\"1.1\" opacity=\".3\"><path d=\"M60 196v14M148 226v16M236 200v14M"
        "320 250v16M104 262v14M280 176v12\"/></g>",
    "noche":
        "<g stroke-width=\"1.5\"><circle cx=\"238\" cy=\"42\" r=\"19\"/></g><g stroke-width=\".7\" opacity="
        "\".32\"><path d=\"M225 32h26M221 42h33M222 52h30M229 60h18\"/></g><g stroke-width=\"1\" opacit"
        "y=\".5\"><path d=\"M120 30v6M117 33h6M180 22v6M177 25h6M232 62v6M229 65h6M148 74v5M145.5 76"
        ".5h5\"/></g><g stroke-width=\"1.7\"><path d=\"M34 130V62h40v68M326 130V62h40v68\"/></g><g str"
        "oke-width=\".85\" opacity=\".6\"><path d=\"M34 80h40M34 98h40M34 116h40M54 62v68M34 62l40 18M"
        "74 62l-40 18M34 80l40 18M74 80l-40 18M34 98l40 18M74 98l-40 18M34 116l40 14M74 116l-40 1"
        "4\"/><path d=\"M326 80h40M326 98h40M326 116h40M346 62v68M326 62l40 18M366 62l-40 18M326 80"
        "l40 18M366 80l-40 18M326 98l40 18M366 98l-40 18M326 116l40 14M366 116l-40 14\"/></g><g st"
        "roke-width=\"1.6\"><path d=\"M28 62h52V44H28zM320 62h52V44h-52z\"/></g><g stroke-width=\".9\" "
        "opacity=\".8\"><circle cx=\"40\" cy=\"53\" r=\"3.2\"/><circle cx=\"54\" cy=\"53\" r=\"3.2\"/><circle c"
        "x=\"68\" cy=\"53\" r=\"3.2\"/><circle cx=\"332\" cy=\"53\" r=\"3.2\"/><circle cx=\"346\" cy=\"53\" r=\"3."
        "2\"/><circle cx=\"360\" cy=\"53\" r=\"3.2\"/></g><g stroke-width=\".9\" opacity=\".2\"><path d=\"M84"
        " 58l122 76M84 68l104 82M316 58L194 134M316 68L212 150\"/></g><path d=\"M12 126h376v29H12z\""
        " stroke-width=\"1.7\"/><g stroke-width=\".7\" opacity=\".28\"><path d=\"M12 136h376M12 146h376\""
        "/><path d=\"M100 126v29M140 126v29M180 126v29M220 126v29M260 126v29M300 126v29\"/></g><pat"
        "h d=\"M12 155h376v133H12z\" stroke-width=\"1.7\"/><g stroke-width=\".75\" opacity=\".2\"><path d"
        "=\"M12 210h376M12 254h376M120 288l36-133M290 288l-36-133\"/></g>",
    "terraza":
        "<g stroke-width=\"1.6\"><circle cx=\"72\" cy=\"52\" r=\"19\"/></g><g stroke-width=\".8\" opacity=\""
        ".38\"><path d=\"M72 24v-8M72 80v8M44 52h-8M100 52h8M52 32l-6-6M92 72l6 6M92 32l6-6M52 72l-"
        "6 6\"/></g><g stroke-width=\"1.1\" opacity=\".5\"><path d=\"M12 134q31-28 62 0t62 0t62 0t62 0t"
        "62 0t62 0H388\"/></g><g stroke-width=\"1\" opacity=\".45\"><path d=\"M40 134v-13h18v13M72 134v"
        "-17h14v13h10v4M296 134v-15h17v15M332 134v-11h20v11\"/><path d=\"M44 121l5-6 5 6M300 119l4-"
        "5 5 5\"/></g><g stroke-width=\"1.05\" opacity=\".55\"><path d=\"M30 138v-9M78 138v-9M126 138v-"
        "9M174 138v-9M222 138v-9M270 138v-9M318 138v-9M366 138v-9\"/><path d=\"M12 131h376\" opacity"
        "=\".5\"/></g><path d=\"M12 138h376v17H12z\" stroke-width=\"1.7\"/><g stroke-width=\".75\" opacit"
        "y=\".45\"><path d=\"M12 144h376M12 150h376\"/></g><path d=\"M12 155h376v133H12z\" stroke-width"
        "=\"1.7\"/><g stroke-width=\".75\" opacity=\".24\"><path d=\"M12 178h376M12 208h376M12 242h376M1"
        "2 272h376\"/><path d=\"M150 288l24-133M250 288l-24-133\"/></g>",
}

# ── SUJETOS (capa 1) ────────────────────────────────────────────────────
SUBJECTS = {
    "aspersores":
        "<g stroke-width=\"1.15\" opacity=\".8\"><path d=\"M100 264q10-40 26-18M100 264q16-60 42-22M10"
        "0 264q22-76 58-20M100 264q28-92 74-14\"/><path d=\"M100 264q-10-40-26-18M100 264q-16-60-42"
        "-22\"/><path d=\"M200 264q10-40 26-18M200 264q16-60 42-22M200 264q22-76 58-20M200 264q28-9"
        "2 74-14\"/><path d=\"M200 264q-10-40-26-18M200 264q-16-60-42-22M200 264q-22-76-58-20M200 2"
        "64q-28-92-74-14\"/><path d=\"M300 264q-10-40-26-18M300 264q-16-60-42-22M300 264q-22-76-58-"
        "20M300 264q-28-92-74-14\"/><path d=\"M300 264q10-40 26-18M300 264q16-60 42-22\"/></g><g str"
        "oke-width=\".9\" opacity=\".45\"><path d=\"M100 264q19-68 50-21M200 264q19-68 50-21M200 264q-"
        "19-68-50-21M300 264q-19-68-50-21\"/></g><g stroke-width=\"1.4\" opacity=\".55\"><path d=\"M174"
        " 248v5M158 242v5M142 240v5M126 244v5M74 244v5M58 240v5M274 248v5M258 242v5M242 240v5M226"
        " 244v5M326 244v5M342 240v5M150 240v5M250 240v5M182 244v5M218 244v5\"/></g><g stroke-width"
        "=\"2.4\"><path d=\"M94 278h12v-14H94zM194 278h12v-14h-12zM294 278h12v-14h-12z\"/></g><g stro"
        "ke-width=\"1.5\"><path d=\"M90 264h20M190 264h20M290 264h20\"/></g><g stroke-width=\"1\" opaci"
        "ty=\".35\"><path d=\"M60 272h28M116 274h34M172 272h18M232 274h30M282 272h22M322 274h20\"/></"
        "g><g stroke-width=\"2.8\"><path d=\"M56 278h288\"/></g>",
    "balon":
        "<g stroke-width=\"1.2\" opacity=\".38\"><path d=\"M56 194h78M266 194h78\"/></g><g stroke-width"
        "=\"1.8\"><path d=\"M56 268q144 18 288 0\"/></g><g stroke-width=\".9\" opacity=\".45\"><path d=\"M"
        "74 271c3-7 6-10 6-10M104 274c2-6 6-9 6-9M296 274c-2-6-6-9-6-9M326 271c-3-7-6-10-6-10\"/><"
        "/g><g stroke-width=\"2.8\"><circle cx=\"200\" cy=\"218\" r=\"60\"/></g><g stroke-width=\"1.7\"><pa"
        "th d=\"M200 194L223 211L214 237L186 237L177 211Z\"/></g><g stroke-width=\"1.5\"><path d=\"M20"
        "0 194v-26M223 211l23-8M214 237l14 20M186 237l-14 20M177 211l-23-8\"/></g><g stroke-width="
        "\"1.35\"><path d=\"M187 172l13-6l13 6l-4 15h-18z\"/><path d=\"M160 249l12-8l13 7l-6 14l-14-2z"
        "\"/><path d=\"M240 249l-12-8l-13 7l6 14l14-2z\"/></g><g stroke-width=\"1.15\" opacity=\".7\"><p"
        "ath d=\"M246 203l16-4M154 203l-16-4M228 257l6 14M172 257l-6 14\"/></g><g stroke-width=\".95"
        "\" opacity=\".4\"><path d=\"M240 178c14 12 21 27 22 44M248 244c8-9 12-20 13-31\"/></g><g stro"
        "ke-width=\"2.2\" opacity=\".65\"><path d=\"M186 276h28\"/></g>",
    "banquillo":
        "<g stroke-width=\"2.8\"><path d=\"M64 200q136-48 272 0\"/></g><g stroke-width=\"1.5\" opacity="
        "\".8\"><path d=\"M64 210q136-48 272 0\"/></g><g stroke-width=\"1.1\" opacity=\".6\"><path d=\"M10"
        "0 195v9M150 190v9M200 188v10M250 190v9M300 195v9\"/></g><g stroke-width=\".9\" opacity=\".35"
        "\"><path d=\"M96 197l40-8M146 190l40-3M206 188l40 3M256 191l40 7\"/></g><g stroke-width=\"2."
        "6\"><path d=\"M68 204v74M332 204v74\"/></g><g stroke-width=\"2.6\"><path d=\"M80 212h240v54H80"
        "z\"/></g><g stroke-width=\"2\"><path d=\"M92 262v-24a11 11 0 0 1 22 0v24M119 262v-24a11 11 0"
        " 0 1 22 0v24M146 262v-24a11 11 0 0 1 22 0v24M173 262v-24a11 11 0 0 1 22 0v24M200 262v-24"
        "a11 11 0 0 1 22 0v24M227 262v-24a11 11 0 0 1 22 0v24M254 262v-24a11 11 0 0 1 22 0v24M281"
        " 262v-24a11 11 0 0 1 22 0v24\"/></g><g stroke-width=\"1.15\" opacity=\".55\"><path d=\"M80 226"
        "h240\"/></g><g stroke-width=\"1.9\"><path d=\"M80 266h240v10H80z\"/></g><g stroke-width=\".95\""
        " opacity=\".5\"><path d=\"M92 276l6-10M112 276l6-10M132 276l6-10M152 276l6-10M172 276l6-10M"
        "192 276l6-10M212 276l6-10M232 276l6-10M252 276l6-10M272 276l6-10M292 276l6-10M312 276l6-"
        "10\"/></g><g stroke-width=\"1.1\" opacity=\".45\"><path d=\"M74 220h6M320 220h6M74 240h6M320 2"
        "40h6\"/></g><g stroke-width=\"2.8\"><path d=\"M56 278h288\"/></g>",
    "camara":
        "<g stroke-width=\"2.4\"><path d=\"M94 226L306 170M94 236L306 180\"/></g><g stroke-width=\"1.3"
        "\"><path d=\"M126 218v10M158 209v10M189 201v10M221 192v10M253 184v10M285 176v10\"/></g><g s"
        "troke-width=\"1.05\" opacity=\".75\"><path d=\"M94 236L126 218M126 228L158 209M158 219L189 20"
        "1M189 211L221 192M221 202L253 184M253 194L285 176M285 186L306 170\"/></g><g stroke-width="
        "\"2.6\"><path d=\"M60 212h38v36H60z\"/></g><g stroke-width=\"1.1\" opacity=\".6\"><path d=\"M60 2"
        "24h38M60 236h38M72 212v36M86 212v36\"/></g><g stroke-width=\"2.6\"><path d=\"M288 174h44v30h"
        "-44z\"/></g><g stroke-width=\"1.5\"><path d=\"M296 174v-9h22v9\"/></g><g stroke-width=\"2.2\"><"
        "circle cx=\"336\" cy=\"189\" r=\"8\"/></g><g stroke-width=\"1.1\" opacity=\".7\"><circle cx=\"336\" "
        "cy=\"189\" r=\"3.5\"/><path d=\"M294 181h14M294 188h10\"/></g><g stroke-width=\"2.2\"><circle cx"
        "=\"200\" cy=\"206\" r=\"8\"/></g><g stroke-width=\"1.1\" opacity=\".6\"><circle cx=\"200\" cy=\"206\" "
        "r=\"3\"/></g><g stroke-width=\"2.6\"><path d=\"M188 214L178 264M212 214l10 50\"/></g><g stroke"
        "-width=\"1.5\"><path d=\"M184 236h32M180 250h40\"/></g><g stroke-width=\"1.05\" opacity=\".7\"><"
        "path d=\"M184 236L216 250M216 236L184 250\"/></g><g stroke-width=\"2.6\"><path d=\"M168 264h6"
        "4v14h-64z\"/></g><g stroke-width=\"1.05\" opacity=\".5\"><path d=\"M182 264v14M200 264v14M218 "
        "264v14\"/></g><g stroke-width=\".95\" opacity=\".5\"><path d=\"M94 236q-8 22 2 42\"/></g><g str"
        "oke-width=\"2.8\"><path d=\"M56 278h288\"/></g>",
    "carro":
        "<g stroke-width=\"2.2\"><path d=\"M62 278l11-32h8l11 32zM96 278l9-26h7l9 26z\"/></g><g strok"
        "e-width=\"1.15\" opacity=\".65\"><path d=\"M68 264h18M100 264h14\"/></g><g stroke-width=\"1.9\">"
        "<path d=\"M56 278h36M92 278h30\"/></g><g stroke-width=\"2.6\"><path d=\"M150 200L124 168M124 "
        "168h-18\"/></g><g stroke-width=\"1.5\"><path d=\"M106 163v10\"/></g><g stroke-width=\"2.2\"><ci"
        "rcle cx=\"174\" cy=\"196\" r=\"17\"/><circle cx=\"208\" cy=\"190\" r=\"17\"/><circle cx=\"242\" cy=\"19"
        "6\" r=\"17\"/></g><g stroke-width=\"1\" opacity=\".7\"><path d=\"M174 185l7 5-3 8h-8l-3-8zM208 1"
        "79l7 5-3 8h-8l-3-8zM242 185l7 5-3 8h-8l-3-8z\"/></g><g stroke-width=\"2.8\"><path d=\"M150 2"
        "02h124l-12 52h-100z\"/></g><g stroke-width=\".95\" opacity=\".6\"><path d=\"M153 218h118M157 2"
        "36h110M172 202l-3 52M194 202l-2 52M216 202v52M238 202l2 52M260 202l3 52\"/></g><g stroke-"
        "width=\"1.9\"><path d=\"M160 254h104\"/></g><g stroke-width=\"2.4\"><circle cx=\"176\" cy=\"266\" "
        "r=\"12\"/><circle cx=\"250\" cy=\"266\" r=\"12\"/></g><g stroke-width=\"1.1\" opacity=\".6\"><circle"
        " cx=\"176\" cy=\"266\" r=\"4\"/><circle cx=\"250\" cy=\"266\" r=\"4\"/></g><g stroke-width=\"2.2\"><ci"
        "rcle cx=\"140\" cy=\"266\" r=\"12\"/></g><g stroke-width=\".95\" opacity=\".7\"><path d=\"M140 257l"
        "6 4-2 7h-8l-2-7z\"/></g><g stroke-width=\"2.2\"><path d=\"M296 278l13-38h9l13 38z\"/></g><g s"
        "troke-width=\"1.15\" opacity=\".7\"><path d=\"M301 264h24M305 252h16\"/></g><g stroke-width=\"1"
        ".9\"><path d=\"M290 278h44\"/></g><g stroke-width=\"2.8\"><path d=\"M56 278h288\"/></g>",
    "corner":
        "<g stroke-width=\"1.8\"><path d=\"M56 248L146 274M146 274L344 234\"/></g><g stroke-width=\"1."
        "4\" opacity=\".8\"><path d=\"M102 260q34 24 80 8\"/></g><g stroke-width=\".9\" opacity=\".45\"><p"
        "ath d=\"M74 256c3-6 7-9 7-9M112 268c2-6 6-8 6-8M206 260c3-6 7-8 7-8M262 249c3-6 7-8 7-8M3"
        "18 238c3-6 7-8 7-8\"/></g><g stroke-width=\"2.8\"><path d=\"M146 274L178 166\"/></g><g stroke"
        "-width=\"1.9\"><circle cx=\"180\" cy=\"161\" r=\"5\"/></g><g stroke-width=\"2.4\"><path d=\"M177 17"
        "2c26 3 48 10 66 20-24 10-50 15-74 16z\"/></g><g stroke-width=\"1\" opacity=\".55\"><path d=\"M"
        "182 180c18 4 32 9 44 16M178 192c16 3 30 7 42 11\"/></g><g stroke-width=\"1.9\"><path d=\"M13"
        "6 272h20v6h-20z\"/></g><g stroke-width=\"1.15\" opacity=\".5\"><path d=\"M130 278c4-6 8-8 8-8M"
        "158 278c3-5 7-7 7-7\"/></g><g stroke-width=\"1.2\" opacity=\".3\"><path d=\"M56 278h288\"/></g>",
    "focos2":
        "<g stroke-width=\"2.6\"><path d=\"M166 158h68v46h-68z\"/></g><g stroke-width=\"1.3\"><path d=\""
        "M166 173h68M166 188h68M183 158v46M200 158v46M217 158v46\"/></g><g stroke-width=\"1.15\" opa"
        "city=\".8\"><circle cx=\"174\" cy=\"165\" r=\"3.6\"/><circle cx=\"191\" cy=\"165\" r=\"3.6\"/><circle "
        "cx=\"209\" cy=\"165\" r=\"3.6\"/><circle cx=\"226\" cy=\"165\" r=\"3.6\"/><circle cx=\"174\" cy=\"180\" "
        "r=\"3.6\"/><circle cx=\"191\" cy=\"180\" r=\"3.6\"/><circle cx=\"209\" cy=\"180\" r=\"3.6\"/><circle c"
        "x=\"226\" cy=\"180\" r=\"3.6\"/><circle cx=\"174\" cy=\"196\" r=\"3.6\"/><circle cx=\"191\" cy=\"196\" r"
        "=\"3.6\"/><circle cx=\"209\" cy=\"196\" r=\"3.6\"/><circle cx=\"226\" cy=\"196\" r=\"3.6\"/></g><g str"
        "oke-width=\"2.4\"><path d=\"M180 204L76 278M220 204l104 74\"/></g><g stroke-width=\"2.1\"><pat"
        "h d=\"M192 204L150 278M208 204l42 74\"/></g><g stroke-width=\"1.3\"><path d=\"M155 222h27M129"
        " 240h43M104 258h57M79 276h72M218 222h27M228 240h43M239 258h57M249 276h72\"/></g><g stroke"
        "-width=\"1.05\" opacity=\".75\"><path d=\"M155 222L172 240M182 222L129 240M129 240L161 258M17"
        "2 240L104 258M104 258L151 276M161 258L79 276\"/><path d=\"M245 222L228 240M218 222L271 240"
        "M271 240L239 258M228 240L296 258M296 258L249 276M239 258L321 276\"/></g><g stroke-width=\""
        "1.05\" opacity=\".5\"><path d=\"M162 154l-32-24M238 154l32-24M172 150l-18-32M228 150l18-32\"/"
        "></g><g stroke-width=\".95\" opacity=\".3\"><path d=\"M158 200l-62 42M158 174l-68 8M242 200l6"
        "2 42M242 174l68 8\"/></g><g stroke-width=\"2.8\"><path d=\"M56 278h288\"/></g>",
    "grada":
        "<g stroke-width=\"2.8\"><path d=\"M56 172L200 202L344 172\"/></g><g stroke-width=\"1.5\" opaci"
        "ty=\".85\"><path d=\"M56 182L200 212L344 182\"/></g><g stroke-width=\"1.9\"><path d=\"M56 164h1"
        "2v8H56zM344 164h-12v8h12z\"/><path d=\"M56 164v-6M344 164v-6\"/></g><g stroke-width=\"1.5\"><"
        "path d=\"M56 194L200 224L344 194M56 206L200 236L344 206M56 218L200 248L344 218M56 230L200"
        " 260L344 230\"/></g><g stroke-width=\"2.2\"><path d=\"M56 242L200 272L344 242\"/></g><g strok"
        "e-width=\"1.15\" opacity=\".7\"><path d=\"M92 180v70M128 187v70M164 195v70M200 202v70M236 195"
        "v70M272 187v70M308 180v70\"/></g><g stroke-width=\".85\" opacity=\".4\"><path d=\"M74 190v46M1"
        "10 197v46M146 205v46M182 212v46M218 212v46M254 205v46M290 197v46M326 190v46\"/></g><g str"
        "oke-width=\"2.4\"><path d=\"M56 242L70 278M344 242L330 278M200 272v6\"/></g><g stroke-width="
        "\"1.2\" opacity=\".55\"><path d=\"M80 247v16M116 254v14M152 262v12M248 262v12M284 254v14M320 "
        "247v16\"/></g><g stroke-width=\"2.8\"><path d=\"M56 278h288\"/></g>",
    "manual":
        "<g stroke-width=\"2.6\"><path d=\"M92 172h216l-14-14H106z\"/></g><g stroke-width=\"2.8\"><path"
        " d=\"M100 172h200v66H100z\"/></g><g stroke-width=\"1.3\" opacity=\".7\"><path d=\"M108 180h184v"
        "54H108z\"/></g><g stroke-width=\"1.4\"><path d=\"M124 184v-4M140 184v-4M160 184v-4M176 184v-"
        "4M224 184v-4M240 184v-4M260 184v-4M276 184v-4\"/></g><g stroke-width=\"2\"><path d=\"M116 18"
        "4h32v38h-32zM152 184h32v38h-32zM216 184h32v38h-32zM252 184h32v38h-32z\"/></g><g stroke-wi"
        "dth=\"1.05\" opacity=\".6\"><path d=\"M116 196h32M116 209h32M152 196h32M152 209h32M216 196h32"
        "M216 209h32M252 196h32M252 209h32\"/></g><g stroke-width=\"1.9\"><circle cx=\"200\" cy=\"203\" "
        "r=\"13\"/></g><g stroke-width=\"1.05\" opacity=\".7\"><circle cx=\"200\" cy=\"203\" r=\"9.5\"/><path"
        " d=\"M200 192v3M200 211v3M189 203h3M208 203h3\"/></g><g stroke-width=\"2\"><path d=\"M200 203"
        "v-8M200 203l6 4\"/></g><g stroke-width=\"1.5\"><path d=\"M116 226h68v8h-68zM216 226h68v8h-68"
        "z\"/></g><g stroke-width=\".9\" opacity=\".5\"><path d=\"M122 230h16M144 230h24M174 230h6M222 "
        "230h20M248 230h12M268 230h12\"/></g><g stroke-width=\"2.6\"><path d=\"M186 238h28v40h-28z\"/>"
        "</g><g stroke-width=\"1.8\" opacity=\".85\"><path d=\"M188 254L148 238M212 254l40-16\"/></g><g"
        " stroke-width=\".95\" opacity=\".5\"><path d=\"M192 248v26M208 248v26\"/></g><g stroke-width=\""
        "2\"><path d=\"M64 278L124 176M78 278L138 176\"/></g><g stroke-width=\"1.4\"><path d=\"M73 263h"
        "14M82 247h14M91 232h14M100 217h14M109 202h14M118 186h14\"/></g><g stroke-width=\"1.9\"><pat"
        "h d=\"M286 278h48v-12h-48zM292 266h36v-8h-36z\"/></g><g stroke-width=\".9\" opacity=\".5\"><pa"
        "th d=\"M298 266v12M310 266v12M322 266v12M304 258v8M316 258v8\"/></g><g stroke-width=\"2.8\">"
        "<path d=\"M56 278h288\"/></g>",
    "marcador2":
        "<g stroke-width=\"2\"><path d=\"M70 172h260l-12-14H82z\"/></g><g stroke-width=\"1.1\" opacity="
        "\".7\"><path d=\"M110 158v-9M158 158v-9M200 158v-9M242 158v-9M290 158v-9\"/></g><g stroke-wi"
        "dth=\"2.6\"><path d=\"M78 172h244v76H78z\"/></g><g stroke-width=\"1.5\"><path d=\"M90 184h220v5"
        "2H90z\"/></g><g stroke-width=\"1.15\" opacity=\".75\"><path d=\"M90 210h220M200 184v52\"/></g><"
        "g stroke-width=\"2\"><path d=\"M116 192h26v14h-26zM258 192h26v14h-26zM116 216h26v14h-26zM25"
        "8 216h26v14h-26z\"/></g><g stroke-width=\"1.3\" opacity=\".8\"><circle cx=\"200\" cy=\"197\" r=\"1"
        "0\"/><path d=\"M200 190v7l5 4\"/></g><g stroke-width=\"1.15\" opacity=\".6\"><path d=\"M158 220h"
        "26M216 220h26M158 228h16M226 228h16M158 196h26M216 196h26\"/></g><g stroke-width=\"2.4\"><p"
        "ath d=\"M126 248L96 278M274 248l30 30\"/></g><g stroke-width=\"2.2\"><path d=\"M162 248v30M23"
        "8 248v30\"/></g><g stroke-width=\"1.15\" opacity=\".55\"><path d=\"M104 266h192\"/></g><g strok"
        "e-width=\"1.05\" opacity=\".45\"><path d=\"M130 254L238 270M270 254L162 270\"/></g><g stroke-w"
        "idth=\"1.05\" opacity=\".5\"><path d=\"M78 248h244\"/></g><g stroke-width=\"2.8\"><path d=\"M56 2"
        "78h288\"/></g>",
    "megafonia":
        "<g stroke-width=\".95\" opacity=\".5\"><path d=\"M166 190L78 272M234 190L322 272M170 198L104 "
        "274M230 198L296 274\"/></g><g stroke-width=\"1.9\"><path d=\"M70 272h18v6H70zM312 272h18v6h-"
        "18zM96 274h16v4H96zM288 274h16v4h-16z\"/></g><g stroke-width=\"2.6\"><path d=\"M178 196L160 "
        "278M222 196l18 82\"/></g><g stroke-width=\"1.5\"><path d=\"M174 214h52M170 232h60M166 250h68"
        "M162 268h76\"/></g><g stroke-width=\"1.05\" opacity=\".7\"><path d=\"M174 214L230 232M226 214L"
        "170 232M170 232L234 250M230 232L166 250M166 250L238 268M234 250L162 268\"/></g><g stroke-"
        "width=\"2.6\"><path d=\"M160 196h80v-10h-80z\"/></g><g stroke-width=\"2.4\"><path d=\"M184 176l"
        "-40-18v36zM216 176l40-18v36z\"/></g><g stroke-width=\"1.5\"><path d=\"M144 158a7 36 0 0 0 0 "
        "36M256 158a7 36 0 0 1 0 36\"/></g><g stroke-width=\"1.6\"><path d=\"M186 190l-30-10v22zM214 "
        "190l30-10v22z\"/></g><g stroke-width=\"1.15\" opacity=\".7\"><path d=\"M156 180a5 22 0 0 0 0 2"
        "2M244 180a5 22 0 0 1 0 22\"/><circle cx=\"184\" cy=\"176\" r=\"4\"/><circle cx=\"216\" cy=\"176\" r"
        "=\"4\"/></g><g stroke-width=\".9\" opacity=\".45\"><path d=\"M136 164l-10-6M136 188l-10 6M130 1"
        "76h-12M264 164l10-6M264 188l10 6M270 176h12\"/></g><g stroke-width=\"1.1\" opacity=\".6\"><pa"
        "th d=\"M200 196v78\"/></g><g stroke-width=\"2.8\"><path d=\"M56 278h288\"/></g>",
    "pizarra":
        "<g stroke-width=\"2.8\"><path d=\"M100 178L300 166L302 254L102 266Z\"/></g><g stroke-width=\""
        "1.3\" opacity=\".7\"><path d=\"M110 186L290 175L292 246L112 257Z\"/></g><g stroke-width=\"1.15"
        "\" opacity=\".8\"><path d=\"M201 181v60\"/><ellipse cx=\"201\" cy=\"211\" rx=\"25\" ry=\"15\"/></g><g"
        " stroke-width=\"1.1\" opacity=\".65\"><path d=\"M110 197l30-2v33l-30 2zM292 186l-30 2v33l30-2"
        "z\"/></g><g stroke-width=\"1.6\"><path d=\"M132 212l10 10M142 212l-10 10M158 232l10 10M168 2"
        "32l-10 10M150 192l10 10M160 192l-10 10\"/></g><g stroke-width=\"1.6\"><circle cx=\"240\" cy=\""
        "199\" r=\"6\"/><circle cx=\"258\" cy=\"221\" r=\"6\"/><circle cx=\"224\" cy=\"229\" r=\"6\"/></g><g str"
        "oke-width=\"1.3\" opacity=\".85\"><path d=\"M170 206q26-14 50-5M212 197l10 4-7 6\"/></g><g str"
        "oke-width=\"2.4\"><path d=\"M126 262L84 278M276 256l44 22\"/></g><g stroke-width=\"2.2\"><path"
        " d=\"M200 260v18\"/></g><g stroke-width=\"1.9\"><path d=\"M120 268L282 258\"/></g><g stroke-wi"
        "dth=\"2\"><path d=\"M176 266l26-2\"/></g><g stroke-width=\"1.9\"><circle cx=\"68\" cy=\"271\" r=\"7"
        "\"/><circle cx=\"332\" cy=\"269\" r=\"7\"/></g><g stroke-width=\"1.05\" opacity=\".6\"><path d=\"M60"
        " 278h16M324 278h16\"/></g><g stroke-width=\"2.8\"><path d=\"M56 278h288\"/></g>",
    "porteria2":
        "<g stroke-width=\"2.8\"><path d=\"M70 264V180h260v84\"/></g><g stroke-width=\"2\"><path d=\"M70"
        " 180l-14 24M330 180l14 24M56 264h288\"/></g><g stroke-width=\".85\" opacity=\".72\"><path d=\""
        "M96 180v84M122 180v84M148 180v84M174 180v84M200 180v84M226 180v84M252 180v84M278 180v84M"
        "304 180v84\"/><path d=\"M70 202h260M70 224h260M70 246h260\"/></g><g stroke-width=\"2.5\"><cir"
        "cle cx=\"266\" cy=\"220\" r=\"20\"/></g><g stroke-width=\"1.15\"><path d=\"M266 203l11.5 8.4-4.4 "
        "13.5h-14.2l-4.4-13.5z\"/><path d=\"M277.5 211.4l13.5-4.4M273 225l4.6 13.6M259 225l-4.6 13."
        "6M254.5 211.4L241 207\"/></g><g stroke-width=\".95\" opacity=\".8\"><path d=\"M246 203c-7 5-11"
        " 11-12 18M286 203c7 5 11 11 12 18M250 240c6 5 12 7 18 7M282 240c-5 5-11 7-17 7\"/></g><g "
        "stroke-width=\"1.5\"><path d=\"M62 264c4-8 8-11 8-11M84 264c3-7 7-10 7-10M316 264c-3-7-7-10"
        "-7-10M338 264c-4-8-8-11-8-11\"/></g><g stroke-width=\"1.15\" opacity=\".65\"><path d=\"M70 272"
        "c5-6 11-8 17-8M124 272c6-6 12-7 18-7M262 272c6-5 12-5 18-2M300 272c5-6 11-8 16-7\"/></g><"
        "g stroke-width=\"2.8\"><path d=\"M56 278h288\"/></g>",
    "puerta":
        "<g stroke-width=\"2.8\"><path d=\"M56 206h98v72H56zM246 206h98v72h-98z\"/></g><g stroke-widt"
        "h=\".9\" opacity=\".45\"><path d=\"M56 224h98M56 242h98M56 260h98M246 224h98M246 242h98M246 2"
        "60h98\"/><path d=\"M80 206v18M116 206v18M98 224v18M62 224v18M134 224v18M80 242v18M116 242v"
        "18M98 260v18M62 260v18M134 260v18\"/><path d=\"M270 206v18M306 206v18M288 224v18M252 224v1"
        "8M324 224v18M270 242v18M306 242v18M288 260v18M252 260v18M324 260v18\"/></g><g stroke-widt"
        "h=\"2\"><path d=\"M92 206v-14M308 206v-14\"/></g><g stroke-width=\"1.9\"><path d=\"M82 192h20l-"
        "4-9H86z\"/><path d=\"M298 192h20l-4-9h-12z\"/></g><g stroke-width=\".9\" opacity=\".45\"><path "
        "d=\"M78 198l-8 6M106 198l8 6M92 200v8M294 198l-8 6M322 198l8 6M308 200v8\"/></g><g stroke-"
        "width=\"2.6\"><path d=\"M144 178h112l-10-16H154z\"/></g><g stroke-width=\"1.1\" opacity=\".6\"><"
        "path d=\"M168 178v-13M200 178v-16M232 178v-13\"/></g><g stroke-width=\"2.8\"><path d=\"M152 2"
        "78V178h96v100\"/></g><g stroke-width=\"2.2\"><path d=\"M162 278V190h76v88\"/></g><g stroke-wi"
        "dth=\"1.9\"><path d=\"M200 190v88\"/></g><g stroke-width=\"1.1\" opacity=\".65\"><path d=\"M170 2"
        "00h24v30h-24zM206 200h24v30h-24zM170 238h24v26h-24zM206 238h24v26h-24z\"/></g><g stroke-w"
        "idth=\"2.2\"><path d=\"M192 232v16M208 232v16\"/></g><g stroke-width=\"1.2\" opacity=\".6\"><pat"
        "h d=\"M162 270h76\"/></g><g stroke-width=\"1.9\"><path d=\"M140 278h120v-9H140z\"/></g><g stro"
        "ke-width=\"2.8\"><path d=\"M56 278h288\"/></g>",
    "reloj":
        "<g stroke-width=\"2.6\"><path d=\"M124 174h152l-14-16H138z\"/></g><g stroke-width=\"1.15\" opa"
        "city=\".6\"><path d=\"M150 174v-16M180 174v-16M220 174v-16M250 174v-16\"/></g><g stroke-widt"
        "h=\"2.8\"><path d=\"M132 174h136v104H132z\"/></g><g stroke-width=\"1.2\" opacity=\".5\"><path d="
        "\"M132 174l24 24M268 174l-24 24M132 278l24-24M268 278l-24-24\"/></g><g stroke-width=\"2.4\">"
        "<circle cx=\"200\" cy=\"224\" r=\"46\"/></g><g stroke-width=\"1.15\" opacity=\".75\"><circle cx=\"2"
        "00\" cy=\"224\" r=\"38\"/></g><g stroke-width=\"1.9\"><path d=\"M200 182v9M200 266v-9M158 224h9M"
        "242 224h-9\"/></g><g stroke-width=\"1.1\" opacity=\".7\"><path d=\"M223 188l-4 7M177 260l4-7M2"
        "36 247l-7-4M164 201l7 4M236 201l-7 4M164 247l7 4M223 260l-4-7M177 188l4 7\"/></g><g strok"
        "e-width=\"2.8\"><path d=\"M200 224v-32M200 224l23 14\"/></g><g stroke-width=\"1.6\"><circle cx"
        "=\"200\" cy=\"224\" r=\"3.6\"/></g><g stroke-width=\"2.4\"><path d=\"M56 250h80M264 250h80\"/></g>"
        "<g stroke-width=\"1.35\"><path d=\"M64 250v16M80 250v16M96 250v16M112 250v16M128 250v16M272"
        " 250v16M288 250v16M304 250v16M320 250v16M336 250v16\"/></g><g stroke-width=\"1.15\" opacity"
        "=\".55\"><path d=\"M56 259h80M264 259h80\"/></g><g stroke-width=\"2.6\"><path d=\"M56 266h288v1"
        "2H56z\"/></g><g stroke-width=\".95\" opacity=\".45\"><path d=\"M92 266v12M140 266v12M188 266v1"
        "2M236 266v12M284 266v12\"/></g>",
    "torniquetes":
        "<g stroke-width=\"2.8\"><path d=\"M64 278V172h44v106M292 278V172h44v106\"/></g><g stroke-wid"
        "th=\"2.4\"><path d=\"M58 172h56v-12H58zM286 172h56v-12h-56z\"/></g><g stroke-width=\".9\" opac"
        "ity=\".45\"><path d=\"M64 190h44M64 206h44M64 222h44M64 238h44M64 254h44M64 270h44M292 190h"
        "44M292 206h44M292 222h44M292 238h44M292 254h44M292 270h44\"/><path d=\"M86 172v18M75 190v1"
        "6M97 190v16M86 206v16M75 222v16M97 222v16M86 238v16M75 254v16M97 254v16M86 270v8\"/><path"
        " d=\"M314 172v18M303 190v16M325 190v16M314 206v16M303 222v16M325 222v16M314 238v16M303 25"
        "4v16M325 254v16M314 270v8\"/></g><g stroke-width=\"2.6\"><path d=\"M108 184h184v30H108z\"/></"
        "g><g stroke-width=\"2\" opacity=\".75\"><path d=\"M126 195h44M180 195h40M230 195h44\"/></g><g "
        "stroke-width=\"1.3\" opacity=\".55\"><path d=\"M144 205h112\"/></g><g stroke-width=\"1.4\" opaci"
        "ty=\".6\"><path d=\"M132 184v-6M200 184v-8M268 184v-6\"/></g><g stroke-width=\"2.4\"><path d=\""
        "M140 278v-42M200 278v-42M260 278v-42\"/></g><g stroke-width=\"2.4\"><path d=\"M128 236h24v-1"
        "4h-24zM188 236h24v-14h-24zM248 236h24v-14h-24z\"/></g><g stroke-width=\"2.8\"><path d=\"M140"
        " 250l-22 11M140 250l22 11M200 250l-22 11M200 250l22 11M260 250l-22 11M260 250l22 11\"/></"
        "g><g stroke-width=\"1.6\"><circle cx=\"140\" cy=\"250\" r=\"6\"/><circle cx=\"200\" cy=\"250\" r=\"6\""
        "/><circle cx=\"260\" cy=\"250\" r=\"6\"/></g><g stroke-width=\"1.15\" opacity=\".6\"><path d=\"M132"
        " 228h16M192 228h16M252 228h16\"/></g><g stroke-width=\"1.5\"><path d=\"M116 278v-16M164 278v"
        "-16M176 278v-16M224 278v-16M236 278v-16M284 278v-16\"/></g><g stroke-width=\"1.1\" opacity="
        "\".5\"><path d=\"M112 268h32M168 268h32M228 268h32\"/></g><g stroke-width=\"2.8\"><path d=\"M56"
        " 278h288\"/></g>",
    "trofeo2":
        "<g stroke-width=\"2.4\"><path d=\"M148 166h104v26c0 28-23 50-52 50s-52-22-52-50z\"/></g><g s"
        "troke-width=\"1.7\"><path d=\"M150 176c-20 0-31 13-31 27s12 25 32 29M250 176c20 0 31 13 31 "
        "27s-12 25-32 29\"/></g><g stroke-width=\".95\" opacity=\".72\"><path d=\"M176 180l7 52M200 178"
        "v56M224 180l-7 52M162 184l5 36M238 184l-5 36\"/></g><g stroke-width=\"1.5\" opacity=\".55\"><"
        "path d=\"M134 180h132\"/></g><g stroke-width=\"2.4\"><path d=\"M200 242v16M148 258h104v10h-10"
        "4z\"/></g><g stroke-width=\"2.6\"><path d=\"M112 268h176v10H112z\"/></g><g stroke-width=\".95\""
        " opacity=\".6\"><path d=\"M124 273h152M164 263h72\"/></g><g stroke-width=\"1.45\"><path d=\"M10"
        "0 264c-20-13-29-35-25-57 20 4 36 20 40 42M300 264c20-13 29-35 25-57-20 4-36 20-40 42\"/><"
        "path d=\"M66 236c-14-11-17-28-12-42 14 6 25 20 25 34M334 236c14-11 17-28 12-42-14 6-25 20"
        "-25 34\"/><path d=\"M126 256c-14-9-20-25-17-40 14 3 25 14 28 30M274 256c14-9 20-25 17-40-1"
        "4 3-25 14-28 30\"/></g><g stroke-width=\".9\" opacity=\".55\"><path d=\"M72 226l10 10M68 242l1"
        "2 8M84 250l9 10M328 226l-10 10M332 242l-12 8M316 250l-9 10\"/></g><g stroke-width=\"2.8\"><"
        "path d=\"M56 278h288\"/></g>",
    "tunel":
        "<g stroke-width=\"2.8\"><path d=\"M70 278V196h46v82M284 278v-82h46v82\"/></g><g stroke-width"
        "=\"2.4\"><path d=\"M64 196h58v-12H64zM278 196h58v-12h-58z\"/></g><g stroke-width=\".9\" opacit"
        "y=\".45\"><path d=\"M70 214h46M70 232h46M70 250h46M70 266h46M284 214h46M284 232h46M284 250h"
        "46M284 266h46\"/><path d=\"M93 196v18M81 214v18M105 214v18M93 232v18M81 250v16M105 250v16M"
        "93 266v12\"/><path d=\"M307 196v18M295 214v18M319 214v18M307 232v18M295 250v16M319 250v16M"
        "307 266v12\"/></g><g stroke-width=\"2.6\"><path d=\"M116 278V214h168v64\"/></g><g stroke-widt"
        "h=\".9\" opacity=\".4\"><path d=\"M116 232h168M116 250h168M116 266h168\"/><path d=\"M140 214v18"
        "M164 214v18M236 214v18M260 214v18M128 232v18M152 232v18M248 232v18M272 232v18M140 250v16"
        "M164 250v16M236 250v16M260 250v16\"/></g><g stroke-width=\"2.8\"><path d=\"M128 278V240a72 7"
        "2 0 0 1 144 0v38\"/></g><g stroke-width=\"1.15\" opacity=\".65\"><path d=\"M120 278V240a80 80 "
        "0 0 1 160 0v38\"/></g><g stroke-width=\"1.3\" opacity=\".8\"><path d=\"M132.3 215.4l-9.4-3.5M1"
        "44.8 193.7l-7.6-6.4M164 177.6l-5-8.6M187.5 169.1l-1.8-9.9M212.5 169.1l1.8-9.9M236 177.6l"
        "5-8.6M255.2 193.7l7.6-6.4M267.7 215.4l9.4-3.5\"/></g><g stroke-width=\"2.4\"><path d=\"M190 "
        "162h20l-3-12h-14z\"/></g><g stroke-width=\"1.9\"><path d=\"M146 278V240a54 54 0 0 1 108 0v38"
        "\"/></g><g stroke-width=\"1.5\"><path d=\"M178 278V250a22 22 0 0 1 44 0v28\"/></g><g stroke-w"
        "idth=\".95\" opacity=\".5\"><path d=\"M146 244l32 10M254 244l-32 10M200 186v42M152 216l26 22M"
        "248 216l-26 22\"/></g><g stroke-width=\".9\" opacity=\".3\"><path d=\"M164 270h72M172 260h56M1"
        "82 250h36\"/></g><g stroke-width=\"2.8\"><path d=\"M56 278h288\"/></g><g stroke-width=\"1.5\"><"
        "path d=\"M132 278v-9h136v9\"/></g>",
}

# ── Familias de silueta ─────────────────────────────────────────────────────
# Los 3 pares que se parecen entre sí a tamaño miniatura (detectados en la hoja
# de contactos de los 18). NO intervienen en la selección: ver la nota en
# `pick()`. Están aquí como dato + los cubre test_illustration para que el
# banco no se desequilibre si alguien añade sujetos.
FAMILIES = {
    "torres":         ("focos2", "megafonia"),      # mástil + diagonales abiertas
    "bloque-central": ("reloj", "puerta"),          # bloque central + alas bajas
    "portico":        ("tunel", "torniquetes"),     # dos pilas + algo en medio
}

# Única exclusión SEMÁNTICA (no visual): los aspersores regando en pleno
# aguacero se leen como absurdo. Visualmente no chocan — se comprobó que los
# arcos finos del riego no hacen eco con la cubierta curva del fondo.
BLOCKED = frozenset({("aspersores", "lluvia")})

# Sal por tipo: decorrela los tipos entre sí, de modo que los artículos de
# DISTINTO tipo del mismo día (el caso habitual: previa + resumen + crónica)
# caigan en sujetos sin relación.
TYPE_SALT = {
    "previa_diaria":            "previa",
    "resumen_diario":           "resumen",
    "cronica_partido":          "cronica",
    "recap_jornada":            "recap",
    "explicador_probabilidad":  "explicador",
    "carrera_titulo":           "titulo",
}

# Orden FIJO y explícito: el índice sale de la posición en estas tuplas, así
# que el orden es parte del contrato. `sorted()` lo hace determinista entre
# versiones de Python (no depende del orden de inserción del dict).
# ponytail: añadir un sujeto reordena y por tanto cambia la ilustración de los
# artículos ya generados. Es churn cosmético, no un fallo — si algún día
# importa, congelar esta tupla a mano en vez de derivarla.
SUBJECT_NAMES = tuple(sorted(SUBJECTS))
BACKDROP_NAMES = tuple(sorted(BACKDROPS))

# Nombre legible de cada grabado: va al pie de la lámina y al aria-label (que
# antes llevaba el tipo de artículo — describía el artículo, no el dibujo, que
# es lo que un lector de pantalla necesita ahí). test_illustration exige que
# estén los 18.
LABELS = {
    "aspersores":  "Aspersores",
    "balon":       "Balón en el punto",
    "banquillo":   "Banquillo",
    "camara":      "Torre de cámara",
    "carro":       "Carro de balones",
    "corner":      "Banderín de córner",
    "focos2":      "Torre de focos",
    "grada":       "Grada esquinada",
    "manual":      "Marcador manual",
    "marcador2":   "Marcador",
    "megafonia":   "Torre de megafonía",
    "pizarra":     "Pizarra táctica",
    "porteria2":   "Portería",
    "puerta":      "Puerta de vestuario",
    "reloj":       "Reloj de estadio",
    "torniquetes": "Torniquetes",
    "trofeo2":     "Trofeo",
    "tunel":       "Boca de túnel",
}


def digest(slug, tipo, fecha):
    """md5 EXPLÍCITO, nunca hash(): hash() de un str va con sal aleatoria por
    proceso (PYTHONHASHSEED), así que el cron de 3h daría una ilustración
    distinta en cada pasada y el artículo cambiaría de dibujo solo. Lo cubre
    test_illustration con dos subprocesos y semillas distintas.

    Público (no `_digest`) porque articles/mosaic.py elige con él la maqueta
    del artículo: la maqueta tiene que ser tan estable entre procesos como el
    dibujo, y hacerlo con el MISMO digest evita una segunda función de hash
    que alguien podría escribir con `hash()`."""
    if isinstance(fecha, str):
        fecha = date.fromisoformat(fecha[:10])
    salt = TYPE_SALT.get(tipo, tipo or "")
    key = f"{slug}|{fecha.toordinal()}|{salt}"
    return int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)


# Pasos coprimos con el nº de sujetos: recorrer la lista de sujetos "a saltos"
# de un paso coprimo la recorre ENTERA sin repetir, así los N grabados de un
# mismo artículo son siempre distintos entre sí (con N <= nº de sujetos) sin
# tener que llevar un conjunto de ya-usados ni reintentar.
_COPRIME_STEPS = tuple(k for k in range(1, len(SUBJECT_NAMES))
                       if math.gcd(k, len(SUBJECT_NAMES)) == 1)


def picks(slug, tipo, fecha, n=1):
    """Los `n` (sujeto, fondo) de un artículo, todos distintos de sujeto.
    `picks(..., 1)[0] == pick(...)`: el primero es exactamente el de antes, así
    que los artículos ya generados no cambian de grabado de cabecera."""
    if n > len(SUBJECT_NAMES):
        raise ValueError(f"solo hay {len(SUBJECT_NAMES)} sujetos, se piden {n}")
    d = digest(slug, tipo, fecha)
    s0 = (d & 0xFFFFFFFF) % len(SUBJECT_NAMES)
    b0 = (d >> 32) & 0xFFFFFFFF
    step = _COPRIME_STEPS[(d >> 64) % len(_COPRIME_STEPS)]
    out = []
    for i in range(n):
        subject = SUBJECT_NAMES[(s0 + i * step) % len(SUBJECT_NAMES)]
        # `+i` para que dos grabados seguidos no compartan fondo; el bucle en
        # `j` es el mismo salto de exclusión de siempre.
        for j in range(len(BACKDROP_NAMES)):
            backdrop = BACKDROP_NAMES[(b0 + i + j) % len(BACKDROP_NAMES)]
            if (subject, backdrop) not in BLOCKED:
                break
        else:
            raise AssertionError(f"todos los fondos excluidos para {subject!r}")
        out.append((subject, backdrop))
    return out


def pick(slug, tipo, fecha):
    """(sujeto, fondo) para un artículo. Función PURA de (slug, tipo, fecha del
    artículo) — no del día de hoy: `render_article` se llama desde dos sitios
    (el artículo recién generado y el re-render del índice de preview) y en
    cada pasada del cron, y las tres tienen que dar el mismo dibujo.

    NOTA sobre las familias: se planteó una "sal de familia" para que dos
    artículos DEL MISMO TIPO y MISMO DÍA no cayeran en el mismo par parecido.
    No se puede garantizar con una función pura — haría falta conocer los
    artículos hermanos, y pasarlos rompería justo la estabilidad de arriba
    (los dos sitios de llamada no ven la misma lista). Y no compensa: elegir
    familia primero deja P(misma familia) = 1/15 = 6,7% frente al 7,4% de
    elegir sujeto uniformemente, es decir nada, a cambio de que los 6 sujetos
    emparejados salgan la mitad de veces que el resto. Se elige uniforme."""
    return picks(slug, tipo, fecha, 1)[0]


def plates(slug, tipo, fecha, n=1):
    """`n` láminas (markup, nombre) de sujetos distintos — las 3-4 que la
    maqueta de mosaico reparte por el artículo (ver articles/mosaic.py)."""
    return [_plate(s, b) for s, b in picks(slug, tipo, fecha, n)]


def plate(slug, tipo, fecha):
    """(markup, nombre_del_grabado). El markup usa `currentColor` (no un color
    fijo): al ir inline SÍ hereda el cascade, a diferencia de los iconos
    data-URI. El nombre lo pinta render.py como pie de la lámina."""
    return plates(slug, tipo, fecha, 1)[0]


def _plate(subject, backdrop):
    label = LABELS[subject]
    markup = (
        f'<svg class="illo" viewBox="{VIEWBOX}" role="img" aria-label="{label}" '
        f'fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" '
        f'data-illo="{subject}/{backdrop}">'
        f"{BACKDROPS[backdrop]}{SUBJECTS[subject]}</svg>"
    )
    return markup, label
