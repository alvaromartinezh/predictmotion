"""Estimador de alturas de columna del broadsheet, sin navegador real.

Por qué es viable: en ESCRITORIO el sheet mantiene un ancho de layout fijo
(`max-width: 1180px` en .bs-sheet; las media queries de artículos-broadsheet.css
solo apilan a ≤1020px) — así que hay UN solo ancho de columna que calcular
para la vista de escritorio. En móvil las columnas se apilan y los grabados de
relleno se ocultan por CSS, de modo que esta estimación solo decide el relleno
de escritorio. Sin ese ancho fijo, la altura real dependería del ancho de cada
pantalla y no habría un número único que estimar de antemano.

Método: suma de bloques de altura fija (calibrados a mano contra
assets/articles-broadsheet.css) + líneas envueltas estimadas para el texto
variable (párrafos de Gemini, titulares) a partir del ancho de columna real
y un ancho medio de carácter por fuente.

Calibración (2026-08-19): comparé esta estimación contra un render real
medido con Firefox headless (hypermotion-resumen-2026-08-17) — sin
corrección, se quedaba corta un 4-5% tanto en la columna Explicador como en
la central. FUDGE compensa ese sesgo. HEURÍSTICO, igual que el resto de
constantes del sitio (STRENGTH_SCALE en seo/config.py, etc.) — afinar con
más muestras reales si el hueco estimado se aleja mucho del real (comparar
capturas antes/después en articles/test_generate.py sería la forma barata
de detectarlo sin gastar cuota de Gemini).
"""

import math

FUDGE = 1.06

# Ancho útil del sheet (1180px de .bs-sheet, menos 2×1px de borde).
SHEET_W = 1178


def column_widths(has_side):
    """Ancho de contenido (tras padding/borde) de cada columna. .bs-grid usa
    auto-fit(minmax(165px,1fr)): sin lateral hay 3 "pistas" de ancho igual
    (explicador=1, resumen=2); con lateral hay 4 (1/2/1) — ver CLAUDE.md."""
    n_tracks = 4 if has_side else 3
    track = SHEET_W / n_tracks
    return {
        "explainer": track - 44,           # padding 22px×2
        "main": 2 * track - 48 - 2,        # padding 24px×2 + borde 1px×2
        "side": (track - 44) if has_side else 0,
    }


# ── Métricas de texto (px medios por carácter, ~0.5-0.55em según fuente) ──
CHAR_W_PROSE = 7.1          # Geist .875rem (14px)
CHAR_W_H2_EXPLAINER = 14    # Saira Condensed 800 uppercase 1.65rem (26.4px)
CHAR_W_H2_MAIN = 19         # Saira Condensed 800 uppercase clamp(~2.4rem en 1180px)
CHAR_W_TEASER = 9.4         # Geist 600 1.0625rem (17px)

LINE_H_PROSE = 22.68        # .875rem * 1.62
LINE_H_H2_EXPLAINER = 26.9  # 1.65rem * 1.02
LINE_H_H2_MAIN = 37.6       # clamp(2rem,3.6vw,3rem) ≈ 2.35rem a 1180px, * .98
LINE_H_TEASER = 24.65       # 1.0625rem * 1.45


def _lines(text, width_px, char_w):
    if not text or width_px <= 0:
        return 0
    per_line = max(int(width_px / char_w), 8)
    return max(1, math.ceil(len(text) / per_line))


# ── Bloques de altura fija (px, calibrados a mano contra el CSS) ──────────
SECTION_LABEL_H = 24
TEAM_ROW_H = 48
STATS_BLOCK_H = 164     # 3 filas + margen propio (.bs-stats)
ILLO_SM_H = 165         # .bs-illo--sm: 130px img + pie + borde
ILLO_FOOTER_H = 155     # .bs-illo--footer: 120px img + pie + borde
COVER_H = 300           # .bs-cover: 250px img + pie + margen
TEASER_FIXED_H = 47     # .bs-teaser sin el texto
BRIEF_HEAD_H = 37       # cabecera de marcador de un brief (.bs-brief__head)
BRIEF_MARGIN = 20       # margin-bottom de .bs-brief
ZONE_H = 38             # .bs-zone (tamaño normal, columna central)
ZONE_SM_H = 34          # .bs-zone--sm (columna lateral)
NOTE_FIXED_H = 71       # caja "Nota del modelo" sin el texto
SIDE_BRIEF_FIXED_H = 90 # h3 + fila de escudos de un side-brief, sin párrafo/zonas


def explainer_height(headline_text, paragraphs, width_px):
    h = SECTION_LABEL_H + TEAM_ROW_H + STATS_BLOCK_H + ILLO_SM_H
    h += _lines(headline_text, width_px, CHAR_W_H2_EXPLAINER) * LINE_H_H2_EXPLAINER + 26
    for p in paragraphs:
        h += _lines(p, width_px, CHAR_W_PROSE) * LINE_H_PROSE + 14
    return h * FUDGE


def main_height(headline_text, teaser_text, lead_paragraphs, note_paragraphs, width_px):
    h = COVER_H + 20  # .bs-main-label
    h += _lines(headline_text, width_px, CHAR_W_H2_MAIN) * LINE_H_H2_MAIN + 16
    h += TEASER_FIXED_H + _lines(teaser_text, width_px, CHAR_W_TEASER) * LINE_H_TEASER
    for p in lead_paragraphs:
        h += BRIEF_HEAD_H + BRIEF_MARGIN
        h += _lines(p, width_px, CHAR_W_PROSE) * LINE_H_PROSE + 9
        h += 2 * ZONE_H
    if note_paragraphs:
        h += NOTE_FIXED_H
        h += _lines(" ".join(note_paragraphs), width_px, CHAR_W_PROSE) * LINE_H_PROSE
    return h * FUDGE


def side_height(side_paragraphs, width_px):
    if not side_paragraphs:
        return 0
    h = SECTION_LABEL_H
    for p in side_paragraphs:
        h += SIDE_BRIEF_FIXED_H
        h += _lines(p, width_px, CHAR_W_PROSE) * LINE_H_PROSE + 9
        h += 2 * ZONE_SM_H
    h += ILLO_FOOTER_H  # el pie de la lateral SIEMPRE lleva su propia ilustración
    return h * FUDGE


# ── Decisión de relleno ────────────────────────────────────────────────────
FILL_THRESHOLD = 180   # px mínimos de hueco para que merezca la pena rellenarlo
FILLER_MAX_H = 320     # tope de alto para el filler (no competir con la portada)
FILLER_BIAS = 0.85     # se queda corto a propósito: mejor un hueco pequeño que
                        # una columna que se pasa y desequilibra el diseño al revés


def plan_fillers(explainer_h, main_h, side_h, has_side):
    """{'explainer': alto_px, 'side': alto_px} para las columnas que se
    quedan cortas frente a la más alta de las tres — {} si ninguna lo
    merece. `main` nunca recibe filler: estructuralmente es casi siempre la
    más alta (portada + 2 leads + nota), y no tiene un hueco natural al
    final del diseño para colocarlo."""
    tallest = max(explainer_h, main_h, side_h if has_side else 0)
    out = {}
    if tallest - explainer_h > FILL_THRESHOLD:
        out["explainer"] = min((tallest - explainer_h) * FILLER_BIAS, FILLER_MAX_H)
    if has_side and tallest - side_h > FILL_THRESHOLD:
        out["side"] = min((tallest - side_h) * FILLER_BIAS, FILLER_MAX_H)
    return out
