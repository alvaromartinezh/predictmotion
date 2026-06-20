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
import i18n
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


def apply_live(groups, live_matches):
    """Ajusta provisionalmente la tabla con los partidos EN JUEGO (estado 'in'),
    igual que el dashboard web: el endpoint de standings de ESPN solo cuenta los
    partidos ya terminados, así que sin esto la imagen de un gol en directo no
    refleja ni el marcador ni las probabilidades del momento. Suma PJ, GF/GC, pts
    y W/D/L según el marcador actual y reordena/re-rankea cada grupo."""
    by_id = {str(t["id"]): t for g in groups for t in g["entries"]}
    for m in live_matches:
        if m["state"] != "in":
            continue
        h = by_id.get(str(m["home_id"]))
        a = by_id.get(str(m["away_id"]))
        if not h or not a:
            continue
        for team, gf, gc in ((h, m["home_score"], m["away_score"]),
                             (a, m["away_score"], m["home_score"])):
            team["gp"] += 1
            team["gf"] += gf
            team["gc"] += gc
            if gf > gc:
                team["pts"] += 3; team["w"] += 1
            elif gf == gc:
                team["pts"] += 1; team["d"] += 1
            else:
                team["l"] += 1
    for g in groups:
        g["entries"].sort(key=lambda t: (-t["pts"], -(t["gf"] - t["gc"]), -t["gf"]))
        for i, t in enumerate(g["entries"]):
            t["rank"] = i + 1


def groups_with_probs(live_matches=None):
    """Trae todos los grupos y les inyecta las probabilidades Monte Carlo
    (pAdv = pasar de ronda, p1st/p2nd/p3rd/pOut). Devuelve (groups, probs).

    Si se pasan `live_matches`, aplica los marcadores en vivo antes de simular
    para que tabla y probabilidades reflejen el estado actual del partido."""
    groups = ds.get_all_groups()
    if live_matches:
        apply_live(groups, live_matches)
    played_pairs, played_results = ds.get_played_results()
    probs  = probabilities.simulate_groups(groups, played_pairs=played_pairs or None,
                                           played_results=played_results or None)
    for g in groups:
        probabilities.enrich(g["entries"], probs)
    return groups, probs


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
            # Nombres de selección traducidos a español (México, Sudáfrica, ...)
            home_es = i18n.translate_team(m["home_name"])
            away_es = i18n.translate_team(m["away_name"])

            # ── KICKOFF ──────────────────────────────────────────────────────
            if m["state"] == "in" and not state.already_notified("kickoff", mid):
                log(f"KICKOFF: {m['home_name']} vs {m['away_name']}")

                if m["is_group"] and m["group"]:
                    groups, _ = groups_with_probs(matches)
                    group = next(
                        (g for g in groups if g["name"].upper() == m["group"].upper()),
                        None,
                    )
                    imgs  = [renderer.standings_group(group)] if group else []
                    text  = generate_text("kickoff", {
                        "grupo":     m["group"],
                        "local":     home_es,
                        "visitante": away_es,
                    })
                else:
                    imgs = []
                    text = generate_text("knockout_kickoff", {
                        "local":     home_es,
                        "visitante": away_es,
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
                    # Equipo que marca (por el lado del marcador que sube), traducido
                    scorer_team = home_es if m["home_score"] > prev_h else away_es

                    # Goleador y descripción de la jugada desde el endpoint summary.
                    # Se separan en campos distintos (antes se mezclaba todo el relato
                    # en inglés dentro de {equipo}); se traducen a español.
                    clock_raw = m["clock"].replace("'", "").strip()
                    goleador = ""
                    jugada   = ""
                    events = ds.get_match_events(mid)
                    for ev in reversed(events):
                        t = ev["type"].lower()
                        if "goal" in t or "gol" in t:
                            goleador = i18n.parse_scorer(ev["text"])
                            jugada   = i18n.translate_play(ev["text"])
                            if ev["team"]:
                                scorer_team = i18n.translate_team(ev["team"])
                            break

                    if not state.already_notified("gol", mid, score_str):
                        log(f"GOL: {goleador or scorer_team} {score_str} min {m['clock']}")

                        gol_ph = {
                            "equipo":    scorer_team,
                            "local":     home_es,
                            "visitante": away_es,
                            "score_h":   m["home_score"],
                            "score_a":   m["away_score"],
                            "marcador":  score_str,
                            "minuto":    clock_raw,
                            "goleador":  goleador,
                            "jugada":    jugada,
                        }

                        if m["is_group"] and m["group"]:
                            groups, _ = groups_with_probs(matches)
                            group = next(
                                (g for g in groups if g["name"].upper() == m["group"].upper()),
                                None,
                            )
                            imgs  = [renderer.standings_group(group)] if group else []
                            text  = generate_text("gol", {"grupo": m["group"], **gol_ph})
                        else:
                            imgs = []
                            text = generate_text("knockout_gol", gol_ph)

                        deliver(imgs, text)
                        if not DRY_RUN:
                            state.mark_notified("gol", mid, score_str)

                if not DRY_RUN:
                    state.update_score(mid, m["home_score"], m["away_score"])

            # ── RESULTADO FINAL (grupos y eliminatoria) ───────────────────────
            if (m["state"] == "post"
                    and not state.already_notified("result", mid)):
                score_str = f"{m['home_score']}-{m['away_score']}"
                log(f"RESULT: {m['home_name']} {score_str} {m['away_name']}")
                res_ph = {
                    "local":     home_es,
                    "visitante": away_es,
                    "score_h":   m["home_score"],
                    "score_a":   m["away_score"],
                    "marcador":  score_str,
                }

                if m["is_group"] and m["group"]:
                    groups, _ = groups_with_probs()
                    group = next(
                        (g for g in groups if g["name"].upper() == m["group"].upper()),
                        None,
                    )
                    imgs = [renderer.standings_group(group)] if group else []
                    text = generate_text("result", {"grupo": m["group"], **res_ph})
                else:
                    imgs = []
                    text = generate_text("knockout_result", res_ph)

                deliver(imgs, text)
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
            "equipo":    i18n.translate_team(home["name"]),
            "local":     i18n.translate_team(home["name"]),
            "visitante": i18n.translate_team(away["name"]),
            "score_h":   1,
            "score_a":   0,
            "marcador":  "1-0",
            "minuto":    "34",
            "goleador":  "Lamine Yamal",
            "jugada":    "con la derecha desde el área",
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
