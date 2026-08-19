"""Orquestador del agregador de noticias.

Flujo (cron en el servidor, sin pasos manuales):
  1. Descarga cada feed RSS (robusto por-feed: uno caído no tumba el run).
  2. Etiqueta cada ítem por liga/equipo (categorías + alias desde ESPN).
  3. Deduplica por enlace, filtra por antigüedad, ordena por fecha desc, capa.
  4. Persiste data/news/latest.json (+ data/news/<slug>.json por liga).

Alerta por email (reusa seo.notify) si NINGÚN ítem se agrega (todos los feeds
caídos/vacíos) o si aborta con una excepción no capturada. Mismo patrón de
robustez que generate_site (ver CLAUDE.md, Principio 2).

Uso:
    python -m news.aggregate            # ejecución del cron
    python -m news.aggregate --dry-run  # no escribe, solo resume
"""

import argparse
import json
import sys
from datetime import datetime, timezone

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from seo import notify
from . import feeds, tagging
from .config import (FEEDS, LEAGUES, MAX_AGE_DAYS, MAX_ITEMS, NEWS_DIR, PER_SLUG_MAX)

# Campos internos que no se exponen en el JSON público.
_INTERNAL = ("categories", "home", "league_hint")


def _clean(item):
    return {k: v for k, v in item.items() if k not in _INTERNAL}


def _collect():
    """Descarga y etiqueta todos los feeds. Devuelve (items, failures)."""
    index = tagging.build_alias_index()
    print(f"Tabla de alias: {len(index)} alias de equipo (ligas: {', '.join(LEAGUES)})")

    items, failures = [], []
    for feed in FEEDS:
        try:
            got = feeds.fetch_feed(feed)
        except Exception as e:  # noqa: BLE001 — por-feed, no debe tumbar el run
            print(f"  [SKIP] {feed['source']} {feed['url']}: {e}", file=sys.stderr)
            failures.append((feed["source"], feed["url"], str(e)))
            continue
        for it in got:
            tagging.tag_item(it, index)
        items.extend(got)
        print(f"  ✓ {feed['source']}: {len(got)} ítems ({feed['url']})")
    return items, failures


def _dedup_sort(items):
    """Dedup por enlace (se queda el más reciente), descarta viejos y ordena por
    fecha desc. SIN cap global: los caps (latest / por-liga) se aplican al escribir."""
    now = datetime.now(timezone.utc).timestamp()
    max_age = MAX_AGE_DAYS * 86400

    by_link = {}
    for it in items:
        if it["ts"] and (now - it["ts"]) > max_age:
            continue  # demasiado vieja para ser "noticia"
        prev = by_link.get(it["link"])
        if prev is None or it["ts"] > prev["ts"]:
            by_link[it["link"]] = it

    return sorted(by_link.values(), key=lambda x: x["ts"], reverse=True)


def _write(all_items, dry_run):
    generated = datetime.now(timezone.utc).isoformat()
    # latest.json (feed global /kiosco): top-N por fecha.
    latest = all_items[:MAX_ITEMS]
    payload = {"generated": generated, "count": len(latest),
               "items": [_clean(it) for it in latest]}

    def dump(path, data):
        if dry_run:
            print(f"    [dry] {path.relative_to(NEWS_DIR.parent.parent)} "
                  f"({data['count']} ítems)")
            return
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    if not dry_run:
        NEWS_DIR.mkdir(parents=True, exist_ok=True)
    dump(NEWS_DIR / "latest.json", payload)

    # Por liga: del set COMPLETO (no del top-N global), para que cada liga tenga
    # sus noticias aunque los feeds españoles dominen la portada global.
    for slug in LEAGUES:
        sub = [it for it in all_items if slug in it.get("leagues", [])][:PER_SLUG_MAX]
        dump(NEWS_DIR / f"{slug}.json",
             {"generated": generated, "count": len(sub),
              "items": [_clean(it) for it in sub]})


def _run(args):
    items, failures = _collect()
    final = _dedup_sort(items)
    _write(final, args.dry_run)

    tagged = sum(1 for it in final if it.get("teams"))
    print(f"\nFin — {len(final)} noticias únicas ({tagged} con equipo etiquetado; "
          f"latest.json capado a {MAX_ITEMS}), {len(failures)} feeds fallidos.")

    # Alerta si NINGUNA noticia se agregó (todos los feeds caídos/vacíos).
    if not final and not args.dry_run:
        motivos = "\n".join(f"  - {src} {url}: {err}" for src, url, err in failures) \
            or "  (todos los feeds devolvieron 0 ítems)"
        notify.send_alert(
            "[PredictMotion] news: 0 noticias agregadas",
            "El cron de noticias terminó sin agregar ninguna noticia. La página "
            "/kiosco se quedará con el último JSON válido (o vacía).\n\n"
            f"Feeds fallidos:\n{motivos}\n\n"
            "Revisar /home/ubuntu/news.log en el servidor.",
            dedup_key="news_zero",
        )
    return 0 if final else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="No escribe ficheros")
    args = ap.parse_args(argv)
    try:
        return _run(args)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        if not args.dry_run:
            notify.send_alert(
                "[PredictMotion] news: el agregador cayó con una excepción",
                "El cron de noticias abortó con una excepción no capturada:\n\n"
                f"{tb}\n"
                "Revisar /home/ubuntu/news.log en el servidor.",
                dedup_key="news_crash",
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
