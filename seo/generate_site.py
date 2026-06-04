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

from . import espn, render_table, render_cup, sitemap, links as L
from .config import LEAGUES, ROOT, SIM_N_TABLE, league_by_slug
from .render_hub import render_selector, render_competition
from .snapshots import (build_table_snapshot, build_cup_snapshot,
                        save_snapshot, load_all)
from . import sim_table, sim_cup


def _write_files(files, dry_run):
    for relpath, html in files.items():
        path = ROOT / relpath
        if dry_run:
            print(f"    [dry] {relpath} ({len(html)} bytes)")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")


def _process_table(league, today, dry_run):
    rows = espn.fetch_table(league["espn_code"])
    meta = espn.fetch_league_meta(league["espn_code"])
    sim = sim_table.simulate(rows, league["p_home"], league["p_draw"],
                             playoff_top=league.get("playoff_top"))
    snap = build_table_snapshot(league, rows, sim, SIM_N_TABLE, today,
                                league_logo=meta["logo"], season=meta["season"])
    if not dry_run:
        save_snapshot(snap)
    snaps = load_all(league["slug"]) or [snap]
    if dry_run and snaps[-1]["date"] != today:
        snaps = snaps + [snap]

    # Calendario restante (best-effort, no se persiste en el snapshot).
    extras = {}
    for t in snap["teams"]:
        sched = espn.fetch_remaining_schedule(league["espn_code"], t["id"])
        if sched:
            extras[t["id"]] = sched

    files, urls = render_table.render(league, snaps, extras=extras)
    _write_files(files, dry_run)
    return snap, urls


def _process_cup(league, today, dry_run):
    groups = espn.fetch_groups(league["espn_code"])
    meta = espn.fetch_league_meta(league["espn_code"])
    sim = sim_cup.simulate(groups)
    # Mundial: el año queda fijo en config (excepción acordada); solo el logo es vivo.
    snap = build_cup_snapshot(league, groups, sim, today, league_logo=meta["logo"])
    if not dry_run:
        save_snapshot(snap)
    snaps = load_all(league["slug"]) or [snap]
    if dry_run and snaps[-1]["date"] != today:
        snaps = snaps + [snap]

    files, urls = render_cup.render(league, snaps)
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

    all_urls = []
    hub_entries = []
    ok = 0

    for league in leagues:
        print(f"\n→ {league['name']} ({league['espn_code']})")
        try:
            if league["kind"] == "table":
                snap, urls = _process_table(league, today, args.dry_run)
            else:
                snap, urls = _process_cup(league, today, args.dry_run)
        except Exception as e:
            print(f"  [SKIP] {league['slug']}: {e}", file=sys.stderr)
            continue
        all_urls.extend(urls)
        hub_entries.append({"league": league, "kind": league["kind"], "snap": snap})
        ok += 1
        print(f"  ✓ {len(urls)} páginas")

    if hub_entries:
        sel_file, sel_html = render_selector(hub_entries)
        _write_files({sel_file: sel_html}, args.dry_run)
        all_urls.append(("/datos", today))
        for e in hub_entries:
            f, h = render_competition(e, hub_entries)
            _write_files({f: h}, args.dry_run)
            all_urls.append((L.datos_league_url(e["league"]["slug"]), today))

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
