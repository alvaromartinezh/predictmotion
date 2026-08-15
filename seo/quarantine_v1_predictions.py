"""Migración ONE-SHOT: aparta las filas de predicción calculadas con el modelo v1
mientras el cron ya simulaba v2.

`seo/predictions.py` llevaba una copia literal de la fórmula v1 que 898680a sacó
de `sim_table.simulate`. Desde que 3a9ac0f activó v2 (2026-08-10T05:24:52+02:00)
hasta que ed26f5a lo arregló (2026-08-15), cada fila emitida registró un 1X2 que
NINGÚN modelo del sitio calculó: para Barcelona–Málaga, (0.5742, 0.26, 0.1658) en
el fichero contra (0.8477, 0.1428, 0.0095) simulado. ~27 puntos en el favorito.

El fichero es append-only e inmutable POR DISEÑO y su único fin es calibrar el
modelo de producción (Fase 4, Brier/reliability), así que dejarlas dentro
significa calibrar contra ruido. No se borran —son rastro de auditoría— sino que
se mueven a `predictions.v1-mismatch.jsonl`, junto al fichero vivo.

Idempotente: una fila con `model` ya es posterior al arreglo y nunca se mueve, así
que volver a ejecutarlo no hace nada. `--dry-run` para revisar antes.

    python3 -m seo.quarantine_v1_predictions --dry-run
    python3 -m seo.quarantine_v1_predictions
"""

import argparse
import json
import sys

from .config import DATA_DIR
from .snapshots import _write_atomic

# Instante en que 3a9ac0f puso USE_ABSOLUTE_RATING=True. El cron del servidor hace
# git pull cada 2 min, así que cualquier fila emitida después ya se simuló con v2.
V2_DESDE = "2026-08-10T03:24:52Z"       # 05:24:52 +02:00

NOMBRE = "predictions.v1-mismatch.jsonl"


def _contaminada(fila):
    """La fila se emitió con v1 mientras la simulación corría v2.

    `model` solo lo escriben las filas posteriores al arreglo (7b3a7d7): si está,
    la fila se describe a sí misma y es de fiar. Si no está y es posterior a v2,
    salió de la fórmula vieja. Las anteriores a v2 son coherentes (cron y registro
    corrían v1 los dos) y se quedan."""
    if fila.get("model"):
        return False
    return (fila.get("issued_at") or "") >= V2_DESDE


def run(dry_run=False):
    movidas = total = 0
    for path in sorted(DATA_DIR.glob("*/*/predictions.jsonl")):
        filas = []
        for linea in path.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea:
                try:
                    filas.append((linea, json.loads(linea)))
                except ValueError:
                    filas.append((linea, {}))       # ilegible: se conserva tal cual
        malas = [(l, o) for l, o in filas if _contaminada(o)]
        if not malas:
            continue
        buenas = [l for l, o in filas if not _contaminada(o)]
        total += len(filas)
        movidas += len(malas)
        rel = path.relative_to(DATA_DIR)
        print(f"  {rel}: {len(malas)}/{len(filas)} filas a cuarentena")
        if dry_run:
            continue
        # La cuarentena se ACUMULA (nunca se pisa) y el fichero vivo se reescribe
        # atómicamente, igual que el resto de escrituras del pipeline.
        destino = path.with_name(NOMBRE)
        previo = destino.read_text(encoding="utf-8") if destino.exists() else ""
        if previo and not previo.endswith("\n"):
            previo += "\n"
        _write_atomic(destino, previo + "\n".join(l for l, _ in malas) + "\n")
        _write_atomic(path, ("\n".join(buenas) + "\n") if buenas else "")

    if not movidas:
        print("Nada que apartar: no hay filas v1 posteriores a la activación de v2.")
    else:
        print(f"\n{movidas} filas apartadas a {NOMBRE} "
              f"({total - movidas} válidas se quedan).")
        if dry_run:
            print("(--dry-run: no se ha escrito nada)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="No escribe, solo lista")
    return run(dry_run=ap.parse_args(argv).dry_run)


if __name__ == "__main__":
    sys.exit(main())
