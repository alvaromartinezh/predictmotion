"""Catálogo de competiciones válidas (para validar follows y votos).

Fuente única: los dos registros de seo/config.py — LEAGUES (clubes) y GROUP_PAGES
(selecciones; ver docs/selecciones). Importar seo.config es barato y seguro (solo
depende de pathlib; sin efectos de red al importar). Si por lo que sea no se
pudiera importar, caemos a una lista fija equivalente para no dejar de validar
(y no rechazar todo).

⚠️ Las dos listas, no solo LEAGUES: una competición que falte aquí no se puede
seguir ni votar (400 invalid-slug), aunque su página funcione. Pasó con las
cuatro de selecciones el 2026-10-08.

Se cachea en memoria: el catálogo solo cambia al añadir una competición (redeploy).
"""

from __future__ import annotations

import logging

log = logging.getLogger("accounts.catalog")

# Fallback fijo (debe casar con seo/config.py → LEAGUES + GROUP_PAGES).
_FALLBACK_SLUGS = {
    "laliga", "hypermotion", "premier", "championship", "seriea", "serieb",
    "bundesliga", "bundesliga2", "ligue1", "ligue2", "primeira", "eredivisie",
    "brasileirao", "ligamx", "mls-este", "mls-oeste",
    "argentina-a", "argentina-b",
    "champions", "europa", "conference",
    "nations-league", "concacaf-nations", "copa-africa-clasificacion", "amistosos",
}

_cache: set[str] | None = None


def valid_league_slugs() -> set[str]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        from seo.config import GROUP_PAGES, LEAGUES
        slugs = {c["slug"] for c in list(LEAGUES) + list(GROUP_PAGES) if c.get("slug")}
        _cache = slugs or set(_FALLBACK_SLUGS)
    except Exception as e:  # noqa: BLE001
        log.warning("no se pudo importar seo.config; uso el catálogo fijo: %s", e)
        _cache = set(_FALLBACK_SLUGS)
    return _cache
