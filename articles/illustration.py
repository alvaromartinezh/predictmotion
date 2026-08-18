"""Selección de ilustraciones para los broadsheets de artículos.

Banco de grabados vintage de dominio público (Wikimedia Commons), el mismo
banco de 10 imágenes ya usado por el sistema de artículos anterior (retirado
pero con las imágenes conservadas en assets/illustrations/). Selección
determinista por (liga, fecha, variant): el mismo artículo siempre muestra la
misma imagen; dos tipos de artículo del mismo día (o de dos ligas distintas)
no eligen la misma.
"""

import hashlib
import os

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "assets", "illustrations")

ILLUSTRATIONS = [
    {"file": "voetbalspelers-1926.jpg", "credit": "Henk Henriët / Rijksmuseum, 1926", "source": "Wikimedia Commons (CC0)"},
    {"file": "yarra-park-1874.jpg", "credit": "Samuel Calvert, 1874", "source": "Wikimedia Commons (PD)"},
    {"file": "england-scotland-1872.jpg", "credit": "William Ralston, 1872", "source": "Wikimedia Commons (PD)"},
    {"file": "assoc-match-1887.jpg", "credit": "From 'Athletics and Football', 1887", "source": "Wikimedia Commons (PD)"},
    {"file": "assoc-heading-1887.jpg", "credit": "From 'Athletics and Football', 1887", "source": "Wikimedia Commons (PD)"},
    {"file": "etonians-rovers-1882.jpg", "credit": "S.T. Dadd, 1882", "source": "Wikimedia Commons (PD)"},
    {"file": "shrovetide-1865.jpg", "credit": "Penny Illustrated News, 1865", "source": "Wikimedia Commons (PD)"},
    {"file": "alcock-goal-1874.jpg", "credit": "Charles Alcock, 1874", "source": "Wikimedia Commons (PD)"},
    {"file": "fa-cup-1892.jpg", "credit": "S.T. Dadd, 1892", "source": "Wikimedia Commons (PD)"},
    {"file": "melbourne-1875.jpg", "credit": "Hugh George, 1875", "source": "Wikimedia Commons (PD)"},
]

def pick(league_slug, fecha, variant, avoid=()):
    """Ilustración determinista por (liga, fecha, variant) — el broadsheet usa
    hasta 4 huecos el mismo día ('cover'/'explainer'/'footer'/un hueco extra
    si sobra espacio, ver layout_estimate.py) y no deben coincidir. `avoid`:
    ficheros ya elegidos ese día para otro hueco — si el hash choca con uno
    de ellos, reintenta con un sufijo hasta encontrar uno libre (o se rinde
    y repite si el banco tiene menos imágenes que huecos)."""
    for attempt in range(len(ILLUSTRATIONS) + 1):
        seed_str = f"{league_slug}|{fecha}|{variant}" + (f"#{attempt}" if attempt else "")
        idx = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % len(ILLUSTRATIONS)
        ill = ILLUSTRATIONS[idx]
        if ill["file"] not in avoid:
            return ill
    return ill


def url(ill):
    return f"/assets/illustrations/{ill['file']}"
