"""URLs limpias (canonical) y rutas de fichero servidas por Caddy try_files.

Caddy resuelve:  /a/b  ->  a/b  |  a/b.html  |  a/b/index.html
Por eso una página "hoja" se escribe como <path>.html y un "hub" como
<path>/index.html; ambas quedan accesibles sin extensión.
"""

from .textutil import slugify


# ── URLs canónicas (sin .html) ──────────────────────────────────────────────

def team_url(league, team_slug):   return f"/equipos/{league}/{team_slug}"
def teams_hub_url(league):         return f"/equipos/{league}"
def jornada_url(league, n):        return f"/jornadas/{league}/{n}"
def jornadas_hub_url(league):      return f"/jornadas/{league}"
def historico_url(league):         return f"/historico/{league}"
def grupo_url(league, letter):     return f"/grupos/{league}/{slugify(letter)}"
def grupos_hub_url(league):        return f"/grupos/{league}"
def datos_url():                   return "/datos"
def datos_league_url(league):      return f"/datos/{league}"


# ── Rutas de fichero (relativas a la raíz del repo) ─────────────────────────

def team_file(league, team_slug):  return f"equipos/{league}/{team_slug}.html"
def teams_hub_file(league):        return f"equipos/{league}/index.html"
def jornada_file(league, n):       return f"jornadas/{league}/{n}.html"
def jornadas_hub_file(league):     return f"jornadas/{league}/index.html"
def historico_file(league):        return f"historico/{league}/index.html"
def grupo_file(league, letter):    return f"grupos/{league}/{slugify(letter)}.html"
def grupos_hub_file(league):       return f"grupos/{league}/index.html"
def datos_file():                  return "datos/index.html"
def datos_league_file(league):     return f"datos/{league}.html"
