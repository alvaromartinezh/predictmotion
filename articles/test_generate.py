"""Autocomprobación de la lógica nueva (crónica de partido / previa diaria):
selección de banda por posición, snapshot "antes" del partido, selección del
equipo más "en juego" de un partido, slugs y render de los 5 tipos. Sin red,
sin Gemini — todo con datos sintéticos. Sin framework, como test_writer.py.

Uso: python3 -m articles.test_generate
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import live_tracker.providers.espn as espn_provider
from live_tracker.models import Athlete, EventType, MatchEvent, StatPair

from . import generate, grounding, render, writer

_BANDS = [
    {"key": "ascenso", "label": "Ascenso directo", "color": "green", "lo": 1, "hi": 2},
    {"key": "playoff", "label": "Play-off de ascenso", "color": "blue", "lo": 3, "hi": 6},
    {"key": "descenso", "label": "Descenso", "color": "red", "lo": 19, "hi": 22},
]


def _team(id_, name, rank, **prob):
    return {"id": id_, "name": name, "logo": f"https://logo/{id_}.png", "rank": rank,
            "prob": prob}


def demo():
    # _best_band: SIEMPRE la banda de mayor probabilidad, sin importar
    # posición ni cercanía a un corte.
    best = grounding._best_band(_BANDS, {"ascenso": 2.0, "playoff": 61.0, "descenso": 8.0})
    assert best["key"] == "playoff", best

    # _team_headline: la zona/prob mostradas son SIEMPRE la de mayor
    # probabilidad — `cerca_de_corte` es un flag aparte (para elegir equipo
    # en render.py:_match_pick), no decide qué banda se enseña. Aquí el
    # equipo está cerca del corte de playoff (rank 6) pero su banda más
    # probable es ascenso: debe mostrarse ascenso, no playoff.
    snap = {"bands": _BANDS}
    near = _team("2", "Cerca del corte pero con otra banda más probable", 6,
                ascenso=80.0, playoff=5.0, descenso=1.0)
    h = grounding._team_headline(snap, near)
    assert h["cerca_de_corte"], h  # sigue cerca del corte por posición
    assert h["zona"] == "Ascenso directo" and h["prob_zona"] == 80.0, h  # pero se enseña la más alta

    far = _team("3", "Mitad de tabla", 12, ascenso=0.0, playoff=2.0, descenso=1.0)
    h2 = grounding._team_headline(snap, far)
    assert not h2["cerca_de_corte"] and h2["zona"] == "Play-off de ascenso", h2  # mayor prob de las 3

    # _match_side_summary (crónica/resumen): mismo criterio — la banda que se
    # enseña es la de mayor probabilidad, no la que toca por posición actual
    # (antes: _team_zone(rank), retirada). Aquí el equipo está en posición de
    # descenso (rank 20) pero su banda más probable es playoff.
    mid_table_by_rank = _team("40", "Salvado en la tabla, pero no en el modelo", 20,
                              ascenso=2.0, playoff=61.0, descenso=8.0)
    summary = grounding._match_side_summary({"teams": [mid_table_by_rank]}, _BANDS, {}, "40")
    assert summary["zona"] == "Play-off de ascenso" and summary["prob_zona_actual"] == 61.0, summary

    # _prior_snapshot: el snapshot diario más reciente ANTES de la fecha dada.
    grounding.load_all = lambda slug, season: [
        {"date": "2026-08-10", "teams": []},
        {"date": "2026-08-13", "teams": []},
        {"date": "2026-08-16", "teams": []},
    ]
    prior = grounding._prior_snapshot("hypermotion", "2025-26", "2026-08-15")
    assert prior["date"] == "2026-08-13", prior
    assert grounding._prior_snapshot("hypermotion", "2025-26", "2026-08-01") is None

    # _match_stats_and_events: stats numéricas (para que numeric_facts() las
    # cubra) y solo eventos GOAL/RED/SUB (no YELLOW), sin etiqueta de lesión.
    class _FakeDetail:
        stats = [StatPair(key="possessionPct", label="Posesión %", home="60.0", away="40.0"),
                StatPair(key="totalShots", label="Tiros", home="no-numero", away="9")]
        events = [
            MatchEvent(type=EventType.GOAL, minute="7'", clock_value=7, period=1,
                      team_side="home", players=[Athlete(id="1", name="Jugador A")], text="Goal"),
            MatchEvent(type=EventType.YELLOW, minute="20'", clock_value=20, period=1,
                      team_side="away", players=[], text="Yellow"),
            MatchEvent(type=EventType.SUB, minute="66'", clock_value=66, period=2,
                      team_side="away", players=[Athlete(id="2", name="Jugador B")], text="Substitution"),
        ]

    class _FakeProvider:
        def get_match(self, league, event_id):
            assert league == "hypermotion" and event_id == "999"
            return _FakeDetail()

    espn_provider.EspnProvider = _FakeProvider
    stats, events = grounding._match_stats_and_events("hypermotion", "999")
    assert {"etiqueta": "Posesión %", "local": 60.0, "visitante": 40.0} in stats
    assert any(s["etiqueta"] == "Tiros" and s["visitante"] == 9.0 for s in stats), stats
    assert len(events) == 2, "GOAL+SUB deberían pasar, YELLOW no"
    assert events[0]["tipo"] == "GOAL" and events[0]["jugadores"] == ["Jugador A"]
    assert events[1]["tipo"] == "SUB" and events[1]["jugadores"] == ["Jugador B"]
    assert not any("lesion" in str(e).lower() or "injury" in str(e).lower() for e in events)

    class _BrokenProvider:
        def get_match(self, league, event_id):
            raise RuntimeError("ESPN caído")

    espn_provider.EspnProvider = _BrokenProvider
    assert grounding._match_stats_and_events("hypermotion", "999") == ([], [])

    # _match_pick (render.py): el equipo cerca de un corte manda; si ninguno
    # lo está, gana el de mayor probabilidad — un partido "aburrido" (ambos
    # lejos de cualquier corte) sigue sacando un stat card, no se descarta.
    l_near = {"nombre": "Local", "cerca_de_corte": True, "prob_zona": 10.0}
    v_far = {"nombre": "Visitante", "cerca_de_corte": False, "prob_zona": 90.0}
    assert render._match_pick(l_near, v_far) is l_near
    l_far = {"nombre": "Local2", "cerca_de_corte": False, "prob_zona": 20.0}
    v_far2 = {"nombre": "Visitante2", "cerca_de_corte": False, "prob_zona": 60.0}
    assert render._match_pick(l_far, v_far2) is v_far2

    # Slugs de los 2 tipos nuevos.
    cronica_payload = {"tipo": "cronica_partido", "jornada": 4, "event_id": "999888"}
    assert writer._article_slug("hypermotion", cronica_payload) == "hypermotion-cronica-999888"
    previa_payload = {"tipo": "previa_diaria", "jornada": 4, "fecha": "2026-08-16"}
    assert writer._article_slug("laliga", previa_payload) == "laliga-previa-2026-08-16"

    # render_article no debe reventar para ninguno de los 5 tipos, y el
    # partido único (crónica) debe llevar hero de 2 escudos; la previa (N
    # partidos) no lleva hero pero sí la fila de escudos + un stat card por
    # partido (no se recorta a 1-2 aunque haya varios).
    league = {"name": "Liga Hypermotion", "dashboard": "/hypermotion", "slug": "hypermotion"}
    base = dict(status="draft", body="Primer párrafo.\n\nSegundo párrafo.",
               title="T", meta_description="D", generated_at="2026-08-16T10:00:00Z")

    payloads = {
        "recap_jornada": {
            "tipo": "recap_jornada", "jornada": 4, "liga": "Liga Hypermotion",
            "zona_principal": "Ascenso directo", "zona_principal_color": "green",
            "lider": {"nombre": "Líder", "id": "10", "logo": "L.png",
                     "prob_zona_principal": 61.2},
            "mayores_subidas_probabilidad": [{"nombre": "Sube", "prob_actual": 30.0}],
            "mayores_bajadas_probabilidad": [{"nombre": "Baja", "prob_actual": 5.0}],
        },
        "explicador_probabilidad": {
            "tipo": "explicador_probabilidad", "jornada": 4, "equipo": "Equipo",
            "equipo_id": "11", "equipo_logo": "E.png", "posicion": 5, "puntos": 20,
            "probabilidades_por_zona": {"Play-off de ascenso": 40.0},
            "zona_colores": {"Play-off de ascenso": "blue"},
        },
        "carrera_titulo": {
            "tipo": "carrera_titulo", "jornada": 4,
            "candidatos": [{"nombre": "Puntero", "id": "12", "logo": "P.png", "prob_titulo": 55.0}],
        },
        "cronica_partido": {
            "tipo": "cronica_partido", "jornada": 4, "liga": "Liga Hypermotion",
            "local": {"nombre": "Local", "id": "13", "logo": "H.png", "zona": "Ascenso directo",
                     "zona_color": "green", "prob_zona_actual": 45.0},
            "visitante": {"nombre": "Visitante", "id": "14", "logo": "A.png", "zona": "Descenso",
                         "zona_color": "red", "prob_zona_actual": 12.0},
            "resultado": {"local": 2, "visitante": 1},
        },
        "previa_diaria": {
            "tipo": "previa_diaria", "jornada": 4, "fecha": "2026-08-16",
            "partidos": [
                {"local": {"nombre": "P1L", "id": "20", "logo": "l1.png", "cerca_de_corte": True,
                          "zona": "Play-off de ascenso", "zona_color": "blue", "prob_zona": 33.0},
                 "visitante": {"nombre": "P1V", "id": "21", "logo": "v1.png", "cerca_de_corte": False,
                              "zona": "Descenso", "zona_color": "red", "prob_zona": 5.0},
                 "event_id": "555"},
                {"local": {"nombre": "P2L", "id": "22", "logo": "l2.png", "cerca_de_corte": False,
                          "zona": "Ascenso directo", "zona_color": "green", "prob_zona": 70.0},
                 "visitante": {"nombre": "P2V", "id": "23", "logo": "v2.png", "cerca_de_corte": False,
                              "zona": "Descenso", "zona_color": "red", "prob_zona": 8.0},
                 "event_id": "556"},
            ],
        },
        "resumen_diario": {
            "tipo": "resumen_diario", "jornada": 4, "fecha": "2026-08-15", "liga": "Liga Hypermotion",
            "partidos": [
                {"local": {"nombre": "R1L", "id": "30", "logo": "rl1.png",
                          "zona": "Ascenso directo", "zona_color": "green", "prob_zona_actual": 60.0,
                          "prob_zona_antes_del_partido": 52.0},
                 "visitante": {"nombre": "R1V", "id": "31", "logo": "rv1.png",
                              "zona": "Descenso", "zona_color": "red", "prob_zona_actual": 10.0},
                 "resultado": {"local": 2, "visitante": 0}, "event_id": "777"},
                {"local": {"nombre": "R2L", "id": "32", "logo": "rl2.png",
                          "zona": "Permanencia", "zona_color": None, "prob_zona_actual": 50.0},
                 "visitante": {"nombre": "R2V", "id": "33", "logo": "rv2.png",
                              "zona": "Play-off de ascenso", "zona_color": "blue", "prob_zona_actual": 35.0},
                 "resultado": {"local": 1, "visitante": 1}, "event_id": "778"},
            ],
        },
    }
    recent = [{"slug": "otro", "title": "Otro artículo", "meta_description": "D",
              "league_name": "LaLiga", "generated_at": "2026-08-15T10:00:00Z"}]
    for tipo, payload in payloads.items():
        article = dict(base, slug=f"test-{tipo}", type=tipo, league="hypermotion",
                       grounding_data=payload)
        _path, html = render.render_article(article, league, logo="https://logo/liga.png",
                                            recent=recent)
        assert "<html" in html and "Equipo" not in "" # smoke: no exception, algo se generó
        if tipo == "previa_diaria":
            # Cabecera GRANDE (match-card compartida) antes de cada párrafo:
            # 2 escudos x 2 partidos = 4 .hero-av, en su propia .comp-link/
            # .card clicable a la CRÓNICA de ese partido (exista o no
            # todavía), en orden, antes de su párrafo.
            assert html.count('class="hero-av"') == 4, "una cabecera de 2 escudos por partido (2 partidos)"
            assert html.count('class="stat ') >= 2, "un stat card por partido (2 partidos) en el resumen de arriba"
            assert 'class="comp-link" href="/articulos/hypermotion-cronica-555"' in html
            assert 'class="comp-link" href="/articulos/hypermotion-cronica-556"' in html
            assert html.index("cronica-555") < html.index("Primer párrafo")
            assert html.index("Primer párrafo") < html.index("cronica-556")
            assert html.index("cronica-556") < html.index("Segundo párrafo")
            # Recuento de párrafos != partidos -> degrada a una única card de
            # texto sin cabeceras (no empareja mal el partido con el párrafo
            # equivocado) y no llama al builder.
            mismatched = render._matches_body_html(
                "Solo un párrafo.", payload["partidos"], lambda m: "<CARD>")
            assert "<CARD>" not in mismatched and "Solo un párrafo." in mismatched
            # _kickoff_label: ISO UTC -> HH:MM de Madrid (CEST = +2 en agosto);
            # None si no hay hora, no revienta.
            assert render._kickoff_label("2026-08-16T18:00:00Z") == "20:00"
            assert render._kickoff_label(None) is None
            # _win_prob_bar: sin win_prob no pinta raya; con win_prob, raya +
            # porcentajes con coma española.
            assert render._win_prob_bar(None, "A", "B") == ""
            wpbar = render._win_prob_bar({"home": 45.2, "draw": 27.0, "away": 27.8}, "Eibar", "Tenerife")
            assert 'class="winbar__seg h"' in wpbar and "Eibar 45,2%" in wpbar and "Tenerife 27,8%" in wpbar
        elif tipo == "resumen_diario":
            # Un BREVE autocontenido por partido (marcador + párrafo + qué le
            # hizo a la prob. de zona de cada equipo), todos dentro de un
            # único .card-pad con columnas y separados por un icono — no la
            # cabecera de escudos + stat-grid + prosa aparte de antes.
            assert 'class="hero-av"' not in html and 'class="stat ' not in html
            assert 'class="winbar"' not in html, "post-partido no lleva raya 1X2"
            assert html.count('class="brief"') == 2
            assert html.count('data-cols="2"') == 1, "2 partidos -> 2 columnas, un solo card"
            assert html.count('class="col-divider"') == 2, "un icono de cierre por breve"
            assert '<b class="sc">2–0</b>' in html and '<b class="sc">1–1</b>' in html
            assert 'class="brief__head" href="/articulos/hypermotion-cronica-777"' in html
            assert 'class="brief__head" href="/articulos/hypermotion-cronica-778"' in html
            assert html.index("cronica-777") < html.index("Primer párrafo")
            assert html.index("Primer párrafo") < html.index("cronica-778")
            assert html.index("cronica-778") < html.index("Segundo párrafo")
            # La zona de cada equipo se cuenta en su breve, con el cambio en
            # pp solo si hay `prob_zona_antes_del_partido` (aquí lo lleva un
            # único equipo: 52,0 -> 60,0). Sin ese dato, prob sin delta
            # inventado — no un "0,0 pp" que no dice nada.
            assert html.count('class="brief__zone ') == 4
            assert html.count('<span class="delta-') == 1
            assert '<span class="delta-up">+8,0 pp</span>' in html
            # Cambio nulo -> "sin cambio", no el "= pp" de las tablas SEO.
            assert render._brief_zone({"nombre": "X", "zona": "Z", "zona_color": None,
                                       "prob_zona_actual": 50.0,
                                       "prob_zona_antes_del_partido": 50.0}
                                      ).endswith('<span class="delta-eq">sin cambio</span></div>')
            # Recuento de párrafos != partidos -> prosa suelta, sin breves.
            degraded = render._briefs_body_html("Solo un párrafo.", payload["partidos"],
                                                "hypermotion")
            assert 'class="brief"' not in degraded and "Solo un párrafo." in degraded
        elif tipo == "cronica_partido":
            # El hero de la propia crónica usa el mismo match-card (marcador
            # + 'Final', sin raya 1X2), pero SIN enlace: enlazarse a sí misma
            # no tiene sentido.
            assert 'class="hero-av"' in html
            assert '<span class="kick">2–1</span><span class="s">Final</span>' in html
            assert '<a class="comp-link"><div class="card" data-icon="goal-net"><div class="match-hero">' not in html
            assert '<div class="card" data-icon="goal-net"><div class="match-hero">' in html
        else:
            assert 'class="hero-av"' in html, f"{tipo} debería llevar hero"
        # Seguir viendo (carrusel de artículos) + Equipos mencionados (chips),
        # como dos secciones separadas, no una mezclada.
        assert "Seguir viendo" in html and 'class="carousel-wrap"' in html
        assert "Equipos mencionados" in html
        assert "carousel-crest" not in html, "los escudos van en .chips, no en el carrusel"

        # Sin `recent`, la sección de artículos no debería aparecer.
        _path2, html2 = render.render_article(article, league, logo="https://logo/liga.png")
        assert "Seguir viendo" not in html2 and 'class="carousel-wrap"' not in html2
        assert "Equipos mencionados" in html2

    # _match_win_prob: mismo modelo de fuerza que /partido (sim_table.
    # snapshot_context + _match_ph_pd), no una fórmula reimplementada aquí.
    # Sin 'strength_model' en el snapshot (liga uniforme/sin prior) -> None,
    # no se inventa una probabilidad plana.
    wp_league = {"p_home": 0.42, "p_draw": 0.27}
    wp_snap_no_strength = {"jornada": 0, "teams": []}
    assert grounding._match_win_prob(wp_league, wp_snap_no_strength, "20", "21") is None
    wp_snap = {"strength_model": "v2", "jornada": 0, "total_md": 42,
              "teams": [{"id": "20", "strength": 0.3}, {"id": "21", "strength": -0.2}]}
    wp = grounding._match_win_prob(wp_league, wp_snap, "20", "21")
    assert wp is not None and abs(wp["home"] + wp["draw"] + wp["away"] - 100) < 0.01
    assert wp["home"] > wp["away"], "el equipo con más fuerza (20) debe salir favorito"

    # ground_resumen_diario: agrega varios partidos del mismo día, misma
    # forma por lado que ground_cronica_partido (antes/después reutilizado
    # vía _match_side_summary).
    wrap_snap = {
        "season": "2025-26", "jornada": 4, "bands": _BANDS,
        "teams": [_team("10", "Sube", 1, ascenso=70.0),
                 _team("11", "Baja", 19, descenso=30.0)],
    }
    grounding.load_all = lambda slug, season: []   # sin histórico -> sin "antes"
    match_ev = {"event_id": "999", "date": "2026-08-15",
               "home": {"id": "10", "name": "Sube"}, "away": {"id": "11", "name": "Baja"},
               "home_score": 2, "away_score": 0}
    league_min = {"slug": "hypermotion", "name": "Liga Hypermotion", "espn_code": "esp.2"}
    resumen = grounding.ground_resumen_diario(league_min, wrap_snap, [match_ev])
    assert resumen["tipo"] == "resumen_diario" and len(resumen["partidos"]) == 1
    p = resumen["partidos"][0]
    assert p["local"]["nombre"] == "Sube" and p["local"]["zona"] == "Ascenso directo"
    assert p["local"]["prob_zona_antes_del_partido"] is None  # sin histórico

    # writer: slug + título para resumen_diario.
    assert writer._article_slug("hypermotion", resumen) == "hypermotion-resumen-2026-08-15"
    title, desc = writer._compose_resumen_head(resumen)
    assert "Resumen del día" in title and "1 partido" in title

    # render: resumen_diario = breves, sin hero ni stat-grid.
    article_resumen = dict(slug="test-resumen", type="resumen_diario", league="hypermotion",
                           title=title, meta_description=desc, body="Cuerpo.\n\nSegundo.",
                           grounding_data=resumen, status="draft",
                           generated_at="2026-08-16T10:00:00Z")
    league_full = {"name": "Liga Hypermotion", "dashboard": "/hypermotion", "slug": "hypermotion"}
    _p, html = render.render_article(article_resumen, league_full, logo="https://logo/liga.png")
    assert 'class="hero-av"' not in html, "resumen_diario no debería llevar hero"
    # 1 partido pero 2 párrafos -> degrada a prosa suelta (no empareja mal).
    assert 'class="brief"' not in html and 'class="stat ' not in html
    # 1 partido y 1 párrafo -> un breve, 1 columna, sin separador.
    _p, html1 = render.render_article(dict(article_resumen, body="Cuerpo."), league_full,
                                      logo="https://logo/liga.png")
    assert html1.count('class="brief"') == 1 and 'data-cols="1"' in html1
    assert html1.count('class="col-divider"') == 1
    assert '<b class="sc">2–0</b>' in html1

    # _pick_daily_preview: NO dispara antes de PREVIEW_LOCAL_HOUR (08:00
    # local), aunque haya partidos programados y no se haya generado hoy.
    prev_snap = {"season": "2025-26", "jornada": 4, "bands": _BANDS, "teams": []}
    generate.espn.fetch_scoreboard_range = lambda code, s, e: [
        {"event_id": "1", "date": "2026-08-16", "state": "pre",
         "home": {"id": "10", "name": "A"}, "away": {"id": "11", "name": "B"},
         "home_score": None, "away_score": None, "kickoff": "2026-08-16T18:00:00Z"},
    ]
    madrid = ZoneInfo("Europe/Madrid")
    early = datetime(2026, 8, 16, 7, 30, tzinfo=madrid)
    late = datetime(2026, 8, 16, 8, 5, tzinfo=madrid)
    assert generate._pick_daily_preview(league_min, prev_snap, {}, "2026-08-16", early) is None, (
        "no debería disparar antes de las 8h locales")
    payload = generate._pick_daily_preview(league_min, prev_snap, {}, "2026-08-16", late)
    assert payload is not None and payload["tipo"] == "previa_diaria"
    already = generate._pick_daily_preview(
        league_min, prev_snap, {"last_preview_date": "2026-08-16"}, "2026-08-16", late)
    assert already is None, "ya generada hoy -> no se repite aunque sea tras las 8h"

    # _pick_daily_wrap: resume el día ANTERIOR (dedupe por la fecha
    # resumida, no por cuándo corrió el cron).
    generate.espn.fetch_scoreboard_range = lambda code, s, e: [
        {"event_id": "2", "date": "2026-08-15", "state": "post",
         "home": {"id": "10", "name": "A"}, "away": {"id": "11", "name": "B"},
         "home_score": 2, "away_score": 1},
    ]
    w = generate._pick_daily_wrap(league_min, prev_snap, {}, "2026-08-16")
    assert w is not None and w["tipo"] == "resumen_diario" and w["fecha"] == "2026-08-15"
    already_wrap = generate._pick_daily_wrap(
        league_min, prev_snap, {"last_wrap_date": "2026-08-15"}, "2026-08-16")
    assert already_wrap is None, "el día de ayer ya se resumió -> no se repite"

    generate.espn.fetch_scoreboard_range = lambda code, s, e: []
    assert generate._pick_daily_wrap(league_min, prev_snap, {}, "2026-08-16") is None, (
        "sin partidos finalizados ayer -> nada que resumir")

    # Preview privado (/preview-articulos): render_article(preview=True) usa
    # el namespace de preview (URL, canonical, breadcrumb) y noindex, sin
    # tocar el contenido.
    preview_article = dict(base, slug="test-cronica_partido", type="cronica_partido",
                           league="hypermotion", status="flagged",
                           grounding_data=payloads["cronica_partido"])
    ppath, phtml = render.render_article(preview_article, league, logo="https://logo/liga.png",
                                         preview=True)
    assert ppath == "preview-articulos/test-cronica_partido.html"
    assert "/preview-articulos/test-cronica_partido" in phtml  # canonical + og:url
    assert 'content="noindex, nofollow"' in phtml
    assert "Artículos (preview)" in phtml and "flagged" in phtml
    # El mismo artículo SIN preview sigue yendo al namespace público de siempre.
    _pub_path, pub_html = render.render_article(preview_article, league, logo="https://logo/liga.png")
    assert 'content="noindex, nofollow"' not in pub_html

    # render_preview_hub: tarjetas con status, enlazando al preview de cada uno.
    hub_path, hub_html = render.render_preview_hub([
        {"slug": "a1", "title": "T1", "meta_description": "D1", "league_name": "LaLiga",
         "generated_at": "2026-08-16T09:00:00Z", "status": "draft"},
    ])
    assert hub_path == "preview-articulos/index.html"
    assert 'href="/preview-articulos/a1"' in hub_html and "draft" in hub_html
    empty_hub_path, empty_hub_html = render.render_preview_hub([])
    assert "Nada en preview ahora mismo" in empty_hub_html

    # _preview_index/_preview_cards: relee de disco (no solo lo de esta
    # pasada), junta ARTICLES_PREVIEW_DIR + lo no publicado de
    # ARTICLES_DATA_DIR, excluye 'published', ordena por fecha desc.
    with tempfile.TemporaryDirectory() as tmp:
        preview_dir, data_dir = Path(tmp) / "preview", Path(tmp) / "data"
        preview_dir.mkdir()
        data_dir.mkdir()
        generate.ARTICLES_PREVIEW_DIR, generate.ARTICLES_DATA_DIR = preview_dir, data_dir

        def _write(d, slug, status, generated_at):
            a = dict(base, slug=slug, type="cronica_partido", league="hypermotion",
                     status=status, generated_at=generated_at,
                     grounding_data=payloads["cronica_partido"])
            (d / f"{slug}.json").write_text(json.dumps(a), encoding="utf-8")

        _write(preview_dir, "old-draft", "draft", "2026-08-14T10:00:00Z")
        _write(data_dir, "new-flagged", "flagged", "2026-08-16T10:00:00Z")
        _write(data_dir, "already-live", "published", "2026-08-15T10:00:00Z")

        idx = generate._preview_index()
        slugs = [a["slug"] for a in idx]
        assert slugs == ["new-flagged", "old-draft"], slugs  # excluye published, ordena desc
        cards = generate._preview_cards(idx)
        assert all("status" in c and c["league_name"] == "Liga Hypermotion" for c in cards)

        # _write_public_index: índice público (data/articles/latest.json) para
        # el carrusel del home — teams/leagues salen de render._mentioned_teams
        # (dato estructurado del payload, no heurística de texto libre como en
        # noticias). Solo artículos PUBLICADOS entran aquí.
        published_article = json.loads((data_dir / "already-live.json").read_text(encoding="utf-8"))
        generate._write_public_index([published_article])
        public = json.loads((data_dir / "latest.json").read_text(encoding="utf-8"))
        assert public["count"] == 1 and len(public["items"]) == 1
        item = public["items"][0]
        assert item["slug"] == "already-live" and item["league"] == "hypermotion"
        assert item["leagues"] == ["hypermotion"]
        assert {t["id"] for t in item["teams"]} == {"13", "14"}, item["teams"]
        # El índice público no es un artículo: _preview_index no debe recogerlo
        # aunque comparta carpeta y extensión con los JSON reales.
        idx2 = generate._preview_index()
        assert "latest" not in [a.get("slug") for a in idx2]
        assert len(idx2) == 2

    # ── --render-only no puede llamar a Gemini NUNCA ────────────────────────
    # Es toda la garantía de la flag: existe para repintar sin gastar cuota, y
    # si algún día se cuela una llamada nadie se enteraría (best-effort: los
    # fallos de Gemini se registran y siguen). Se sabotea write_article para
    # que reviente si alguien lo invoca, y se comprueba además que run() sigue
    # llevando la flag en su Namespace hecho a mano — olvidarla mata el cron
    # con AttributeError.
    # Se sabotean los _pick_* (no write_article) a propósito: se llaman UNA vez
    # por liga con contexto, sin depender del state del día, así la prueba es
    # determinista — con write_article dependería de que hubiera algo que
    # generar hoy y podría pasar en vacío. Además los _pick_* son los que tocan
    # ESPN, así que esto cubre también el "0 red".
    import argparse as _ap

    def _boom(*a, **k):
        raise AssertionError("--render-only ha entrado en la fase de generación")

    _origs = {n: getattr(generate, n) for n in
              ("_pick_daily_preview", "_pick_daily_wrap", "_pick_recap",
               "_pick_explainer", "_pick_title_race", "_pick_match_reports")}
    for n in _origs:
        setattr(generate, n, _boom)
    try:
        base = dict(dry_run=False, publish=False, league=None)
        generate._run(_ap.Namespace(**base, render_only=True))   # no debe explotar
        # …y la prueba no es vacía: sin la flag, esos mismos _pick_* SÍ se
        # llaman (hay snapshots en disco), así que debe explotar.
        vacia = False
        try:
            generate._run(_ap.Namespace(**base, render_only=False))
            vacia = True
        except AssertionError:
            pass
        assert not vacia, ("sin --render-only tampoco se llamó a los _pick_*: "
                           "no hay snapshots en disco y la prueba no verifica nada")
    finally:
        for n, f in _origs.items():
            setattr(generate, n, f)

    import inspect
    src = inspect.getsource(generate.run)
    assert "render_only" in src, (
        "run() construye su Namespace a mano: si no incluye render_only, "
        "_run() muere con AttributeError en el cron de 3h")

    print("articles.test_generate: OK")


if __name__ == "__main__":
    demo()
