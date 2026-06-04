"""PRNG determinista — port fiel del mulberry32 del navegador.

Replicar las operaciones de 32 bits de JavaScript (Math.imul, >>> , | 0) en
Python para que el seed derivado de la tabla produzca la misma secuencia y los
porcentajes sean reproducibles.
"""

_U32 = 0xFFFFFFFF


def _imul(a, b):
    """Equivalente a Math.imul: multiplicación entera de 32 bits con signo."""
    a &= _U32
    b &= _U32
    r = (a * b) & _U32
    return r - 0x100000000 if r & 0x80000000 else r


def make_rng(seed):
    """rng() -> [0,1). Implementación lineal fiel a mulberry32 del navegador."""
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


def standings_seed(rows):
    """Hash determinista de la tabla — port de standingsSeed() del JS.

    rows: lista de dicts con name, pts, gp.
    """
    s = "|".join(f"{r['name']}:{r['pts']}:{r['gp']}" for r in rows)
    h = 0
    for ch in s:
        h = (_imul(31, h) + ord(ch)) & _U32
        if h & 0x80000000:
            h -= 0x100000000
    return h & _U32


def groups_seed(groups):
    """Port de groupsSeed() del JS para el Mundial."""
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
