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

    def send_text(self, text: str, disable_preview: bool = True) -> bool:
        r = requests.post(
            self._url("sendMessage"),
            json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_preview,
            },
            timeout=15,
        )
        if not r.ok:
            print(f"[Telegram ERROR sendMessage] {r.status_code} {r.text[:200]}")
        return r.ok

    def send_image(self, image_path: str | Path, caption: str = "") -> bool:
        """Envía una imagen con caption (puede incluir HTML con enlaces)."""
        with open(image_path, "rb") as f:
            r = requests.post(
                self._url("sendPhoto"),
                data={
                    "chat_id":    self.chat_id,
                    "caption":    caption,
                    "parse_mode": "HTML",
                },
                files={"photo": f},
                timeout=30,
            )
        if not r.ok:
            print(f"[Telegram ERROR sendPhoto] {r.status_code} {r.text[:200]}")
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
