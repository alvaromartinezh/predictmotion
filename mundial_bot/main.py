#!/usr/bin/env python3
"""
PredictMotion Mundial Bot — Asistente semi-automático de publicación en X.

Flujo:
  1. Detecta eventos (kickoff, gol, resultados) y los resúmenes diarios.
  2. Genera imagen PNG (estética PredictMotion) y texto con variante aleatoria.
  3. Envía por Telegram: imagen + texto + enlace de redacción de X.
  4. Tú abres el enlace, adjuntas la imagen a mano y publicas.

Nota sobre el enlace X: https://x.com/intent/tweet?text=...
  El intent pre-rellena el texto pero NO adjunta imagen automáticamente.
  La imagen te llega por Telegram; adjúntala tú antes de publicar.

Uso:
  python main.py                  # modo normal (scheduler en bucle)
  python main.py --dry-run        # simula sin enviar por Telegram
  python main.py --test-morning   # dispara resumen matutino y sale
  python main.py --test-evening   # dispara resumen vespertino y sale
  python main.py --test-live      # un tick de partidos en vivo y sale
"""

from __future__ import annotations
import argparse
import sys
from datetime import datetime
from pathlib import Path

import pytz

import config
import state
from datasource import DataSource
from image_renderer import ImageRenderer
from notifier import TelegramNotifier
from scheduler import build_scheduler
from text_generator import generate_text, build_tweet_intent

# ── Globals ───────────────────────────────────────────────────────────────────
DRY_RUN  = False
ds       = DataSource(config.ESPN_CODE)
renderer = ImageRenderer()
notifier = TelegramNotifier()


def log(msg: str):
    tz = pytz.timezone(config.TIMEZONE)
    ts = datetime.now(tz).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ── Entrega ───────────────────────────────────────────────────────────────────

def deliver(images: list[Path], text: str):
    """Envía imagen(es) + texto + intent link de X.
    En --dry-run imprime en consola sin enviar."""
    intent   = build_tweet_intent(text)
    full_msg = f"{text}\n\n<a href='{intent}'>✍️ Publicar en X →</a>"

    if DRY_RUN:
        log(f"[DRY-RUN] {'='*50}")
        log(f"[DRY-RUN] Texto:\n{text}")
        log(f"[DRY-RUN] Intent: {intent}")
        if images:
            log(f"[DRY-RUN] Imágenes: {[str(p) for p in images]}")
        return

    try:
        if images:
            ok = notifier.send_images(images, caption=full_msg)
        else:
            ok = notifier.send_text(full_msg)
        if ok:
            log(f"[Telegram OK] {text[:60].strip()!r}")
    except Exception as e:
        log(f"[Telegram ERROR] {e}")


# ── Live tick ─────────────────────────────────────────────────────────────────

def on_live_tick():
    try:
        matches = ds.get_live_matches()
        if not matches:
            return

        for m in matches:
            mid = m["id"]

            # ── KICKOFF ──────────────────────────────────────────────────────
            if m["state"] == "in" and not state.already_notified("kickoff", mid):
                log(f"KICKOFF: {m['home_name']} vs {m['away_name']}")

                if m["is_group"] and m["group"]:
                    group = ds.get_group_standings(m["group"])
                    imgs  = [renderer.standings_group(group)] if group else []
                    text  = generate_text("kickoff", {
                        "grupo":     m["group"],
                        "local":     m["home_name"],
                        "visitante": m["away_name"],
                    })
                else:
                    imgs = []
                    text = generate_text("knockout_kickoff", {
                        "local":     m["home_name"],
                        "visitante": m["away_name"],
                    })

                deliver(imgs, text)
                if not DRY_RUN:
                    state.mark_notified("kickoff", mid)
                    state.update_score(mid, m["home_score"], m["away_score"])

            # ── GOL — detecta cambio de marcador ─────────────────────────────
            if m["state"] == "in":
                last = state.get_last_score(mid)
                cur  = (m["home_score"], m["away_score"])

                if last is not None and cur != last:
                    prev_h, prev_a = last
                    score_str = f"{m['home_score']}-{m['away_score']}"
                    scorer_team = m["home_name"] if m["home_score"] > prev_h else m["away_name"]

                    # Intenta obtener nombre del goleador desde el endpoint de summary
                    clock_raw = m["clock"].replace("'", "").strip()
                    events = ds.get_match_events(mid)
                    for ev in reversed(events):
                        t = ev["type"].lower()
                        if "goal" in t or "gol" in t:
                            if ev["text"]:
                                scorer_team = ev["text"]
                            break

                    if not state.already_notified("gol", mid, score_str):
                        log(f"GOL: {scorer_team} {score_str} min {m['clock']}")

                        if m["is_group"] and m["group"]:
                            group = ds.get_group_standings(m["group"])
                            imgs  = [renderer.standings_group(group)] if group else []
                            text  = generate_text("gol", {
                                "grupo":     m["group"],
                                "equipo":    scorer_team,
                                "local":     m["home_name"],
                                "visitante": m["away_name"],
                                "score_h":   m["home_score"],
                                "score_a":   m["away_score"],
                                "marcador":  score_str,
                                "minuto":    clock_raw,
                            })
                        else:
                            imgs = []
                            text = generate_text("knockout_gol", {
                                "equipo":    scorer_team,
                                "local":     m["home_name"],
                                "visitante": m["away_name"],
                                "score_h":   m["home_score"],
                                "score_a":   m["away_score"],
                                "marcador":  score_str,
                                "minuto":    clock_raw,
                            })

                        deliver(imgs, text)
                        if not DRY_RUN:
                            state.mark_notified("gol", mid, score_str)

                if not DRY_RUN:
                    state.update_score(mid, m["home_score"], m["away_score"])

            # ── RESULTADO FINAL (fase eliminatoria) ───────────────────────────
            if (m["state"] == "post" and not m["is_group"]
                    and not state.already_notified("result", mid)):
                score_str = f"{m['home_score']}-{m['away_score']}"
                log(f"RESULT: {m['home_name']} {score_str} {m['away_name']}")
                text = generate_text("knockout_result", {
                    "local":     m["home_name"],
                    "visitante": m["away_name"],
                    "score_h":   m["home_score"],
                    "score_a":   m["away_score"],
                    "marcador":  score_str,
                })
                deliver([], text)
                if not DRY_RUN:
                    state.mark_notified("result", mid)

    except Exception as e:
        log(f"[ERROR on_live_tick] {e}")


# ── Resúmenes diarios ─────────────────────────────────────────────────────────

def on_morning_window():
    try:
        if not DRY_RUN and state.already_sent_today("morning"):
            return
        log("Generando resumen matutino...")
        groups = ds.get_all_groups()
        thirds = ds.get_best_third_placed()
        advancing = max(0, 32 - len(groups) * 2)

        img_all = renderer.all_groups(groups)
        img_3rd = renderer.best_thirds(thirds, advancing=advancing)

        deliver([img_all], generate_text("morning_groups", {}))
        deliver([img_3rd], generate_text("morning_thirds", {}))
        if not DRY_RUN:
            state.mark_sent_today("morning")
    except Exception as e:
        log(f"[ERROR morning] {e}")


def on_evening_window():
    try:
        if not DRY_RUN and state.already_sent_today("evening"):
            return
        log("Generando resumen vespertino...")
        groups = ds.get_all_groups()
        thirds = ds.get_best_third_placed()
        advancing = max(0, 32 - len(groups) * 2)

        img_all = renderer.all_groups(groups)
        img_3rd = renderer.best_thirds(thirds, advancing=advancing)

        deliver([img_all], generate_text("evening_groups", {}))
        deliver([img_3rd], generate_text("evening_thirds", {}))
        if not DRY_RUN:
            state.mark_sent_today("evening")
    except Exception as e:
        log(f"[ERROR evening] {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    global DRY_RUN

    parser = argparse.ArgumentParser(description="PredictMotion Mundial Bot")
    parser.add_argument("--dry-run",      action="store_true", help="Simula sin enviar por Telegram")
    parser.add_argument("--test-morning", action="store_true", help="Dispara resumen matutino y sale")
    parser.add_argument("--test-evening", action="store_true", help="Dispara resumen vespertino y sale")
    parser.add_argument("--test-live",    action="store_true", help="Un tick de partidos en vivo y sale")
    args = parser.parse_args()

    DRY_RUN = args.dry_run
    state.init_db()
    log(f"Bot iniciado {'· DRY-RUN (no se envía nada)' if DRY_RUN else ''}")

    if args.test_morning:
        on_morning_window()
        return
    if args.test_evening:
        on_evening_window()
        return
    if args.test_live:
        on_live_tick()
        return

    sched = build_scheduler(on_live_tick, on_morning_window, on_evening_window)
    log(f"Scheduler activo · poll={config.POLL_INTERVAL}s · "
        f"mañana={config.MORNING_HOUR_START}-{config.MORNING_HOUR_END}h · "
        f"tarde={config.EVENING_HOUR_START}-{config.EVENING_HOUR_END}h")
    log("Ctrl+C para parar.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log("Bot detenido.")


if __name__ == "__main__":
    main()
