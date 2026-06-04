"""Esqueleto HTML compartido de las páginas generadas.

Replica el sistema visual del dashboard de PredictMotion (paleta navy+ámbar,
Barlow / Barlow Condensed / Inconsolata, estética "sports data terminal"):
header con logo + badge, tarjetas, tablas con filas teñidas por zona, barra-zona
con glow, avatares de equipo y celdas de probabilidad con número grande + barra
de degradado. Todo el HTML se construye con f-strings; nada de texto a mano.
"""

import html
import json

from .config import SITE

GTM_HEAD = """<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
})(window,document,'script','dataLayer','GTM-NG2T7CM4');</script>"""

GTM_BODY = ('<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-NG2T7CM4"'
            ' height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>')

LOGO = "/media/twitter_profile.png"

# Paleta de fondo para avatares fallback (idéntica al dashboard).
COLOR_PALETTE = [
    '#e11d48', '#7c3aed', '#2563eb', '#0891b2', '#059669', '#ca8a04', '#ea580c',
    '#db2777', '#4f46e5', '#0284c7', '#16a34a', '#d97706', '#dc2626', '#9333ea',
    '#0369a1', '#15803d', '#b45309', '#be185d', '#6d28d9', '#0e7490', '#166534', '#92400e',
]

CSS = """
:root{--bg:#060916;--surface:#0c1124;--surface2:#121a30;--border:#1d2e48;
--accent:#e6a117;--green:#00c97a;--green-dim:rgba(0,201,122,.06);
--blue:#3d8ef5;--blue-dim:rgba(61,142,245,.06);--violet:#9b6bff;--violet-dim:rgba(155,107,255,.06);
--red:#f53050;--red-dim:rgba(245,48,80,.06);--text:#dce8fa;--muted:#4d6285;--radius:8px}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Barlow',sans-serif;background:var(--bg);
background-image:radial-gradient(ellipse 70% 45% at 4% 0%,rgba(230,161,23,.05),transparent 55%),
radial-gradient(ellipse 50% 40% at 96% 100%,rgba(61,142,245,.04),transparent 55%);
color:var(--text);min-height:100vh;padding:0 16px 70px;overflow-x:hidden;line-height:1.5}
a{color:inherit}
.wrap{max-width:940px;margin:0 auto}

/* Header */
.header-wrap{margin:0 -16px 18px;border-top:3px solid var(--accent);
background:linear-gradient(180deg,rgba(10,17,40,.92),transparent);
border-bottom:1px solid var(--border);padding:20px 16px 16px}
.header{max-width:940px;margin:0 auto;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.logo{width:46px;height:46px;flex-shrink:0;display:flex;align-items:center;justify-content:center;
filter:drop-shadow(0 2px 12px rgba(230,161,23,.22))}
.logo img{width:100%;height:100%;object-fit:contain}
.header-text h1{font-family:'Barlow Condensed',sans-serif;font-size:1.7rem;font-weight:800;
text-transform:uppercase;letter-spacing:.05em;line-height:1.05}
.header-text p{font-size:.64rem;color:var(--muted);margin-top:5px;letter-spacing:.12em;text-transform:uppercase}
.header-actions{margin-left:auto;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.badge{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:6px 13px;
font-size:.72rem;color:var(--muted);font-family:'Inconsolata',monospace;white-space:nowrap;letter-spacing:.03em}
.badge strong{color:var(--text)}

/* Nav */
.league-nav{max-width:940px;margin:0 auto 16px;display:flex;gap:6px;flex-wrap:wrap}
.league-btn{padding:8px 20px;border-radius:20px;font-family:'Barlow Condensed',sans-serif;
font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;
border:1px solid var(--border);background:var(--surface2);color:var(--muted);
text-decoration:none;white-space:nowrap;transition:color .15s,border-color .15s,background .15s}
.league-btn.active{background:rgba(230,161,23,.10);border-color:rgba(230,161,23,.45);color:var(--accent)}
.league-btn:not(.active):hover{color:var(--text);border-color:var(--muted)}

/* Breadcrumbs */
.crumbs{font-size:.7rem;color:var(--muted);margin:0 auto 16px;font-family:'Inconsolata',monospace;
display:flex;gap:7px;flex-wrap:wrap;align-items:center;letter-spacing:.02em}
.crumbs a{color:var(--muted);text-decoration:none}
.crumbs a:hover{color:var(--text)}
.crumbs .sep{opacity:.35}

/* Card */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
margin-bottom:16px;overflow:hidden}
.card-pad{padding:18px 20px}
.card h2{font-family:'Barlow Condensed',sans-serif;font-size:1.05rem;font-weight:700;
text-transform:uppercase;letter-spacing:.08em;color:var(--text)}
.section-label{font-family:'Barlow Condensed',sans-serif;font-size:.72rem;font-weight:700;
text-transform:uppercase;letter-spacing:.16em;color:var(--muted);margin:0 0 11px 2px}
.lede{font-size:1.05rem;color:var(--text);line-height:1.55}
.lede strong{color:var(--text);font-weight:700}
.muted{color:var(--muted)}
.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}

/* Hero (perfil de equipo / grupo) */
.hero{display:flex;align-items:center;gap:18px;padding:22px 20px;
background:linear-gradient(180deg,var(--surface2),var(--surface));border-bottom:1px solid var(--border)}
.hero-av{width:64px;height:64px;flex-shrink:0}
.hero-meta{min-width:0}
.hero-meta .h{font-family:'Barlow Condensed',sans-serif;font-size:1.9rem;font-weight:800;
line-height:1.02;text-transform:uppercase;letter-spacing:.02em}
.hero-meta .s{font-size:.78rem;color:var(--muted);margin-top:6px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.poschip{font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:.74rem;letter-spacing:.05em;
text-transform:uppercase;padding:3px 10px;border-radius:20px;border:1px solid var(--border);background:var(--surface)}
.poschip.green{color:var(--green);border-color:rgba(0,201,122,.4)}
.poschip.blue{color:var(--blue);border-color:rgba(61,142,245,.4)}
.poschip.violet{color:var(--violet);border-color:rgba(155,107,255,.4)}
.poschip.red{color:var(--red);border-color:rgba(245,48,80,.4)}
.poschip.gray{color:var(--muted)}

/* Stat cards */
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;padding:18px 20px}
.stat{position:relative;background:var(--surface2);border:1px solid var(--border);border-radius:8px;
padding:15px 16px 17px;overflow:hidden}
.stat .v{font-family:'Barlow Condensed',sans-serif;font-size:2.15rem;font-weight:800;line-height:1}
.stat .l{font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-top:7px}
.stat .u{position:absolute;left:0;bottom:0;height:3px;border-radius:0 2px 0 0}
.stat.green .v{color:var(--green)} .stat.green .u{background:linear-gradient(90deg,#009960,#00c97a)}
.stat.blue .v{color:var(--blue)} .stat.blue .u{background:linear-gradient(90deg,#1f6ec4,#3d8ef5)}
.stat.violet .v{color:var(--violet)} .stat.violet .u{background:linear-gradient(90deg,#6d3fd1,#9b6bff)}
.stat.red .v{color:var(--red)} .stat.red .u{background:linear-gradient(90deg,#c01535,#f53050)}
.stat.accent .v{color:var(--accent)} .stat.accent .u{background:linear-gradient(90deg,#b97d0e,#e6a117)}

/* Tabla estilo dashboard */
table{width:100%;border-collapse:collapse}
thead th{background:var(--surface2);padding:10px 14px;font-family:'Barlow Condensed',sans-serif;
font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);
text-align:left;border-bottom:1px solid var(--border)}
thead th.r{text-align:right}
tbody tr{border-top:1px solid var(--border);transition:background .12s}
tbody tr:hover{background:var(--surface2)}
tbody tr.zone-green{background:var(--green-dim)} tbody tr.zone-green:hover{background:rgba(0,201,122,.1)}
tbody tr.zone-blue{background:var(--blue-dim)} tbody tr.zone-blue:hover{background:rgba(61,142,245,.1)}
tbody tr.zone-violet{background:var(--violet-dim)} tbody tr.zone-violet:hover{background:rgba(155,107,255,.1)}
tbody tr.zone-red{background:var(--red-dim)} tbody tr.zone-red:hover{background:rgba(245,48,80,.1)}
td{padding:10px 14px;vertical-align:middle}
td.r{text-align:right}
.pos{font-family:'Barlow Condensed',sans-serif;font-size:1.05rem;font-weight:700;color:var(--muted);
width:34px;text-align:center}
.zbar{width:3px;height:26px;border-radius:2px}
.zbar.green{background:var(--green);box-shadow:0 0 8px rgba(0,201,122,.38)}
.zbar.blue{background:var(--blue);box-shadow:0 0 8px rgba(61,142,245,.38)}
.zbar.violet{background:var(--violet);box-shadow:0 0 8px rgba(155,107,255,.38)}
.zbar.red{background:var(--red);box-shadow:0 0 8px rgba(245,48,80,.38)}
.zbar.none{background:transparent}
.tcell{display:flex;align-items:center;gap:10px}
.tname{font-size:.9rem;font-weight:600;color:var(--text);text-decoration:none;transition:color .15s}
.tname:hover{color:var(--accent)}
.ptsv{font-family:'Inconsolata',monospace;font-size:.96rem;font-weight:700;text-align:right}

/* Avatar de equipo — el color vivo solo se usa en el fallback de iniciales */
.av{flex-shrink:0;display:flex;align-items:center;justify-content:center;border-radius:6px;overflow:hidden}
.av img{width:100%;height:100%;object-fit:contain}
.av b{display:none;font-family:'Barlow Condensed',sans-serif;font-weight:700;color:#fff;
align-items:center;justify-content:center;width:100%;height:100%;font-size:.7em;letter-spacing:.02em}
.av.fb{background:var(--c,#333)}
.av.fb img{display:none}
.av.fb b{display:flex}

/* Celda de probabilidad */
.prob{min-width:96px}
.prob .ph{font-family:'Barlow Condensed',sans-serif;font-size:1.1rem;font-weight:700;line-height:1;margin-bottom:5px}
.prob .pbg{height:3px;border-radius:2px;background:var(--border);overflow:hidden}
.prob .pf{height:100%;border-radius:2px}
.fill-green{background:linear-gradient(90deg,#009960,#00c97a)}
.fill-blue{background:linear-gradient(90deg,#1f6ec4,#3d8ef5)}
.fill-violet{background:linear-gradient(90deg,#6d3fd1,#9b6bff)}
.fill-red{background:linear-gradient(90deg,#c01535,#f53050)}

/* Deltas / sparkline */
.delta-up{color:var(--green)} .delta-down{color:var(--red)} .delta-eq{color:var(--muted)}
.spark{display:block;margin:4px 0}

/* Hub /datos — rejilla de competiciones */
.comp-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.comp-link{text-decoration:none;color:inherit;display:block}
.comp-link .card{height:100%;margin-bottom:0;transition:border-color .15s}
.comp-link:hover .card{border-color:var(--muted)}
.comp-cta{display:inline-block;margin-top:13px;font-family:'Barlow Condensed',sans-serif;font-weight:700;
font-size:.78rem;letter-spacing:.05em;text-transform:uppercase;color:var(--accent)}
.comp-head{display:flex;align-items:center;gap:13px}
.comp-logo{width:44px;height:44px;flex-shrink:0;display:flex;align-items:center;justify-content:center}
.comp-logo img{width:100%;height:100%;object-fit:contain}
.comp-head .t{font-family:'Barlow Condensed',sans-serif;font-size:1.2rem;font-weight:800;
text-transform:uppercase;letter-spacing:.03em;line-height:1.05}
.comp-head .t small{display:block;font-size:.6rem;color:var(--muted);letter-spacing:.12em;margin-top:4px;font-weight:600}
.comp-meta{font-size:.72rem;color:var(--muted);margin:12px 0 0;font-family:'Inconsolata',monospace}
.hl{display:flex;align-items:center;gap:10px;background:var(--surface2);border:1px solid var(--border);
border-radius:8px;padding:10px 12px;margin:13px 0}
.hl .hl-l{font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;line-height:1.3}
.hl .hl-n{font-weight:600;font-size:.9rem}
.hl .hl-v{margin-left:auto;font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1.35rem;color:var(--green)}

/* Chips de enlaces internos */
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chips a{display:inline-flex;align-items:center;gap:7px;font-size:.82rem;font-weight:500;
text-decoration:none;color:var(--text);background:var(--surface2);border:1px solid var(--border);
border-radius:8px;padding:8px 11px;transition:border-color .15s,color .15s}
.chips a:hover{border-color:var(--muted);color:var(--accent)}
.chips a .av{border-radius:4px}

/* Footer */
footer{max-width:940px;margin:26px auto 0;padding-top:16px;border-top:1px solid var(--border);
font-size:.7rem;color:var(--muted);display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between}
footer a{color:var(--muted);text-decoration:none}
footer a:hover{color:var(--text)}

@media (max-width:600px){
.header-text h1{font-size:1.4rem}.hero-meta .h{font-size:1.5rem}.hero-av{width:52px;height:52px}
thead th,td{padding:8px 9px}.prob{min-width:78px}.stat .v{font-size:1.85rem}.lede{font-size:.98rem}}
"""

# Ligas para la barra de navegación (mismas rutas limpias del sitio).
NAV = [
    ("/", "Liga Hypermotion"),
    ("/laliga", "LaLiga"),
    ("/mundial", "Mundial 2026"),
]


def esc(s):
    return html.escape(str(s), quote=True)


def initials(name):
    parts = [w for w in name.split() if w]
    return "".join(w[0] for w in parts[:2]).upper() or "?"


def avatar(logo, name, color, size=32):
    """Avatar de equipo: logo de ESPN con fallback a iniciales sobre color.

    El fallback usa un onerror inline (no es JS externo) que oculta la img y
    muestra las iniciales — mismo comportamiento que el dashboard.
    """
    style = f"width:{size}px;height:{size}px;font-size:{max(size*0.42,10):.0f}px;--c:{color}"
    img = ""
    if logo:
        img = (f'<img src="{esc(logo)}" alt="{esc(name)}" loading="lazy" '
               f'onerror="this.parentNode.classList.add(\'fb\')">')
    cls = "av" if logo else "av fb"
    return (f'<span class="{cls}" style="{style}">{img}'
            f'<b>{esc(initials(name))}</b></span>')


def prob_cell(value, color):
    """Celda de probabilidad estilo dashboard: número grande + barra de degradado."""
    from .textutil import pct
    txt = pct(value)
    w = min(max(value, 0), 100)
    return (f'<div class="prob"><div class="ph">{txt}</div>'
            f'<div class="pbg"><div class="pf fill-{color}" style="width:{w:.1f}%"></div></div></div>')


def stat_card(value, label, color):
    from .textutil import pct
    w = min(max(value, 0), 100)
    return (f'<div class="stat {color}"><div class="v">{pct(value)}</div>'
            f'<div class="l">{esc(label)}</div><div class="u" style="width:{w:.1f}%"></div></div>')


def sparkline(values, color="#3d8ef5", w=260, h=44):
    """SVG inline de una serie 0..100. Sin JS. '' si <2 puntos."""
    if len([v for v in values if v is not None]) < 2:
        return ""
    n = len(values)
    maxv = max(max(values), 1)
    step = w / (n - 1)
    coords = [f"{i*step:.1f},{h - (v/maxv)*(h-6) - 3:.1f}" for i, v in enumerate(values)]
    poly = " ".join(coords)
    area = f"0,{h} " + poly + f" {w},{h}"
    lx, ly = coords[-1].split(",")
    return (f'<svg class="spark" width="100%" height="{h}" viewBox="0 0 {w} {h}" '
            f'preserveAspectRatio="none" aria-hidden="true">'
            f'<polygon points="{area}" fill="{color}" opacity="0.08"/>'
            f'<polyline fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round" points="{poly}"/>'
            f'<circle cx="{lx}" cy="{ly}" r="3" fill="{color}"/></svg>')


def crumbs(items):
    """items: lista de (label, href|None)."""
    out = []
    for i, (label, href) in enumerate(items):
        out.append(f'<a href="{href}">{esc(label)}</a>' if href else f'<span>{esc(label)}</span>')
        if i < len(items) - 1:
            out.append('<span class="sep">/</span>')
    return '<div class="crumbs">' + "".join(out) + "</div>"


def page(title, description, canonical_path, body, *, heading, logo=None, badge=None,
         json_ld=None, active_nav=None):
    """HTML completo. `heading` = H1 del header; `title` = <title>/meta.

    `logo` = logo de la COMPETICIÓN (nunca el de la web). Se usa en la cabecera,
    og:image y favicon. Si no hay logo, simplemente se omiten.
    """
    ld = ""
    for block in (json_ld or []):
        ld += ('<script type="application/ld+json">'
               + json.dumps(block, ensure_ascii=False) + "</script>\n")

    nav_html = ""
    for href, label in NAV:
        if href == active_nav:
            nav_html += f'<span class="league-btn active">{esc(label)}</span>'
        else:
            nav_html += f'<a class="league-btn" href="{href}">{esc(label)}</a>'

    badge_html = f'<div class="header-actions"><div class="badge">{badge}</div></div>' if badge else ""
    logo_box = f'<div class="logo"><img src="{esc(logo)}" alt="{esc(heading)}"></div>' if logo else ""
    og_image = f'<meta property="og:image" content="{esc(logo)}">' if logo else ""
    icons = (f'<link rel="icon" type="image/png" href="{esc(logo)}">'
             f'<link rel="apple-touch-icon" href="{esc(logo)}">') if logo else ""
    canonical = SITE + canonical_path
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">
<meta name="theme-color" content="#060916">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{canonical}">
{og_image}
<meta property="og:locale" content="es_ES">
<meta property="og:site_name" content="PredictMotion">
<meta name="twitter:card" content="summary">
{icons}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="dns-prefetch" href="https://a.espncdn.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Condensed:wght@400;600;700;800&family=Inconsolata:wght@400;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
{ld}</head>
<body>
{GTM_BODY}
<div class="header-wrap"><div class="header">
{logo_box}
<div class="header-text"><h1>{esc(heading)}</h1>
<p>PredictMotion · Simulación Monte Carlo</p></div>
{badge_html}
</div></div>
<nav class="league-nav">{nav_html}</nav>
<div class="wrap">
{body}
</div>
<footer>
<span>© 2025 PredictMotion · Todos los derechos reservados</span>
<span><a href="/datos">Datos y probabilidades</a> · <a href="/privacy">Privacidad</a></span>
</footer>
</body>
</html>"""
