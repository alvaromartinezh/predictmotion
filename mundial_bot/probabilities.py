"""Monte Carlo de la fase de grupos del Mundial — autocontenido para el bot.

Port fiel de simulateGroups() de mundial.html / seo/sim_cup.py: ajusta las
probabilidades de cada partido por ranking FIFA (Elo derivado) y devuelve, por
selección, la prob de ser 1ª/2ª/3ª de grupo, de quedar eliminada y de pasar a la
fase eliminatoria (pAdv). El bot es un servicio independiente, así que aquí va el
PRNG mulberry32 y el seed inline (no se importa el paquete `seo`).
"""

from __future__ import annotations
import math

SIM_N = 5000          # iteraciones (igual que seo/SIM_N_CUP)
P_HOME = 0.37
P_DRAW = 0.27

_U32 = 0xFFFFFFFF

# Ranking FIFA (Transfermarkt, junio 2026). Equipos no listados → 80.
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


# ── PRNG mulberry32 (port fiel del navegador) ─────────────────────────────────

def _imul(a, b):
    a &= _U32
    b &= _U32
    r = (a * b) & _U32
    return r - 0x100000000 if r & 0x80000000 else r


def _make_rng(seed):
    state = seed & _U32

    def rng():
        nonlocal state
        state = (state + 0x6D2B79F5) & _U32
        t = state
        t = _imul(t ^ (t >> 15), 1 | t) & _U32
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & _U32) ^ t
        t &= _U32
        return ((t ^ (t >> 14)) & _U32) / 4294967296.0

    return rng


def _groups_seed(groups):
    s = "||".join(
        "|".join(f"{t['name']}:{t['pts']}:{t['gp']}" for t in g["entries"])
        for g in groups
    )
    h = 0
    for ch in s:
        h = (_imul(31, h) + ord(ch)) & _U32
        if h & 0x80000000:
            h -= 0x100000000
    return h & _U32


# ── Modelo de partido ─────────────────────────────────────────────────────────

def _elo(abbr):
    rank = FIFA_RANK.get(abbr, 80)
    return 2000 - (rank - 1) * 3.5


def _match_probs(a, b):
    diff = _elo(a) - _elo(b)
    p_elo = 1 / (1 + math.pow(10, -diff / 400))
    adj = p_elo - 0.5
    scale = 0.5
    pw = max(0.05, min(0.85, P_HOME + adj * scale))
    pl = max(0.05, min(0.85, (1 - P_HOME - P_DRAW) - adj * scale))
    return pw, 1 - pw - pl, pl


# ── Simulación ────────────────────────────────────────────────────────────────

def _pair_key(a, b):
    return "|".join(sorted((str(a), str(b))))


# Desempate FIFA 2026: cara a cara entre empatados antes que DG total.
def _h2h_order(cluster, stat, results):
    ids = set(cluster)
    h = {tid: [0, 0, 0] for tid in cluster}   # [pts, gd, gf] entre empatados
    for m in results:
        if m["a"] not in ids or m["b"] not in ids:
            continue
        h[m["a"]][2] += m["ag"]; h[m["a"]][1] += m["ag"] - m["bg"]
        h[m["b"]][2] += m["bg"]; h[m["b"]][1] += m["bg"] - m["ag"]
        if m["ag"] > m["bg"]:
            h[m["a"]][0] += 3
        elif m["ag"] < m["bg"]:
            h[m["b"]][0] += 3
        else:
            h[m["a"]][0] += 1; h[m["b"]][0] += 1
    return sorted(cluster, reverse=True, key=lambda tid: (
        h[tid][0], h[tid][1], h[tid][2], stat[tid][1], stat[tid][2]))


def _rank_group_ids(ids, stat, results):
    by_pts = sorted(ids, key=lambda tid: stat[tid][0], reverse=True)
    out, i = [], 0
    while i < len(by_pts):
        j = i
        while j < len(by_pts) and stat[by_pts[j]][0] == stat[by_pts[i]][0]:
            j += 1
        cluster = by_pts[i:j]
        out.extend(cluster if len(cluster) == 1 else _h2h_order(cluster, stat, results))
        i = j
    return out


def simulate_groups(groups, sim_n=SIM_N, played_pairs=None, played_results=None):
    """Devuelve dict team_id -> {p1st, p2nd, p3rd, pOut, pAdv} (porcentajes).

    `played_pairs`: set de claves '<idA>|<idB>' (ids ordenados) de partidos ya
    jugados. Si se pasa, se sabe exacto qué emparejamientos faltan; si no, se cae
    al proxy por PJ (solo fiable a inicio/fin de fase).
    `played_results`: dict pair_key -> {'a','ag','b','bg'} para el desempate cara a
    cara (2026); si falta, cae a DG total."""
    rng = _make_rng(_groups_seed(groups))
    num_groups = len(groups)
    best3_total = 0 if num_groups <= 8 else min(8, num_groups)

    counts = {}
    for g in groups:
        for t in g["entries"]:
            counts[t["id"]] = {"r1": 0, "r2": 0, "r3": 0, "out": 0, "ko16": 0}

    for _ in range(sim_n):
        all_thirds = []
        for g in groups:
            teams = g["entries"]
            n = len(teams)
            pts = {t["id"]: t["pts"] for t in teams}
            gd  = {t["id"]: t["gf"] - t["gc"] for t in teams}
            gf  = {t["id"]: t["gf"] for t in teams}
            gp  = {t["id"]: t["gp"] for t in teams}
            total_gp = 3
            results = []   # partidos del grupo (reales + simulados) para el cara a cara

            for i in range(n):
                for j in range(i + 1, n):
                    ti, tj = teams[i], teams[j]
                    if played_pairs is not None:
                        played = _pair_key(ti["id"], tj["id"]) in played_pairs
                    else:
                        played = gp[ti["id"]] + gp[tj["id"]] >= 2 * total_gp - (n - 1 - max(i, j))
                    if played:
                        if played_results:
                            real = played_results.get(_pair_key(ti["id"], tj["id"]))
                            if real:
                                results.append(real)
                        continue
                    pw, pd, _ = _match_probs(ti["abbr"], tj["abbr"])
                    r = rng()
                    if r < pw:
                        hi = int(rng() * 2) + 1 + int(rng() * 2); ai = int(rng() * 2)
                    elif r < pw + pd:
                        hi = ai = int(rng() * 2)
                    else:
                        hi = int(rng() * 2); ai = int(rng() * 2) + 1 + int(rng() * 2)
                    if hi > ai:
                        pts[ti["id"]] += 3
                    elif hi == ai:
                        pts[ti["id"]] += 1; pts[tj["id"]] += 1
                    else:
                        pts[tj["id"]] += 3
                    gd[ti["id"]] += hi - ai; gd[tj["id"]] += ai - hi
                    gf[ti["id"]] += hi; gf[tj["id"]] += ai
                    results.append({"a": str(ti["id"]), "ag": hi, "b": str(tj["id"]), "bg": ai})

            stat = {t["id"]: (pts[t["id"]], gd[t["id"]], gf[t["id"]]) for t in teams}
            by_id = {t["id"]: t for t in teams}
            srt = [by_id[tid] for tid in _rank_group_ids([t["id"] for t in teams], stat, results)]
            counts[srt[0]["id"]]["r1"] += 1
            counts[srt[1]["id"]]["r2"] += 1
            if len(srt) > 2:
                tid = srt[2]["id"]
                counts[tid]["r3"] += 1
                all_thirds.append((tid, pts[tid], gd[tid], gf[tid]))
            if len(srt) > 3:
                counts[srt[3]["id"]]["out"] += 1

        all_thirds.sort(key=lambda x: (x[1], x[2], x[3]), reverse=True)
        for tid, *_ in all_thirds[:best3_total]:
            counts[tid]["ko16"] += 1

    out = {}
    for tid, c in counts.items():
        out[tid] = {
            "p1st": round(c["r1"] / sim_n * 100, 1),
            "p2nd": round(c["r2"] / sim_n * 100, 1),
            "p3rd": round(c["r3"] / sim_n * 100, 1),
            "pOut": round(c["out"] / sim_n * 100, 1),
            "pAdv": round((c["r1"] + c["r2"] + c["ko16"]) / sim_n * 100, 1),
        }
    return out


def enrich(items, probs):
    """Escribe padv/p1st/p2nd/p3rd/pout en cada dict de `items` (in-place).

    Sirve tanto para entries de un grupo como para la lista de mejores terceros;
    ambos llevan `id`. Si un equipo no está en `probs`, deja padv=None."""
    for t in items:
        p = probs.get(t["id"])
        if p:
            t["padv"] = p["pAdv"]
            t["p1st"] = p["p1st"]
            t["p2nd"] = p["p2nd"]
            t["p3rd"] = p["p3rd"]
            t["pout"] = p["pOut"]
        else:
            t["padv"] = None
    return items
