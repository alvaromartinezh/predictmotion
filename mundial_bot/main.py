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
import probabilities
import x_publisher
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


def groups_with_probs():
    """Trae todos los grupos y les inyecta las probabilidades Monte Carlo
    (pAdv = pasar de ronda, p1st/p2nd/p3rd/pOut). Devuelve (groups, probs)."""
    groups = ds.get_all_groups()
    probs  = probabilities.simulate_groups(groups)
    for g in groups:
        probabilities.enrich(g["entries"], probs)
    return groups, probs


# ── Entrega ───────────────────────────────────────────────────────────────────

def deliver(images: list[Path], text: str):
    """Envía imagen(es) + texto a Telegram.

    - Si la API de X está configurada: añade un botón "Publicar en X" que, al
      pulsarlo, publica el texto + la foto directamente (sin descargar nada).
    - Si no: cae al flujo antiguo (enlace intent para pre-rellenar el texto;
      la foto se adjunta a mano).
    En --dry-run imprime en consola sin enviar."""
    use_button = x_publisher.is_enabled()

    if use_button:
        image_path = str(images[0]) if images else None
        caption = text
        markup  = None  # se rellena tras crear el pending (necesita su id)
    else:
        intent  = build_tweet_intent(text)
        caption = f"{text}\n\n<a href='{intent}'>✍️ Publicar en X →</a>"
        markup  = None

    if DRY_RUN:
        log(f"[DRY-RUN] {'='*50}")
        log(f"[DRY-RUN] Texto:\n{text}")
        log(f"[DRY-RUN] Botón X: {'sí' if use_button else 'no (intent link)'}")
        if images:
            log(f"[DRY-RUN] Imágenes: {[str(p) for p in images]}")
        return

    try:
        if use_button and len(images) <= 1:
            pid    = state.add_pending_post(text, image_path)
            markup = {"inline_keyboard": [[
                {"text": "📣 Publicar en X", "callback_data": f"pub:{pid}"}
            ]]}

        if images and len(images) == 1:
            ok = notifier.send_image(images[0], caption=caption, reply_markup=markup)
        elif images:
            # Álbum (varias imágenes): Telegram no admite botón; usa intent link
            ok = notifier.send_images(images, caption=caption)
        else:
            ok = notifier.send_text(caption, reply_markup=markup)

        if ok:
            log(f"[Telegram OK] {text[:60].strip()!r}")
    except Exception as e:
        log(f"[Telegram ERROR] {e}")


# ── Botón "Publicar en X" (callback queries de Telegram) ──────────────────────

def poll_telegram_updates():
    """Sondea Telegram por pulsaciones del botón 'Publicar en X' y las procesa."""
    try:
        raw    = state.get_meta("tg_offset")
        offset = int(raw) + 1 if raw else None
        for u in notifier.get_updates(offset=offset, timeout=0):
            state.set_meta("tg_offset", str(u["update_id"]))
            cq = u.get("callback_query")
            if cq and (cq.get("data") or "").startswith("pub:"):
                _handle_publish_callback(cq)
    except Exception as e:
        log(f"[ERROR tg-updates] {e}")


def _handle_publish_callback(cq: dict):
    pid_str = cq["data"].split(":", 1)[1]
    msg      = cq.get("message") or {}
    chat_id  = msg.get("chat", {}).get("id")
    msg_id   = msg.get("message_id")
    is_photo = "photo" in msg
    cqid     = cq["id"]

    try:
        post = state.get_pending_post(int(pid_str))
    except ValueError:
        post = None

    if not post:
        notifier.answer_callback(cqid, "No encuentro ese mensaje.")
        return
    if post["status"] == "published":
        notifier.answer_callback(cqid, "Ya estaba publicado ✅")
        return

    notifier.answer_callback(cqid, "Publicando en X…")
    ok, res = x_publisher.publish(post["text"], post["image_path"] or None)

    if ok:
        state.set_pending_status(post["id"], "published")
        log(f"[X OK] {res}")
        notifier.finalize_message(
            chat_id, msg_id,
            f"{post['text']}\n\n✅ <b>Publicado en X</b> · <a href='{res}'>ver tweet</a>",
            is_photo=is_photo,
        )
    else:
        state.set_pending_status(post["id"], "failed")
        log(f"[X ERROR] {res}")
        notifier.answer_callback(cqid, "Error al publicar (ver logs)", show_alert=True)
        notifier.finalize_message(
            chat_id, msg_id,
            f"{post['text']}\n\n⚠️ <b>Error al publicar:</b> {res[:150]}",
            is_photo=is_photo, keep_markup=True,
        )


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
                    groups, _ = groups_with_probs()
                    group = next(
                        (g for g in groups if g["name"].upper() == m["group"].upper()),
                        None,
                    )
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
                            groups, _ = groups_with_probs()
                            group = next(
                                (g for g in groups if g["name"].upper() == m["group"].upper()),
                                None,
                            )
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
        groups, probs = groups_with_probs()
        thirds = ds.get_best_third_placed()
        probabilities.enrich(thirds, probs)
        advancing = max(0, 32 - len(groups) * 2)

        img_all = renderer.all_groups(groups)
        img_3rd = renderer.best_thirds(thirds, advancing=advancing)

        deliver([img_all], generate_text("morning_groups", {}))
        deliver([img_3rd], generate_text("morning_thirds", {}))
        if not DRY_RUN:
            state.mark_sent_today("morning")
    except Exception as e:
        log(f"[ERROR morning] {e}")


def on_test_goal():
    """Manda una imagen de ejemplo de 'gol de grupo' (primer grupo disponible)
    con tabla y probabilidades, tal como llegaría en un gol real."""
    try:
        log("Generando GOL de prueba...")
        groups, _ = groups_with_probs()
        group = next((g for g in groups if len(g["entries"]) >= 2), None)
        if not group:
            log("No hay grupos disponibles para la prueba.")
            return
        home, away = group["entries"][0], group["entries"][1]
        img  = renderer.standings_group(group)
        text = generate_text("gol", {
            "grupo":     group["name"],
            "equipo":    home["name"],
            "local":     home["name"],
            "visitante": away["name"],
            "score_h":   1,
            "score_a":   0,
            "marcador":  "1-0",
            "minuto":    "34",
        })
        deliver([img], "🧪 PRUEBA · " + text)
    except Exception as e:
        log(f"[ERROR test-goal] {e}")


def on_evening_window():
    try:
        if not DRY_RUN and state.already_sent_today("evening"):
            return
        log("Generando resumen vespertino...")
        groups, probs = groups_with_probs()
        thirds = ds.get_best_third_placed()
        probabilities.enrich(thirds, probs)
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
    parser.add_argument("--test-goal",    action="store_true", help="Manda una imagen de gol de ejemplo y sale")
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
    if args.test_goal:
        on_test_goal()
        return

    tg_updates = poll_telegram_updates if config.X_ENABLED else None
    sched = build_scheduler(on_live_tick, on_morning_window, on_evening_window, tg_updates)
    log(f"Scheduler activo · poll={config.POLL_INTERVAL}s · "
        f"mañana={config.MORNING_HOUR_START}-{config.MORNING_HOUR_END}h · "
        f"tarde={config.EVENING_HOUR_START}-{config.EVENING_HOUR_END}h · "
        f"X={'ON (botón Publicar)' if config.X_ENABLED else 'OFF (intent link)'}")
    log("Ctrl+C para parar.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log("Bot detenido.")


if __name__ == "__main__":
    main()
