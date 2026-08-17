"""Autocomprobación del validador de grounding numérico (sin framework).

Uso: python3 -m articles.test_writer
"""

from . import gemini_client, writer
from .config import PREVIA_NEWS_REVIEW_UNTIL
from .writer import validate_grounding


def demo():
    payload = {
        "tipo": "explicador_probabilidad",
        "equipo": "Real Sociedad",
        "probabilidades_por_zona": {"Champions League": 38.4, "Europa League": 22.1},
        "puntos": 42,
    }

    # Cifra real (con coma española, como la escribiría el redactor) y una
    # ligeramente distinta por redondeo del modelo -> dentro de tolerancia.
    ok_body = ("La Real Sociedad tiene un 38,4% de opciones de Champions y un "
               "22% de Europa League, con 42 puntos en juego.")
    ok, bad = validate_grounding(ok_body, payload)
    assert ok, f"cifras reales (con redondeo) no deberían marcarse: {bad}"

    # Cifra inventada por el modelo (65%), no está en el payload -> debe fallar.
    bad_body = "La Real Sociedad roza ya un 65% de clasificarse a la Champions."
    ok, bad = validate_grounding(bad_body, payload)
    assert not ok, "una cifra inventada (65%) debería marcarse como no fundamentada"
    assert bad == [65.0]

    # Sin ningún '%' en el cuerpo -> siempre pasa (nada que contrastar).
    ok, bad = validate_grounding("Un buen partido para el equipo.", payload)
    assert ok and not bad

    # extract_sources: groundingChunks -> [{uri,title}]; sin metadata -> [].
    candidate_with = {"groundingMetadata": {"groundingChunks": [
        {"web": {"uri": "https://a.com/x", "title": "Fuente A"}},
        {"web": {"uri": "https://b.com/y"}},   # sin title -> cae al uri
        {"web": {}},                            # sin uri -> se descarta
    ]}}
    sources = gemini_client.extract_sources(candidate_with)
    assert sources == [{"uri": "https://a.com/x", "title": "Fuente A"},
                       {"uri": "https://b.com/y", "title": "https://b.com/y"}], sources
    assert gemini_client.extract_sources({}) == []
    assert gemini_client.extract_sources(None) == []

    # write_article: solo previa_diaria usa generate_grounded(); el status
    # depende de si trae fuentes Y si aún estamos dentro de la ventana de
    # revisión (PREVIA_NEWS_REVIEW_UNTIL).
    called = {"grounded": 0, "plain": 0}
    writer.generate_grounded = lambda prompt, **kw: (called.__setitem__("grounded", called["grounded"] + 1)
                                                      or ("Previa con contexto real.", [
                                                          {"uri": "https://x.com", "title": "X"}]))
    writer.generate = lambda prompt, **kw: (called.__setitem__("plain", called["plain"] + 1)
                                            or "Cuerpo sin cifras inventadas.")

    previa_payload = {"tipo": "previa_diaria", "liga": "LaLiga", "jornada": 3,
                      "fecha": "2026-08-16", "partidos": []}
    a = writer.write_article("laliga", previa_payload)
    assert called == {"grounded": 1, "plain": 0}, "previa_diaria debe usar generate_grounded, no generate"
    assert a["sources"] == [{"uri": "https://x.com", "title": "X"}]
    assert a["status"] == "pending_review", (
        f"con fuentes y dentro de la ventana ({PREVIA_NEWS_REVIEW_UNTIL}) debería quedar pendiente: {a['status']}")

    # Sin fuentes (nada que citar) -> no hay nada externo que revisar, sale como draft.
    writer.generate_grounded = lambda prompt, **kw: ("Previa sin nada que citar.", [])
    a2 = writer.write_article("laliga", previa_payload)
    assert a2["sources"] == [] and a2["status"] == "draft", a2["status"]

    # Fuera de la ventana de revisión -> aunque traiga fuentes, sale como draft.
    writer.generate_grounded = lambda prompt, **kw: ("Previa con contexto real.", [
        {"uri": "https://x.com", "title": "X"}])
    import articles.writer as _w
    orig_until = _w.PREVIA_NEWS_REVIEW_UNTIL
    _w.PREVIA_NEWS_REVIEW_UNTIL = "2000-01-01"
    try:
        a3 = writer.write_article("laliga", previa_payload)
        assert a3["status"] == "draft", f"pasada la ventana debería publicarse sola: {a3['status']}"
    finally:
        _w.PREVIA_NEWS_REVIEW_UNTIL = orig_until

    # Cualquier otro tipo usa generate() normal, nunca generate_grounded(), y
    # sources queda siempre vacío.
    called["grounded"] = called["plain"] = 0
    recap_payload = {"tipo": "recap_jornada", "liga": "LaLiga", "jornada": 3,
                     "zona_principal": "Ascenso directo",
                     "lider": {"nombre": "Equipo X", "id": "1", "logo": None,
                              "puntos": 20, "prob_zona_principal": 50.0}}
    a4 = writer.write_article("laliga", recap_payload)
    assert called == {"grounded": 0, "plain": 1}, "recap_jornada no debe usar grounding"
    assert a4["sources"] == []

    # Reparto de modelo: la llamada grounded (previa_diaria) va a 2.5-flash
    # porque el tool google_search NO existe en free tier para 3.x (429 sin
    # QuotaFailure, medido — ver config.py); el resto va a Flash-Lite, que es
    # de donde sale el margen de cuota. Sin red: solo se comprueba el reparto.
    from .config import GEMINI_MODEL, GEMINI_MODEL_GROUNDED, gemini_endpoint
    from .gemini_client import _model_for
    assert _model_for(None) == GEMINI_MODEL == "gemini-3.5-flash-lite"
    assert _model_for([{"google_search": {}}]) == GEMINI_MODEL_GROUNDED == "gemini-2.5-flash"
    assert gemini_endpoint("m").endswith("/models/m:generateContent")

    print("articles.test_writer: OK")


if __name__ == "__main__":
    demo()
