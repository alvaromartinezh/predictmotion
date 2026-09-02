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

from . import espn, render_table, sitemap, predictions, zone_predictions, notify, links
from .config import (LEAGUES, ROOT, SIM_N_TABLE, league_by_slug, SCORE_MODEL,
                     CALENDAR_YEAR_CODES)
from .snapshots import (build_table_snapshot, save_snapshot, load_all,
                        save_offseason_latest)
from . import sim_table
from . import poisson


def _football_year(today):
    """Año de la temporada de fútbol EUROPEA vigente según el calendario.
    Julio en adelante → temporada que empieza este año; antes → la anterior. La
    ventana julio es segura: ninguna liga europea (dom. mediados de agosto; sorteo
    UEFA finales de agosto) empieza antes."""
    y, m = int(today[:4]), int(today[5:7])
    return y if m >= 7 else y - 1


def _season_start_year(season):
    """Año inicial de una etiqueta 'YYYY-YY' de ESPN (p. ej. '2025-26' → 2025)."""
    try:
        return int(str(season)[:4])
    except (TypeError, ValueError):
        return None


def _is_offseason(season, today):
    """True si la temporada que sirve ESPN es de un ciclo YA PASADO respecto al
    calendario (p. ej. hoy es agosto de 2026 pero ESPN sigue dando la UEFA 2025-26,
    ya terminada, porque el sorteo 2026-27 aún no se ha publicado). Genérico y
    auto-recuperable: en cuanto ESPN publica la temporada nueva, start_year sube y
    esto vuelve a False solo. En temporada (p. ej. febrero, con la fase de liga ya
    cerrada pero la eliminatoria en curso) da False, así que NO oculta nada vivo."""
    start = _season_start_year(season)
    return start is not None and start < _football_year(today)


def _upcoming_season_label(today):
    """Etiqueta 'YYYY-YY' de la temporada que está por empezar (la del calendario)."""
    y = _football_year(today)
    return f"{y}-{str(y + 1)[2:]}"


def _write_files(files, dry_run):
    for relpath, html in files.items():
        path = ROOT / relpath
        if dry_run:
            print(f"    [dry] {relpath} ({len(html)} bytes)")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")


def _process_offseason(league, meta, today, dry_run):
    """Escribe un latest.json de 'fuera de temporada' para una competición cuyo
    ciclo ya terminó y cuya temporada nueva ESPN aún no ha publicado (típico de la
    fase de liga UEFA en agosto). El dashboard lo lee y muestra el estado
    placeholder en vez de la tabla final congelada. Se re-genera cada run y se
    auto-revierte a tabla viva en cuanto ESPN publique la temporada nueva."""
    upcoming = _upcoming_season_label(today)
    snap = {
        "league":       league["slug"],
        "kind":         "table",
        "name":         league["name"],
        "season":       upcoming,
        "offseason":    True,
        "upcoming_season": upcoming,
        "prev_season":  meta.get("season"),
        "league_logo":  meta.get("logo"),
        "date":         today,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows_html":    "",   # sin tabla que servir (placeholder del dashboard)
    }
    if not dry_run:
        save_offseason_latest(league["slug"], snap)
    return snap


def _process_table(league, today, dry_run, ratings=None, goal_strengths=None):
    meta = espn.fetch_league_meta(league["espn_code"])
    # Fuera de temporada (Principio 1): si ESPN aún sirve un ciclo ya terminado
    # (UEFA en agosto, antes del sorteo nuevo), NO congelamos la tabla final; se
    # escribe un latest.json 'offseason' que el dashboard muestra como placeholder.
    # Se limita a los dashboards `uefa` (los únicos con render de placeholder); las
    # ligas domésticas ruedan de temporada solas en ESPN y no entran en este hueco.
    if league.get("dashboard_template") == "uefa" and _is_offseason(meta.get("season"), today):
        snap = _process_offseason(league, meta, today, dry_run)
        return snap, []

    # La temporada es la CLAVE DE PARTICIÓN del histórico. Si el scoreboard falla
    # (endpoint distinto del de standings: ya han fallado por separado),
    # fetch_league_meta devuelve season=None y el snapshot caía al `season` FIJO de
    # config.py — 2025-26 — archivando la tabla de 2026-27 dentro de la temporada
    # anterior y cruzando por jornada las dos, justo lo que la partición existe para
    # evitar. Mejor saltarse la liga esta pasada: el aviso de fallo parcial lo dice y
    # la siguiente se recupera sola.
    if not meta.get("season"):
        raise RuntimeError(
            "ESPN no devolvió la temporada (scoreboard caído): no se archiva el "
            "snapshot para no mezclarlo con la temporada de config.py")

    rows = espn.fetch_table(league["espn_code"])
    # use_strength=False (UEFA) → modelo uniforme, sin prior. Se fuerza ratings=None
    # para NO heredar un prior parcial e inconsistente (los clubes que además juegan
    # su liga doméstica activa sí estarían en `ratings`). Ver config.py / Fase 4.
    lg_ratings = None if league.get("use_strength") is False else ratings
    # v3 (Poisson): las desviaciones de ataque/defensa se calculan aquí, en el
    # worker, a partir de los blends multi-temporada (`goal_strengths`, uno por
    # proceso). Se restan la media de la liga actual y se usa la base de goles
    # real; sin `goal_strengths` → adj=None → la sim corre en modo uniforme
    # (solo base + hfa) y el snapshot NO declara v3.
    lg_adj = None
    lg_base = None
    if SCORE_MODEL == "poisson" and league.get("use_strength") is not False \
            and goal_strengths:
        lg_adj = poisson.league_adjust(goal_strengths, rows)
        lg_base = poisson.league_base(rows)
    sim = sim_table.simulate(rows, league["p_home"], league["p_draw"],
                             playoff_top=league.get("playoff_top"), ratings=lg_ratings,
                             matches_per_team=league.get("matches_per_team"),
                             adj=lg_adj, base=lg_base,
                             k_att=league.get("poisson_k_att"),
                             k_def=league.get("poisson_k_def"))
    snap = build_table_snapshot(league, rows, sim, SIM_N_TABLE, today,
                                league_logo=meta["logo"], season=meta["season"],
                                ratings=lg_ratings, adj=lg_adj, base=lg_base,
                                k_att=league.get("poisson_k_att"),
                                k_def=league.get("poisson_k_def"))
    if not dry_run:
        save_snapshot(snap)
    # Solo la temporada VIVA (partición por temporada): no mezclar histórico de
    # 2025-26 con 2026-27.
    snaps = load_all(league["slug"], snap["season"]) or [snap]
    if dry_run and snaps[-1]["date"] != today:
        snaps = snaps + [snap]

    # Calendario restante (best-effort, no se persiste en el snapshot). UNA llamada
    # para toda la liga; antes era una por equipo (ver fetch_remaining_schedules).
    extras = espn.fetch_remaining_schedules(league["espn_code"])

    # Registro append-only de predicciones 1X2 (para Brier / calibración).
    if not dry_run:
        predictions.record_matchday(league, snap)
        # Registro de probabilidades de zona por jornada completa (calibración de
        # zona, complementaria al Brier por partido). Upsert por jornada.
        zone_predictions.record_jornada(league, snap)

    files, urls = render_table.render(league, snaps, extras=extras)
    _write_files(files, dry_run)
    # La jornada 0 (pretemporada) ya no se genera (render_table.render): borrar el
    # fichero que quedó de pasadas anteriores para que no siga accesible como URL
    # huérfana (sin sitemap ni enlaces, pero directa).
    if not dry_run:
        (ROOT / links.jornada_file(league["slug"], 0)).unlink(missing_ok=True)
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
_GOAL_STRENGTHS = None


def _pool_init(ratings, goal_strengths=None):
    global _RATINGS, _GOAL_STRENGTHS
    _RATINGS = ratings
    _GOAL_STRENGTHS = goal_strengths


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
            _snap, urls = _process_table(league, today, dry_run, ratings=_RATINGS,
                                         goal_strengths=_GOAL_STRENGTHS)
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
    # El año sale de UNA sola llamada; si esa falla, TODAS las ligas pierden el
    # prior. Se reintenta con las siguientes antes de rendirse: son endpoints
    # distintos y ESPN ha fallado por liga suelta.
    current_year = None
    for lg in leagues:
        current_year = espn.fetch_current_season_year(lg["espn_code"])
        if current_year:
            break
    active_codes = {lg["espn_code"] for lg in leagues}
    # Ligas de AÑO NATURAL: `current_year` sale de la primera liga de la lista
    # (europea) y para ellas se desfasa medio año. Una llamada extra por liga de
    # este tipo, solo si está activa. Ver espn.build_strength_ratings.
    year_by_code = {}
    for code in sorted(CALENDAR_YEAR_CODES & active_codes):
        y = espn.fetch_current_season_year(code)
        if y:
            year_by_code[code] = y
    ratings = espn.build_strength_ratings(current_year, active_codes, year_by_code)
    print(f"Prior de fuerza: {len(ratings)} equipos con rating"
          f" (temporada previa {current_year - 1 if current_year else '??'})")

    # v3 (Poisson): ataque/defensa multi-temporada, UNA vez en el padre y
    # compartido a los workers (mismo patrón que `ratings`). Solo si el modelo
    # activo es poisson; con SCORE_MODEL='legacy' (rollback) no se descarga nada.
    goal_strengths = None
    if SCORE_MODEL == "poisson":
        goal_strengths = espn.build_attack_defense(current_year, active_codes,
                                                   year_by_code)
        print(f"Prior de goles (att/def): {len(goal_strengths)} equipos"
              f" (v3, temporadas previas {current_year - 1 if current_year else '??'})")

    # Sin ratings, las 15 ligas simulan con el modelo UNIFORME (en pretemporada,
    # todos los equipos con el mismo %) y publican un snapshot sin `strength`. Como
    # las ligas sí se generan, `ok` sale 15 y no saltaba ninguna de las dos alertas:
    # el sitio entero cambiaba de modelo en silencio. Solo se avisa si alguna liga
    # esperaba prior (UEFA corre sin él por diseño, use_strength=False).
    if not ratings and not args.dry_run and not args.league \
            and any(lg.get("use_strength") is not False for lg in leagues):
        notify.send_alert(
            "[PredictMotion] generate_site: sin prior de fuerza",
            "No se pudo construir el prior de fuerza (temporada previa de ESPN), "
            "así que TODAS las ligas se han simulado con el modelo uniforme: en "
            "pretemporada eso son porcentajes casi iguales para todos los equipos.\n\n"
            f"Año de temporada detectado: {current_year or 'ninguno'}.\n\n"
            "Revisar /home/ubuntu/seo_generate.log en el servidor.",
            dedup_key="generate_site_no_strength",
        )
    # v3: sin ataque/defensa → TODAS las ligas que esperan prior simulan en
    # uniforme (solo base + hfa) y publican snapshot sin `strength_model`; el
    # modelo cambia en silencio. Mismo patrón de alerta que el de ratings.
    if SCORE_MODEL == "poisson" and not goal_strengths \
            and not args.dry_run and not args.league \
            and any(lg.get("use_strength") is not False for lg in leagues):
        notify.send_alert(
            "[PredictMotion] generate_site: sin prior de goles (v3)",
            "No se pudo construir el blend de ataque/defensa (temporadas previas "
            "de ESPN), así que las ligas con prior han simulado en modo uniforme "
            "y publican snapshot SIN strength_model=v3.\n\n"
            f"Año de temporada detectado: {current_year or 'ninguno'}.\n\n"
            "Revisar /home/ubuntu/seo_generate.log en el servidor.",
            dedup_key="generate_site_no_goals",
        )

    jobs = _resolve_jobs(args, len(leagues))
    tasks = [(lg["slug"], today, args.dry_run) for lg in leagues]
    print(f"Procesando {len(leagues)} ligas con {jobs} proceso(s).")

    # Ejecuta las tareas y recoge {slug: (urls, error, log)}. El pool las corre en
    # paralelo (imap_unordered: reparte según se liberan procesos); da igual el
    # orden porque luego reensamblamos siguiendo el orden de `leagues`.
    results = {}
    if jobs == 1:
        _pool_init(ratings, goal_strengths)
        for task in tasks:
            slug, urls, err, log = _worker(task)
            results[slug] = (urls, err, log)
    else:
        with mp.Pool(processes=jobs, initializer=_pool_init,
                     initargs=(ratings, goal_strengths)) as pool:
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

    # Fotos de jugador (TheSportsDB): mantenimiento incremental dentro del cron.
    # Best-effort: si TheSportsDB falla o el backfill está en curso (lock), no
    # debe tumbar la generación. Solo en la ejecución completa del cron.
    if not args.dry_run and not args.league:
        try:
            from . import player_cuts
            player_cuts.run(leagues, limit=player_cuts.DEFAULT_LIMIT)
        except Exception as exc:
            print(f"  [SKIP] player_cuts: {exc}", file=sys.stderr)

    # Fichas de jugador: data/players/<id>.json + index.json.
    # Se ejecuta en cada run completo (no con --league puntual) para mantener
    # los datos de plantilla sincronizados.
    if not args.dry_run and not args.league:
        try:
            from . import players
            res = players.run()
            # `run()` recoge un error por liga y sigue: sin mirar el retorno, que
            # /buscar se quedara sin la mitad de los jugadores (o sin ninguno) no lo
            # veía nadie. Mismo patrón de fallo silencioso que el de las ligas.
            if res and res.get("errors"):
                notify.send_alert(
                    "[PredictMotion] players: fichas incompletas",
                    f"players.run() escribió {res.get('ok', 0)} fichas con "
                    f"{len(res['errors'])} errores. El buscador (/buscar) solo "
                    "encuentra a los jugadores del índice.\n\n"
                    + "\n".join(f"  - {e}" for e in res["errors"][:20]),
                    dedup_key="players_partial",
                )
        except Exception as exc:
            print(f"  [SKIP] players: {exc}", file=sys.stderr)
            notify.send_alert(
                "[PredictMotion] players: excepción",
                f"players.run() lanzó: {exc}", dedup_key="players_crash")

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
    elif failures and not args.dry_run and not args.league:
        # Fallo PARCIAL: con 15 ligas, que una se caiga sola (código ESPN que
        # cambia, 403, liga sin tabla) no llega nunca a ok==0, así que no avisaba
        # nadie y ESA liga se congelaba en silencio mientras las otras 14 seguían
        # — el patrón exacto que este proyecto persigue. La clave de dedupe lleva
        # los slugs fallidos: un fallo distinto avisa, el mismo se calla 6 h.
        motivos = "\n".join(f"  - {slug}: {err}" for slug, err in failures)
        slugs = ",".join(sorted(slug for slug, _ in failures))
        notify.send_alert(
            f"[PredictMotion] generate_site: {len(failures)} liga(s) sin generar",
            f"El cron SEO generó {ok}/{len(leagues)} ligas. Las que fallaron se "
            "quedan con el snapshot viejo (dashboard e histórico congelados) "
            "mientras el resto del sitio sigue actualizándose.\n\n"
            f"Ligas fallidas:\n{motivos}\n\n"
            "Revisar /home/ubuntu/seo_generate.log en el servidor.",
            dedup_key=f"generate_site_partial:{slugs}",
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
