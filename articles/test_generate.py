"""Autocomprobación del broadsheet diario (sin framework, sin red).

Uso: python3 -m articles.test_generate
"""

import json

from . import generate, grounding, illustration, layout_estimate, render, writer
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

    # ── write_headline: el titular DEBE llevar un porcentaje (a petición
    # expresa, es lo que se manda tal cual a Telegram) — sin red, se
    # sustituye writer.generate por un doble determinista ──
    _orig_generate = writer.generate
    try:
        writer.generate = lambda prompt, temperature=0.9: "Titular sin cifra\nSubtítulo cualquiera"
        assert writer.write_headline({"tipo": "resumen_diario", "liga": "Liga Hypermotion"}) is None
        writer.generate = lambda prompt, temperature=0.9: "El play-off sube al 33%\nSubtítulo cualquiera"
        assert writer.write_headline({"tipo": "resumen_diario", "liga": "Liga Hypermotion", "x": 33.0}) == (
            "El play-off sube al 33%", "Subtítulo cualquiera")
    finally:
        writer.generate = _orig_generate

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
                                     league_slug="hypermotion", fecha="2026-08-16", league_logo=None,
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

    # ── illustration.pick: mismo (liga,fecha,variant) es determinista; avoid evita colisión ──
    a = illustration.pick("hypermotion", "2026-08-16", "cover")
    assert illustration.pick("hypermotion", "2026-08-16", "cover") == a
    b = illustration.pick("hypermotion", "2026-08-16", "explainer", avoid={a["file"]})
    assert b["file"] != a["file"]

    # ── render_broadsheet con filler: aparece una ilustración extra distinta de las demás ──
    html_filled = render.render_broadsheet(
        payload_resumen, two_paras, payload_explainer, explainer_body,
        league_slug="hypermotion", fecha="2026-08-16", league_logo=None, headline="Titular", subtitle="Subtítulo",
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
        league_slug="hypermotion", headline="Titular de partido", teaser="Entradilla de partido", league_logo=None,
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
    probe_slug = render.slug_for_match("hypermotion", "1999-01-01", "EquipoTestA", "EquipoTestB")
    probe_path = ARTICLES_OUT_DIR / f"{probe_slug}.html"
    assert not generate._match_already_handled("hypermotion", probe_payload)
    ARTICLES_OUT_DIR.mkdir(parents=True, exist_ok=True)
    probe_path.write_text("<html></html>", encoding="utf-8")
    try:
        assert generate._match_already_handled("hypermotion", probe_payload)
    finally:
        probe_path.unlink()

    # ── slug_for_match: determinista, sin acentos/mayúsculas, namespaced por liga ──
    assert render.slug_for_match("hypermotion", "2026-08-16", "Eibar", "Tenerife") == "hypermotion-eibar-tenerife-2026-08-16"
    assert render.slug_for_match("laliga", "2026-08-16", "Eibar", "Tenerife") == "laliga-eibar-tenerife-2026-08-16"

    # ── _team_headline: sube/baja/sin histórico ──
    up = render._team_headline({"zona": "Play-off", "prob_zona_actual": 30.0, "prob_zona_antes_del_partido": 20.0})
    down = render._team_headline({"zona": "Play-off", "prob_zona_actual": 10.0, "prob_zona_antes_del_partido": 20.0})
    first = render._team_headline({"zona": "Play-off", "prob_zona_actual": 15.0, "prob_zona_antes_del_partido": None})
    assert "sube al" in up and "cae al" in down and "queda en el" in first

    # ── _effective_bands / _match_side_summary: ascenso directo + play-off se
    # funden en "ascenso total" en la primera mitad de temporada; pasada la
    # mitad se listan por separado (política 2026-08-18) ──
    bands_hyper = [
        {"key": "ascenso", "label": "Ascenso directo", "zone": "promo"},
        {"key": "playoff", "label": "Play-off de ascenso", "zone": "playoff"},
        {"key": "descenso", "label": "Descenso", "zone": "relega"},
    ]
    team_mid = {"id": "9", "name": "Racing", "logo": None, "rank": 5, "pts": 10, "gp": 2,
                "wins": 3, "draws": 1, "losses": 0, "strength": 0.1,
                "prob": {"ascenso": 12.0, "playoff": 26.0, "descenso": 3.0, "ascenso_total": 38.0}}
    early = grounding._match_side_summary({"teams": [team_mid], "total_md": 42, "jornada": 2}, bands_hyper, {}, "9")
    late = grounding._match_side_summary({"teams": [team_mid], "total_md": 42, "jornada": 25}, bands_hyper, {}, "9")
    assert early["zona_key"] == "ascenso_total" and early["prob_zona_actual"] == 38.0
    assert late["zona_key"] == "playoff" and late["prob_zona_actual"] == 26.0
    # "zonas" completas (detalle real) nunca se funde, aunque la zona "mejor" sí
    assert {z["key"] for z in early["zonas"]} == {"ascenso", "playoff", "descenso"}
    # ligas sin play-off (bands sin 'playoff'): _effective_bands no toca nada
    bands_top1 = [{"key": "champions", "label": "Champions", "zone": "promo"},
                  {"key": "descenso", "label": "Descenso", "zone": "relega"}]
    assert grounding._effective_bands({"total_md": 42, "jornada": 2}, bands_top1) == bands_top1

    # ── grounding.pick_stat_kind: alterna por franja horaria + día, determinista ──
    assert grounding.pick_stat_kind(10, day=100) == grounding.pick_stat_kind(10, day=100)  # mismo día+hora -> mismo kind
    assert grounding.pick_stat_kind(10, day=100) != grounding.pick_stat_kind(12, day=100)  # franjas seguidas no repiten
    assert grounding.pick_stat_kind(10, day=100) != grounding.pick_stat_kind(10, day=101)  # mismo hora, día siguiente -> rota
    # el offset del día es lo que evita que el ciclo de 6 franjas deje un kind fuera:
    # a lo largo de len(STAT_KINDS) días a una hora fija se recorren TODOS los kinds
    n_kinds = len(grounding.STAT_KINDS)
    assert {grounding.pick_stat_kind(10, day=100 + d) for d in range(n_kinds)} == set(grounding.STAT_KINDS)

    # ── grounding.ground_stat: protagonista = mayor prob["last"]/["first"] ──
    bands_top1 = [{"key": "champions", "label": "Champions", "zone": "promo", "lo": 1, "hi": 4},
                  {"key": "descenso", "label": "Descenso", "zone": "relega", "lo": 18, "hi": 20}]
    snap_stat = {
        "season": "2026-27", "jornada": 1, "num_teams": 4, "bands": bands_top1, "total_md": 6,
        "teams": [
            {"id": "1", "name": "Tenerife", "logo": None, "rank": 2, "pts": 3, "gp": 1, "strength": -1.74,
             "prob": {"champions": 4.0, "descenso": 27.8, "first": 1.0, "last": 15.2}},
            {"id": "2", "name": "Córdoba", "logo": None, "rank": 5, "pts": 1, "gp": 1, "strength": -0.9,
             "prob": {"champions": 2.0, "descenso": 25.5, "first": 0.5, "last": 10.1}},
            {"id": "3", "name": "Albacete", "logo": None, "rank": 3, "pts": 3, "gp": 1, "strength": 0.2,
             "prob": {"champions": 10.0, "descenso": 20.6, "first": 3.0, "last": 8.4}},
            {"id": "4", "name": "Eibar", "logo": None, "rank": 1, "pts": 4, "gp": 1, "strength": 0.6,
             "prob": {"champions": 30.0, "descenso": 5.0, "first": 12.0, "last": 6.9}},
        ],
    }
    league_stat = {"slug": "hypermotion-test", "name": "Liga de prueba"}
    payload_stat = grounding.ground_stat(league_stat, snap_stat, "colista", "2026-08-19", 12)
    assert payload_stat["protagonista"]["nombre"] == "Tenerife"
    assert payload_stat["perseguidores"][0]["nombre"] == "Córdoba"
    assert len(payload_stat["perseguidores"]) == 3
    assert payload_stat["dato_verbo"] == "acabar colista"

    # ── grounding.format_val: % por defecto, goles/partido con signo (fmt "goles") ──
    assert grounding.format_val("colista", 15.2) == "15,2%"
    assert grounding.format_val("muro", -0.5) == "-0,50 goles/partido"

    # ── grounding._ground_equipo (kind "muro"): protagonista = menor def (blend) ──
    snap_equipo = dict(snap_stat)
    snap_equipo["teams"] = [
        {"id": "1", "name": "Tenerife", "logo": None, "rank": 2, "pts": 3, "gp": 1, "strength": -1.74, "att": 0.3, "def": -0.5,
         "prob": {"champions": 4.0, "descenso": 27.8, "first": 1.0, "last": 15.2}},
        {"id": "2", "name": "Córdoba", "logo": None, "rank": 5, "pts": 1, "gp": 1, "strength": -0.9, "att": -0.2, "def": -0.1,
         "prob": {"champions": 2.0, "descenso": 25.5, "first": 0.5, "last": 10.1}},
        {"id": "3", "name": "Albacete", "logo": None, "rank": 3, "pts": 3, "gp": 1, "strength": 0.2, "att": 0.5, "def": 0.2,
         "prob": {"champions": 10.0, "descenso": 20.6, "first": 3.0, "last": 8.4}},
        {"id": "4", "name": "Eibar", "logo": None, "rank": 1, "pts": 4, "gp": 1, "strength": 0.6, "att": 0.8, "def": 0.4,
         "prob": {"champions": 30.0, "descenso": 5.0, "first": 12.0, "last": 6.9}},
    ]
    payload_muro = grounding.ground_stat(league_stat, snap_equipo, "muro", "2026-08-19", 12)
    assert payload_muro["protagonista"]["nombre"] == "Tenerife"  # def -0,5 = la más baja = muro
    assert payload_muro["protagonista"]["valor"] == -0.5
    assert len(payload_muro["ranking"]) == 4

    # ── grounding._ground_jornada (kinds de la próxima jornada, modelo v3): la
    # próxima jornada se resuelve con el MISMO modelo del snapshot. Sin fixtures
    # (scoreboard vacío) no se publica (grounding, no inventar). ──
    snap_v3 = dict(snap_stat)
    snap_v3["strength_model"] = "v3"
    snap_v3["poisson_base"] = 1.3
    snap_v3["poisson_hfa"] = 0.25
    snap_v3["poisson_k_att"] = 0.7
    snap_v3["poisson_k_def"] = 0.7
    snap_v3["poisson_max_goals"] = 6
    snap_v3["teams"] = [
        {"id": "1", "name": "Tenerife", "logo": None, "rank": 2, "pts": 3, "gp": 1, "strength": -1.74, "att": 0.4, "def": -0.3,
         "prob": {"champions": 4.0, "descenso": 27.8, "first": 1.0, "last": 15.2}},
        {"id": "2", "name": "Córdoba", "logo": None, "rank": 5, "pts": 1, "gp": 1, "strength": -0.9, "att": -0.2, "def": -0.1,
         "prob": {"champions": 2.0, "descenso": 25.5, "first": 0.5, "last": 10.1}},
        {"id": "3", "name": "Albacete", "logo": None, "rank": 3, "pts": 3, "gp": 1, "strength": 0.2, "att": 0.5, "def": 0.2,
         "prob": {"champions": 10.0, "descenso": 20.6, "first": 3.0, "last": 8.4}},
        {"id": "4", "name": "Eibar", "logo": None, "rank": 1, "pts": 4, "gp": 1, "strength": 0.6, "att": 0.8, "def": 0.4,
         "prob": {"champions": 30.0, "descenso": 5.0, "first": 12.0, "last": 6.9}},
    ]
    league_jornada = {"slug": "hypermotion-test", "name": "Liga de prueba", "espn_code": "esp.2",
                      "p_home": 0.45, "p_draw": 0.26}
    real_fetch = grounding.espn.fetch_scoreboard_range

    def fake_scoreboard(code, start, end):
        assert code == "esp.2"
        return [
            {"event_id": "101", "date": "2026-08-25", "kickoff": "2026-08-25T19:00:00Z", "state": "pre",
             "home": {"id": 1, "name": "Tenerife"}, "away": {"id": 3, "name": "Albacete"},
             "home_score": None, "away_score": None, "venue": "Estadio"},
            {"event_id": "102", "date": "2026-08-26", "kickoff": "2026-08-26T19:00:00Z", "state": "pre",
             "home": {"id": 4, "name": "Eibar"}, "away": {"id": 2, "name": "Córdoba"},
             "home_score": None, "away_score": None, "venue": "Estadio"},
            {"event_id": "999", "date": "2026-08-24", "kickoff": "2026-08-24T17:00:00Z", "state": "post",
             "home": {"id": 1, "name": "Tenerife"}, "away": {"id": 2, "name": "Córdoba"},
             "home_score": 1, "away_score": 1, "venue": "Estadio"},
        ]

    try:
        grounding.espn.fetch_scoreboard_range = fake_scoreboard

        # sin fixtures: la próxima jornada no existe -> no se publica (None)
        grounding.espn.fetch_scoreboard_range = lambda code, a, b: []
        assert grounding.ground_stat(league_jornada, snap_v3, "goleado", "2026-08-19", 12) is None

        grounding.espn.fetch_scoreboard_range = fake_scoreboard

        payload_gol = grounding.ground_stat(league_jornada, snap_v3, "goleado", "2026-08-19", 12)
        assert payload_gol is not None and payload_gol["shape"] == "team"
        assert len(payload_gol["ranking"]) == 4
        assert all(0 <= r["valor"] <= 100 for r in payload_gol["ranking"])

        payload_fav = grounding.ground_stat(league_jornada, snap_v3, "favorito_jornada", "2026-08-19", 12)
        assert payload_fav is not None
        assert payload_fav["protagonista"]["nombre"] in {"Tenerife", "Córdoba", "Albacete", "Eibar"}

        payload_nivel = grounding.ground_stat(league_jornada, snap_v3, "nivel_jornada", "2026-08-19", 12)
        assert payload_nivel is not None and payload_nivel["shape"] == "partido"
        prot = payload_nivel["protagonista"]
        assert prot["tipo"] == "partido" and " vs " in prot["nombre"]
        assert 0 <= prot["p_local"] <= 100 and 0 <= prot["p_visita"] <= 100
        assert abs((prot["p_local"] + prot["p_empate"] + prot["p_visita"]) - 100) < 1
        assert all(it["tipo"] == "partido" for it in payload_nivel["ranking"])

        payload_pc = grounding.ground_stat(league_jornada, snap_v3, "porteria_cero", "2026-08-19", 12)
        assert payload_pc is not None and payload_pc["shape"] == "team"
        assert all(0 <= r["valor"] <= 100 for r in payload_pc["ranking"])

        payload_emp = grounding.ground_stat(league_jornada, snap_v3, "empate_jornada", "2026-08-19", 12)
        assert payload_emp is not None and payload_emp["shape"] == "partido"
        assert abs(payload_emp["protagonista"]["valor"] - payload_emp["protagonista"]["p_empate"]) < 0.1

        payload_gol = grounding.ground_stat(league_jornada, snap_v3, "goles_jornada", "2026-08-19", 12)
        assert payload_gol is not None and payload_gol["shape"] == "partido"
        assert payload_gol["protagonista"]["valor"] > 0
    finally:
        grounding.espn.fetch_scoreboard_range = real_fetch

    # ── render_stat_broadsheet: smoke-test end-to-end sobre datos sintéticos ──
    stat_body_4p = "Uno.\n\nDos.\n\nTres.\n\nCuatro."
    stat_chasers_3p = "Uno.\n\nDos.\n\nTres."
    html_stat = render.render_stat_broadsheet(
        payload_stat, stat_body_4p, stat_chasers_3p,
        league_slug="hypermotion", headline="Tenerife roza el 15% de acabar colista", teaser="Entradilla del dato",
        league_logo=None,
    )
    assert "<!DOCTYPE html>" in html_stat
    assert "Tenerife" in html_stat and "Córdoba" in html_stat
    assert "Tenerife roza el 15%" in html_stat and "Entradilla del dato" in html_stat
    assert "Ficha del dato" in html_stat and "Cómo se calcula" in html_stat
    assert html_stat.count("bs-chaser__row") == 3

    # render de un kind shape="partido": cabecera con los dos equipos + 1X2
    html_match_stat = render.render_stat_broadsheet(
        payload_nivel, stat_body_4p, stat_chasers_3p,
        league_slug="hypermotion", headline="El partido de la jornada", teaser="Entradilla del dato",
        league_logo=None,
    )
    assert " vs " in html_match_stat and "Ficha del dato" in html_match_stat
    assert "1X2" in html_match_stat and "bs-rankbox" in html_match_stat

    # ── slug_for_stat: determinista, namespaced por liga+kind+fecha+hora ──
    assert render.slug_for_stat("hypermotion", "2026-08-19", 12, "colista") == "hypermotion-dato-colista-2026-08-19-12"

    # ── _stat_already_handled: idempotencia sin red (existe HTML -> True) ──
    probe_slug = render.slug_for_stat("hypermotion", "1999-01-01", 10, "colista")
    probe_path = ARTICLES_OUT_DIR / f"{probe_slug}.html"
    assert not generate._stat_already_handled("hypermotion", "1999-01-01", 10, "colista")
    ARTICLES_OUT_DIR.mkdir(parents=True, exist_ok=True)
    probe_path.write_text("<html></html>", encoding="utf-8")
    try:
        assert generate._stat_already_handled("hypermotion", "1999-01-01", 10, "colista")
    finally:
        probe_path.unlink()

    # ── _article_meta_from_file / _write_articles_index: self-healing, se
    # reconstruye escaneando articulos/*.html (sin estado propio) — así un
    # artículo publicado antes de que existiera el índice aparece igual ──
    from .config import DATA_DIR

    def _write_probe(stem, title):
        p = ARTICLES_OUT_DIR / f"{stem}.html"
        p.write_text(f"<html><head><title>{title} | PredictMotion</title></head></html>", encoding="utf-8")
        return p

    probes = [
        _write_probe("hypermotion-resumen-1999-01-01", "Resumen de prueba"),
        _write_probe("hypermotion-dato-colista-1999-01-01-10", "Dato de prueba"),
        _write_probe("hypermotion-equipoa-equipob-1999-01-01", "Crónica de prueba"),
        _write_probe("hypermotion-jornada-1-recap", "Resto de un sistema viejo, sin fecha"),
    ]
    try:
        assert generate._article_meta_from_file(probes[0]) == ("diario", "hypermotion", "1999-01-01", "Resumen de prueba")
        assert generate._article_meta_from_file(probes[1]) == ("dato", "hypermotion", "1999-01-01", "Dato de prueba")
        assert generate._article_meta_from_file(probes[2]) == ("partido", "hypermotion", "1999-01-01", "Crónica de prueba")
        assert generate._article_meta_from_file(probes[3]) is None  # sin fecha final -> no encaja ningún patrón

        generate._write_articles_index()
        index = json.loads((DATA_DIR / "articles" / "index.json").read_text(encoding="utf-8"))
        slugs_1999 = {it["slug"]: it["tipo"] for it in index if it["fecha"] == "1999-01-01"}
        assert slugs_1999 == {
            "hypermotion-resumen-1999-01-01": "diario",
            "hypermotion-dato-colista-1999-01-01-10": "dato",
            "hypermotion-equipoa-equipob-1999-01-01": "partido",
        }
    finally:
        for p in probes:
            p.unlink()

    print("articles.test_generate: OK")


if __name__ == "__main__":
    demo()
