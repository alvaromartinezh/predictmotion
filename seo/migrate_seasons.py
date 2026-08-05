"""Migración one-shot: particionar snapshots por temporada.

De la estructura vieja (mezclaba temporadas):
    data/<slug>/snapshots/<date>.json
a la nueva:
    data/<slug>/<season>/snapshots/<date>.json   (+ <season>/latest.json)

Lee el campo `season` de CADA snapshot (no la fecha del nombre) para decidir la
carpeta, así los 2025-26 y los 2026-27 se separan SIN perderse. Mantiene el
data/<slug>/latest.json de la raíz (contrato de los dashboards). Idempotente: si
no queda la carpeta vieja, no hace nada.

Uso (en el servidor, una vez):  python3 -m seo.migrate_seasons
                                  python3 -m seo.migrate_seasons --dry-run
"""

import argparse
import json
import shutil
import sys

from .config import DATA_DIR


def _season_of(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("season")
    except Exception:
        return None


def migrate(dry_run=False):
    if not DATA_DIR.exists():
        print("(no hay data/)")
        return 0
    total_moved = 0
    for slug_dir in sorted(p for p in DATA_DIR.iterdir() if p.is_dir()):
        old = slug_dir / "snapshots"
        if not old.is_dir():
            continue  # ya migrado o sin snapshots
        files = sorted(old.glob("*.json"))
        if not files:
            continue
        by_season = {}
        skipped = 0
        for f in files:
            season = _season_of(f)
            if not season:
                skipped += 1
                continue
            by_season.setdefault(season, []).append(f)
        print(f"→ {slug_dir.name}: {len(files)} snapshots"
              + (f" ({skipped} sin season, se dejan)" if skipped else ""))
        for season, fs in sorted(by_season.items()):
            dest = slug_dir / season / "snapshots"
            latest_src = max(fs, key=lambda p: p.name)   # fecha más alta de la temporada
            print(f"   {season}: {len(fs)} → {dest.relative_to(DATA_DIR)}"
                  f"  (latest {latest_src.name})")
            if dry_run:
                continue
            dest.mkdir(parents=True, exist_ok=True)
            for f in fs:
                shutil.move(str(f), str(dest / f.name))
            shutil.copy(str(dest / latest_src.name), str(slug_dir / season / "latest.json"))
            total_moved += len(fs)
        # limpiar la carpeta vieja solo si quedó vacía (no había 'sin season')
        if not dry_run and not any(old.iterdir()):
            old.rmdir()
    print(f"\n{'[dry-run] ' if dry_run else ''}Movidos {total_moved} snapshots."
          " El latest.json de la raíz de cada liga NO se toca.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(migrate(ap.parse_args().dry_run))
