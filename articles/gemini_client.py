"""Cliente mínimo de la API de Gemini: HTTP directo (urllib), sin SDK.

Mismo principio "cero dependencias" que seo/espn.py, news/feeds.py y
live_tracker/providers/espn.py: el endpoint REST de generateContent es JSON
simple por HTTPS con la key como header, no hace falta el SDK google-genai
(ese se usó solo para el script suelto de prueba de la key, fuera del repo).
"""

import json
import os
import urllib.error
import urllib.request

from seo.notify import _load_env
from .config import GEMINI_ENDPOINT

HTTP_TIMEOUT = 60  # s — generación de texto, más lento que un fetch normal


class GeminiError(Exception):
    """Fallo de la llamada a Gemini (HTTP, respuesta vacía o key ausente)."""


def generate(prompt, *, temperature=0.6):
    """Llama a generateContent y devuelve el texto plano de la respuesta.

    Lanza GeminiError con el detalle (código HTTP + cuerpo) si falla — el
    llamador decide si es best-effort (igual que espn.fetch_* deja propagar y
    el orquestador captura por-artículo, como news/aggregate.py hace por-feed).
    """
    _load_env()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GEMINI_API_KEY no está definida en el entorno/.env")

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }).encode("utf-8")

    req = urllib.request.Request(
        GEMINI_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise GeminiError(f"HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise GeminiError(f"Fallo de red: {e.reason}") from e

    try:
        candidates = payload["candidates"]
        parts = candidates[0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError) as e:
        raise GeminiError(f"Respuesta sin texto utilizable: {payload}") from e

    if not text.strip():
        raise GeminiError(f"Respuesta vacía: {payload}")
    return text.strip()
