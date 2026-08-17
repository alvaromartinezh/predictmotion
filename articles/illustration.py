"""Selección de ilustraciones para artículos editoriales.

Banco de grabados vintage de dominio público (Wikimedia Commons) reemplaza
los SVGs dibujados a mano del sistema anterior. Selección determinista por
slug: el mismo artículo siempre muestra la misma imagen.

Contrato de ubicación (ver render.py):
  - resumen_diario: UNA ilustración DENTRO del primer brief (bajo el
    marcador, encima del texto del breve).
  - Los otros 5 tipos de prosa (recap_jornada, explicador_probabilidad,
    carrera_titulo, cronica_partido, previa_diaria): UNA ilustración como
    caja independiente con etiqueta en el flujo de columnas (~245-275 px
    de ancho), con pie de foto y etiqueta derivada del tipo de artículo.
"""

import hashlib
import json
import os

# ── Banco de ilustraciones ──────────────────────────────────────────────
# Cada entrada: (filename, source_description, source_url).
# Todas son dominio público (Wikimedia Commons PD-Art / PD-old / CC0).
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "assets", "illustrations")

ILLUSTRATIONS = [
    {
        "file": "voetbalspelers-1926.jpg",
        "credit": "Henk Henriët / Rijksmuseum, 1926",
        "source": "Wikimedia Commons (CC0)",
    },
    {
        "file": "yarra-park-1874.jpg",
        "credit": "Samuel Calvert, 1874",
        "source": "Wikimedia Commons (PD)",
    },
    {
        "file": "england-scotland-1872.jpg",
        "credit": "William Ralston, 1872",
        "source": "Wikimedia Commons (PD)",
    },
    {
        "file": "assoc-match-1887.jpg",
        "credit": "From 'Athletics and Football', 1887",
        "source": "Wikimedia Commons (PD)",
    },
    {
        "file": "assoc-heading-1887.jpg",
        "credit": "From 'Athletics and Football', 1887",
        "source": "Wikimedia Commons (PD)",
    },
    {
        "file": "etonians-rovers-1882.jpg",
        "credit": "S.T. Dadd, 1882",
        "source": "Wikimedia Commons (PD)",
    },
    {
        "file": "shrovetide-1865.jpg",
        "credit": "Penny Illustrated News, 1865",
        "source": "Wikimedia Commons (PD)",
    },
    {
        "file": "alcock-goal-1874.jpg",
        "credit": "Charles Alcock, 1874",
        "source": "Wikimedia Commons (PD)",
    },
    {
        "file": "fa-cup-1892.jpg",
        "credit": "S.T. Dadd, 1892",
        "source": "Wikimedia Commons (PD)",
    },
    {
        "file": "melbourne-1875.jpg",
        "credit": "Hugh George, 1875",
        "source": "Wikimedia Commons (PD)",
    },
]

# Etiquetas por tipo de artículo — el label que aparece sobre la imagen.
_LABELS = {
    "recap_jornada": "Recap de jornada",
    "explicador_probabilidad": "Explicador",
    "carrera_titulo": "Carrera por el título",
    "cronica_partido": "Crónica",
    "previa_diaria": "Previa del día",
    "resumen_diario": "Resumen del día",
}

# Sal por tipo: garantiza que dos artículos del mismo tipo y mismo día pero
# distinta liga no elijan la misma imagen (el slug de liga entra en el hash,
# pero esto da variedad extra).
_SAL = {
    "recap_jornada": "recap",
    "explicador_probabilidad": "explainer",
    "carrera_titulo": "race",
    "cronica_partido": "chronicle",
    "previa_diaria": "preview",
    "resumen_diario": "summary",
}


def pick(slug, tipo, fecha):
    """Selecciona UNA ilustración de forma determinista por (slug, tipo, fecha).

    Devuelve dict con file/credit/source/label, o None si el banco está vacío.
    """
    if not ILLUSTRATIONS:
        return None
    seed_str = f"{slug}|{fecha}|{_SAL.get(tipo, tipo)}"
    idx = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % len(ILLUSTRATIONS)
    ill = ILLUSTRATIONS[idx].copy()
    ill["label"] = _LABELS.get(tipo, "Artículo")
    return ill


def illustration_url(ill):
    """URL pública de la imagen (relativa a la raíz del sitio)."""
    return f"/assets/illustrations/{ill['file']}"


def figure_html(ill, *, full_width=False):
    """Genera el HTML de la ilustración como <figure>.

    full_width=True: ancho completo (para resumen_diario dentro del brief).
    full_width=False: caja con ancho limitado en el flujo de columnas.

    Incluye pie de foto con crédito y fuente (PD, cortesía).
    """
    url = illustration_url(ill)
    cls = "illo" + (" illo--full" if full_width else "")
    return (
        f'<figure class="{cls}">'
        f'<img src="{url}" alt="{ill["label"]}" loading="lazy">'
        f'<figcaption>{ill["credit"]} · {ill["source"]}</figcaption>'
        f'</figure>'
    )
