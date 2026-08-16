"""Generador de artículos editoriales de PredictMotion (Gemini API).

Genera recaps de jornada, explicadores "por qué el modelo da a X un Y%" y
análisis de carrera por el título, grounded en los snapshots reales que ya
produce `seo/` (data/<slug>/latest.json). Solo stdlib (llamada a Gemini vía
HTTP directo, sin SDK — ver articles/gemini_client.py).

Por defecto NO publica nada (ver generate.py --publish): mientras se afina,
escribe a data/articles_preview/ para revisión manual.
"""
