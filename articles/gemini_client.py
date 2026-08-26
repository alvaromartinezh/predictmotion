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
    """Fallo de la llamada a Gemini (HTTP, respuesta vacía o key ausente).

    `transient` distingue lo que se arregla solo de lo que necesita a un humano:

    - **transitorio** (timeout, 429, corte de red): el artículo de esta pasada no
      sale, pero el cron vuelve en 5 min o en 1 h y lo reintenta. Avisar por email
      de esto es ruido — el 2026-08-26 llegó una alerta por un timeout de 60 s que
      ya se había recuperado solo.
    - **permanente** (falta GEMINI_API_KEY, respuesta con una forma que no
      entendemos): no se arregla reintentando y sí hay que enterarse.
    """

    def __init__(self, msg, transient=False):
        super().__init__(msg)
        self.transient = transient


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
        # 429 = cuota (se recupera al reiniciarse la ventana), 5xx = lado Google.
        raise GeminiError(f"HTTP {e.code} [{model}]: {detail}",
                          transient=e.code == 429 or e.code >= 500) from e
    except urllib.error.URLError as e:
        raise GeminiError(f"Fallo de red: {e.reason}", transient=True) from e
    except TimeoutError as e:
        # urlopen(timeout=) lanza TimeoutError, que NO es subclase de URLError:
        # se escapaba de los dos except de arriba, subía en crudo hasta main() y
        # ABORTABA la liga entera (se veía en articles_previa.log: la previa de
        # laliga muerta con alerta por email). Convertido a GeminiError degrada a
        # un [SKIP] del artículo, que es lo que el orquestador ya sabe manejar; el
        # propio cron es el reintento, no hace falta un bucle aquí.
        raise GeminiError(f"Timeout de {HTTP_TIMEOUT}s [{model}]", transient=True) from e

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
