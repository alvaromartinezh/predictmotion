"""Autocomprobación de seo.predictions: conversión moneyline → probabilidad
implícita y normalización a suma 1 (quitando el margen de la casa).
python3 -m seo.test_predictions"""

from seo import predictions as p


def demo():
    # Positivo (underdog): 100/(ml+100).
    assert abs(p._ml_to_prob(110) - 100 / 210) < 1e-9
    # Negativo (favorito): -ml/(-ml+100).
    assert abs(p._ml_to_prob(-150) - 150 / 250) < 1e-9
    # Caso real verificado 2026-10-14, Levante-Deportivo (esp.1).
    raw_home = p._ml_to_prob(110)
    raw_draw = p._ml_to_prob(250.0)
    raw_away = p._ml_to_prob(245)
    total = raw_home + raw_draw + raw_away
    assert total > 1.0, "las tres implícitas sin normalizar deben sumar >1 (vig)"

    probs = p._market_probs({"home": 110, "draw": 250.0, "away": 245})
    # Tolerancia = el redondeo a 4 decimales de _market_probs, no el total exacto.
    assert abs(sum(probs.values()) - 1.0) < 1e-3, "normalizado debe sumar ~1"
    assert abs(probs["home"] - raw_home / total) < 1e-3
    # Moneyline más bajo = más favorito = más probabilidad implícita. En el caso
    # real (110/250/245) el orden es home > away > draw (245 < 250).
    assert probs["home"] > probs["away"] > probs["draw"], \
        "el moneyline más bajo debe quedar con más probabilidad"

    print("seo.test_predictions: OK")


if __name__ == "__main__":
    demo()
