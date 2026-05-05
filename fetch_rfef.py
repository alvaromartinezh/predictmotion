#!/usr/bin/env python3
"""
Primera RFEF standings scraper — Playwright + Marca.com
Guarda cache/rfef_g1.json y cache/rfef_g2.json en el mismo directorio.

Instalación en el servidor (una sola vez):
    pip3 install playwright
    playwright install chromium
    playwright install-deps chromium

Cron (cada 30 min):
    */30 * * * * /usr/bin/python3 /home/ubuntu/predictmotion/fetch_rfef.py >> /home/ubuntu/rfef_scraper.log 2>&1
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: instala playwright → pip3 install playwright && playwright install chromium")
    sys.exit(1)

CACHE_DIR = Path(__file__).parent / "cache"
SEASON    = "2025/26"

GROUPS = [
    {
        "name": "Grupo 1",
        "url":  "https://www.marca.com/futbol/primera-rfef/clasificacion/grupo-1.html",
        "out":  "rfef_g1.json",
    },
    {
        "name": "Grupo 2",
        "url":  "https://www.marca.com/futbol/primera-rfef/clasificacion/grupo-2.html",
        "out":  "rfef_g2.json",
    },
]

# ── Parseo de JSON capturado via intercepción de red ───────────────────────

def _to_int(v):
    try:
        return int(str(v).strip().lstrip("+"))
    except Exception:
        return 0

def _get(d, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return _to_int(v)
    return 0

def _parse_entries(items):
    out = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue

        # Nombre del equipo — varios formatos
        name = ""
        for k in ("nombre", "name", "equipo", "teamName", "team_name", "club"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                name = v.strip()
                break
            if isinstance(v, dict):
                for kk in ("nombre", "name"):
                    if isinstance(v.get(kk), str):
                        name = v[kk].strip()
                        break
            if name:
                break
        if not name:
            continue

        # Logo
        logo = ""
        for k in ("escudo", "logo", "crest", "image", "img", "icon"):
            v = item.get(k)
            if isinstance(v, str) and v.startswith("http"):
                logo = v
                break
            if isinstance(v, dict):
                for kk in ("url", "src", "href"):
                    if isinstance(v.get(kk), str):
                        logo = v[kk]
                        break
            if logo:
                break

        out.append({
            "rank":   _get(item, "posicion", "rank", "pos") or i + 1,
            "name":   name,
            "logo":   logo,
            "gp":     _get(item, "jugados", "played", "pj", "gp", "matchesPlayed"),
            "wins":   _get(item, "ganados", "wins", "win", "victorias", "pg"),
            "draws":  _get(item, "empatados", "draws", "draw", "empates", "pe"),
            "losses": _get(item, "perdidos", "losses", "lost", "derrotas", "pp"),
            "gf":     _get(item, "golesFavor", "goalsFor", "gf", "goles_favor"),
            "gc":     _get(item, "golesContra", "goalsAgainst", "gc", "goles_contra"),
            "pts":    _get(item, "puntos", "points", "pts"),
        })

    return out if len(out) >= 8 else None


def try_parse_json(data):
    """
    Intenta encontrar la lista de equipos dentro de un JSON arbitrario.
    Devuelve lista de dicts normalizada o None.
    """
    if isinstance(data, list) and len(data) >= 8:
        result = _parse_entries(data)
        if result:
            return result

    if isinstance(data, dict):
        for key in ("clasificacion", "standings", "table", "teams", "data",
                    "Clasificacion", "Standings", "Table", "Teams", "Data"):
            sub = data.get(key)
            if isinstance(sub, list) and len(sub) >= 8:
                result = _parse_entries(sub)
                if result:
                    return result
            if isinstance(sub, dict):
                for inner_key in ("equipo", "team", "teams", "equipos", "rows"):
                    inner = sub.get(inner_key)
                    if isinstance(inner, list) and len(inner) >= 8:
                        result = _parse_entries(inner)
                        if result:
                            return result
    return None


# ── Extracción HTML del DOM renderizado ───────────────────────────────────

EXTRACT_JS = """
() => {
    // Buscar la tabla con más filas de datos
    let best = null, maxR = 0;
    for (const t of document.querySelectorAll('table')) {
        const rows = [...t.querySelectorAll('tbody tr')]
            .filter(r => r.querySelectorAll('td').length >= 6);
        if (rows.length > maxR) { maxR = rows.length; best = rows; }
    }
    if (!best || maxR < 8) return null;

    const result = [];
    best.forEach((row, idx) => {
        const cells  = [...row.querySelectorAll('td')];
        const img    = row.querySelector('img');
        const link   = row.querySelector('a');
        const name   = link ? link.textContent.trim() : '';
        if (!name || name.length < 2) return;

        const nums = cells.map(c => {
            const t = c.textContent.trim().replace(/[+ ]/g, '');
            return /^\d+$/.test(t) ? parseInt(t) : null;
        }).filter(n => n !== null);

        if (nums.length < 5) return;

        // Columnas desde el final: ..., gf, gc, [dif], pts
        const pts  = nums[nums.length - 1];
        const gc   = nums[nums.length - 2];
        const gf   = nums[nums.length - 3];
        const loss = nums[nums.length - 4];
        const draw = nums.length >= 5 ? nums[nums.length - 5] : 0;
        const wins = nums.length >= 6 ? nums[nums.length - 6] : 0;
        const pj   = nums.length >= 7 ? nums[nums.length - 7] : 0;

        result.push({
            rank:   idx + 1,
            name,
            logo:   img ? (img.src || img.dataset.src || '') : '',
            gp: pj, wins, draws: draw, losses: loss, gf, gc, pts,
        });
    });
    return result.length >= 8 ? result : null;
}
"""


async def scrape_group(browser, group):
    page = await browser.new_page()
    captured = {}

    async def on_response(response):
        try:
            ct = response.headers.get("content-type", "")
            if "json" not in ct or response.status != 200:
                return
            body = await response.text()
            if len(body) < 200:
                return
            body_lower = body.lower()
            if any(k in body_lower for k in ("equipo", "puntos", "standing", "clasificacion", "points", "teamname")):
                captured[response.url] = body
        except Exception:
            pass

    page.on("response", on_response)

    try:
        await page.goto(group["url"], wait_until="networkidle", timeout=35000)
        await page.wait_for_timeout(2500)

        # Estrategia 1 — JSON interceptado
        for url, body in captured.items():
            try:
                data = json.loads(body)
                standings = try_parse_json(data)
                if standings:
                    print(f"  [JSON] {url[:90]}")
                    await page.close()
                    return standings
            except Exception:
                pass

        # Estrategia 2 — DOM renderizado
        standings = await page.evaluate(EXTRACT_JS)
        if standings:
            print(f"  [HTML] {len(standings)} equipos extraídos del DOM")
            await page.close()
            return standings

        print(f"  [WARN] Sin datos en {group['url']}", file=sys.stderr)
        await page.close()
        return None

    except Exception as e:
        print(f"  [ERR] {e}", file=sys.stderr)
        try:
            await page.close()
        except Exception:
            pass
        return None


async def main():
    CACHE_DIR.mkdir(exist_ok=True)
    ok = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )

        for group in GROUPS:
            print(f"\n→ {group['name']}  {group['url']}")
            standings = await scrape_group(browser, group)

            if not standings:
                print(f"  [SKIP] {group['name']}: sin datos", file=sys.stderr)
                continue

            out = {
                "updated":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "season":    SEASON,
                "group":     group["name"],
                "standings": standings,
            }
            path = CACHE_DIR / group["out"]
            path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  ✓ {path.name}  ({len(standings)} equipos)  1º: {standings[0]['name']} {standings[0]['pts']}pts")
            ok += 1

        await browser.close()

    print(f"\nFin — {ok}/{len(GROUPS)} grupos actualizados.")
    sys.exit(0 if ok > 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
