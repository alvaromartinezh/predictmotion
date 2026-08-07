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


def render(league):
    """HTML del dashboard de una liga: plantilla de su nivel + substitución de tokens."""
    tmpl = (TMPL_DIR / f"{league['dashboard_template']}.html").read_text(encoding="utf-8")
    vals = {
        "{{SLUG}}":      league["slug"],
        "{{ESPN_CODE}}": league["espn_code"],
        "{{NAME}}":      league["name"],
        "{{SUBTITLE}}":  league["subtitle"],
        "{{P_HOME}}":    str(league["p_home"]),
        "{{P_DRAW}}":    str(league["p_draw"]),
        "{{SHORTNAME}}": league.get("shortname", league["name"]),
        "{{RELEG_TO}}":  league.get("releg_to", "categoría inferior"),
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
