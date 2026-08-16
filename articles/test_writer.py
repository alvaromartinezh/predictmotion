"""Autocomprobación del validador de grounding numérico (sin framework).

Uso: python3 -m articles.test_writer
"""

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

    print("articles.test_writer: OK")


if __name__ == "__main__":
    demo()
