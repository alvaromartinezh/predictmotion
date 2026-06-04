# Generador de páginas SEO — PredictMotion

Genera **páginas estáticas indexables** a partir de los datos reales de la
simulación Monte Carlo, sin escribir contenido a mano y **sin IA**: todo el
texto se construye con plantillas (f-strings) rellenadas con variables reales.
Si un dato no existe, la frase no se incluye.

## Qué produce

Por cada liga (Hypermotion, LaLiga, Mundial) y a partir de la API pública de
ESPN:

| URL limpia | Contenido |
|---|---|
| `/equipos/<liga>/<equipo>` | Prob. por zona, evolución (sparkline), delta vs jornada anterior, calendario restante |
| `/equipos/<liga>` | Hub de equipos de la liga |
| `/jornadas/<liga>/<n>` | Probabilidades antes/después y qué equipo movió más la carrera |
| `/jornadas/<liga>` | Índice de jornadas |
| `/grupos/mundial/<X>` | Probabilidades de un grupo (solo Mundial) |
| `/grupos/mundial` | Hub de grupos (solo Mundial) |
| `/historico/<liga>` | Snapshots por fecha |
| `/datos` | Hub global que enlaza todo |

Cada página lleva `<title>`, meta description, canonical, Open Graph,
enlazado interno cruzado y **JSON-LD** (`SportsTeam`, `ItemList`, `Dataset`,
`CollectionPage`). El `sitemap-data.xml` se regenera con todas las URLs.

## La simulación es un port fiel del navegador

El Monte Carlo del dashboard corre en el navegador del visitante. Aquí se porta
a Python (mismo modelo de partido, mismo PRNG `mulberry32`, mismo desempate
pts→DG→GF, mismas zonas y mismo play-off / mismo ajuste por ranking FIFA en el
Mundial). El servidor lo ejecuta y **persiste snapshots**, que es lo que permite
construir histórico y evolución (el navegador no guardaba nada).

## Uso

```bash
python3 -m seo.generate_site                  # genera todo (lo que corre el cron)
python3 -m seo.generate_site --dry-run        # no escribe nada, solo lista
python3 -m seo.generate_site --league laliga  # una sola liga
```

- **Solo stdlib** (urllib). No requiere instalar dependencias.
- Robusto por liga: si una falla (ESPN caído, etc.) se salta y **no borra** lo ya
  generado.
- Salida y snapshots están **gitignored**: viven solo en el servidor, no en git.

## Integración con el cron (servidor)

El auto-deploy hace `git pull` cada 2 min y trae el código de `seo/`. La
generación es un cron aparte (mismo patrón que `fetch_rfef.py`). Añadir en el
crontab del servidor:

```cron
# Páginas SEO — cada 3 horas
0 */3 * * * cd /home/ubuntu/predictmotion && /usr/bin/python3 -m seo.generate_site >> /home/ubuntu/seo_generate.log 2>&1
```

> Ejecutar **siempre desde la raíz del repo** (`cd`) para que el paquete `seo`
> sea importable. Caddy sirve los ficheros generados tal cual (URLs limpias vía
> `try_files`), sin build.

## Sitemaps

- `sitemap.xml` (commiteado) → índice que apunta a:
  - `sitemap-static.xml` (commiteado, páginas fijas)
  - `sitemap-data.xml` (generado por este script en el servidor)

## Añadir una liga regular nueva

Basta con añadir una entrada a `LEAGUES` en `seo/config.py` (slug, `espn_code`,
`p_home`/`p_draw`, bandas de zona y `article`). Ningún otro fichero cambia.
