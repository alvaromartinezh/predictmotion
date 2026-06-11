"""Entrega de mensajes e imágenes por Telegram."""

from __future__ import annotations
import json
from pathlib import Path

import requests

import config


class TelegramNotifier:
    _BASE = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token   = token   or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID

    def _url(self, method: str) -> str:
        return self._BASE.format(token=self.token, method=method)

    def send_text(self, text: str, disable_preview: bool = True,
                  reply_markup: dict | None = None) -> bool:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        r = requests.post(self._url("sendMessage"), json=payload, timeout=15)
        if not r.ok:
            print(f"[Telegram ERROR sendMessage] {r.status_code} {r.text[:200]}")
        return r.ok

    def send_image(self, image_path: str | Path, caption: str = "",
                   reply_markup: dict | None = None) -> bool:
        """Envía una imagen con caption (puede incluir HTML con enlaces) y,
        opcionalmente, un teclado inline (botones)."""
        data = {
            "chat_id":    self.chat_id,
            "caption":    caption,
            "parse_mode": "HTML",
        }
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        with open(image_path, "rb") as f:
            r = requests.post(
                self._url("sendPhoto"),
                data=data,
                files={"photo": f},
                timeout=30,
            )
        if not r.ok:
            print(f"[Telegram ERROR sendPhoto] {r.status_code} {r.text[:200]}")
        return r.ok

    # ── Lectura de pulsaciones de botones (callback queries) ──────────────────

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> list:
        """Sondea updates de Telegram (solo callback_query). Devuelve la lista."""
        params: dict = {"timeout": timeout, "allowed_updates": json.dumps(["callback_query"])}
        if offset is not None:
            params["offset"] = offset
        r = requests.get(self._url("getUpdates"), params=params, timeout=timeout + 15)
        if not r.ok:
            print(f"[Telegram ERROR getUpdates] {r.status_code} {r.text[:200]}")
            return []
        return r.json().get("result", [])

    def answer_callback(self, callback_query_id: str, text: str = "",
                        show_alert: bool = False) -> bool:
        r = requests.post(
            self._url("answerCallbackQuery"),
            json={"callback_query_id": callback_query_id, "text": text,
                  "show_alert": show_alert},
            timeout=15,
        )
        return r.ok

    def finalize_message(self, chat_id, message_id: int, new_text: str,
                         is_photo: bool, keep_markup: bool = False) -> bool:
        """Edita el caption/texto de un mensaje y quita el teclado (salvo keep_markup)."""
        method = "editMessageCaption" if is_photo else "editMessageText"
        key    = "caption" if is_photo else "text"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            key: new_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if not keep_markup:
            payload["reply_markup"] = {"inline_keyboard": []}
        r = requests.post(self._url(method), json=payload, timeout=15)
        if not r.ok:
            print(f"[Telegram ERROR {method}] {r.status_code} {r.text[:200]}")
        return r.ok

    def send_images(self, image_paths: list[str | Path], caption: str = "") -> bool:
        """Envía varias imágenes como álbum (media group). Caption solo en la primera."""
        if not image_paths:
            return True
        if len(image_paths) == 1:
            return self.send_image(image_paths[0], caption)

        media  = []
        files  = {}
        handles = []
        try:
            for i, p in enumerate(image_paths):
                key = f"file{i}"
                fh  = open(p, "rb")
                handles.append(fh)
                files[key] = fh
                item: dict = {"type": "photo", "media": f"attach://{key}"}
                if i == 0 and caption:
                    item["caption"]    = caption
                    item["parse_mode"] = "HTML"
                media.append(item)

            r = requests.post(
                self._url("sendMediaGroup"),
                data={
                    "chat_id": self.chat_id,
                    "media":   json.dumps(media),
                },
                files=files,
                timeout=30,
            )
            if not r.ok:
                print(f"[Telegram ERROR sendMediaGroup] {r.status_code} {r.text[:200]}")
            return r.ok
        finally:
            for fh in handles:
                fh.close()
