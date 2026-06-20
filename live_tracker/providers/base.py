"""Interfaz de proveedor de datos de partido.

Toda implementación devuelve SIEMPRE modelos normalizados (models.py), nunca el
JSON crudo de la fuente. Así, migrar de ESPN a otra API solo implica escribir otra
subclase, sin tocar caché, servidor, modelo de probabilidad ni frontend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Match, MatchDetail


class MatchDataProvider(ABC):
    @abstractmethod
    def list_matches(self, league: str) -> list[Match]:
        """Partidos (ligeros) de la liga: del scoreboard."""

    @abstractmethod
    def get_match(self, league: str, event_id: str) -> MatchDetail:
        """Detalle normalizado de un partido: del summary."""
