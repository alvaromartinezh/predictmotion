"""Autocomprobación del broadsheet diario (sin framework, sin red).

Uso: python3 -m articles.test_generate
"""

import json
import shutil

from . import generate, grounding, illustration, layout_estimate, render, writer
from .config import ARTICLES_OUT_DIR, DATA_DIR
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
    # el offset del día es lo que evita que el ciclo de 7 franjas deje kinds fuera:
    # a lo largo de len(STAT_KINDS) días a una hora fija se recorren TODOS los kinds
    n_kinds = len(grounding.STAT_KINDS)
    assert {grounding.pick_stat_kind(10, day=100 + d) for d in range(n_kinds)} == set(grounding.STAT_KINDS)
    # si el kind base ya está usado en la jornada, salta al siguiente disponible
    base_kind = grounding.pick_stat_kind(10, day=100)
    next_kind = grounding.pick_stat_kind(10, day=100, used=[base_kind])
    assert next_kind != base_kind
    assert next_kind in grounding.STAT_KINDS
    # si todos los kinds están usados, cae al kind base (repetición inevitable)
    assert grounding.pick_stat_kind(10, day=100, used=list(grounding.STAT_KINDS)) == base_kind

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
            {"id": "5", "name": "Oviedo", "logo": None, "rank": 6, "pts": 1, "gp": 1, "strength": -0.3,
             "prob": {"champions": 1.0, "descenso": 28.0, "first": 0.2, "last": 9.5}},
        ],
    }
    league_stat = {"slug": "hypermotion-test", "name": "Liga de prueba"}
    payload_stat = grounding.ground_stat(league_stat, snap_stat, "colista", "2026-08-19", 12)
    assert payload_stat["protagonista"]["nombre"] == "Tenerife"
    assert payload_stat["perseguidores"][0]["nombre"] == "Córdoba"
    assert len(payload_stat["perseguidores"]) == 3
    assert payload_stat["dato_verbo"] == "acabar colista"

    # ── grounding.format_val: % por defecto, goles/partido con signo (fmt "goles"),
    # goles esperados (fmt "goles_abs") y delta en pp (fmt "pp") ──
    assert grounding.format_val("colista", 15.2) == "15,2%"
    assert grounding.format_val("muro", -0.5) == "-0,50 goles/partido"
    assert grounding.format_val("sorpresa_temporada", 15.0) == "+15,0 pp"

    # ── grounding._ground_posicion con exclude_rank_1: tapado salta al líder actual ──
    payload_tapado = grounding.ground_stat(league_stat, snap_stat, "tapado", "2026-08-19", 12)
    assert payload_tapado["protagonista"]["nombre"] != "Eibar"  # Eibar es líder (rank 1)
    assert payload_tapado["protagonista"]["posicion"] != 1

    # ── grounding._ground_zona: suma de probabilidades de bandas mejores/peores ──
    bands_zona = [
        {"key": "ascenso", "label": "Ascenso directo", "zone": "promo", "lo": 1, "hi": 2},
        {"key": "playoff", "label": "Play-off", "zone": "playoff", "lo": 3, "hi": 6},
        {"key": "permanencia", "label": "Permanencia", "zone": None, "lo": 7, "hi": 18},
        {"key": "descenso", "label": "Descenso", "zone": "relega", "lo": 19, "hi": 22},
    ]
    snap_zona = {
        "season": "2026-27", "jornada": 10, "num_teams": 22, "bands": bands_zona, "total_md": 42,
        "teams": [
            {"id": "1", "name": "Líder", "logo": None, "rank": 1, "pts": 25, "gp": 10,
             "prob": {"ascenso": 75.0, "playoff": 20.0, "permanencia": 4.0, "descenso": 0.5}},
            {"id": "2", "name": "Playoff", "logo": None, "rank": 4, "pts": 18, "gp": 10,
             "prob": {"ascenso": 30.0, "playoff": 55.0, "permanencia": 10.0, "descenso": 1.0}},
            {"id": "3", "name": "Permanencia", "logo": None, "rank": 10, "pts": 14, "gp": 10,
             "prob": {"ascenso": 5.0, "playoff": 25.0, "permanencia": 45.0, "descenso": 20.0}},
            {"id": "4", "name": "Descenso", "logo": None, "rank": 20, "pts": 8, "gp": 10,
             "prob": {"ascenso": 1.0, "playoff": 5.0, "permanencia": 20.0, "descenso": 70.0}},
            {"id": "5", "name": "Castellón", "logo": None, "rank": 8, "pts": 13, "gp": 10,
             "prob": {"ascenso": 2.0, "playoff": 10.0, "permanencia": 60.0, "descenso": 5.0}},
        ],
    }
    league_zona = {"slug": "hypermotion-test", "name": "Liga de prueba"}
    payload_subida = grounding.ground_stat(league_zona, snap_zona, "subida_zona", "2026-08-19", 12)
    assert payload_subida is not None
    # Permanencia (rank 10) tiene mejor zona ascenso+playoff = 30; Playoff tiene ascenso = 30; Descenso = 6
    assert payload_subida["protagonista"]["nombre"] in {"Permanencia", "Playoff"}
    payload_caida = grounding.ground_stat(league_zona, snap_zona, "caida_zona", "2026-08-19", 12)
    assert payload_caida is not None
    # Líder tiene abajo playoff+descenso = 20.5; Playoff tiene descenso = 1.0
    assert payload_caida["protagonista"]["nombre"] == "Líder"

    # ── grounding._ground_temporada: mejora de mejor zona vs primer snapshot (fmt "pp") ──
    first_snap = {
        "season": "2026-27", "date": "2026-08-01", "jornada": 0, "num_teams": 5,
        "bands": bands_top1, "total_md": 6,
        "teams": [
            {"id": "1", "name": "Tenerife", "prob": {"champions": 5.0, "descenso": 25.0, "first": 1.0, "last": 15.0}},
            {"id": "2", "name": "Córdoba", "prob": {"champions": 5.0, "descenso": 25.0, "first": 1.0, "last": 15.0}},
            {"id": "3", "name": "Albacete", "prob": {"champions": 5.0, "descenso": 25.0, "first": 1.0, "last": 15.0}},
            {"id": "4", "name": "Eibar", "prob": {"champions": 5.0, "descenso": 25.0, "first": 1.0, "last": 15.0}},
            {"id": "5", "name": "Oviedo", "prob": {"champions": 5.0, "descenso": 25.0, "first": 1.0, "last": 15.0}},
        ],
    }
    real_load_all = grounding.load_all
    grounding.load_all = lambda slug, season: [first_snap]
    try:
        payload_temp = grounding.ground_stat(league_stat, snap_stat, "sorpresa_temporada", "2026-08-19", 12)
        assert payload_temp is not None
        assert payload_temp["protagonista"]["valor"] > 0
        assert grounding.format_val("sorpresa_temporada", payload_temp["protagonista"]["valor"]).endswith(" pp")
    finally:
        grounding.load_all = real_load_all

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

        # nuevos kinds de partido y equipo de la próxima jornada
        payload_over = grounding.ground_stat(league_jornada, snap_v3, "over_25", "2026-08-19", 12)
        assert payload_over is not None and payload_over["shape"] == "partido"
        assert all(0 <= it["valor"] <= 100 for it in payload_over["ranking"])

        payload_btts = grounding.ground_stat(league_jornada, snap_v3, "ambos_marcan", "2026-08-19", 12)
        assert payload_btts is not None and payload_btts["shape"] == "partido"

        payload_sorp = grounding.ground_stat(league_jornada, snap_v3, "sorpresa_jornada", "2026-08-19", 12)
        assert payload_sorp is not None and payload_sorp["shape"] == "partido"

        payload_marc = grounding.ground_stat(league_jornada, snap_v3, "marcador_jornada", "2026-08-19", 12)
        assert payload_marc is not None and payload_marc["shape"] == "partido"
        assert payload_marc["protagonista"].get("marcador") is not None
        assert "-" in payload_marc["protagonista"]["marcador"]

        payload_goleador = grounding.ground_stat(league_jornada, snap_v3, "goleador", "2026-08-19", 12)
        assert payload_goleador is not None and payload_goleador["shape"] == "team"
        assert all(0 <= r["valor"] <= 100 for r in payload_goleador["ranking"])

        payload_inv = grounding.ground_stat(league_jornada, snap_v3, "invicto_jornada", "2026-08-19", 12)
        assert payload_inv is not None and payload_inv["shape"] == "team"

        payload_der = grounding.ground_stat(league_jornada, snap_v3, "derrota_jornada", "2026-08-19", 12)
        assert payload_der is not None and payload_der["shape"] == "team"

        # Nuevos kinds de jornada (segunda tanda)
        payload_menos_fav = grounding.ground_stat(league_jornada, snap_v3, "menos_favorito_jornada", "2026-08-19", 12)
        assert payload_menos_fav is not None and payload_menos_fav["shape"] == "team"

        payload_under_j = grounding.ground_stat(league_jornada, snap_v3, "under_jornada", "2026-08-19", 12)
        assert payload_under_j is not None and payload_under_j["shape"] == "team"

        payload_sin_gol = grounding.ground_stat(league_jornada, snap_v3, "sin_gol_jornada", "2026-08-19", 12)
        assert payload_sin_gol is not None and payload_sin_gol["shape"] == "team"

        payload_under_25 = grounding.ground_stat(league_jornada, snap_v3, "under_25", "2026-08-19", 12)
        assert payload_under_25 is not None and payload_under_25["shape"] == "partido"

        payload_local_claro = grounding.ground_stat(league_jornada, snap_v3, "local_claro", "2026-08-19", 12)
        assert payload_local_claro is not None and payload_local_claro["shape"] == "partido"

        payload_visitante_claro = grounding.ground_stat(league_jornada, snap_v3, "visitante_claro", "2026-08-19", 12)
        assert payload_visitante_claro is not None and payload_visitante_claro["shape"] == "partido"
    finally:
        grounding.espn.fetch_scoreboard_range = real_fetch

    # ── grounding.ground_previa_diaria: TODOS los partidos 'pre' de hoy,
    # 1X2 vía el dispatcher central (mismo snap_v3 de _ground_jornada), sin
    # "antes/después" porque el partido no se ha jugado ──
    matches_previa = [
        {"event_id": "201", "date": "2026-08-19", "kickoff": "2026-08-19T19:00:00Z", "state": "pre",
         "home": {"id": 1, "name": "Tenerife"}, "away": {"id": 3, "name": "Albacete"},
         "home_score": None, "away_score": None, "venue": "Heliodoro"},
        {"event_id": "202", "date": "2026-08-19", "kickoff": "2026-08-19T21:00:00Z", "state": "pre",
         "home": {"id": 4, "name": "Eibar"}, "away": {"id": 2, "name": "Córdoba"},
         "home_score": None, "away_score": None, "venue": "Ipurua"},
    ]
    payload_previa = grounding.ground_previa_diaria(league_jornada, snap_v3, matches_previa)
    assert payload_previa["tipo"] == "previa_diaria" and payload_previa["fecha"] == "2026-08-19"
    assert len(payload_previa["partidos"]) == 2
    m0 = payload_previa["partidos"][0]
    assert m0["local"]["nombre"] == "Tenerife" and m0["visitante"]["nombre"] == "Albacete"
    assert m0["hora"] == "21:00"  # 19:00 UTC -> CEST (+2)
    assert 95.0 <= m0["p_local"] + m0["p_empate"] + m0["p_visita"] <= 100.0  # Poisson truncado a max_goals
    assert m0["local"]["prob_zona_antes_del_partido"] is None

    # ── generate._pick_preview_team_id: el mayor favorito del día ──
    team_id = generate._pick_preview_team_id(payload_previa["partidos"])
    assert team_id in ("1", "2", "3", "4")

    # ── render_previa_broadsheet: smoke-test end-to-end ──
    html_previa = render.render_previa_broadsheet(
        payload_previa, two_paras, payload_explainer, explainer_body,
        league_slug="hypermotion", fecha="2026-08-19", league_logo=None,
        headline="Titular de previa", subtitle="Subtítulo de previa",
    )
    assert "<!DOCTYPE html>" in html_previa
    assert "Tenerife" in html_previa and "Albacete" in html_previa
    assert "Titular de previa" in html_previa and "Subtítulo de previa" in html_previa
    assert "Previa del día" in html_previa
    assert html_previa.count("bs-brief__head") >= 2

    # ── slug_for_previa / _previa_already_handled: namespaced, idempotente ──
    assert render.slug_for_previa("hypermotion", "2026-08-19") == "hypermotion-previa-2026-08-19"
    assert not generate._previa_already_handled("hypermotion-test-x", "1999-01-01")
    probe_previa_path = ARTICLES_OUT_DIR / f"{render.slug_for_previa('hypermotion-test-x', '1999-01-01')}.html"
    ARTICLES_OUT_DIR.mkdir(parents=True, exist_ok=True)
    probe_previa_path.write_text("<html></html>", encoding="utf-8")
    try:
        assert generate._previa_already_handled("hypermotion-test-x", "1999-01-01")
    finally:
        probe_previa_path.unlink()

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

    # ── _rebuild_stat_kinds_state / _stat_kinds_used_for_matchday: self-healing,
    # no se repite kind dentro de la misma jornada de competición ──
    state_path = DATA_DIR / "articles" / "stat_kinds_used.json"
    state_backup = state_path.read_text(encoding="utf-8") if state_path.exists() else None
    league_slug = "hypermotiontest"  # slug sin guiones para que _DATO_SLUG_RE haga match
    season, jornada, fecha_test = "2026-27", 5, "2026-08-20"
    day_int = int(fecha_test.replace("-", ""))
    base_kind = grounding.pick_stat_kind(10, day=day_int)
    snap_dir = DATA_DIR / league_slug / season / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f"{fecha_test}.json"
    snap_path.write_text(json.dumps({"date": fecha_test, "jornada": jornada, "teams": []}), encoding="utf-8")
    dato_path = ARTICLES_OUT_DIR / f"{league_slug}-dato-{base_kind}-{fecha_test}-10.html"
    ARTICLES_OUT_DIR.mkdir(parents=True, exist_ok=True)
    dato_path.write_text("<html></html>", encoding="utf-8")
    try:
        rebuilt = generate._rebuild_stat_kinds_state(league_slug)
        assert rebuilt.get(f"{season}|{jornada}") == [base_kind]
        used = generate._stat_kinds_used_for_matchday(league_slug, season, jornada)
        assert used == [base_kind]
        # ahora pick_stat_kind a la misma hora/día evita el kind ya usado
        assert grounding.pick_stat_kind(10, day=day_int, used=used) != base_kind
    finally:
        dato_path.unlink(missing_ok=True)
        snap_path.unlink(missing_ok=True)
        if (DATA_DIR / league_slug).exists():
            shutil.rmtree(DATA_DIR / league_slug)
        if state_backup is not None:
            state_path.write_text(state_backup, encoding="utf-8")
        elif state_path.exists():
            state_path.unlink()

    # ── Sanity check de TODOS los kinds (segunda tanda incluida) ──
    required_fields = {"tipo", "eyebrow", "verbo", "verbo_largo", "dato_label"}
    for kind, info in grounding.STAT_KINDS.items():
        missing = required_fields - set(info)
        assert not missing, f"{kind} falta {missing}"
        if info["tipo"] == "posicion":
            assert "prob_key" in info, f"{kind} es posicion sin prob_key"
        if info["tipo"] == "equipo":
            assert "campo" in info and "sort" in info, f"{kind} es equipo sin campo/sort"
        if info["tipo"] == "zona_especifica":
            assert "zone_type" in info, f"{kind} es zona_especifica sin zone_type"
        if info["tipo"] == "goles":
            assert "campo" in info and "sort" in info, f"{kind} es goles sin campo/sort"

    # Snapshot completo para probar kinds snapshot-based de la segunda tanda
    bands_full = [
        {"key": "ascenso", "label": "Ascenso directo", "zone": "promo", "lo": 1, "hi": 2},
        {"key": "playoff", "label": "Play-off", "zone": "playoff", "lo": 3, "hi": 6},
        {"key": "permanencia", "label": "Permanencia", "zone": None, "lo": 7, "hi": 18},
        {"key": "descenso", "label": "Descenso", "zone": "relega", "lo": 19, "hi": 22},
    ]
    snap_full = {
        "season": "2026-27", "jornada": 5, "num_teams": 22, "bands": bands_full, "total_md": 42,
        "teams": [
            {"id": "1", "name": "Líder", "logo": None, "rank": 1, "pts": 13, "gp": 5, "gf": 12, "gc": 3,
             "att": 0.8, "def": -0.6,
             "prob": {"ascenso": 55.0, "playoff": 30.0, "permanencia": 12.0, "descenso": 1.0,
                      "first": 25.0, "last": 0.1}},
            {"id": "2", "name": "Playoff", "logo": None, "rank": 4, "pts": 10, "gp": 5, "gf": 8, "gc": 7,
             "att": 0.3, "def": -0.1,
             "prob": {"ascenso": 20.0, "playoff": 45.0, "permanencia": 25.0, "descenso": 5.0,
                      "first": 5.0, "last": 1.0}},
            {"id": "3", "name": "Permanencia", "logo": None, "rank": 10, "pts": 7, "gp": 5, "gf": 5, "gc": 8,
             "att": -0.2, "def": 0.2,
             "prob": {"ascenso": 5.0, "playoff": 15.0, "permanencia": 50.0, "descenso": 20.0,
                      "first": 0.5, "last": 5.0}},
            {"id": "4", "name": "Descenso", "logo": None, "rank": 20, "pts": 3, "gp": 5, "gf": 3, "gc": 12,
             "att": -0.5, "def": 0.7,
             "prob": {"ascenso": 1.0, "playoff": 4.0, "permanencia": 25.0, "descenso": 60.0,
                      "first": 0.1, "last": 15.0}},
            {"id": "5", "name": "Colista", "logo": None, "rank": 22, "pts": 1, "gp": 5, "gf": 2, "gc": 14,
             "att": -0.8, "def": 1.0,
             "prob": {"ascenso": 0.5, "playoff": 2.0, "permanencia": 12.0, "descenso": 75.0,
                      "first": 0.0, "last": 35.0}},
        ],
    }
    league_full = {"slug": "hypermotiontest", "name": "Liga de prueba"}

    # Zonas específicas
    for kind in ["descenso", "ascenso_directo", "playoff"]:
        p = grounding.ground_stat(league_full, snap_full, kind, "2026-08-20", 12)
        assert p is not None, f"{kind} debería tener payload"
    # champions no existe en esta liga -> None
    assert grounding.ground_stat(league_full, snap_full, "champions", "2026-08-20", 12) is None

    # Fuerza cara B
    assert grounding.ground_stat(league_full, snap_full, "coladero", "2026-08-20", 12)["protagonista"]["nombre"] == "Colista"
    assert grounding.ground_stat(league_full, snap_full, "peor_ataque", "2026-08-20", 12)["protagonista"]["nombre"] == "Colista"
    assert grounding.ground_stat(league_full, snap_full, "equilibrio", "2026-08-20", 12)["protagonista"]["nombre"] == "Líder"
    assert grounding.ground_stat(league_full, snap_full, "desequilibrio", "2026-08-20", 12)["protagonista"]["nombre"] == "Colista"

    # Goles reales
    assert grounding.ground_stat(league_full, snap_full, "goleador_real", "2026-08-20", 12)["protagonista"]["nombre"] == "Líder"
    assert grounding.ground_stat(league_full, snap_full, "coladero_real", "2026-08-20", 12)["protagonista"]["nombre"] == "Colista"
    assert grounding.ground_stat(league_full, snap_full, "efectividad", "2026-08-20", 12)["protagonista"]["valor"] > 0

    # Ranking vs prob
    subrep = grounding.ground_stat(league_full, snap_full, "subrepresentado", "2026-08-20", 12)
    assert subrep is not None
    assert grounding.format_val("subrepresentado", subrep["protagonista"]["valor"]).endswith(" posiciones")

    # Temporada con direction
    first_snap_full = {
        "season": "2026-27", "date": "2026-08-01", "jornada": 0, "num_teams": 22,
        "bands": bands_full, "total_md": 42,
        "teams": [
            {"id": "1", "name": "Líder", "prob": {"ascenso_total": 80.0, "permanencia": 10.0, "descenso": 5.0}},
            {"id": "2", "name": "Playoff", "prob": {"playoff": 40.0, "permanencia": 45.0, "descenso": 10.0}},
            {"id": "3", "name": "Permanencia", "prob": {"ascenso_total": 15.0, "permanencia": 55.0, "descenso": 20.0}},
            {"id": "4", "name": "Descenso", "prob": {"ascenso_total": 10.0, "permanencia": 25.0, "descenso": 65.0}},
            {"id": "5", "name": "Colista", "prob": {"playoff": 5.0, "permanencia": 10.0, "descenso": 80.0}},
        ],
    }
    real_load_all = grounding.load_all
    grounding.load_all = lambda slug, season: [first_snap_full]
    try:
        decep = grounding.ground_stat(league_full, snap_full, "decepcion_temporada", "2026-08-20", 12)
        assert decep is not None
        estab = grounding.ground_stat(league_full, snap_full, "estabilidad_temporada", "2026-08-20", 12)
        assert estab is not None
    finally:
        grounding.load_all = real_load_all

    # ── Resiliencia del cron (dos caídas reales, 2026-08) ──────────────────
    # 1) round(None): los *_val() devuelven None cuando el equipo previo no tiene
    #    datos (gp==0 a principio de temporada) y ground_stat() moría entero.
    assert grounding._round_or_none(None, 2) is None
    assert grounding._round_or_none(1.23456, 2) == 1.23
    assert grounding._round_or_none(0, 1) == 0        # 0 no es None: debe pasar

    # 2) TimeoutError de urlopen() no es URLError: se escapaba de los except de
    #    _call() y abortaba la liga entera en vez de saltarse UN artículo.
    import urllib.request
    from . import gemini_client
    _real = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(TimeoutError())
    try:
        gemini_client._call("hola", 0.6)
    except gemini_client.GeminiError as e:
        assert "Timeout" in str(e), e
    else:
        raise AssertionError("un TimeoutError debe salir como GeminiError")
    finally:
        urllib.request.urlopen = _real

    print("articles.test_generate: OK")


if __name__ == "__main__":
    demo()
