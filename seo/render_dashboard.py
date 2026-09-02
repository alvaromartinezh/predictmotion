"""Genera los dashboards estáticos por liga desde una plantilla + tokens.

Los dashboards (`<slug>.html`) son HTML estático servido por Caddy (indexable).
Se generan en **tiempo de commit**, NO en el cron: el cron (generate_site) solo
escribe en `data/` (gitignored); si tocara ficheros trackeados rompería el
`git pull` de auto-deploy del servidor. Añadir una liga = entrada en LEAGUES con
`dashboard_template` + volver a ejecutar esto + commitear el `<slug>.html`.

Plantillas en seo/dashboards/ (top1 = 1ª división europea, top2 = 2ª). Reusan el
motor compartido PMEngine; solo cambian por liga los tokens de abajo. Las
plantillas se extrajeron VERBATIM de laliga.html/hypermotion.html, así que
generar esas dos reproduce el fichero actual byte a byte (ver --check).

Uso:
    python3 -m seo.render_dashboard            # escribe <slug>.html de todas
    python3 -m seo.render_dashboard --check    # no escribe; compara con el actual
    python3 -m seo.render_dashboard --league laliga
"""

import argparse
import sys
from pathlib import Path

from .config import LEAGUES, ROOT, league_by_slug

TMPL_DIR = Path(__file__).resolve().parent / "dashboards"


# Zonas de la plantilla `top1`: etiqueta larga (leyenda, cabecera de columna),
# etiqueta corta (píldora, visible en el apilado móvil) y cortes de fallback
# (nº de plazas de cada zona + descenso). Los valores por defecto son los de la 1ª
# división EUROPEA, que es lo que la plantilla llevaba escrito a mano; una liga los
# sobreescribe con `zone_labels`/`zone_labels_short`/`zone_slots` en LEAGUES (así
# el Brasileirão reusa la misma plantilla con Libertadores/Sudamericana en vez de
# duplicarla — duplicar el motor es justo lo que causó la divergencia v1/v2 del
# 2026-08-10, ver docs/modelo-fuerza).
ZONE_LABELS_DEFAULT       = ("Champions League", "Europa League", "Conference League")
ZONE_LABELS_SHORT_DEFAULT = ("Champions", "Europa", "Conference")
ZONE_SLOTS_DEFAULT        = (4, 5, 6, 3)


def _zones_text(league, labels):
    """Enumeración de zonas para las metas y el texto editorial. Va SIN 'y' final
    porque la plantilla la cierra ella ("… y descenso"). Una liga puede
    sobreescribirla con `zones_text` cuando la lista literal de etiquetas queda
    torpe en prosa (el Brasileirão parte la Libertadores en dos columnas —directa y
    previa— pero en la frase se nombra una sola vez)."""
    return league.get("zones_text") or ", ".join(labels)


def render(league):
    """HTML del dashboard de una liga: plantilla de su nivel + substitución de tokens."""
    tmpl = (TMPL_DIR / f"{league['dashboard_template']}.html").read_text(encoding="utf-8")
    zl = league.get("zone_labels", ZONE_LABELS_DEFAULT)
    zs = league.get("zone_labels_short", ZONE_LABELS_SHORT_DEFAULT)
    slots = league.get("zone_slots", ZONE_SLOTS_DEFAULT)
    vals = {
        "{{SLUG}}":      league["slug"],
        "{{ESPN_CODE}}": league["espn_code"],
        "{{NAME}}":      league["name"],
        "{{SUBTITLE}}":  league["subtitle"],
        "{{SEASON}}":    league["season"],
        "{{P_HOME}}":    str(league["p_home"]),
        "{{P_DRAW}}":    str(league["p_draw"]),
        "{{SHORTNAME}}": league.get("shortname", league["name"]),
        "{{RELEG_TO}}":  league.get("releg_to", "categoría inferior"),
        "{{ABOUT}}":     league.get("about", ""),
        "{{ZONE_PROMO}}":        zl[0],
        "{{ZONE_EUROPA}}":       zl[1],
        "{{ZONE_CONF}}":         zl[2],
        "{{ZONE_PROMO_SHORT}}":  zs[0],
        "{{ZONE_EUROPA_SHORT}}": zs[1],
        "{{ZONE_CONF_SHORT}}":   zs[2],
        "{{ZONES_TEXT}}":        _zones_text(league, zl),
        "{{PROMO_SLOTS}}":       str(slots[0]),
        "{{EUROPA_SLOTS}}":      str(slots[1]),
        "{{CONF_SLOTS}}":        str(slots[2]),
        "{{RELEG_SLOTS}}":       str(slots[3]),
    }
    for tok, val in vals.items():
        tmpl = tmpl.replace(tok, val)
    return tmpl


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", help="Solo esta liga (slug)")
    ap.add_argument("--check", action="store_true",
                    help="No escribe; compara byte a byte con el <slug>.html actual")
    args = ap.parse_args(argv)

    if args.league:
        lg = league_by_slug(args.league)
        leagues = [lg] if lg else []
    else:
        leagues = list(LEAGUES)

    rc = 0
    for lg in leagues:
        if not lg or not lg.get("dashboard_template"):
            continue
        html = render(lg)
        path = ROOT / f"{lg['slug']}.html"
        if args.check:
            cur = path.read_text(encoding="utf-8") if path.exists() else None
            ident = cur == html
            note = "" if cur is not None else " (no existe aún)"
            print(f"{'✅' if ident else '❌'} {lg['slug']}.html: "
                  f"{'byte-idéntico' if ident else 'DIVERGE'}{note}")
            if cur is not None and not ident:
                rc = 1
                for i, (a, b) in enumerate(zip(cur, html)):
                    if a != b:
                        print(f"    primer diff byte {i}: {cur[i-15:i+15]!r} vs {html[i-15:i+15]!r}")
                        break
                if len(cur) != len(html):
                    print(f"    longitudes: actual={len(cur)} generado={len(html)}")
        else:
            path.write_text(html, encoding="utf-8")
            print(f"escrito {lg['slug']}.html ({len(html)} bytes)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
