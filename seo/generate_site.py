"""Orquestador del generador de páginas SEO de PredictMotion.

Flujo (se ejecuta en el servidor vía cron, sin pasos manuales):
  1. Por cada liga: descarga datos de ESPN → Monte Carlo → snapshot persistido.
  2. Renderiza páginas estáticas (equipo/jornada/grupo/histórico/hubs).
  3. Regenera sitemap-data.xml.

Robusto por liga: si una falla, se salta y NO borra lo ya generado.

Uso:
    python -m seo.generate_site                 # genera todo
    python -m seo.generate_site --dry-run       # simula sin escribir
    python -m seo.generate_site --league laliga # solo una liga
"""

import argparse
import sys
from datetime import datetime, timezone

# Consola UTF-8 también en Windows (en el servidor Linux ya lo es).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from . import espn, render_table, sitemap, predictions, zone_predictions
from .config import LEAGUES, ROOT, SIM_N_TABLE, league_by_slug
from .snapshots import build_table_snapshot, save_snapshot, load_all
from . import sim_table


def _write_files(files, dry_run):
    for relpath, html in files.items():
        path = ROOT / relpath
        if dry_run:
            print(f"    [dry] {relpath} ({len(html)} bytes)")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")


def _process_table(league, today, dry_run, ratings=None):
    rows = espn.fetch_table(league["espn_code"])
    meta = espn.fetch_league_meta(league["espn_code"])
    sim = sim_table.simulate(rows, league["p_home"], league["p_draw"],
                             playoff_top=league.get("playoff_top"), ratings=ratings)
    snap = build_table_snapshot(league, rows, sim, SIM_N_TABLE, today,
                                league_logo=meta["logo"], season=meta["season"],
                                ratings=ratings)
    if not dry_run:
        save_snapshot(snap)
    # Solo la temporada VIVA (partición por temporada): no mezclar histórico de
    # 2025-26 con 2026-27.
    snaps = load_all(league["slug"], snap["season"]) or [snap]
    if dry_run and snaps[-1]["date"] != today:
        snaps = snaps + [snap]

    # Calendario restante (best-effort, no se persiste en el snapshot).
    extras = {}
    for t in snap["teams"]:
        sched = espn.fetch_remaining_schedule(league["espn_code"], t["id"])
        if sched:
            extras[t["id"]] = sched

    # Registro append-only de predicciones 1X2 (para Brier / calibración).
    if not dry_run:
        predictions.record_matchday(league, snap)
        # Registro de probabilidades de zona por jornada completa (calibración de
        # zona, complementaria al Brier por partido). Upsert por jornada.
        zone_predictions.record_jornada(league, snap)

    files, urls = render_table.render(league, snaps, extras=extras)
    _write_files(files, dry_run)
    return snap, urls


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="No escribe ficheros")
    ap.add_argument("--league", help="Procesar solo esta liga (slug)")
    args = ap.parse_args(argv)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    leagues = [league_by_slug(args.league)] if args.league else LEAGUES
    if args.league and not leagues[0]:
        print(f"Liga desconocida: {args.league}", file=sys.stderr)
        return 1

    # Prior de fuerza: se construye UNA vez (la temporada previa de ambas
    # divisiones) y se comparte entre ligas. Best-effort: si falla, ratings={} y
    # el Monte Carlo corre en modo uniforme de siempre.
    current_year = espn.fetch_current_season_year(LEAGUES[0]["espn_code"])
    ratings = espn.build_strength_ratings(current_year)
    print(f"Prior de fuerza: {len(ratings)} equipos con rating"
          f" (temporada previa {current_year - 1 if current_year else '??'})")

    all_urls = []
    ok = 0

    for league in leagues:
        print(f"\n→ {league['name']} ({league['espn_code']})")
        try:
            snap, urls = _process_table(league, today, args.dry_run, ratings=ratings)
        except Exception as e:
            print(f"  [SKIP] {league['slug']}: {e}", file=sys.stderr)
            continue
        all_urls.extend(urls)
        ok += 1
        print(f"  ✓ {len(urls)} páginas")

    # El hub /datos y /datos/<slug> se retiró (ver CLAUDE.md): 301 → home en Caddy.
    # Las páginas de contenido (/equipos, /jornadas, /historico) se siguen generando.

    # El sitemap-data.xml es global: solo se reescribe en ejecución completa
    # (con --league sería parcial y borraría las URLs de las demás ligas).
    if all_urls and not args.dry_run and not args.league:
        sitemap.write_data_sitemap(ROOT, all_urls)
        print(f"\n✓ sitemap-data.xml: {len(set(u for u, _ in all_urls))} URLs")
    elif args.league:
        print("\n(sitemap-data.xml no reescrito: ejecución parcial con --league)")

    print(f"\nFin — {ok}/{len(leagues)} ligas generadas.")
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
