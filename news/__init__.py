"""Agregador de noticias de PredictMotion.

Consume feeds RSS públicos de medios deportivos españoles (sindicación), los
normaliza, los etiqueta por liga/equipo y persiste JSON que lee el frontend
(/noticias). Solo stdlib. Corre en su propio cron, sin pasos manuales.

Legal / sindicación: SOLO se usa lo que el propio RSS ofrece — título + resumen
CORTO (truncado defensivamente) + enlace al original + atribución de la fuente.
Nunca el cuerpo del artículo (`content:encoded` se ignora) ni scraping del HTML.
"""
