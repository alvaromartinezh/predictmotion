"""Selecciona plantillas de texto al azar y construye el enlace de redacción de X.

- Inyecta {url} y {torneo} automáticamente (variables globales del bot).
- Filtra las variantes según los placeholders disponibles: una plantilla que use
  {goleador} o {jugada} solo se elige si ese dato llega. Así puedes mezclar
  variantes con y sin esos campos sin que el .format() falle ni queden huecos.
- Anti-repetición: no repite la misma variante dos veces seguidas por evento.
"""

from __future__ import annotations
import random
import string
import urllib.parse
from pathlib import Path

import yaml

import config

_TMPL_PATH = Path(__file__).parent / "text_templates.yaml"
_templates: dict | None = None
_last_choice: dict[str, str] = {}   # event_type -> última plantilla usada


def _load() -> dict:
    global _templates
    if _templates is None:
        _templates = yaml.safe_load(_TMPL_PATH.read_text(encoding="utf-8"))
    return _templates


def _required_fields(template: str) -> set[str]:
    """Nombres de placeholder que usa la plantilla ({grupo}, {goleador}, ...)."""
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _pick_cta() -> str:
    """Elige una frase de llamada a la acción del pool (con el enlace ya incrustado),
    evitando repetir la última usada."""
    pool = _load().get("cta") or ["{url}"]
    last = _last_choice.get("cta")
    candidates = [c for c in pool if c != last] or pool
    chosen = random.choice(candidates)
    _last_choice["cta"] = chosen
    return chosen.format(url=config.WEB_URL)


def generate_text(event_type: str, placeholders: dict) -> str:
    """Elige una variante aleatoria del tipo de evento y rellena los placeholders.

    {cta} (frase + enlace), {url} y {torneo} se inyectan solos. Las variantes que
    requieran un placeholder ausente (o vacío) se descartan."""
    tmpl = _load()
    variants = tmpl.get(event_type)
    if not variants:
        return f"[sin plantilla para '{event_type}']\n{config.WEB_URL}"

    base = {"url": config.WEB_URL, "torneo": config.TOURNAMENT, "cta": _pick_cta()}
    # Solo cuentan como disponibles los placeholders con valor real (no vacío).
    available = set(base) | {k for k, v in placeholders.items() if v not in (None, "")}

    eligible = [v for v in variants if _required_fields(v) <= available]
    if not eligible:
        eligible = variants  # red de seguridad: nunca quedarse sin texto

    # Evita repetir la última variante usada para este evento, si hay alternativa.
    last = _last_choice.get(event_type)
    pool = [v for v in eligible if v != last] or eligible
    chosen = random.choice(pool)
    _last_choice[event_type] = chosen

    return chosen.format(**base, **placeholders)


def build_tweet_intent(text: str) -> str:
    """Genera el enlace de X Web Intent con texto pre-rellenado.
    El enlace NO adjunta imagen; hay que añadirla manualmente antes de publicar."""
    encoded = urllib.parse.urlencode({"text": text})
    return f"https://x.com/intent/tweet?{encoded}"
