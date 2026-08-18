"""Autocomprobación del broadsheet diario (sin framework, sin red).

Uso: python3 -m articles.test_generate
"""

from . import generate, illustration, layout_estimate, render
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

    # ── _pick_tweet_cta: determinista por fecha, siempre del pool ──
    cta = generate._pick_tweet_cta("2026-08-17")
    assert cta == generate._pick_tweet_cta("2026-08-17")
    assert cta in generate._TWEET_CTAS

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
                                     fecha="2026-08-16", league_logo=None,
                                     headline="Titular de prueba", subtitle="Subtítulo de prueba")
    assert "<!DOCTYPE html>" in html
    assert "Castellón" in html and "Tenerife" in html
    assert "Nota del modelo" in html
    assert "Titular de prueba" in html and "Subtítulo de prueba" in html
    assert html.count("bs-brief__head") >= 2  # los 2 partidos como brief, no prosa degradada

    # ── layout_estimate: una columna mucho más corta pide relleno ──
    fillers = layout_estimate.plan_fillers(explainer_h=400, main_h=1200, side_h=0, has_side=False)
    assert "explainer" in fillers and 0 < fillers["explainer"] <= layout_estimate.FILLER_MAX_H
    assert layout_estimate.plan_fillers(explainer_h=1150, main_h=1200, side_h=0, has_side=False) == {}

    # ── illustration.pick: mismo (fecha,variant) es determinista; avoid evita colisión ──
    a = illustration.pick("2026-08-16", "cover")
    assert illustration.pick("2026-08-16", "cover") == a
    b = illustration.pick("2026-08-16", "explainer", avoid={a["file"]})
    assert b["file"] != a["file"]

    # ── render_broadsheet con filler: aparece una ilustración extra distinta de las demás ──
    html_filled = render.render_broadsheet(
        payload_resumen, two_paras, payload_explainer, explainer_body,
        fecha="2026-08-16", league_logo=None, headline="Titular", subtitle="Subtítulo",
        explainer_filler_h=250,
    )
    assert html_filled.count("<figure") == 3  # portada + explicador + hueco extra (2 partidos, sin lateral)
    assert "height:250px" in html_filled
    # ── render_match_broadsheet: smoke-test end-to-end sobre datos sintéticos ──
    def _side(nombre, id_, posicion, puntos, zona, zona_key, actual, antes, strength):
        return {
            "nombre": nombre, "id": id_, "logo": None, "posicion": posicion, "puntos": puntos,
            "pj": 1, "victorias": 1, "empates": 0, "derrotas": 0, "rating_fuerza": strength,
            "zona": zona, "zona_key": zona_key,
            "prob_zona_actual": actual, "prob_zona_antes_del_partido": antes,
            "zonas": [
                {"label": "Ascenso directo", "key": "ascenso", "actual": 4.9, "antes": 6.7},
                {"label": "Play-off de ascenso", "key": "playoff", "actual": actual, "antes": antes},
                {"label": "Descenso", "key": "descenso", "actual": 12.7, "antes": 8.6},
            ],
        }

    payload_match = {
        "tipo": "match_cronica", "liga": "Liga Hypermotion", "temporada": "2026-27", "jornada": 1,
        "fecha": "2026-08-16", "event_id": "401883229", "estadio": "Ipurua", "hora": "21:00",
        "local": _side("Eibar", "3752", 20, 0, "Play-off de ascenso", "playoff", 22.1, 25.7, -0.8421),
        "visitante": _side("Tenerife", "245", 2, 3, "Descenso", "descenso", 27.8, 38.8, 1.1203),
        "resultado": {"local": 1, "visitante": 3},
    }
    match_body_3p = "Párrafo uno.\n\nPárrafo dos.\n\nPárrafo tres."
    match_body_4p = "Uno.\n\nDos.\n\nTres.\n\nCuatro."
    html_match = render.render_match_broadsheet(
        payload_match, match_body_3p, match_body_3p, match_body_4p,
        headline="Titular de partido", teaser="Entradilla de partido", league_logo=None,
    )
    assert "<!DOCTYPE html>" in html_match
    assert "Eibar" in html_match and "Tenerife" in html_match
    assert "Titular de partido" in html_match and "Entradilla de partido" in html_match
    assert "Ficha del partido" in html_match and "Movimientos del modelo" in html_match and "Lectura del modelo" in html_match
    assert html_match.count("<figure") == 3  # portada + local + visitante
    assert "1–3" in html_match

    # ── _match_already_handled: idempotencia sin red (existe HTML -> True) ──
    from .config import ARTICLES_OUT_DIR
    probe_payload = {"fecha": "1999-01-01",
                      "local": {"nombre": "EquipoTestA", "id": "1"},
                      "visitante": {"nombre": "EquipoTestB", "id": "2"}}
    probe_slug = render.slug_for_match("1999-01-01", "EquipoTestA", "EquipoTestB")
    probe_path = ARTICLES_OUT_DIR / f"{probe_slug}.html"
    assert not generate._match_already_handled(probe_payload)
    ARTICLES_OUT_DIR.mkdir(parents=True, exist_ok=True)
    probe_path.write_text("<html></html>", encoding="utf-8")
    try:
        assert generate._match_already_handled(probe_payload)
    finally:
        probe_path.unlink()

    # ── slug_for_match: determinista y sin acentos/mayúsculas ──
    assert render.slug_for_match("2026-08-16", "Eibar", "Tenerife") == "hypermotion-eibar-tenerife-2026-08-16"

    # ── _team_headline: sube/baja/sin histórico ──
    up = render._team_headline({"zona": "Play-off", "prob_zona_actual": 30.0, "prob_zona_antes_del_partido": 20.0})
    down = render._team_headline({"zona": "Play-off", "prob_zona_actual": 10.0, "prob_zona_antes_del_partido": 20.0})
    first = render._team_headline({"zona": "Play-off", "prob_zona_actual": 15.0, "prob_zona_antes_del_partido": None})
    assert "sube al" in up and "cae al" in down and "queda en el" in first

    print("articles.test_generate: OK")


if __name__ == "__main__":
    demo()
