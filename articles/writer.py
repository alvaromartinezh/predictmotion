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
from .config import GROUNDING_TOLERANCE_PP, STAT_KINDS
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
        "Escribe un resumen de los partidos de {liga} que han terminado hoy: "
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

# Broadsheet de PARTIDO (un partido de Hypermotion terminado hoy, ver
# render.py:render_match_broadsheet): 3 llamadas de contenido (local /
# visitante / crónica central) sobre el MISMO payload (grounding.ground_match)
# con solo el campo "tipo" cambiado por el llamador (generate.py) — así los
# tres textos comparten pool de hechos válidos para el validador de
# grounding, en vez de tener payloads recortados por texto.
_MATCH_SIDE_INSTR_TMPL = (
    "Analiza el partido desde la perspectiva del equipo {lado} (el objeto DATOS.{campo}): "
    "cómo le afecta el resultado, cómo cambia la probabilidad de su zona actual (compara "
    "'antes' con 'actual' en DATOS.{campo}.zonas) y su situación en la tabla (posición, "
    "puntos). Si DATOS.{campo}.rating_fuerza está presente, puedes usarlo como el "
    "argumento de fondo del modelo para sus opciones a más largo plazo.\n\n"
    "FORMATO OBLIGATORIO: escribe EXACTAMENTE 3 párrafos cortos (50-80 palabras cada uno) "
    "separados por una línea en blanco. Sin introducción ni cierre genérico: cada párrafo "
    "aporta algo nuevo (el efecto inmediato del resultado / cómo lo lee el modelo / qué "
    "viene después). No repitas el marcador completo en cada párrafo."
)

_INSTRUCTIONS["match_local"] = _MATCH_SIDE_INSTR_TMPL.format(lado="local", campo="local")
_INSTRUCTIONS["match_visitante"] = _MATCH_SIDE_INSTR_TMPL.format(lado="visitante", campo="visitante")
_INSTRUCTIONS["match_cronica"] = (
    "Escribe la crónica central de este partido de {liga}: el resultado, qué explica "
    "ese marcador y qué dice del nivel de cada equipo según el modelo. Usa el resultado y "
    "los datos de DATOS.local/DATOS.visitante — si no hay detalle de goles o jugadas, cíñete "
    "al marcador final, no inventes minutos ni autores.\n\n"
    "FORMATO OBLIGATORIO: escribe EXACTAMENTE 4 párrafos separados por una línea en blanco. "
    "Sin titular ni frase de apertura tipo 'En un partido...': empieza directo con el hecho."
)

# "Dato curioso" (articles/render.py:render_stat_broadsheet, ver STAT_KINDS en
# config.py): 2 llamadas de contenido sobre el MISMO payload
# (grounding.ground_stat) — el protagonista (DATOS.protagonista) y sus
# perseguidores (DATOS.perseguidores, un párrafo por elemento, mismo
# contrato que _ONE_PARA_PER_MATCH). Una instrucción por kind (registradas
# más abajo con el verbo ya sustituido) para no obligar a Gemini a inferir
# "acabar colista" vs "acabar líder" del resto del payload.
_STAT_PROTAGONIST_INSTR = (
    "Escribe sobre el dato curioso del día: el equipo con más probabilidad, según el "
    "modelo, de {verb} (DATOS.protagonista es ese equipo). Explica el contraste entre su "
    "situación real en la tabla (posición, puntos, forma) y lo que dice el modelo (compara "
    "DATOS.protagonista.valor con DATOS.protagonista.valor_antes si existe), y qué papel "
    "juega su rating de fuerza (DATOS.protagonista.rating_fuerza) en esa proyección a largo "
    "plazo.\n\n"
    "FORMATO OBLIGATORIO: escribe EXACTAMENTE 4 párrafos cortos (60-90 palabras cada uno) "
    "separados por una línea en blanco. Sin introducción genérica ni cierre tipo 'en "
    "resumen': cada párrafo aporta algo nuevo."
)

_STAT_CHASERS_INSTR = (
    "Escribe sobre los otros candidatos a {verb}: DATOS.perseguidores es la lista de los "
    "siguientes equipos con más probabilidad tras el protagonista, en orden. Un párrafo "
    "breve por cada uno explicando por qué el modelo lo sitúa ahí.\n\n"
    "FORMATO OBLIGATORIO: escribe EXACTAMENTE un párrafo por cada elemento de "
    "DATOS.perseguidores, en el MISMO orden, separados por una línea en blanco (si hay 3 "
    "elementos, 3 párrafos: ni uno más ni uno menos). Cada párrafo se publica junto al "
    "nombre y el dato de ese equipo, así que no hace falta repetirlo como apertura forzada, "
    "y no empieces con conectores que remitan al párrafo anterior."
)


def _compose_stat_head(payload):
    p = payload["protagonista"]
    title = f'{p["nombre"]}, el favorito a {payload["dato_verbo"]} en {payload["liga"]} | PredictMotion'
    desc = (f'El modelo de PredictMotion da al {p["nombre"]} un {pct(p["valor"])} de probabilidad de '
            f'{payload["dato_verbo"]} en {payload["liga"]} tras la jornada {payload["jornada"]}.')
    return title, desc


def build_prompt(payload):
    instr = _INSTRUCTIONS[payload["tipo"]].format(liga=payload["liga"])
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


def _compose_match_head(payload):
    l, v, r = payload["local"], payload["visitante"], payload["resultado"]
    title = f'{l["nombre"]} {r["local"]}-{r["visitante"]} {v["nombre"]} | PredictMotion'
    desc = (f'Crónica del {l["nombre"]} {r["local"]}-{r["visitante"]} {v["nombre"]} '
            f'({payload["liga"]}, jornada {payload["jornada"]}) y cómo cambia la '
            f'probabilidad de zona de ambos según el modelo de PredictMotion.')
    return title, desc


_HEAD_BUILDERS = {
    "resumen_diario": _compose_resumen_head,
    "explicador_probabilidad": _compose_explainer_head,
    "match_local": _compose_match_head,
    "match_visitante": _compose_match_head,
    "match_cronica": _compose_match_head,
}

# Un tipo "dato_<kind>_protagonista"/"dato_<kind>_perseguidores" por cada
# STAT_KINDS, con el verbo ya sustituido (ver _STAT_PROTAGONIST_INSTR/
# _STAT_CHASERS_INSTR arriba) — mismo patrón que match_local/visitante con
# lado/campo ya sustituidos.
for _stat_kind, _stat_info in STAT_KINDS.items():
    _INSTRUCTIONS[f"dato_{_stat_kind}_protagonista"] = _STAT_PROTAGONIST_INSTR.format(verb=_stat_info["verbo_largo"])
    _INSTRUCTIONS[f"dato_{_stat_kind}_perseguidores"] = _STAT_CHASERS_INSTR.format(verb=_stat_info["verbo_largo"])
    _HEAD_BUILDERS[f"dato_{_stat_kind}_protagonista"] = _compose_stat_head
    _HEAD_BUILDERS[f"dato_{_stat_kind}_perseguidores"] = _compose_stat_head
del _stat_kind, _stat_info


_HEADLINE_SYSTEM = (
    "Eres el redactor de titulares de PredictMotion, un sitio de predicciones de "
    "fútbol basadas en simulación Monte Carlo. Español, tono periodístico con "
    "gancho — el titular y el subtítulo deben dar ganas de hacer clic, sin caer en "
    "el sensacionalismo vacío ni en inventar nada."
)

_HEADLINE_INSTR = (
    "Escribe un titular llamativo para la portada de un resumen de los partidos de "
    "{liga} de hoy (sin dos puntos, sin comillas, sin mencionar el número de "
    "partidos jugados). El TITULAR (la primera línea) es lo que se manda tal cual a "
    "Telegram como titular del tuit, así que DEBE incluir al menos un porcentaje real "
    "de DATOS (una probabilidad de zona de algún equipo, con el símbolo %) — es el "
    "gancho del tuit. Y, en la línea siguiente, un subtítulo corto y también llamativo "
    "que cuente cómo han quedado los equipos. Que no se repitan casi las mismas "
    "palabras entre las dos líneas.\n\n"
    "FORMATO OBLIGATORIO: EXACTAMENTE 2 líneas — primero el titular (CON el "
    "porcentaje), luego el subtítulo — sin etiquetas ('Titular:'/'Subtítulo:'), sin "
    "numerarlas, sin nada más de texto. Usa siempre el nombre de cada equipo tal cual "
    "aparece en DATOS — NUNCA un gentilicio, apodo o ciudad ('alicantina', 'merengues', "
    "'el conjunto de Vigo'...): si no estás seguro de a qué ciudad o afición "
    "corresponde, lo más probable es que te equivoques, y eso no está en DATOS."
)


_MATCH_HEADLINE_INSTR = (
    "Escribe un titular llamativo para la crónica de este partido de {liga} (sin dos "
    "puntos, sin comillas). El TITULAR (la primera línea) es lo que se manda tal cual a "
    "Telegram como titular del tuit, así que DEBE incluir al menos un porcentaje real de "
    "DATOS.local o DATOS.visitante (una probabilidad de zona de alguno de los dos "
    "equipos, con el símbolo %) — es el gancho del tuit; el marcador del partido también "
    "puedes mencionarlo, está en DATOS. Y, en la línea siguiente, una entradilla corta y "
    "también llamativa (1 frase) que enganche a seguir leyendo. Que no se repitan casi "
    "las mismas palabras entre las dos líneas.\n\n"
    "FORMATO OBLIGATORIO: EXACTAMENTE 2 líneas — primero el titular (CON el "
    "porcentaje), luego la entradilla — sin etiquetas ('Titular:'/'Entradilla:'), sin "
    "numerarlas, sin nada más de texto. Usa siempre el nombre de cada equipo tal cual "
    "aparece en DATOS.local.nombre/DATOS.visitante.nombre — NUNCA un gentilicio, apodo o "
    "ciudad: si no estás seguro de a qué ciudad o afición corresponde, lo más probable "
    "es que te equivoques."
)


_STAT_HEADLINE_INSTR = (
    "Escribe un titular llamativo para un artículo sobre el dato curioso del día: el equipo "
    "con más probabilidad de {verb}, según el modelo (el objeto DATOS.protagonista). Sin dos "
    "puntos, sin comillas. El TITULAR (la primera línea) es lo que se manda tal cual a "
    "Telegram como titular del tuit, así que DEBE incluir el porcentaje real "
    "DATOS.protagonista.valor (con el símbolo %) y el nombre del equipo tal cual aparece en "
    "DATOS.protagonista.nombre. Y, en la línea siguiente, una entradilla corta y también "
    "llamativa (1 frase) que enganche a seguir leyendo.\n\n"
    "FORMATO OBLIGATORIO: EXACTAMENTE 2 líneas — primero el titular (CON el porcentaje y el "
    "nombre del equipo), luego la entradilla — sin etiquetas ('Titular:'/'Entradilla:'), sin "
    "numerarlas, sin nada más de texto. Usa siempre el nombre del equipo tal cual aparece en "
    "DATOS.protagonista.nombre — NUNCA un gentilicio, apodo o ciudad: si no estás seguro de a "
    "qué ciudad o afición corresponde, lo más probable es que te equivoques."
)

_STAT_HEADLINE_INSTR_BY_KIND = {
    k: _STAT_HEADLINE_INSTR.format(verb=v["verbo_largo"]) for k, v in STAT_KINDS.items()
}


def write_headline(payload, instr=_HEADLINE_INSTR):
    """Titular + subtítulo llamativos (a petición expresa: deben "dar ganas
    de hacer clic"). Devuelve (titular, subtitulo) o None si Gemini falla,
    no respeta el formato de 2 líneas, el titular no lleva ningún porcentaje
    (a petición expresa: el titular es lo que se manda tal cual a Telegram
    como titular del tuit — generate._notify_telegram solo usa esta primera
    línea, no la segunda), o cuela una cifra que no está en el payload — en
    cualquiera de esos casos el llamador cae a la cabecera determinista en
    vez de bloquear la publicación por un titular que solo es un adorno.
    `instr`: _HEADLINE_INSTR (resumen diario) por defecto; _MATCH_HEADLINE_INSTR
    para el broadsheet de partido."""
    instr = instr.format(liga=payload["liga"])
    prompt = f"{_HEADLINE_SYSTEM}\n\n{instr}\n\nDATOS:\n{grounding.to_prompt_json(payload)}"
    try:
        text = generate(prompt, temperature=0.9)
    except GeminiError:
        return None
    lines = [l.strip(" \"'") for l in text.strip().split("\n") if l.strip()]
    if len(lines) != 2:
        return None
    if not _PCT_RE.search(lines[0]):
        return None
    ok, _ = validate_grounding(text, payload)
    if not ok:
        return None
    return lines[0], lines[1]


def write_match_headline(payload):
    """write_headline() con las instrucciones del broadsheet de partido
    (titular + entradilla, marcador permitido en vez de vetado)."""
    return write_headline(payload, instr=_MATCH_HEADLINE_INSTR)


def write_stat_headline(payload):
    """write_headline() con las instrucciones del dato curioso (una por kind,
    ver STAT_KINDS/_STAT_HEADLINE_INSTR_BY_KIND — el verbo ya sustituido)."""
    return write_headline(payload, instr=_STAT_HEADLINE_INSTR_BY_KIND[payload["kind"]])


def split_explainer_paragraphs(body):
    """(side_paras, note_paras) según el contrato de 3 párrafos de
    _INSTRUCTIONS['explicador_probabilidad'] — los 2 primeros van en la
    columna estrecha, el resto (normalmente 1) en la caja "Nota del
    modelo". Si Gemini no respetó el contrato (<3 párrafos), todo va a la
    columna estrecha y no hay nota. Única fuente: la usan tanto render.py
    (maquetación) como layout_estimate.py (estimar altura de columna)."""
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    return (paras[:2], paras[2:]) if len(paras) >= 3 else (paras, [])


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
