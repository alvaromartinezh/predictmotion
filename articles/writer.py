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
from .config import GROUNDING_TOLERANCE_PP, PREVIA_NEWS_REVIEW_UNTIL
from .gemini_client import generate, generate_grounded

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

# Solo se añade al prompt de previa_diaria (el único tipo con Grounding with
# Google Search activado) — SUAVIZA la regla inquebrantable de arriba (que
# por defecto prohíbe cualquier cosa fuera de DATOS) para permitir contexto
# real de búsqueda, sin abrir la puerta a inventar.
_SEARCH_SYSTEM_SUFFIX = (
    "\n\nADEMÁS, para esta previa tienes activada la búsqueda de Google: puedes buscar "
    "bajas, sanciones o noticias recientes de los equipos de DATOS y usarlas. Pero SOLO "
    "si la búsqueda encuentra algo real y concreto — si no encuentras nada relevante para "
    "un equipo, no menciones su actualidad y quédate con las probabilidades del modelo. "
    "Una búsqueda vacía no es excusa para inventar contexto. Si citas una cifra que viene "
    "de la búsqueda (no del bloque DATOS), no la escribas con el símbolo '%' — así no se "
    "confunde con las probabilidades del modelo."
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
    "cronica_partido": (
        "Escribe una crónica breve del partido que acaba de terminar: el resultado y cómo "
        "queda cada equipo. Antes del partido el modelo daba a cada equipo la probabilidad "
        "'prob_zona_antes_del_partido' de su zona; compárala explícitamente con "
        "'prob_zona_actual' para explicar qué cambió con este resultado. Si el payload trae "
        "'estadisticas' (posesión, tiros...) o 'eventos' (goles, expulsiones, cambios), úsalos "
        "para explicar CÓMO se dio el resultado, no solo el marcador — p.ej. si un equipo ganó "
        "pese a tener menos posesión o menos tiros. No etiquetes ningún cambio como forzado por "
        "lesión: el dato no lo dice, no lo inventes."
    ),
    "previa_diaria": (
        "Escribe una previa de los partidos de hoy: qué se juega cada equipo según "
        "el modelo y por qué le importa a la afición."
    ),
    "resumen_diario": (
        "Escribe un resumen de los partidos de esta liga que han terminado hoy: resultados y "
        "cómo cambia la probabilidad de zona de cada equipo implicado. Antes de cada partido el "
        "modelo daba a cada equipo la probabilidad 'prob_zona_antes_del_partido' de su zona; "
        "compárala con 'prob_zona_actual' para explicar qué cambió con el resultado. Si hay "
        "varios partidos, dales a todos su espacio, no solo al más llamativo."
    ),
}


def build_prompt(payload):
    instr = _INSTRUCTIONS[payload["tipo"]]
    system = _SYSTEM + (_SEARCH_SYSTEM_SUFFIX if payload["tipo"] == "previa_diaria" else "")
    return (
        f"{system}\n\n{instr}\n\n"
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


def _compose_cronica_head(payload):
    l, v, r = payload["local"], payload["visitante"], payload["resultado"]
    title = (f'{l["nombre"]} {r["local"]}-{r["visitante"]} {v["nombre"]}: crónica y '
             f'probabilidades | PredictMotion')
    desc = (f'{l["nombre"]} {r["local"]}-{r["visitante"]} {v["nombre"]} en {payload["liga"]}. '
            f'Cómo cambia el modelo de PredictMotion tras el partido.')
    return title, desc


def _compose_previa_head(payload):
    n = len(payload["partidos"])
    plural = "partidos" if n != 1 else "partido"
    title = f'Previa de hoy en {payload["liga"]}: {n} {plural} | PredictMotion'
    desc = (f'Lo que se juega hoy en {payload["liga"]} (jornada {payload["jornada"]}): '
            f'probabilidades de zona de los equipos en liza, según el modelo de PredictMotion.')
    return title, desc


def _compose_resumen_head(payload):
    n = len(payload["partidos"])
    plural = "partidos" if n != 1 else "partido"
    title = f'Resumen del día en {payload["liga"]}: {n} {plural} | PredictMotion'
    desc = (f'Cómo han quedado hoy los {n} {plural} de {payload["liga"]} y cómo cambian las '
            f'probabilidades de zona según el modelo de PredictMotion.')
    return title, desc


_HEAD_BUILDERS = {
    "recap_jornada": _compose_recap_head,
    "explicador_probabilidad": _compose_explainer_head,
    "carrera_titulo": _compose_title_race_head,
    "cronica_partido": _compose_cronica_head,
    "previa_diaria": _compose_previa_head,
    "resumen_diario": _compose_resumen_head,
}


def cronica_slug(league_slug, event_id):
    """Slug de la crónica de UN partido — única fuente (la usan _article_slug
    aquí abajo y render.py para enlazar a la crónica de un partido desde la
    previa/el resumen, exista ya o no)."""
    return f"{league_slug}-cronica-{event_id}"


def _article_slug(league_slug, payload):
    tipo = payload["tipo"]
    if tipo == "recap_jornada":
        return f"{league_slug}-jornada-{payload['jornada']}-recap"
    if tipo == "explicador_probabilidad":
        return f"{league_slug}-{slugify(payload['equipo'])}-probabilidad-j{payload['jornada']}"
    if tipo == "carrera_titulo":
        return f"{league_slug}-carrera-titulo-j{payload['jornada']}"
    if tipo == "cronica_partido":
        return cronica_slug(league_slug, payload['event_id'])
    if tipo == "previa_diaria":
        return f"{league_slug}-previa-{payload['fecha']}"
    if tipo == "resumen_diario":
        return f"{league_slug}-resumen-{payload['fecha']}"
    raise ValueError(f"tipo de artículo desconocido: {tipo}")


def write_article(league_slug, payload):
    """Genera un artículo a partir de un payload de hechos ya construido.

    Devuelve el dict de metadata+cuerpo listo para persistir. Status:
    - 'flagged' si no pasa el validador de grounding numérico (nunca se
      publica; nunca lanza por esto, solo por un fallo real de la llamada a
      Gemini, que el llamador trata best-effort).
    - 'pending_review' si es previa_diaria, pasó el validador Y trae fuentes
      de búsqueda (contexto externo real, no solo probabilidades del
      modelo) Y todavía estamos dentro de PREVIA_NEWS_REVIEW_UNTIL — se
      audita pero no se publica hasta que alguien lo revise o pase la fecha.
    - 'draft' en cualquier otro caso (se publica).
    """
    tipo = payload["tipo"]
    prompt = build_prompt(payload)
    if tipo == "previa_diaria":
        body, sources = generate_grounded(prompt)
    else:
        body, sources = generate(prompt), []

    ok, bad_values = validate_grounding(body, payload)
    title, description = _HEAD_BUILDERS[tipo](payload)

    status = "draft" if ok else "flagged"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if status == "draft" and tipo == "previa_diaria" and sources and today < PREVIA_NEWS_REVIEW_UNTIL:
        status = "pending_review"

    return {
        "slug": _article_slug(league_slug, payload),
        "type": tipo,
        "league": league_slug,
        "title": title,
        "meta_description": description,
        "body": body,
        "grounding_data": payload,
        "sources": sources,
        "status": status,
        "flagged_values": bad_values,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
