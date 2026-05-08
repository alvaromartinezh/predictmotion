#!/usr/bin/env python3
"""
PredictMotion Bluesky Bot

Modos de uso:
  python twitter_bot.py weekend   — post general de tabla (cron viernes/sábado/domingo 12:00)
  python twitter_bot.py matches   — detecta inicio y fin de partidos (cron cada 5 min vie/sáb/dom)
"""

import json
import sys
import time
import requests
from pathlib import Path
from atproto import Client
from playwright.sync_api import sync_playwright

# ── Credenciales ─────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
BLUESKY_DIR = BASE / "BLUESKY"

HANDLE   = (BLUESKY_DIR / "HANDLE.txt").read_text().strip()
APP_PASS = (BLUESKY_DIR / "APP.txt").read_text().strip()

# ── Configuración de ligas ────────────────────────────────────────────────────
LEAGUES = {
    "esp.2": {
        "name":  "Liga Hypermotion",
        "url":   "https://predictmotion.com",
        "short": "2ª División",
    },
    "esp.1": {
        "name":  "LaLiga",
        "url":   "https://predictmotion.com/laliga.html",
        "short": "LaLiga",
    },
}

STATE_FILE = BASE / "twitter_state.json"

# ── Bluesky client ────────────────────────────────────────────────────────────
def get_client():
    client = Client()
    client.login(HANDLE, APP_PASS)
    return client

# ── Captura de pantalla ───────────────────────────────────────────────────────
def screenshot(url, path):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 900, "height": 700})
        page.goto(url, wait_until="networkidle", timeout=30000)
        try:
            page.wait_for_selector("tbody tr", timeout=15000)
        except Exception:
            pass
        time.sleep(2)
        page.screenshot(path=str(path))
        browser.close()

# ── ESPN API ──────────────────────────────────────────────────────────────────
def fetch_standings(espn_code):
    url = f"https://site.api.espn.com/apis/v2/sports/soccer/{espn_code}/standings"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        entries = data["children"][0]["standings"]["entries"]
        teams = []
        for e in entries:
            stats = {s["name"]: s.get("value", 0) for s in e.get("stats", [])}
            teams.append({
                "name": e["team"]["displayName"],
                "pts":  int(stats.get("points", 0)),
                "pj":   int(stats.get("gamesPlayed", 0)),
            })
        return teams
    except Exception as ex:
        print(f"[ESPN standings error] {ex}")
        return []

def fetch_scoreboard(espn_code):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{espn_code}/scoreboard"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        matches = []
        for event in data.get("events", []):
            comp = event["competitions"][0]
            competitors = comp["competitors"]
            home = next(c for c in competitors if c["homeAway"] == "home")
            away = next(c for c in competitors if c["homeAway"] == "away")
            matches.append({
                "id":      event["id"],
                "state":   event["status"]["type"]["state"],
                "home":    home["team"]["displayName"],
                "away":    away["team"]["displayName"],
                "score_h": home.get("score", "0"),
                "score_a": away.get("score", "0"),
            })
        return matches
    except Exception as ex:
        print(f"[ESPN scoreboard error] {ex}")
        return []

# ── Generación de texto ───────────────────────────────────────────────────────
def text_weekend(espn_code, teams):
    league = LEAGUES[espn_code]
    if not teams:
        return None
    leader = teams[0]
    second = teams[1] if len(teams) > 1 else None
    jornada = leader["pj"]

    if espn_code == "esp.2":
        txt = (
            f"📊 Liga Hypermotion · Jornada {jornada}\n"
            f"🥇 {leader['name']} lidera con {leader['pts']} pts"
        )
        if second:
            txt += f"\n🥈 {second['name']} ({second['pts']} pts)"
        txt += f"\n\n¿Quién sube a LaLiga? Probabilidades en tiempo real 👇\n{league['url']}"
    else:
        txt = (
            f"📊 LaLiga · Jornada {jornada}\n"
            f"🥇 {leader['name']} lidera con {leader['pts']} pts"
        )
        if second:
            txt += f"\n🥈 {second['name']} ({second['pts']} pts)"
        txt += f"\n\nChampions, Europa y descenso · Probabilidades en vivo 👇\n{league['url']}"

    return txt

def text_match_start(match, espn_code):
    league = LEAGUES[espn_code]
    return (
        f"⚽ ¡Arranca! {match['home']} vs {match['away']}\n"
        f"{league['short']} · ¿Cómo afecta a la tabla?\n"
        f"Sigue las probabilidades en tiempo real 👇\n{league['url']}"
    )

def text_match_end(match, espn_code):
    league = LEAGUES[espn_code]
    return (
        f"⏱ Final: {match['home']} {match['score_h']} - {match['score_a']} {match['away']}\n"
        f"{league['short']} · Así quedan las probabilidades de ascenso y descenso 👇\n{league['url']}"
    )

# ── Post con imagen ───────────────────────────────────────────────────────────
def post(text, img_path=None):
    client = get_client()
    if img_path and img_path.exists():
        img_data = img_path.read_bytes()
        client.send_image(text=text, image=img_data, image_alt="Tabla de clasificación · predictmotion.com")
    else:
        client.send_post(text=text)
    print(f"[OK] Post publicado: {text[:80]}...")

# ── Estado persistente ────────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"tweeted_start": [], "tweeted_end": []}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ── Modo: weekend ─────────────────────────────────────────────────────────────
def mode_weekend():
    print("[weekend] Generando posts de tabla...")
    img = BASE / "screenshot_tmp.png"
    for espn_code, league in LEAGUES.items():
        teams = fetch_standings(espn_code)
        text = text_weekend(espn_code, teams)
        if not text:
            print(f"[SKIP] Sin datos para {league['name']}")
            continue
        try:
            screenshot(league["url"], img)
            post(text, img)
        except Exception as e:
            print(f"[ERROR] {league['name']}: {e}")
        time.sleep(5)
    if img.exists():
        img.unlink()

# ── Modo: matches ─────────────────────────────────────────────────────────────
def mode_matches():
    print("[matches] Comprobando partidos en curso...")
    state = load_state()
    img = BASE / "screenshot_tmp.png"
    changed = False

    for espn_code, league in LEAGUES.items():
        matches = fetch_scoreboard(espn_code)
        for m in matches:
            mid = m["id"]

            if m["state"] == "in" and mid not in state["tweeted_start"]:
                print(f"[START] {m['home']} vs {m['away']}")
                try:
                    screenshot(league["url"], img)
                    post(text_match_start(m, espn_code), img)
                    state["tweeted_start"].append(mid)
                    changed = True
                except Exception as e:
                    print(f"[ERROR] {e}")
                time.sleep(5)

            if m["state"] == "post" and mid not in state["tweeted_end"]:
                print(f"[END] {m['home']} {m['score_h']}-{m['score_a']} {m['away']}")
                try:
                    screenshot(league["url"], img)
                    post(text_match_end(m, espn_code), img)
                    state["tweeted_end"].append(mid)
                    changed = True
                except Exception as e:
                    print(f"[ERROR] {e}")
                time.sleep(5)

    if len(state["tweeted_start"]) > 500:
        state["tweeted_start"] = state["tweeted_start"][-200:]
    if len(state["tweeted_end"]) > 500:
        state["tweeted_end"] = state["tweeted_end"][-200:]

    if changed:
        save_state(state)

    if img.exists():
        img.unlink()

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "matches"
    if mode == "weekend":
        mode_weekend()
    elif mode == "matches":
        mode_matches()
    else:
        print(f"Modo desconocido: {mode}")
        sys.exit(1)
