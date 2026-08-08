"""Catálogo de competiciones válidas (para validar follows).

Fuente única: el registro de ligas de seo/config.py (los 15 slugs). Importar
seo.config es barato y seguro (solo depende de pathlib; sin efectos de red al
importar). Si por lo que sea no se pudiera importar, caemos a una lista fija
equivalente para no dejar de validar (y no rechazar todo).

Se cachea en memoria: el catálogo solo cambia al añadir una liga (redeploy).
"""

from __future__ import annotations

import logging

log = logging.getLogger("accounts.catalog")

# Fallback fijo = los 15 slugs actuales (debe casar con seo/config.py → LEAGUES).
_FALLBACK_SLUGS = {
    "laliga", "hypermotion", "premier", "championship", "seriea", "serieb",
    "bundesliga", "bundesliga2", "ligue1", "ligue2", "primeira", "eredivisie",
    "champions", "europa", "conference",
}

_cache: set[str] | None = None


def valid_league_slugs() -> set[str]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        from seo.config import LEAGUES
        slugs = {l["slug"] for l in LEAGUES if l.get("slug")}
        _cache = slugs or set(_FALLBACK_SLUGS)
    except Exception as e:  # noqa: BLE001
        log.warning("no se pudo importar seo.config; uso el catálogo fijo: %s", e)
        _cache = set(_FALLBACK_SLUGS)
    return _cache
