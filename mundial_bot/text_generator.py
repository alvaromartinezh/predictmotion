"""Selecciona plantillas de texto al azar y construye el enlace de redacción de X."""

from __future__ import annotations
import random
import urllib.parse
from pathlib import Path

import yaml

import config

_TMPL_PATH = Path(__file__).parent / "text_templates.yaml"
_templates: dict | None = None


def _load() -> dict:
    global _templates
    if _templates is None:
        _templates = yaml.safe_load(_TMPL_PATH.read_text(encoding="utf-8"))
    return _templates


def generate_text(event_type: str, placeholders: dict) -> str:
    """Elige una variante aleatoria del tipo de evento y rellena los placeholders.
    {url} se inyecta automáticamente con la URL del Mundial."""
    tmpl = _load()
    variants = tmpl.get(event_type)
    if not variants:
        return f"[sin plantilla para '{event_type}']\n{config.WEB_URL}"
    chosen = random.choice(variants)
    filled = chosen.format(url=config.WEB_URL, **placeholders)
    return filled


def build_tweet_intent(text: str) -> str:
    """Genera el enlace de X Web Intent con texto pre-rellenado.
    El enlace NO adjunta imagen; hay que añadirla manualmente antes de publicar."""
    encoded = urllib.parse.urlencode({"text": text})
    return f"https://x.com/intent/tweet?{encoded}"
