"""Autocomprobación del broadsheet diario (sin framework, sin red).

Uso: python3 -m articles.test_generate
"""

from . import generate, render
from .writer import validate_grounding

_TEAM_A = {"nombre": "Eibar", "id": "3752", "logo": None, "posicion": 20,
           "zona": "Play-off de ascenso", "zona_key": "playoff",
           "prob_zona_actual": 22.1, "prob_zona_antes_del_partido": 25.7}
_TEAM_B = {"nombre": "Tenerife", "id": "245", "logo": None, "posicion": 2,
           "zona": "Descenso", "zona_key": "descenso",
           "prob_zona_actual": 27.8, "prob_zona_antes_del_partido": 38.8}
_TEAM_C = {"nombre": "Burgos", "id": "12597", "logo": None, "posicion": 4,
           "zona": "Play-off de ascenso", "zona_key": "playoff",
           "prob_zona_actual": 23.7, "prob_zona_antes_del_partido": 17.5}
_TEAM_D = {"nombre": "Córdoba", "id": "8447", "logo": None, "posicion": 17,
           "zona": "Descenso", "zona_key": "descenso",
           "prob_zona_actual": 25.5, "prob_zona_antes_del_partido": 23.0}

_PARTIDOS = [
    {"local": _TEAM_A, "visitante": _TEAM_B, "event_id": "401883229", "resultado": {"local": 1, "visitante": 3}},
    {"local": _TEAM_C, "visitante": _TEAM_D, "event_id": "401883230", "resultado": {"local": 3, "visitante": 2}},
]


def demo():
    # ── validate_grounding: cifra real (con redondeo) pasa, inventada no ──
    payload = {"tipo": "explicador_probabilidad",
               "probabilidades_por_zona": {"Play-off de ascenso": 33.2, "Descenso": 4.2}}
    ok, bad = validate_grounding("El modelo le da un 33% de play-off.", payload)
    assert ok, f"cifra real con redondeo no debería marcarse: {bad}"
    ok, bad = validate_grounding("Ya roza el 90% de play-off.", payload)
    assert not ok and bad == [90.0]

    # ── _pick_highlight_team_id: el mayor |delta| gana (Tenerife, 11.0 pp) ──
    assert generate._pick_highlight_team_id(_PARTIDOS) == "245"

    # ── _teaser: determinista, sin red ──
    t = render._teaser(_PARTIDOS)
    assert "Tenerife" in t and t.endswith(".")

    # ── _split_briefs: 1 párrafo por partido empareja; recuento roto degrada ──
    two_paras = "Párrafo del primer partido.\n\nPárrafo del segundo partido."
    pairs = render._split_briefs(two_paras, _PARTIDOS)
    assert pairs is not None and len(pairs) == 2
    assert render._split_briefs("Un solo párrafo.", _PARTIDOS) is None

    # ── render_broadsheet: smoke-test end-to-end sobre datos sintéticos ──
    payload_resumen = {"tipo": "resumen_diario", "liga": "Liga Hypermotion",
                        "temporada": "2026-27", "jornada": 1, "fecha": "2026-08-16",
                        "partidos": _PARTIDOS}
    payload_explainer = {"tipo": "explicador_probabilidad", "liga": "Liga Hypermotion",
                          "temporada": "2026-27", "jornada": 1,
                          "equipo": "Castellón", "equipo_id": "4438", "equipo_logo": None,
                          "posicion": 6, "puntos": 3, "pj": 1, "victorias": 1, "empates": 0,
                          "derrotas": 0, "rating_fuerza": -1.1994,
                          "probabilidades_por_zona": {"Ascenso directo": 7.4, "Play-off de ascenso": 33.2, "Descenso": 4.2},
                          "vecinos_en_la_tabla": []}
    explainer_body = ("Párrafo uno del explicador.\n\nPárrafo dos del explicador.\n\n"
                       "Párrafo tres, la nota del modelo.")
    html = render.render_broadsheet(payload_resumen, two_paras, payload_explainer, explainer_body,
                                     fecha="2026-08-16", league_logo=None)
    assert "<!DOCTYPE html>" in html
    assert "Castellón" in html and "Tenerife" in html
    assert "Nota del modelo" in html
    assert html.count("bs-brief__head") >= 2  # los 2 partidos como brief, no prosa degradada
    print("articles.test_generate: OK")


if __name__ == "__main__":
    demo()
