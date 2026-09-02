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
import re
import sys
from pathlib import Path

from .config import LEAGUES, ROOT, league_by_slug

TMPL_DIR = Path(__file__).resolve().parent / "dashboards"


# Zonas por PLANTILLA: etiqueta larga (leyenda, cabecera), etiqueta corta (píldora,
# visible en el apilado móvil) y cortes de fallback. Los valores por defecto son los
# que la plantilla llevaba escritos a mano, así que las ligas que no declaran nada
# generan exactamente el mismo HTML que antes. Una liga los sobreescribe con
# `zone_labels` / `zone_labels_short` / `zone_slots` / `zones_text` en LEAGUES.
#
# Por qué tokens y no una plantilla por familia de liga: `top1` la comparten las 7
# europeas y el Brasileirão, y `tier2` las 4 segundas europeas con Liga MX, MLS y
# Argentina. Duplicar la plantilla duplicaría el motor, que es justo lo que causó la
# divergencia v1/v2 del 2026-08-10 (ver docs/modelo-fuerza).
#
# `slots` es (cabeza, intermedia, [tercera,] cola): 4 valores en `top1`
# (promo/europa/conf + descenso) y 3 en `tier2` (promo/playoffTop + cola).
ZONE_DEFAULTS = {
    "top1": {
        "labels": ("Champions League", "Europa League", "Conference League"),
        "short":  ("Champions", "Europa", "Conference"),
        "slots":  (4, 5, 6, 3),
        "text":   "Champions League, Europa League, Conference League",
    },
    "tier2": {
        "labels": ("Ascenso directo", "Play-off de ascenso", "Descenso a {RELEG_TO}"),
        "short":  ("Ascenso", "Play-off", "Descenso"),
        "slots":  (2, 6, 3),
        "text":   "ascenso directo, play-off y descenso",
        "text_largo": "ascenso directo, play-off de ascenso, permanencia o descenso a {RELEG_TO}",
    },
}

# Marcadores de la ZONA INTERMEDIA en `tier2` (cabecera, leyenda y píldora). Las
# ligas de DOS zonas —Argentina: clasificado a octavos o eliminado, sin nada en
# medio— se generan sin esa columna: con `playoffTop == promoSlots` la leyenda
# imprimiría un rango vacío ("Play-off (9º–8º)") y la píldora sería un "—" fijo.
# Se recortan en tiempo de render (los dashboards son estáticos), así que el
# cliente no lleva ningún condicional nuevo.
_MID_ZONE_RE = re.compile(r"<!--z2-->(.*?)<!--/z2-->", re.S)


def _zones_text(league, defaults, key="text"):
    """Enumeración de zonas para las metas y el texto editorial. Va SIN 'y' final
    cuando la plantilla la cierra ella ("… y descenso"). Una liga la sobreescribe
    con `zones_text` cuando la lista literal de etiquetas queda torpe en prosa (el
    Brasileirão parte la Libertadores en dos columnas —directa y previa— pero en la
    frase se nombra una sola vez)."""
    propio = league.get("zones_text" if key == "text" else "zones_text_largo")
    if propio:
        return propio
    if league.get("zone_labels"):
        return ", ".join(league["zone_labels"])
    return defaults.get(key) or defaults["text"]


def render(league):
    """HTML del dashboard de una liga: plantilla de su nivel + substitución de tokens."""
    template = league["dashboard_template"]
    tmpl = (TMPL_DIR / f"{template}.html").read_text(encoding="utf-8")
    d = ZONE_DEFAULTS.get(template, ZONE_DEFAULTS["top1"])
    releg_to = league.get("releg_to", "categoría inferior")
    sub = lambda t: t.replace("{RELEG_TO}", releg_to)
    zl = tuple(map(sub, league.get("zone_labels", d["labels"])))
    zs = tuple(map(sub, league.get("zone_labels_short", d["short"])))
    slots = league.get("zone_slots", d["slots"])
    # Claves del bloque `prob` del snapshot = claves de las BANDAS de la liga
    # (snapshots.build_table_snapshot las escribe con ellas). Se derivan, no se
    # declaran: así el dashboard y el cron no pueden separarse. El nº de equipos da
    # igual, las claves no dependen de él.
    bkeys = [b["key"] for b in league["bands"](20)]
    # Dos zonas (sin intermedia): fuera la columna de en medio.
    tmpl = (_MID_ZONE_RE.sub("", tmpl) if len(zl) < 3
            else _MID_ZONE_RE.sub(lambda m: m.group(1), tmpl))
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
        # Zonas. `top1` usa promo/europa/conf; `tier2`, promo/playoff/relega. El
        # último slot es siempre la cola (descenso / eliminado), de ahí slots[-1].
        "{{ZONE_PROMO}}":          zl[0],
        "{{ZONE_PROMO_SHORT}}":    zs[0],
        "{{ZONE_EUROPA}}":         zl[1] if len(zl) > 1 else "",
        "{{ZONE_EUROPA_SHORT}}":   zs[1] if len(zs) > 1 else "",
        "{{ZONE_PLAYOFF}}":        zl[1] if len(zl) > 2 else "",
        "{{ZONE_PLAYOFF_SHORT}}":  zs[1] if len(zs) > 2 else "",
        "{{ZONE_CONF}}":           zl[2] if len(zl) > 2 else "",
        "{{ZONE_CONF_SHORT}}":     zs[2] if len(zs) > 2 else "",
        "{{ZONE_RELEGA}}":         zl[-1],
        "{{ZONE_RELEGA_SHORT}}":   zs[-1],
        "{{ZONES_TEXT}}":          sub(_zones_text(league, d)),
        "{{ZONES_TEXT_LARGO}}":    sub(_zones_text(league, d, "text_largo")),
        "{{PROMO_SLOTS}}":         str(slots[0]),
        "{{EUROPA_SLOTS}}":        str(slots[1]),
        "{{CONF_SLOTS}}":          str(slots[2]) if len(slots) > 3 else "",
        "{{PLAYOFF_TOP}}":         str(slots[1]),
        "{{RELEG_SLOTS}}":         str(slots[-1]),
        "{{MATCHES_PER_TEAM}}":    str(league.get("matches_per_team") or "null"),
        "{{CHILD}}":               str(league.get("child") or 0),
        "{{PROB_PROMO}}":          bkeys[0],
        "{{PROB_EUROPA}}":         bkeys[1] if len(bkeys) > 1 else "",
        "{{PROB_PLAYOFF}}":        bkeys[1] if len(bkeys) > 2 else "",
        "{{PROB_CONF}}":           bkeys[2] if len(bkeys) > 2 else "",
        "{{PROB_RELEGA}}":         bkeys[-1],
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
