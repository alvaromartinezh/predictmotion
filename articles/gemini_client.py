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
from .config import GEMINI_MODEL, GEMINI_MODEL_GROUNDED, gemini_endpoint

HTTP_TIMEOUT = 60  # s — generación de texto, más lento que un fetch normal


class GeminiError(Exception):
    """Fallo de la llamada a Gemini (HTTP, respuesta vacía o key ausente)."""


def _model_for(tools):
    """Qué modelo atiende esta llamada. El criterio es si lleva grounding, no
    el tipo de artículo: `tools` solo lo pone generate_grounded() y ese camino
    es exclusivo de previa_diaria (writer.py). Así el reparto vive en UN sitio
    y no hay un mapa tipo→modelo que mantener en paralelo al `if` de writer."""
    return GEMINI_MODEL_GROUNDED if tools else GEMINI_MODEL


def _call(prompt, temperature, tools=None):
    """POST a generateContent; devuelve (texto, candidate) crudo. Compartido
    por generate() y generate_grounded() — la única diferencia entre ambas es
    si se manda `tools` (Grounding with Google Search) y qué se extrae del
    candidate además del texto."""
    _load_env()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GEMINI_API_KEY no está definida en el entorno/.env")

    req_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    if tools:
        req_body["tools"] = tools

    model = _model_for(tools)
    req = urllib.request.Request(
        gemini_endpoint(model),
        data=json.dumps(req_body).encode("utf-8"),
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
        # El modelo va en el mensaje: desde que hay dos, un 429 no dice nada
        # si no se sabe cuál lo dio (la cuota es por modelo).
        raise GeminiError(f"HTTP {e.code} [{model}]: {detail}") from e
    except urllib.error.URLError as e:
        raise GeminiError(f"Fallo de red: {e.reason}") from e

    try:
        candidate = payload["candidates"][0]
        text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
    except (KeyError, IndexError) as e:
        raise GeminiError(f"Respuesta sin texto utilizable: {payload}") from e

    if not text.strip():
        raise GeminiError(f"Respuesta vacía: {payload}")
    return text.strip(), candidate


def generate(prompt, *, temperature=0.6):
    """Llama a generateContent y devuelve el texto plano de la respuesta.

    Lanza GeminiError con el detalle (código HTTP + cuerpo) si falla — el
    llamador decide si es best-effort (igual que espn.fetch_* deja propagar y
    el orquestador captura por-artículo, como news/aggregate.py hace por-feed).
    """
    text, _candidate = _call(prompt, temperature)
    return text


def extract_sources(candidate):
    """[{'uri','title'}] de groundingChunks, o [] si no hay — nunca lanza
    (defensivo: un cambio de forma en el JSON de Google degrada a sin
    fuentes, no a una excepción)."""
    out = []
    chunks = ((candidate or {}).get("groundingMetadata") or {}).get("groundingChunks") or []
    for chunk in chunks:
        web = (chunk or {}).get("web") or {}
        if web.get("uri"):
            out.append({"uri": web["uri"], "title": web.get("title") or web["uri"]})
    return out


def generate_grounded(prompt, *, temperature=0.6):
    """Como generate(), pero con Grounding with Google Search activado —
    para contenido que necesita datos que no están en nuestro propio payload
    (noticias/lesiones de previa_diaria; NINGÚN otro tipo de artículo la usa).
    Devuelve (texto, fuentes); fuentes vacío si Gemini no buscó o no citó nada
    (esto es una salida válida, no un error — el prompt le pide explícitamente
    no rellenar con inventos si no hay nada real que citar)."""
    text, candidate = _call(prompt, temperature, tools=[{"google_search": {}}])
    return text, extract_sources(candidate)
