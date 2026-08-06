# Presentación de arquitectura — mantenimiento

Deck interactivo que explica cómo funciona PredictMotion, por **capas técnicas**.
Entrada: `/<slug>.html` (ruta no adivinable, `noindex`, protegida con auth básica
en Caddy). Assets: `assets/deck.css`, `assets/deck.js`, `assets/deck-demo.js`.

> **Es una foto fija del sistema tal como funciona HOY**, no un registro de su
> evolución. No narra cambios ("antes X, ahora Y"): describe el estado actual en
> presente, como si siempre hubiera sido así.

## Ancla de sincronización con CLAUDE.md
`CLAUDE.md` está **gitignored** (local, con datos de infra), así que no se puede
diffear por git ni versionar. El ancla es un **snapshot local**: `_claudemd_synced.md`
(en la raíz, gitignored) = copia de `CLAUDE.md` en la última sync. Diffeando contra
él se ve lo que cambió desde entonces.

## Cuándo tocar el deck (filtro diseño vs parche)
Solo cambios que alteran **CÓMO funciona** algo o **POR QUÉ** se diseñó así.

- **SÍ** actualizar: pieza/algoritmo nuevo, cambio de flujo de datos, principio de
  producto, qué competiciones cubre el sistema, contrato entre componentes.
  - *Ej.:* se añade el prior de fuerza → la slide del motor pasa a nombrarlo.
  - *Ej.:* una competición se retira → deja de aparecer (sin decir "se retiró").
- **NO** actualizar: fix de bug, ajuste de un parámetro numérico, parche operativo
  (User-Agent, credenciales, caché), detalle que no cambia el comportamiento
  observable ni el diseño.
  - *Ej.:* redondeo del 1X2, cambio de UA por un 403, bump de versión de assets.

**Prueba rápida:** *"¿alguien que ya entiende el sistema tendría que re-aprender
algo?"* Sí → toca slide. No → ignóralo.

## Procedimiento de sync (manual — NO va en el cron)
No forma parte de `generate_site` ni de ningún cron: es documentación cuya
actualización exige juicio semántico (diseño vs parche) que no se automatiza con
fiabilidad, y si se desfasa **no rompe el sitio**. Se dispara a mano (p. ej.
"actualiza la presentación") o como último paso al cerrar un cambio de arquitectura.

1. `diff _claudemd_synced.md CLAUDE.md` — revisa qué cambió desde la última sync.
2. Por cada bloque, aplica el filtro de arriba. Si pasa, localiza la(s) slide(s)
   por el comentario `<!-- src: CLAUDE.md » … -->` de cada `<section class="slide">`
   y **reescribe en presente** (reemplaza el texto, no lo anexes).
3. Si tocaste `deck.*`, bumpea el `?v=` (como el resto del sitio).
4. Refresca el ancla: `cp CLAUDE.md _claudemd_synced.md`.

## Mapa slide ↔ fuente
Vive en el propio HTML: cada `<section class="slide">` lleva su `<!-- src: … -->`.
Recorrerlos (`grep 'src: CLAUDE.md' <slug>.html`) da el índice completo.
