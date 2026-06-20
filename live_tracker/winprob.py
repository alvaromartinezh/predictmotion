"""Probabilidad estimada victoria/empate/derrota EN VIVO.

Desacoplado tras la interfaz `WinProbabilityModel`: el resto del código pide
`estimate(state)` y recibe un `WinProbability` normalizado. Para sustituir la
fórmula por un Monte Carlo o un modelo xG más adelante, basta con otra
implementación de la interfaz — sin tocar UI ni provider.

⚠️  Los pesos/factores viven en config.py y son HEURÍSTICOS SIN VALIDAR.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from . import config
from .models import WinProbability


@dataclass
class MatchState:
    """Entrada normalizada al modelo (no depende de ESPN)."""
    league: str
    state: str                 # 'pre' | 'in' | 'post'
    minute_num: int
    home_score: int
    away_score: int
    men_home: int              # 11 - rojas local
    men_away: int
    stats: dict                # {statKey: (home_val, away_val)} numéricos
    home_abbr: str = ""        # para el ajuste por ranking FIFA (sedes neutrales)
    away_abbr: str = ""


class WinProbabilityModel(ABC):
    @abstractmethod
    def estimate(self, state: MatchState) -> WinProbability: ...


# Ranking FIFA (mismo que el Monte Carlo de grupos). No listados → 80.
FIFA_RANK = {
    "FRA": 1, "ESP": 2, "ARG": 3, "ENG": 4, "POR": 5, "BRA": 6, "NED": 7,
    "MAR": 8, "BEL": 9, "GER": 10, "CRO": 11, "ITA": 12, "COL": 13, "SEN": 14,
    "MEX": 15, "USA": 16, "URU": 17, "JPN": 18, "SUI": 19, "DEN": 20, "IRN": 21,
    "TUR": 22, "ECU": 23, "AUT": 24, "KOR": 25, "NGA": 26, "AUS": 27, "ALG": 28,
    "EGY": 29, "CAN": 30, "NOR": 31, "UKR": 32, "PAN": 33, "CIV": 34, "POL": 35,
    "WAL": 37, "SWE": 38, "SRB": 39, "PAR": 40, "CZE": 41, "HUN": 42, "SCO": 43,
    "TUN": 44, "CMR": 45, "DRC": 46, "GRE": 47, "SVK": 48, "VEN": 49, "UZB": 50,
    "CRC": 51, "MLI": 52, "PER": 53, "CHI": 54, "QAT": 55, "ROM": 56, "IRQ": 57,
    "SVN": 58, "RSA": 60, "SAU": 61, "JOR": 63, "ALB": 64, "HON": 66, "JAM": 71,
    "GHA": 74, "BOL": 85, "NZL": 98, "SLV": 93,
}


def _elo(abbr):
    return 2000 - (FIFA_RANK.get(abbr, 80) - 1) * 3.5


# ── Utilidades de Poisson (agregación cerrada, determinista) ──────────────────

def _poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _result_probs(lh, la, max_goals=8):
    """P(local gana / empate / visitante gana) si los goles restantes de cada
    equipo son Poisson(lh) y Poisson(la) independientes. Cerrado, sin RNG."""
    ph = pd = pa = 0.0
    hp = [_poisson_pmf(i, lh) for i in range(max_goals + 1)]
    ap = [_poisson_pmf(j, la) for j in range(max_goals + 1)]
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = hp[i] * ap[j]
            if i > j:
                ph += p
            elif i == j:
                pd += p
            else:
                pa += p
    tot = ph + pd + pa or 1.0
    return ph / tot, pd / tot, pa / tot


# Cache de calibración por liga: (p_home,p_draw) -> (lambda_home, lambda_away)
_CALIB_CACHE: dict = {}


def _calibrate_lambdas(p_home, p_draw):
    """Encuentra (λ_local, λ_visitante) a 90' tales que un 0-0 completo reproduzca
    aproximadamente las probabilidades pre-partido de la liga. Búsqueda en rejilla
    (se ejecuta una vez por liga; barato). Da coherencia con el motor del sitio."""
    key = (round(p_home, 3), round(p_draw, 3))
    if key in _CALIB_CACHE:
        return _CALIB_CACHE[key]
    p_away = max(0.0, 1.0 - p_home - p_draw)
    best, best_err = (1.4, 1.1), 1e9
    lh = 0.4
    while lh <= 2.6:
        la = 0.3
        while la <= 2.2:
            ph, pd, pa = _result_probs(lh, la)
            err = (ph - p_home) ** 2 + (pa - p_away) ** 2 + (pd - p_draw) ** 2
            if err < best_err:
                best_err, best = err, (lh, la)
            la += 0.05
        lh += 0.05
    _CALIB_CACHE[key] = best
    return best


class InPlayStatsModel(WinProbabilityModel):
    """Marcador + tiempo restante + stats en vivo → probabilidad estimada.

    Las stats modulan la tasa de gol esperada en el tiempo restante; el marcador y
    el tiempo restante dominan. Ver el desglose de la fórmula en CLAUDE.md.
    """

    def estimate(self, state: MatchState) -> WinProbability:
        note = config.WINPROB_UI_NOTE
        src = config.WINPROB_SOURCE

        # Partido terminado → resultado real con certeza.
        if state.state == "post":
            if state.home_score > state.away_score:
                return WinProbability(100.0, 0.0, 0.0, src, note)
            if state.home_score < state.away_score:
                return WinProbability(0.0, 0.0, 100.0, src, note)
            return WinProbability(0.0, 100.0, 0.0, src, note)

        p_home, p_draw = config.LEAGUE_BASE_PROBS.get(state.league, config.DEFAULT_BASE_PROBS)
        neutral = state.league in config.NEUTRAL_VENUE_LEAGUES
        if neutral:
            # Sin localía: victorias simétricas (mismo lambda base para ambos).
            p_home = (1 - p_draw) / 2
        lam0_h, lam0_a = _calibrate_lambdas(p_home, p_draw)

        # Ajuste por ranking FIFA (solo sedes neutrales): sesga la tasa de gol
        # hacia la mejor selección. Sustituye a la ventaja de campo.
        rank_h = rank_a = 1.0
        if neutral and state.home_abbr and state.away_abbr:
            p_elo = 1 / (1 + math.pow(10, -(_elo(state.home_abbr) - _elo(state.away_abbr)) / 400))
            adj = p_elo - 0.5
            rank_h = math.exp(config.WINPROB_RANK_WEIGHT * adj)
            rank_a = math.exp(-config.WINPROB_RANK_WEIGHT * adj)

        # Fracción de partido restante (0..1). En 'pre' o min 0 → 1 (cae a base).
        full = config.WINPROB_FULL_TIME
        f = max(0.0, (full - state.minute_num)) / full
        f = min(1.0, f)

        # Multiplicador por stats: log-suma ponderada de (cuota_local - 0.5).
        s = 0.0
        for key, w in config.WINPROB_STAT_WEIGHTS.items():
            pair = state.stats.get(key)
            if not pair:
                continue  # stat ausente → se descarta (defensivo)
            hv, av = pair
            tot = hv + av
            if tot <= 0:
                continue
            q = hv / tot                 # cuota del local
            # foulsCommitted/yellow penalizan al que las comete: invertimos su signo
            if key in ("foulsCommitted", "yellowCards"):
                s += w * (0.5 - q)
            else:
                s += w * (q - 0.5)
        mult_h = min(config.WINPROB_MULT_MAX, max(config.WINPROB_MULT_MIN, math.exp(s)))
        mult_a = min(config.WINPROB_MULT_MAX, max(config.WINPROB_MULT_MIN, math.exp(-s)))

        # Ventaja de hombres (rojas).
        adv_h = adv_a = 1.0
        diff = state.men_home - state.men_away
        if diff > 0:
            adv_h = config.WINPROB_MAN_ADV_UP ** diff
            adv_a = config.WINPROB_MAN_ADV_DOWN ** diff
        elif diff < 0:
            adv_a = config.WINPROB_MAN_ADV_UP ** (-diff)
            adv_h = config.WINPROB_MAN_ADV_DOWN ** (-diff)

        lam_h = lam0_h * f * mult_h * adv_h * rank_h
        lam_a = lam0_a * f * mult_a * adv_a * rank_a

        # Probabilidad de los goles restantes y suma al marcador actual.
        ph = pd = pa = 0.0
        max_g = 8
        hp = [_poisson_pmf(i, lam_h) for i in range(max_g + 1)]
        ap = [_poisson_pmf(j, lam_a) for j in range(max_g + 1)]
        for i in range(max_g + 1):
            for j in range(max_g + 1):
                p = hp[i] * ap[j]
                fh = state.home_score + i
                fa = state.away_score + j
                if fh > fa:
                    ph += p
                elif fh == fa:
                    pd += p
                else:
                    pa += p
        tot = ph + pd + pa or 1.0
        return WinProbability(
            round(ph / tot * 100, 1), round(pd / tot * 100, 1), round(pa / tot * 100, 1),
            src, note,
        )


# Instancia por defecto que usa el backend. Cambiar aquí para sustituir el modelo.
DEFAULT_MODEL: WinProbabilityModel = InPlayStatsModel()
