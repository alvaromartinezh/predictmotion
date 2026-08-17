"""Maqueta de mosaico de periódico para el cuerpo de un artículo: rejilla de 3
columnas donde alternan celdas de TEXTO y de FOTO (grabado), al estilo de la
portada de un diario antiguo — T P T / P T P / T P T y variantes.

POR QUÉ UNA REJILLA Y NO `column-count`
El cuerpo iba en multi-columna CSS (`.card-pad[data-cols]`), que equilibra las
alturas solo pero NO deja decidir en qué columna cae cada grabado: el navegador
reparte el flujo donde le cabe. Con `display:grid` cada celda se coloca donde
dice la maqueta, y las tres columnas siguen acabando a la misma altura porque
las filas de una rejilla se alinean por definición (la altura de fila es la de
su celda más alta y todas las celdas se estiran a ella). Es decir: la rejilla
da control de posición Y alturas iguales; el multi-columna solo lo segundo.

FORMATO DE UNA MAQUETA
Una tupla de filas; cada fila es una cadena de celdas separadas por espacios:
`"T"` texto, `"P"` foto, y la letra repetida = esa celda ocupa 2 columnas
(`"PP"` = foto ancha, `"TT"` = texto ancho). La suma de anchos de cada fila
tiene que ser 3 — lo comprueba test_mosaic sobre las maquetas del banco.

CÓMO SE ELIGE — POR CAPACIDAD, NO POR Nº DE PÁRRAFOS
Que las columnas midan lo mismo no basta si dentro de una fila el texto es el
doble de alto que la foto: la fila entera crece y la celda de la foto queda
medio vacía. Así que la unidad de medida aquí es la ALTURA DE FILA, y la manda
la foto: una foto de 1 columna mide ~265 px de alto (4:3 + kicker + pie) y una
de 2 columnas ~505 px. De ahí sale la *capacidad* en caracteres de cada celda
de texto (cuántos caracteres caben en ese alto, a ese ancho) y la capacidad de
una maqueta es la suma. Se elige la maqueta cuya capacidad más se acerca al
texto real y se reparte el texto entre las celdas EN PROPORCIÓN a su capacidad
— por eso una celda al lado de una foto ancha recibe más texto que una al lado
de una estrecha, y las filas salen parejas.

Entre las maquetas de capacidad parecida se desempata con el MISMO digest md5
que el grabado (illustration.digest): determinista entre procesos y entre
pasadas del cron, ver el docstring de esa función.

El texto se re-trocea frase a frase para llenar esas celdas. Nunca se recorta
ni se reordena; las fronteras de párrafo se conservan dentro de cada celda.
"""

import re

from seo.chrome import esc

from . import illustration

# ── Modelo de altura ────────────────────────────────────────────────────────
# ponytail: Python no tiene motor de maquetación, así que la altura de cada
# celda se ESTIMA. Los números salen de medir un render real a 1280 px con
# `getBoundingClientRect` (columna de 282 px, línea de 29,4 px, celda de foto
# estrecha de 264 px de alto, ~30 caracteres por línea). Es el pomo de
# calibración de toda la maqueta: si las filas salen descompensadas se ajusta
# AQUÍ, no en el CSS. Si algún día cambian el ancho de `.wrap`, el cuerpo de
# `.lede` o el relleno de `.illo-aside`, hay que volver a medir.
_WRAP, _CARD_PAD, _GAP = 940, 21, 26
_RULE_PAD = 26                    # padding-left de las celdas que no son col 1
_COL = (_WRAP - 2 * _CARD_PAD - 2 * _GAP) / 3
_CHAR_W, _LINE_H = 8.6, 29.4
_FIG_PAD = 22                     # relleno + bordes de .illo-aside
_FIG_CHROME = 89                  # ese relleno + kicker + pie, en vertical
# Alto de una fila SIN foto: la marca el propio texto, así que se le da el de
# una fila de foto estrecha para que el ritmo de la página no cambie.
_PLAIN_ROW = 264
# La capitular de la primera celda le roba unos caracteres a sus 3 primeras
# líneas (flota, no ocupa líneas enteras): media línea de texto, no dos.
_DROPCAP_COST = 0.5 * _LINE_H
# Tamaño máximo de una pieza de reparto, como fracción de la celda más pequeña.
# Más bajo = columnas más parejas pero más cortes a mitad de frase (que en un
# periódico son normales: el texto salta de columna); más alto, al revés.
_GRANULARITY = 0.4

# Mínimo de texto para que un mosaico tenga sentido: por debajo, el llamante se
# queda con la prosa en columnas de siempre (3 celdas de 100 caracteres serían
# ridículas).
MIN_CHARS = 700

# Banco de maquetas. Todas llevan 3 o 4 fotos (el encargo) y suman 3 de ancho
# por fila. La variedad es intencionada — foto estrecha, foto ancha, filas solo
# de texto —; la capacidad de cada una se calcula sola (ver `capacity`), así
# que añadir una maqueta nueva no obliga a tocar ningún umbral.
LAYOUTS = (
    ("T P T", "P T P"),
    ("T P T", "T T T", "P T P"),
    ("TT P", "T T T", "P T P"),
    ("T P T", "T T P", "P TT"),
    ("PP T", "T T T", "T P T", "P T T"),
    ("T PP", "T T T", "P T T", "T P T"),
    ("P T T", "T T T", "T P T", "T T P"),
    ("T P T", "P T P", "T T T", "T P T"),
    ("T P T", "T T T", "P T P", "T T T", "T P T"),
    ("T PP", "T T T", "P T T", "T T T", "T P T"),
    ("PP T", "T T T", "T P T", "T T T", "P T P"),
)

_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def _span_width(span):
    """Ancho útil (ya sin el filete y su relleno) de una celda de `span`
    columnas."""
    return span * _COL + (span - 1) * _GAP - _RULE_PAD


def _pic_height(span):
    """Alto de una celda de foto: el 4:3 del grabado más su kicker y su pie.
    Es lo que fija el alto de la fila, y por tanto cuánto texto cabe al lado."""
    return (_span_width(span) - _FIG_PAD) * 0.75 + _FIG_CHROME


def _row_height(row):
    """El alto de una fila lo fija su foto más alta; sin fotos, el alto tipo."""
    pics = [_pic_height(len(t)) for t in row.split() if t[0] == "P"]
    return max(pics) if pics else _PLAIN_ROW


def weights(rows):
    """Capacidad en caracteres de cada celda de TEXTO, en orden de lectura."""
    out = []
    for row in rows:
        h = _row_height(row)
        for tok in row.split():
            if tok[0] == "T":
                alto = h - (_DROPCAP_COST if not out else 0)
                out.append((alto / _LINE_H) * (_span_width(len(tok)) / _CHAR_W))
    return out


def counts(rows):
    """(celdas de texto, celdas de foto) de una maqueta."""
    toks = [t for r in rows for t in r.split()]
    return sum(t[0] == "T" for t in toks), sum(t[0] == "P" for t in toks)


def capacity(rows):
    return sum(weights(rows))


def _units(text, minimum, maxlen=None):
    """El texto partido en frases, como [(frase, ¿abre párrafo?)]. Las frases
    son las piezas indivisibles del reparto, así que su tamaño es el límite de
    lo fino que puede hilar `chunks`: se parten por palabra las que pasen de
    `maxlen` (y, pase lo que pase, hasta tener `minimum` piezas — con menos,
    alguna celda se quedaría vacía)."""
    units = []
    for i, para in enumerate(p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        for j, sent in enumerate(s for s in _SENTENCE.split(para) if s.strip()):
            units.append([sent.strip(), j == 0 and i > 0])

    def _cut(i):
        a, b = _split_words(units[i][0])
        if not b:
            return False
        units[i:i + 1] = [[a, units[i][1]], [b, False]]
        return True

    if maxlen:
        i = 0
        while i < len(units):
            if len(units[i][0]) <= maxlen or not _cut(i):
                i += 1
    while len(units) < minimum:
        if not _cut(max(range(len(units)), key=lambda i: len(units[i][0]))):
            break
    return units


def _split_words(s):
    """Parte por el espacio más cercano a la mitad (una frase larga suelta
    también tiene que poder partirse, o la maqueta se queda sin celdas)."""
    cuts = [m.end() for m in re.finditer(r"\s+", s) if 0 < m.end() < len(s)]
    if not cuts:
        return s, ""
    i = min(cuts, key=lambda c: abs(c - len(s) // 2))
    return s[:i].strip(), s[i:].strip()


def chunks(text, w):
    """El texto repartido en `len(w)` celdas con tamaños PROPORCIONALES a los
    pesos `w` (la capacidad de cada celda), en orden y sin perder nada.

    Es un reparto ÓPTIMO por programación dinámica, no un llenado codicioso:
    los cortes solo pueden caer en frontera de frase, así que ir llenando celda
    a celda hasta cubrir el objetivo arrastra el error hacia el final (se vio:
    una celda de 97 caracteres seguida de otra de 470, con la foto de al lado
    dejando 200 px en blanco). La tabla es de 10×25 casillas — cuesta menos que
    parchear el codicioso, y no puede volver a desequilibrarse."""
    n = len(w)
    # Primera pasada solo para saber cuánto texto hay y, con ello, cuál es la
    # celda más pequeña: las frases que pasen de esa medida se parten por
    # palabra, o el reparto no tiene piezas lo bastante finas para cuadrar
    # (una frase de 300 caracteres no cabe en una celda de 267 sin desbordarla
    # ni dejarla medio vacía si se pone en la siguiente).
    total = sum(len(u) for u, _ in _units(text, n))
    units = _units(text, n, maxlen=_GRANULARITY * total * min(w) / sum(w))
    m = len(units)
    acum = [0]
    for u, _ in units:
        acum.append(acum[-1] + len(u))
    objetivo = [acum[m] * x / sum(w) or 1 for x in w]

    INF = float("inf")
    # coste[i][j] = mejor coste repartiendo las j primeras frases en las i
    # primeras celdas; el error de una celda es relativo a SU objetivo, para
    # que una celda pequeña no se sacrifique en favor de una grande.
    coste = [[INF] * (m + 1) for _ in range(n + 1)]
    corte = [[0] * (m + 1) for _ in range(n + 1)]
    coste[0][0] = 0
    for i in range(1, n + 1):
        for j in range(i, m - (n - i) + 1):
            for k in range(i - 1, j):
                if coste[i - 1][k] == INF:
                    continue
                c = coste[i - 1][k] + ((acum[j] - acum[k]) / objetivo[i - 1] - 1) ** 2
                if c < coste[i][j]:
                    coste[i][j], corte[i][j] = c, k

    cortes, j = [m], m
    for i in range(n, 0, -1):
        j = corte[i][j]
        cortes.append(j)
    cortes.reverse()
    return ["".join(("\n\n" if newp and k else " " if k else "") + u
                    for k, (u, newp) in enumerate(units[a:b]))
            for a, b in zip(cortes, cortes[1:])]


def _pick_layout(text_len, seed):
    """La maqueta cuya capacidad mejor encaja con el texto. Entre las que
    quedan a menos de un 12% de la mejor se elige con el digest, para que dos
    artículos de largo parecido no salgan siempre con la misma página."""
    scored = sorted(((abs(capacity(l) - text_len), i, l) for i, l in enumerate(LAYOUTS)))
    best = scored[0][0]
    near = [l for d, _, l in scored if d <= best * 1.12 + 40]
    return near[(seed >> 96) % len(near)]


def build(text, slug, tipo, fecha, figure):
    """HTML del cuerpo en mosaico, o None si el texto es demasiado corto (el
    llamante vuelve entonces a la prosa en columnas de siempre).

    `figure(markup, label)` construye el HTML de una lámina — lo pasa render.py
    para no duplicar aquí su `.illo-aside`; este módulo solo maqueta."""
    body = text.strip()
    if len(body) < MIN_CHARS:
        return None
    seed = illustration.digest(slug, tipo, fecha)
    rows = _pick_layout(len(body), seed)
    n_text, n_pics = counts(rows)
    cells = chunks(body, weights(rows))
    figs = [figure(m, l) for m, l in illustration.plates(slug, tipo, fecha, n_pics)]

    out, ti, pi = [], 0, 0
    for row in rows:
        col = 1
        for tok in row.split():
            # `data-col` = columna en la que ARRANCA la celda. Lo escribe
            # Python porque el CSS no puede deducirlo: con una celda ancha de
            # por medio el índice en el DOM ya no coincide con la columna, así
            # que un `nth-child(3n+1)` pondría el filete vertical donde no toca.
            # El ancho va como CLASE, no como `style="grid-column:span 2"`: en
            # móvil la rejilla es de UNA columna y un span en línea le crea una
            # segunda columna implícita (se vio: media página en dos columnas
            # estrujadas a 390 px). Con la clase, el CSS lo activa solo a partir
            # de 700 px.
            wide = " mos-wide" if len(tok) > 1 else ""
            if tok[0] == "T":
                paras = "".join(f'<p class="lede">{esc(p)}</p>'
                                for p in cells[ti].split("\n\n") if p.strip())
                lead = " mos-lead" if ti == 0 else ""
                out.append(f'<div class="mos-t{lead}{wide}" data-col="{col}">{paras}</div>')
                ti += 1
            else:
                out.append(f'<div class="mos-p{wide}" data-col="{col}">{figs[pi]}</div>')
                pi += 1
            col += len(tok)
    return f'<div class="mosaic">{"".join(out)}</div>'
