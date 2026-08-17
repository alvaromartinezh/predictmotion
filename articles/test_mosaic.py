"""Prueba del maquetador de mosaico (articles/mosaic.py).

Lo que de verdad puede romperse aquí: (1) una maqueta del banco que no sume 3
de ancho por fila — descuadraría la rejilla entera —, (2) el troceo del texto,
que tiene que devolver EXACTAMENTE las celdas que pide la maqueta y sin perder
ni reordenar una palabra, y (3) el determinismo entre procesos, igual que en
test_illustration: si la maqueta se eligiera con `hash()`, el cron de 3 h
recolocaría el artículo entero en cada pasada.

    python3 -m articles.test_mosaic
"""

import os
import re
import subprocess
import sys

from . import mosaic

_FIG = lambda markup, label: f'<figure class="illo-aside">{label}</figure>'  # noqa: E731

_TEXT = "\n\n".join(
    f"Párrafo {i} de prueba. " + "Una frase razonablemente larga para llenar la celda. " * 8
    for i in range(1, 5)
)


def test_layouts_bien_formadas():
    for rows in mosaic.LAYOUTS:
        for row in rows:
            assert sum(len(t) for t in row.split()) == 3, row
            assert all(set(t) <= {"T"} or set(t) <= {"P"} for t in row.split()), row
        t, p = mosaic.counts(rows)
        assert 3 <= p <= 4, (rows, p)              # el encargo: 3-4 fotos
        assert len(mosaic.weights(rows)) == t, rows


def test_chunks_exactos_y_sin_perder_texto():
    palabras = _TEXT.split()
    for n in range(1, 12):
        cells = mosaic.chunks(_TEXT, [1.0] * n)
        assert len(cells) == n, (n, len(cells))
        assert all(c.strip() for c in cells), (n, cells)
        assert " ".join(" ".join(cells).split()) == " ".join(palabras)
    # Un párrafo de una sola frase también se parte (por palabra).
    assert len(mosaic.chunks("palabra " * 200, [1.0] * 4)) == 4


def test_chunks_reparten_en_proporcion_al_peso():
    """Una celda al lado de una foto ancha tiene que recibir más texto que una
    estrecha — es lo que empareja las alturas de una fila."""
    a, b = mosaic.chunks(_TEXT, [1.0, 3.0])
    assert len(b) > 2 * len(a), (len(a), len(b))


def test_celdas_cuadran_con_la_maqueta():
    for chars in (900, 1400, 1800, 2100, 2600, 3200):
        text = ("Frase de relleno para el cuerpo del artículo. " * 400)[:chars]
        html = mosaic.build(text, "slug-x", "recap_jornada", "2026-08-17", _FIG)
        assert html, chars
        assert html.count('class="mos-t') + html.count('class="mos-p') >= 6, chars
        assert html.count("mos-lead") == 1, chars
        n_pics = html.count('class="mos-p')
        assert 3 <= n_pics <= 4, (chars, n_pics)
        # Una foto por lámina y todas distintas (illustration.picks es coprimo).
        labels = re.findall(r'<figure class="illo-aside">([^<]*)</figure>', html)
        assert len(labels) == n_pics and len(set(labels)) == n_pics, labels
        # Las columnas de arranque de cada fila cubren la rejilla sin solapar.
        cols = [int(c) for c in re.findall(r'data-col="(\d)"', html)]
        assert cols[0] == 1 and max(cols) <= 3, cols


def test_texto_corto_no_maqueta():
    assert mosaic.build("Muy corto.", "s", "recap_jornada", "2026-08-17", _FIG) is None


_CHILD = (
    "from articles import mosaic\n"
    "F = lambda m, l: l\n"
    "T = 'Frase de relleno para el cuerpo del artículo. ' * 50\n"
    "for slug in ('a', 'b', 'c', 'laliga-jornada-1-recap'):\n"
    "    print(slug, mosaic.build(T, slug, 'recap_jornada', '2026-08-17', F))\n"
)


def test_determinismo_entre_procesos():
    """Misma salida con PYTHONHASHSEED distinto — el mismo guard que
    test_illustration, porque `build` elige maqueta Y grabados por hash."""
    out = []
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run([sys.executable, "-c", _CHILD], env=env,
                           capture_output=True, text=True,
                           cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        assert r.returncode == 0, r.stderr
        out.append(r.stdout)
    assert len(set(out)) == 1, "la maqueta cambia entre procesos (¿hash() en vez de md5?)"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print(f"articles.test_mosaic: OK ({len(mosaic.LAYOUTS)} maquetas, capacidad "
          f"{int(min(map(mosaic.capacity, mosaic.LAYOUTS)))}–"
          f"{int(max(map(mosaic.capacity, mosaic.LAYOUTS)))} car.)")
