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
import contextlib
import io
import multiprocessing as mp
import os
import sys
import traceback
from datetime import datetime, timezone

# Consola UTF-8 también en Windows (en el servidor Linux ya lo es).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from . import espn, render_table, sitemap, predictions, zone_predictions, notify
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
    # use_strength=False (UEFA) → modelo uniforme, sin prior. Se fuerza ratings=None
    # para NO heredar un prior parcial e inconsistente (los clubes que además juegan
    # su liga doméstica activa sí estarían en `ratings`). Ver config.py / Fase 4.
    lg_ratings = None if league.get("use_strength") is False else ratings
    sim = sim_table.simulate(rows, league["p_home"], league["p_draw"],
                             playoff_top=league.get("playoff_top"), ratings=lg_ratings,
                             matches_per_team=league.get("matches_per_team"))
    snap = build_table_snapshot(league, rows, sim, SIM_N_TABLE, today,
                                league_logo=meta["logo"], season=meta["season"],
                                ratings=lg_ratings)
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


# ── Paralelización por liga ────────────────────────────────────────────────
# Cada liga es INDEPENDIENTE y DETERMINISTA: escribe solo a rutas data/<slug>/…
# (ningún fichero compartido dentro del bucle) y su Monte Carlo se siembra del
# hash de su propia tabla (no del orden ni de estado global). Por eso repartir
# las ligas entre procesos da los MISMOS números que en serie. El sitemap se
# escribe fuera del bucle y ordena por path, así que el orden de llegada tampoco
# le afecta. El prior de fuerza (`ratings`) se calcula UNA vez en el padre y se
# comparte a los hijos vía initializer (no se re-descarga ni se re-pickle por
# tarea).
_RATINGS = None


def _pool_init(ratings):
    global _RATINGS
    _RATINGS = ratings


def _worker(task):
    """Ejecuta una liga (por SLUG) y devuelve (slug, urls, error, log).

    La tarea es solo el slug, NO el dict de liga: este último contiene closures
    (`bands`) que no se pueden picklear al enviarlos al proceso. El worker resuelve
    el dict con `league_by_slug` desde el registro LEAGUES, que el hijo ya tiene en
    memoria (heredado por fork; o reconstruido al re-importar con spawn) — con sus
    closures intactos y sin pasar por pickle.

    Aísla el fallo por-liga DENTRO del proceso (como el try/except secuencial de
    siempre) para que una liga rota no tumbe el pool. Captura el stdout de la liga
    y lo devuelve para que el padre lo imprima agrupado y EN ORDEN (los procesos
    escribirían entremezclado si no)."""
    slug, today, dry_run = task
    league = league_by_slug(slug)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            _snap, urls = _process_table(league, today, dry_run, ratings=_RATINGS)
        return (slug, urls, None, buf.getvalue())
    except Exception as e:  # noqa: BLE001 — se reporta como fallo de liga
        return (slug, None, str(e), buf.getvalue())


def _resolve_jobs(args, n_leagues):
    """Nº de procesos. Secuencial (1) para --dry-run o --league (una sola liga no
    gana nada en paralelo y evita interleaving de logs). Si no, --jobs o, por
    defecto, tantos como núcleos (en la VM = 4), acotado al nº de ligas."""
    if args.dry_run or args.league or n_leagues <= 1:
        return 1
    if args.jobs and args.jobs > 0:
        return min(args.jobs, n_leagues)
    return min(os.cpu_count() or 1, n_leagues)


def _run(args):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    leagues = [league_by_slug(args.league)] if args.league else LEAGUES

    # Prior de fuerza: se construye UNA vez (la temporada previa de ambas
    # divisiones) y se comparte entre ligas. Best-effort: si falla, ratings={} y
    # el Monte Carlo corre en modo uniforme de siempre.
    current_year = espn.fetch_current_season_year(LEAGUES[0]["espn_code"])
    active_codes = {lg["espn_code"] for lg in leagues}
    ratings = espn.build_strength_ratings(current_year, active_codes)
    print(f"Prior de fuerza: {len(ratings)} equipos con rating"
          f" (temporada previa {current_year - 1 if current_year else '??'})")

    jobs = _resolve_jobs(args, len(leagues))
    tasks = [(lg["slug"], today, args.dry_run) for lg in leagues]
    print(f"Procesando {len(leagues)} ligas con {jobs} proceso(s).")

    # Ejecuta las tareas y recoge {slug: (urls, error, log)}. El pool las corre en
    # paralelo (imap_unordered: reparte según se liberan procesos); da igual el
    # orden porque luego reensamblamos siguiendo el orden de `leagues`.
    results = {}
    if jobs == 1:
        _pool_init(ratings)
        for task in tasks:
            slug, urls, err, log = _worker(task)
            results[slug] = (urls, err, log)
    else:
        with mp.Pool(processes=jobs, initializer=_pool_init,
                     initargs=(ratings,)) as pool:
            for slug, urls, err, log in pool.imap_unordered(_worker, tasks):
                results[slug] = (urls, err, log)

    all_urls = []
    ok = 0
    failures = []  # (slug, motivo) para el email de alerta si acaba en 0 ligas

    # Reporte y agregación EN ORDEN de `leagues` (determinista, independiente del
    # orden de finalización de los procesos).
    for league in leagues:
        urls, err, log = results[league["slug"]]
        print(f"\n→ {league['name']} ({league['espn_code']})")
        if log:
            print(log, end="")
        if err is not None:
            print(f"  [SKIP] {league['slug']}: {err}", file=sys.stderr)
            failures.append((league["slug"], err))
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

    # Alerta por email si NINGUNA liga se generó. Solo en la ejecución real del
    # cron (run completo, sin --dry-run): un dry-run o un --league puntual no
    # deben disparar avisos. Dedupe 6h para no repetir mientras dure el fallo.
    if ok == 0 and not args.dry_run and not args.league:
        motivos = "\n".join(f"  - {slug}: {err}" for slug, err in failures) \
            or "  (sin ligas configuradas)"
        notify.send_alert(
            "[PredictMotion] generate_site: 0 ligas generadas",
            "El cron SEO terminó sin generar ninguna liga. Los dashboards siguen "
            "vivos (fallback en cliente) pero el histórico/SEO se congela.\n\n"
            f"Ligas fallidas:\n{motivos}\n\n"
            "Revisar /home/ubuntu/seo_generate.log en el servidor.",
            dedup_key="generate_site_zero",
        )

    return 0 if ok > 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="No escribe ficheros")
    ap.add_argument("--league", help="Procesar solo esta liga (slug)")
    ap.add_argument("--jobs", "-j", type=int, default=None,
                    help="Procesos en paralelo (def: nº de núcleos, 4 en la VM). "
                         "-j 1 = secuencial. Ignorado con --dry-run/--league.")
    args = ap.parse_args(argv)

    if args.league and not league_by_slug(args.league):
        print(f"Liga desconocida: {args.league}", file=sys.stderr)
        return 1

    # Envoltura de nivel superior: una excepción no capturada (fuera del bucle
    # por-liga, p. ej. en el prior de fuerza o el sitemap) tumbaría el cron en
    # silencio. La convertimos en email antes de propagar el fallo.
    try:
        return _run(args)
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        if not args.dry_run and not args.league:
            notify.send_alert(
                "[PredictMotion] generate_site cayó con una excepción",
                "El cron SEO abortó con una excepción no capturada:\n\n"
                f"{tb}\n"
                "Revisar /home/ubuntu/seo_generate.log en el servidor.",
                dedup_key="generate_site_crash",
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
