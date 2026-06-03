"""Renderiza plantillas HTML a PNG usando Playwright (screenshot)."""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
import pytz

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

import config

_TMPL_DIR = Path(__file__).parent / "templates"
_jinja = Environment(loader=FileSystemLoader(str(_TMPL_DIR)), autoescape=True)

_COLORS = [
    "#1a6b4a","#1a4b8a","#8a1a1a","#6b4a1a",
    "#2a5c6e","#5c2a6e","#6e5c2a","#2a6e5c",
]


def _ts() -> str:
    tz = pytz.timezone(config.TIMEZONE)
    return datetime.now(tz).strftime("%d/%m/%Y %H:%M")


def _out_path(name: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return config.OUTPUT_DIR / f"{name}_{ts}.png"


def _add_colors(entries: list[dict]) -> list[dict]:
    return [{**e, "color": _COLORS[i % len(_COLORS)]} for i, e in enumerate(entries)]


def _screenshot(html: str, width: int) -> Path:
    """Guarda html como PNG temporal y devuelve la ruta."""
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    try:
        out = _out_path(Path(tmp).stem)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.goto(f"file:///{tmp}", wait_until="networkidle")
            page.screenshot(path=str(out), full_page=True)
            browser.close()
        return out
    finally:
        os.unlink(tmp)


class ImageRenderer:

    def standings_group(self, group: dict) -> Path:
        """PNG de clasificación de UN grupo."""
        tmpl = _jinja.get_template("standings_group.html")
        html = tmpl.render(
            group_name=group["name"],
            entries=_add_colors(group["entries"]),
            timestamp=_ts(),
        )
        out = _out_path(f"grupo_{group['name']}")
        _render_to_file(html, out, width=640)
        return out

    def all_groups(self, groups: list[dict]) -> Path:
        """PNG con todos los grupos en grid."""
        tmpl = _jinja.get_template("all_groups.html")
        processed = [{"name": g["name"], "entries": g["entries"]} for g in groups]
        html = tmpl.render(groups=processed, timestamp=_ts())
        out = _out_path("all_groups")
        _render_to_file(html, out, width=1200)
        return out

    def best_thirds(self, thirds: list[dict], advancing: int = 8) -> Path:
        """PNG del ranking de mejores terceros."""
        tmpl = _jinja.get_template("best_thirds.html")
        html = tmpl.render(thirds=thirds, advancing=advancing, timestamp=_ts())
        out = _out_path("best_thirds")
        _render_to_file(html, out, width=700)
        return out


def _render_to_file(html: str, out: Path, width: int):
    import tempfile, os
    with tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8", dir=str(config.OUTPUT_DIR)
    ) as f:
        f.write(html)
        tmp = f.name
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.goto(f"file:///{tmp}", wait_until="networkidle")
            page.screenshot(path=str(out), full_page=True)
            browser.close()
    finally:
        os.unlink(tmp)
