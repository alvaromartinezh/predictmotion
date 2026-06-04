"""Genera sitemap-data.xml (gitignored) con todas las URLs generadas.

El sitemap.xml commiteado es un índice que apunta a:
  - sitemap-static.xml  (páginas fijas, commiteado)
  - sitemap-data.xml    (generado aquí en el servidor)
"""

from xml.sax.saxutils import escape

from .config import SITE


def write_data_sitemap(root, urls):
    """urls: lista de (path, lastmod). Escribe <root>/sitemap-data.xml."""
    seen = {}
    for path, lastmod in urls:
        seen[path] = lastmod  # dedup, último gana
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path in sorted(seen):
        loc = escape(SITE + path)
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        if seen[path]:
            lines.append(f"    <lastmod>{escape(seen[path])}</lastmod>")
        lines.append("    <changefreq>daily</changefreq>")
        lines.append("  </url>")
    lines.append("</urlset>")
    (root / "sitemap-data.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")
