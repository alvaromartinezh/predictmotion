"""Construcción del prompt, llamada a Gemini y validación de grounding.

El título y la meta description NUNCA los escribe Gemini: se componen aquí de
forma determinista a partir del mismo payload de hechos (igual que
seo/snapshots.py:render_head_fragments hace para los dashboards), para no
dejar la superficie SEO-crítica (<title>/<meta>) en manos de texto libre. Solo
el cuerpo narrativo es generado, y se valida antes de aceptarlo.
"""

import re
from datetime import datetime, timezone

from seo.textutil import pct, slugify

from . import grounding
from .config import GROUNDING_TOLERANCE_PP
from .gemini_client import generate

_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")

_SYSTEM = (
    "Eres redactor deportivo de PredictMotion, un sitio de predicciones de fútbol "
    "basadas en simulación Monte Carlo. Escribe en español, tono periodístico y "
    "cercano, SIN titulares, SIN encabezados markdown, SIN listas — solo párrafos "
    "de prosa (3 a 5 párrafos).\n\n"
    "REGLA INQUEBRANTABLE: usa ÚNICAMENTE los datos numéricos del bloque DATOS de "
    "abajo. No inventes estadísticas, porcentajes, lesionados, fichajes, resultados "
    "de partidos ni cifras que no estén ahí. Si te falta contexto, exprésalo en "
    "términos generales sin inventar ningún número."
)

_INSTRUCTIONS = {
    "recap_jornada": (
        "Escribe un recap de la jornada: quién lidera, qué equipos han subido o "
        "bajado más probabilidad, y por qué le importa a la afición."
    ),
    "explicador_probabilidad": (
        "Explica por qué el modelo le da a este equipo esas probabilidades: "
        "compáralo con sus vecinos de tabla y con su rating de fuerza."
    ),
    "carrera_titulo": (
        "Analiza la carrera por el título/primera plaza: quién manda, cuánto "
        "margen tiene y cómo ha cambiado desde la jornada anterior."
    ),
}


def build_prompt(payload):
    instr = _INSTRUCTIONS[payload["tipo"]]
    return (
        f"{_SYSTEM}\n\n{instr}\n\n"
        f"DATOS:\n{grounding.to_prompt_json(payload)}"
    )


def validate_grounding(body, payload):
    """True si toda cifra '%' del cuerpo cae a <= GROUNDING_TOLERANCE_PP de algún
    valor real del payload. Devuelve (ok, cifras_no_encontradas)."""
    facts = grounding.numeric_facts(payload)
    bad = []
    for raw in _PCT_RE.findall(body):
        val = float(raw.replace(",", "."))
        if not any(abs(val - f) <= GROUNDING_TOLERANCE_PP for f in facts):
            bad.append(val)
    return (not bad, bad)


def _compose_recap_head(payload):
    lider = payload["lider"]
    title = (f'Jornada {payload["jornada"]} de {payload["liga"]}: {lider["nombre"]} lidera '
             f'con {pct(lider["prob_zona_principal"])} de {payload["zona_principal"].lower()} '
             f'| PredictMotion')
    desc = (f'Recap de la jornada {payload["jornada"]} de {payload["liga"]}: '
            f'{lider["nombre"]} manda con {lider["puntos"]} puntos y '
            f'{pct(lider["prob_zona_principal"])} de {payload["zona_principal"].lower()} '
            f'según el modelo de PredictMotion.')
    return title, desc


def _compose_explainer_head(payload):
    zonas = payload["probabilidades_por_zona"]
    top_zona, top_val = max(zonas.items(), key=lambda kv: kv[1] or 0)
    title = (f'¿Por qué el modelo da al {payload["equipo"]} un {pct(top_val)} de '
             f'{top_zona.lower()}? | PredictMotion')
    desc = (f'El {payload["equipo"]} es {payload["posicion"]}º en {payload["liga"]} con '
            f'{payload["puntos"]} puntos. El modelo de PredictMotion le da un {pct(top_val)} '
            f'de {top_zona.lower()} tras la jornada {payload["jornada"]}.')
    return title, desc


def _compose_title_race_head(payload):
    c = payload["candidatos"][0]
    title = (f'Carrera por el título en {payload["liga"]}: {c["nombre"]} con '
             f'{pct(c["prob_titulo"])} tras la jornada {payload["jornada"]} | PredictMotion')
    desc = (f'{c["nombre"]} lidera la carrera por el título de {payload["liga"]} con '
            f'{pct(c["prob_titulo"])} de probabilidad según el modelo de PredictMotion, '
            f'tras la jornada {payload["jornada"]}.')
    return title, desc


_HEAD_BUILDERS = {
    "recap_jornada": _compose_recap_head,
    "explicador_probabilidad": _compose_explainer_head,
    "carrera_titulo": _compose_title_race_head,
}


def _article_slug(league_slug, payload):
    tipo = payload["tipo"]
    j = payload["jornada"]
    if tipo == "recap_jornada":
        return f"{league_slug}-jornada-{j}-recap"
    if tipo == "explicador_probabilidad":
        return f"{league_slug}-{slugify(payload['equipo'])}-probabilidad-j{j}"
    if tipo == "carrera_titulo":
        return f"{league_slug}-carrera-titulo-j{j}"
    raise ValueError(f"tipo de artículo desconocido: {tipo}")


def write_article(league_slug, payload):
    """Genera un artículo a partir de un payload de hechos ya construido.

    Devuelve el dict de metadata+cuerpo listo para persistir (status
    'draft' si pasa el validador de grounding, 'flagged' si no — nunca lanza
    por un fallo de validación, solo por un fallo real de la llamada a
    Gemini, que el llamador trata best-effort).
    """
    prompt = build_prompt(payload)
    body = generate(prompt)
    ok, bad_values = validate_grounding(body, payload)
    title, description = _HEAD_BUILDERS[payload["tipo"]](payload)

    return {
        "slug": _article_slug(league_slug, payload),
        "type": payload["tipo"],
        "league": league_slug,
        "title": title,
        "meta_description": description,
        "body": body,
        "grounding_data": payload,
        "status": "draft" if ok else "flagged",
        "flagged_values": bad_values,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
