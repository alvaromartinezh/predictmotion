"""Construcción del prompt, llamada a Gemini y validación de grounding.

El título NUNCA lo escribe Gemini: se compone aquí de forma determinista a
partir del mismo payload de hechos (igual que seo/snapshots.py hace para los
dashboards), para no dejar la superficie SEO-crítica en manos de texto
libre. Solo el cuerpo narrativo es generado, y se valida antes de aceptarlo.
"""

import re

from seo.textutil import pct

from . import grounding
from .config import GROUNDING_TOLERANCE_PP
from .gemini_client import generate

_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")

_SYSTEM = (
    "Eres redactor deportivo de PredictMotion, un sitio de predicciones de fútbol "
    "basadas en simulación Monte Carlo. Escribe en español, tono periodístico y "
    "cercano, SIN titulares, SIN encabezados markdown, SIN listas — solo párrafos "
    "de prosa.\n\n"
    "REGLA INQUEBRANTABLE: usa ÚNICAMENTE los datos numéricos del bloque DATOS de "
    "abajo. No inventes estadísticas, porcentajes, lesionados, fichajes, resultados "
    "de partidos ni cifras que no estén ahí. Si te falta contexto, exprésalo en "
    "términos generales sin inventar ningún número."
)

# render.py MAQUETA por partido (un breve por partido, ver _briefs_html): si
# el recuento no es 1:1 degrada a prosa suelta, así que sin esta regla
# explícita la maqueta por partido no sale nunca.
_ONE_PARA_PER_MATCH = (
    "\n\nFORMATO OBLIGATORIO: escribe EXACTAMENTE un párrafo por cada partido de "
    "DATOS.partidos, en el MISMO orden, separados por una línea en blanco. Si hay 4 "
    "partidos, el cuerpo tiene 4 párrafos: ni uno más ni uno menos. Nada de párrafo de "
    "introducción o de cierre, y nada de juntar dos partidos en un mismo párrafo. Cada "
    "párrafo tiene que sostenerse solo (se publica como una pieza independiente, no como "
    "parte de un texto corrido): no empieces con conectores que remitan al párrafo "
    "anterior ('Continuando con...', 'En otro frente...', 'El cierre de la jornada...')."
)

_INSTRUCTIONS = {
    "resumen_diario": (
        "Escribe un resumen de los partidos de Hypermotion que han terminado hoy: "
        "resultados y cómo cambia la probabilidad de zona de cada equipo implicado. "
        "Antes de cada partido el modelo daba a cada equipo la probabilidad "
        "'prob_zona_antes_del_partido' de su zona; compárala con 'prob_zona_actual' "
        "para explicar qué cambió con el resultado." + _ONE_PARA_PER_MATCH
    ),
    "explicador_probabilidad": (
        "Explica por qué el modelo le da a este equipo esas probabilidades: "
        "compáralo con sus vecinos de tabla y con su rating de fuerza.\n\n"
        "FORMATO OBLIGATORIO: escribe EXACTAMENTE 3 párrafos separados por una línea "
        "en blanco. Los dos primeros son cortos (60-90 palabras cada uno) y van en una "
        "columna estrecha: sitúan al equipo (posición, puntos, forma) y comparan con "
        "sus vecinos de tabla. El tercero es una nota de cierre (70-100 palabras) que "
        "explica el papel del rating de fuerza en las probabilidades del modelo — se "
        "publica aparte como 'Nota del modelo', así que tiene que sostenerse solo, sin "
        "frases que remitan a los párrafos anteriores."
    ),
}


def build_prompt(payload):
    instr = _INSTRUCTIONS[payload["tipo"]]
    return f"{_SYSTEM}\n\n{instr}\n\nDATOS:\n{grounding.to_prompt_json(payload)}"


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


def _compose_resumen_head(payload):
    n = len(payload["partidos"])
    plural = "partidos" if n != 1 else "partido"
    title = f'Resumen del día en {payload["liga"]}: {n} {plural} | PredictMotion'
    desc = (f'Cómo han quedado hoy los {n} {plural} de {payload["liga"]} y cómo cambian las '
            f'probabilidades de zona según el modelo de PredictMotion.')
    return title, desc


def _compose_explainer_head(payload):
    zonas = payload["probabilidades_por_zona"]
    top_zona, top_val = max(zonas.items(), key=lambda kv: kv[1] or 0)
    title = (f'El modelo da al {payload["equipo"]} un {pct(top_val)} de '
             f'{top_zona.lower()} | PredictMotion')
    desc = (f'El {payload["equipo"]} es {payload["posicion"]}º en {payload["liga"]} con '
            f'{payload["puntos"]} puntos. El modelo de PredictMotion le da un {pct(top_val)} '
            f'de {top_zona.lower()} tras la jornada {payload["jornada"]}.')
    return title, desc


_HEAD_BUILDERS = {
    "resumen_diario": _compose_resumen_head,
    "explicador_probabilidad": _compose_explainer_head,
}


def write_article(payload):
    """Genera el cuerpo de un artículo a partir de un payload de hechos ya
    construido. Devuelve dict con title/description/body/status/flagged_values.

    status='flagged' si no pasa el validador de grounding numérico — nunca se
    publica; el llamador decide qué hacer (best-effort, alerta y aborta el
    día). Nunca lanza por esto, solo por un fallo real de la llamada a
    Gemini, que el llamador trata best-effort."""
    tipo = payload["tipo"]
    body = generate(build_prompt(payload))
    ok, bad_values = validate_grounding(body, payload)
    title, description = _HEAD_BUILDERS[tipo](payload)
    return {
        "title": title, "meta_description": description, "body": body,
        "status": "draft" if ok else "flagged", "flagged_values": bad_values,
    }
