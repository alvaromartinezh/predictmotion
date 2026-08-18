"""Selección de ilustraciones para el broadsheet diario de Hypermotion.

Banco de grabados vintage de dominio público (Wikimedia Commons), el mismo
banco de 10 imágenes ya usado por el sistema de artículos anterior (retirado
pero con las imágenes conservadas en assets/illustrations/). Selección
determinista por (slug, tipo, fecha): el mismo artículo siempre muestra la
misma imagen; dos tipos de artículo del mismo día no eligen la misma.
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

def pick(fecha, variant):
    """Ilustración determinista por (fecha, variant) — el broadsheet usa 3
    huecos el mismo día ('cover'/'explainer'/'footer') y no deben coincidir."""
    seed_str = f"hypermotion|{fecha}|{variant}"
    idx = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % len(ILLUSTRATIONS)
    return ILLUSTRATIONS[idx]


def url(ill):
    return f"/assets/illustrations/{ill['file']}"
