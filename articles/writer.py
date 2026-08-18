"""Construcción del prompt, llamada a Gemini y validación de grounding.

El título/meta lo compone esta función de forma determinista a partir del
mismo payload de hechos (igual que seo/snapshots.py hace para los
dashboards), para no dejar la superficie SEO-crítica en manos de texto
libre por defecto. Única excepción, a petición expresa: el titular+subtítulo
"llamativos" del resumen diario (`write_headline`) SÍ los escribe Gemini —
pero pasan por el mismo validador de grounding, y si fallan (API, formato,
cifra inventada) el llamador cae al título determinista en vez de bloquear
la publicación por esto.
"""

import re

from seo.textutil import pct

from . import grounding
from .config import GROUNDING_TOLERANCE_PP
from .gemini_client import GeminiError, generate

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
    title = f'Resumen del día en {payload["liga"]} | PredictMotion'
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


_HEADLINE_SYSTEM = (
    "Eres el redactor de titulares de PredictMotion, un sitio de predicciones de "
    "fútbol basadas en simulación Monte Carlo. Español, tono periodístico con "
    "gancho — el titular y el subtítulo deben dar ganas de hacer clic, sin caer en "
    "el sensacionalismo vacío ni en inventar nada."
)

_HEADLINE_INSTR = (
    "Escribe un titular llamativo para la portada de un resumen de los partidos de "
    "Hypermotion de hoy (sin dos puntos, sin comillas, sin mencionar el número de "
    "partidos jugados) y, en la línea siguiente, un subtítulo corto y también "
    "llamativo que cuente cómo han quedado los equipos. Que no se repitan casi las "
    "mismas palabras entre las dos líneas.\n\n"
    "FORMATO OBLIGATORIO: EXACTAMENTE 2 líneas — primero el titular, luego el "
    "subtítulo — sin etiquetas ('Titular:'/'Subtítulo:'), sin numerarlas, sin nada "
    "más de texto. No menciones ningún porcentaje ni cifra: eso va en el cuerpo del "
    "artículo, no aquí."
)


def write_headline(payload):
    """Titular + subtítulo llamativos para el resumen del día (a petición
    expresa: deben "dar ganas de hacer clic"). Devuelve (titular, subtitulo)
    o None si Gemini falla, no respeta el formato de 2 líneas, o cuela una
    cifra que no está en el payload — en cualquiera de esos casos el
    llamador cae a la cabecera determinista en vez de bloquear la
    publicación por un titular que solo es un adorno."""
    prompt = f"{_HEADLINE_SYSTEM}\n\n{_HEADLINE_INSTR}\n\nDATOS:\n{grounding.to_prompt_json(payload)}"
    try:
        text = generate(prompt, temperature=0.9)
    except GeminiError:
        return None
    lines = [l.strip(" \"'") for l in text.strip().split("\n") if l.strip()]
    if len(lines) != 2:
        return None
    ok, _ = validate_grounding(text, payload)
    if not ok:
        return None
    return lines[0], lines[1]


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
