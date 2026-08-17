"""Autocomprobación del banco de ilustraciones (sin framework).

Uso: python3 -m articles.test_illustration

La prueba que MANDA aquí es la de determinismo ENTRE PROCESOS. El cron
regenera los artículos cada 3 h y `render_article` se llama desde dos sitios
distintos (artículo recién generado + re-render del índice de preview): si la
selección dejara de ser estable, cada artículo cambiaría de dibujo solo, en
producción, sin que fallara nada. Es exactamente el modo de fallo silencioso
que ya mordió en este proyecto (403 de ESPN, v1/v2 del motor), así que va
cubierto por una prueba que revienta, no por un vistazo.
"""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date

from . import illustration as I
from .config import ROOT

# Corpus sintético parecido a los slugs reales de generate.py/writer.py.
_TIPOS = list(I.TYPE_SALT)
_CORPUS = [(f"{tipo}-{liga}-j{n}", tipo, f"2026-{8 + n % 5:02d}-{1 + n % 28:02d}")
           for tipo in _TIPOS
           for liga in ("laliga", "hypermotion")
           for n in range(24)]

# Lo que el subproceso imprime: una línea por artículo, en orden.
_CHILD = (
    "import sys; sys.path.insert(0, %r)\n"
    "from articles import illustration as I\n"
    "from articles.test_illustration import _CORPUS\n"
    "print('\\n'.join('%%s %%s/%%s' %% (s, *I.pick(s, t, f)) for s, t, f in _CORPUS))\n"
)


def _picks_in_subprocess(hashseed):
    env = dict(os.environ, PYTHONHASHSEED=hashseed)
    out = subprocess.run([sys.executable, "-c", _CHILD % str(ROOT)],
                         cwd=str(ROOT), env=env, capture_output=True, text=True)
    assert out.returncode == 0, f"subproceso PYTHONHASHSEED={hashseed} falló:\n{out.stderr}"
    return out.stdout


def demo():
    # ── 1. El banco está entero y sin duplicados ────────────────────────────
    assert len(I.SUBJECTS) == 18, f"esperados 18 sujetos, hay {len(I.SUBJECTS)}"
    assert len(I.BACKDROPS) == 4, f"esperados 4 fondos, hay {len(I.BACKDROPS)}"
    assert len(set(I.SUBJECTS.values())) == 18, "hay sujetos con el mismo dibujo (¿error al portar?)"
    assert len(set(I.BACKDROPS.values())) == 4, "hay fondos con el mismo dibujo"
    for name, d in (("sujeto", I.SUBJECTS), ("fondo", I.BACKDROPS)):
        for k, v in d.items():
            assert v.count("<g") == v.count("</g>"), f"{name} {k}: <g> descuadrado"
            assert "#" not in v, f"{name} {k}: color fijo incrustado (debe ir por currentColor)"

    # ── 1b. El contrato geométrico, en lo que se puede comprobar a máquina ──
    # El horizonte en y=155 es la parte del contrato con más radio de acción:
    # un fondo nuevo con otra altura no rompe ese fondo, rompe los 18 sujetos a
    # la vez (todos se apoyan asumiendo que la grada acaba ahí).
    for b, v in I.BACKDROPS.items():
        assert "155h376" in v, (
            f"el fondo {b!r} no traza el horizonte en y=155. Es el eje del "
            "contrato: sin él los 18 sujetos quedan flotando o pisando grada.")
    # La base y=278 NO se comprueba: se apoya de formas distintas y no todas
    # dejan un 278 literal — 'balon' toca el suelo por geometría (círculo
    # cy=218 r=60) y 'reloj' por un plinto. Un `assert "278" in v` da falso
    # positivo en 'balon'; comprobarlo de verdad exigiría parsear los paths
    # (relativos, arcos y curvas incluidos).
    # ponytail: el encuadre se revisa a ojo en la hoja de contactos. Subir a un
    # parser de paths solo si alguna vez se cuela un sujeto desencuadrado.

    # ── 2. Las 72 composiciones son XML válido ──────────────────────────────
    for s in I.SUBJECT_NAMES:
        for b in I.BACKDROP_NAMES:
            markup = (f'<svg viewBox="{I.VIEWBOX}" fill="none" stroke="currentColor">'
                      f"{I.BACKDROPS[b]}{I.SUBJECTS[s]}</svg>")
            ET.fromstring(markup)  # revienta si la concatenación deja markup roto

    # ── 3. Determinismo dentro del proceso ──────────────────────────────────
    for slug, tipo, fecha in _CORPUS[:20]:
        assert I.pick(slug, tipo, fecha) == I.pick(slug, tipo, fecha)
    # y da igual pasar la fecha como str o como date
    assert I.pick("x", "recap_jornada", "2026-08-17") == \
           I.pick("x", "recap_jornada", date(2026, 8, 17))

    # ── 4. Determinismo ENTRE PROCESOS (la que de verdad importa) ───────────
    # PYTHONHASHSEED distinto en cada hijo: si la selección usara hash() en vez
    # de hashlib.md5, estas salidas divergirían. Con "random" además cambia en
    # cada ejecución, así que una regresión no puede colarse por casualidad.
    base = _picks_in_subprocess("0")
    assert base.strip(), "el subproceso no imprimió nada"
    for seed in ("1", "12345", "random", "random"):
        other = _picks_in_subprocess(seed)
        assert other == base, (
            f"la selección NO es estable entre procesos (PYTHONHASHSEED={seed}).\n"
            "Casi seguro que algo usa hash() en vez de hashlib.md5: hash() de un\n"
            "str va con sal aleatoria por proceso, así que el cron de 3h le\n"
            "cambiaría el dibujo a cada artículo en cada pasada."
        )
    # y coincide con lo que calcula ESTE proceso
    aqui = "\n".join(f"{s} {a}/{b}" for s, t, f in _CORPUS for a, b in [I.pick(s, t, f)]) + "\n"
    assert aqui == base, "el proceso padre y el hijo no coinciden"

    # ── 5. La exclusión semántica se respeta, y no matando al sujeto ────────
    todos = [I.pick(s, t, f) for s, t, f in _CORPUS]
    for par in todos:
        assert par not in I.BLOCKED, f"combinación excluida servida igualmente: {par}"
    fondos_asp = {b for s, b in todos if s == "aspersores"}
    assert fondos_asp, "aspersores no sale nunca (¿la exclusión se lo ha comido?)"
    assert "lluvia" not in fondos_asp
    assert len(fondos_asp) >= 2, f"aspersores solo cae en {fondos_asp}: la rotación no gira"

    # ── 6. Cobertura: no hay sujetos ni fondos muertos ──────────────────────
    vistos_s = {s for s, _ in todos}
    vistos_b = {b for _, b in todos}
    assert vistos_s == set(I.SUBJECT_NAMES), f"sujetos que no salen nunca: {set(I.SUBJECT_NAMES) - vistos_s}"
    assert vistos_b == set(I.BACKDROP_NAMES), f"fondos que no salen nunca: {set(I.BACKDROP_NAMES) - vistos_b}"

    # ── 7. Las familias siguen siendo dato válido y equilibrado ─────────────
    miembros = [m for grupo in I.FAMILIES.values() for m in grupo]
    assert len(miembros) == len(set(miembros)), "un sujeto está en dos familias"
    for grupo in I.FAMILIES.values():
        assert len(grupo) <= 2, ("una familia de 3+ sí desequilibraría el banco: "
                                 "redibujar uno o partir la familia")
        for m in grupo:
            assert m in I.SUBJECTS, f"familia con sujeto inexistente: {m}"

    # ── 8. El markup que se incrusta es el esperado ─────────────────────────
    markup, label = I.plate("recap-jornada-3-laliga", "recap_jornada", "2026-08-17T09:00:00")
    assert markup.startswith("<svg class=\"illo\"")
    assert 'stroke="currentColor"' in markup and "#" not in markup
    assert f'viewBox="{I.VIEWBOX}"' in markup
    assert f'aria-label="{label}"' in markup, "el aria-label debe describir el DIBUJO"
    ET.fromstring(markup)

    # ── 9. Cada sujeto tiene nombre legible (pie de lámina + aria-label) ────
    faltan = set(I.SUBJECT_NAMES) - set(I.LABELS)
    assert not faltan, f"sujetos sin nombre en LABELS: {faltan}"
    sobran = set(I.LABELS) - set(I.SUBJECT_NAMES)
    assert not sobran, f"LABELS con sujetos inexistentes: {sobran}"
    assert len(set(I.LABELS.values())) == len(I.LABELS), "dos sujetos con el mismo nombre"

    print(f"articles.test_illustration: OK "
          f"({len(I.SUBJECTS)}×{len(I.BACKDROPS)}−{len(I.BLOCKED)} = "
          f"{len(I.SUBJECTS) * len(I.BACKDROPS) - len(I.BLOCKED)} composiciones)")


if __name__ == "__main__":
    demo()
