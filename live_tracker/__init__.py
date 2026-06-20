"""Seguimiento de partido en vivo — backend proxy + caché sobre la API de ESPN.

Toda la lógica específica de ESPN vive en `providers/espn.py`. El resto del
código trabaja con el modelo normalizado de `models.py`, de modo que cambiar de
fuente (API-Football, etc.) solo afecta al provider. Ver CLAUDE.md.
"""
