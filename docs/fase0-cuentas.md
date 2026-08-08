# Fase 0 — Cimientos técnicos para cuentas de usuario

> Investigación previa al rediseño. Objetivo final: cuentas de usuario,
> seguimiento de equipos/competiciones favoritos y una home personalizada, con
> el backend pensado **como API separada** (no mezclado en el HTML) para que una
> app móvil futura hable con los mismos endpoints. **Restricción dura: coste 0.**

## Decisiones tomadas (2026-08-08)

1. **Verificación del ID token de Google:** directo a **JWKS local pure-stdlib**
   (opción B). No se pasa por el endpoint `tokeninfo`.
2. **Backup:** **ambos** — repo privado de GitHub como primario (versionado) +
   email a Gmail como red de seguridad adicional.
3. **Home personalizada:** **mejora progresiva del selector actual** (reordenar
   por seguidos), no una página "Mi PredictMotion" separada.

---

## Resumen (una línea por punto)

| # | Tema | Decisión |
|---|------|----------|
| 1 | Login | Google Identity Services (botón) → ID token → **verificación local vía JWKS, pure-stdlib** (sin deps, sin `client_secret`) |
| 2 | Almacenamiento | **SQLite** (`sqlite3` stdlib, WAL) en `user_data/` (gitignored) + **backup off-site**: repo privado GitHub (primario) + email (respaldo) |
| 3 | Backend API | **Servicio nuevo** `accounts/` en `:8771`, clon del patrón `live_tracker`, tras Caddy (`/api/auth/*`, `/api/me`, `/api/follows/*`, `/api/account`) |
| 4 | Sesiones | **Token opaco** en SQLite + cookie `HttpOnly; Secure; SameSite=Lax` (revocable, stdlib `secrets`) |
| 5 | Arquitectura | El pipeline ESPN→MC→SEO **no se toca**; se añade una isla con estado, aislada, aditiva y degradable |

Transversal y **no negociable (UE/RGPD)**: `privacy.html` ampliada + endpoint de
borrado de cuenta **antes** de que el login sea público.

---

## 1. LOGIN — "Iniciar sesión con Google"

### Flujo elegido (identidad pura, sin `client_secret`)

1. Se carga el script de **Google Identity Services** (GIS) y se pinta el botón
   oficial con el **Client ID** (público, puede ir en el JS).
2. El usuario se autentica; GIS devuelve **en el navegador** un **ID token** (JWT
   firmado por Google: `sub`, `email`, `name`, `picture`).
3. El frontend hace `POST /api/auth/google` con el token.
4. El backend **verifica la firma**, hace upsert del usuario y crea sesión.

Sin `client_secret`, sin redirect-URI dance, sin intercambio de tokens. Solo el
Client ID + verificación de firma. Encaja con "vanilla HTML/JS, sin build".

### Coste y verificación de Google (confirmado 2026-08)

- **Gratis**, sin coste.
- Con **scopes no sensibles** (`openid`, `email`, `profile`) **no** hace falta el
  proceso de verificación de la app. La verificación (y el aviso "app no
  verificada") solo aplica a scopes sensibles/restringidos, o si se quiere
  nombre+logo en la pantalla de consentimiento (verificación *ligera*, opcional).
- El cap de 100 usuarios es del estado de publicación **"Testing"**; en
  **"In production"** con scopes no sensibles, sin cap.

### Verificación del token — decisión: JWKS local pure-stdlib

Verificar un JWT **RS256** necesita RSA, que la stdlib no expone en una llamada.
Enfoque elegido: **bajar las claves públicas de Google**
(`https://www.googleapis.com/oauth2/v3/certs`), **cachearlas por `kid`** (respetando
el `Cache-Control`/`max-age` de la respuesta), y **verificar PKCS#1 v1.5**
manualmente con `pow(sig, e, n)` + `hashlib` (~60 líneas). Sin dependencias, sin
llamada de red por login, sin el throttling que Google advierte del `tokeninfo`.

Comprobaciones obligatorias del token: firma válida; `iss` ∈
{`accounts.google.com`, `https://accounts.google.com`}; `aud` == Client ID; `exp`
no vencido; `email_verified == true`.

> Alternativas descartadas: `tokeninfo` (Google lo marca "no apto para
> producción"); `google-auth` (rompe "cero dependencias").

---

## 2. ALMACENAMIENTO — SQLite + backup desde el día 1

### Base de datos

**SQLite (`sqlite3`, stdlib)**, un único fichero. Cero servidor extra, cero
coste, cero dependencias; sobra para la escala.

- **Ubicación:** `user_data/predictmotion.db` — carpeta nueva, **gitignored**
  (como `live_data/` y `data/`). El `git pull` del auto-deploy **nunca** la toca.
- **Modo WAL** (`PRAGMA journal_mode=WAL`): lecturas concurrentes + backup en
  caliente.
- **Un solo escritor:** el servicio `accounts` es el único proceso que escribe →
  sin contención.

Esquema inicial:

```
users(id, google_sub UNIQUE, email, name, picture_url, created_at, last_login_at)
sessions(token_hash PK, user_id, created_at, expires_at, user_agent)
favorite_team(user_id PK, espn_team_id, league_slug)   -- uno solo
followed_teams(user_id, espn_team_id, league_slug)     -- N
followed_competitions(user_id, league_slug)            -- N
```

IDs de equipo = **IDs ESPN** (estables). Competiciones = **slugs**.
**Minimización RGPD:** solo `sub`, email, nombre y URL de foto.

### Backup (aprendiendo del incidente del volumen de arranque, 2026-08-04)

Estos datos **no son recalculables desde ESPN** → una copia en el propio servidor
**no basta** (si se va el volumen, se va con él). Regla: **copia off-site**.

Diseño (cron nocturno, sin intervención manual — Principio 2):

1. `sqlite3` `.backup()` (API stdlib) → copia **consistente en caliente** (no
   `cp` del fichero vivo).
2. gzip + cifrado (`gpg`/`age`) — aunque el repo sea privado, contiene **PII**.
3. **Primario:** `git push` a **repo privado dedicado** (deploy key propia,
   **jamás** el repo público) → versionado, restore a cualquier fecha.
4. **Respaldo:** email del dump cifrado a Gmail (reusa `seo/notify.py`).
5. Rotación local de las últimas N copias para restore rápido.
6. **Alerta solo en fallo** (reusa `notify.py`, dedupe por transición).

> Restore probado y documentado desde el día 1: sin restore probado, no hay
> backup.

---

## 3. BACKEND COMO API — servicio nuevo, no mezclar en el HTML

### Servicio nuevo (no extender `live_tracker`)

`live_tracker` es un **proxy/caché sin estado** sobre ESPN; cuentas es
**stateful, con DB, PII, cookies y OAuth**. Mezclarlos acopla superficies muy
distintas (un crash del tracker no debe desloguear a nadie; deploy/seguridad
independientes). Se clona el **precedente exacto**: servicio Python stdlib +
`systemd` + Caddy `reverse_proxy`.

Estructura (espejo de `live_tracker/`):

```
accounts/
  config.py     # ACCOUNTS_ENABLED (flag), PORT=8771, rutas DB/backup
  db.py         # sqlite3 + esquema + WAL (única capa que toca SQL)
  auth.py       # verificación del ID token de Google (JWKS local)   [CP1]
  sessions.py   # crear/validar/revocar sesión (secrets + cookie)     [CP1]
  app.py        # HTTP stdlib — routing /api/*
  __main__.py   # arranque (systemd)
  accounts.service
  deploy.sh
```

Endpoints (JSON, estilo `{ok: bool, ...}` como `live_tracker`):

```
POST   /api/auth/google              # ID token → verifica → sesión → set-cookie
POST   /api/auth/logout              # revoca sesión, borra cookie
GET    /api/me                       # usuario actual (o {ok:false})
GET    /api/follows                  # favorito + equipos + competiciones
PUT    /api/follows/favorite-team
POST   /api/follows/teams/{espnId}
DELETE /api/follows/teams/{espnId}
POST   /api/follows/competitions/{slug}
DELETE /api/follows/competitions/{slug}
DELETE /api/account                  # borrado de cuenta (RGPD)
GET    /api/health
```

Caddy (dentro del `route{}`, junto al `reverse_proxy /api/* localhost:8770`):

```
reverse_proxy /api/auth/*    localhost:8771
reverse_proxy /api/me        localhost:8771
reverse_proxy /api/follows/* localhost:8771
reverse_proxy /api/account   localhost:8771
reverse_proxy /api/live/*    localhost:8770   # ya existe
```

Mismo origen en producción → cookies "just work", sin CORS. Es justo lo que
necesita la **app móvil** futura: la lógica de negocio vive en la API.

---

## 4. SESIONES

Tras verificar el ID token **no** se reutiliza el JWT de Google (caduca ~1h y no
es revocable). Sesión propia: **token opaco** (`secrets.token_urlsafe(32)`) →
fila en `sessions` (se guarda solo el **hash** del token). Cookie:

```
Set-Cookie: pm_session=<token>; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=<30d>
```

- `HttpOnly`: el JS no lee la cookie (mitiga XSS); el frontend sabe si hay login
  vía `GET /api/me`.
- `SameSite=Lax`: suficiente (el login no es POST cross-site).
- Expiración deslizante + **cron de limpieza** de sesiones vencidas.

Descartado: cookie firmada / JWT propio (no revocable; ya tenemos la DB).

---

## 5. IMPACTO EN LA ARQUITECTURA

### Se mantiene intacto

- **Todo el pipeline ESPN → Monte Carlo → SEO → snapshots** (cron 3h, plantillas,
  dashboards estáticos). No se toca.
- El sitio sigue **100% funcional para anónimos**. Las cuentas son **aditivas y
  degradables**: servicio caído o flag off ⇒ el sitio se comporta como hoy.
- **Sin build step.** Frontend de cuentas = JS vanilla con `fetch` a la API
  (como `PMLive`/`PMNews`/`PMFixtures`).
- `data/` sigue recalculable-y-gitignored.

### Cambia (por primera vez)

1. **Estado persistente ligado a personas reales.** La DB es el primer fichero
   cuya pérdida es **irreversible** → backup off-site obligatorio.
2. **PII → RGPD (UE).** Antes de abrir el login: `privacy.html` (qué se guarda,
   base legal = consentimiento, uso de Google como IdP, retención, borrado) +
   endpoint `DELETE /api/account`, y enlace a la política en el login.
3. **Nueva superficie de seguridad:** cookies, OAuth, SQL (consultas
   parametrizadas, `HttpOnly`/`Secure`, verificación estricta del token,
   rate-limit en `/api/auth`).
4. **Un servicio con estado que cuidar en deploy/upgrade:** la DB vive en
   `user_data/` (fuera del repo); ni el `git pull` ni un reinicio la pierden.

### Home personalizada

**Mejora progresiva sobre `index.html`, que sigue estático y cacheable:** al
cargar, el JS llama a `/api/me` + `/api/follows`; con login, reordena/destaca las
competiciones y equipos seguidos; sin login, el selector actual tal cual. SEO y
caché intactos (el HTML no cambia por usuario; personaliza el cliente).

---

## Plan por checkpoints

Cada checkpoint es desplegable, verificable y no rompe lo anterior. El servicio
nace tras un feature flag (`ACCOUNTS_ENABLED`) y **sin UI pública** hasta el final.

- **CP0 — Andamiaje del servicio (a oscuras).** `accounts/` clonando
  `live_tracker`: `config.py` (flag + puerto 8771), `db.py` (SQLite + esquema +
  WAL en `user_data/`, gitignored), `app.py` con `/api/health`, `systemd` + ruta
  Caddy + `deploy.sh`. Flag off / sin UI. *Verificar:* `/api/health` responde; DB
  y tablas se crean; `git pull` no la toca.
- **CP1 — Login Google end-to-end (a oscuras).** Client ID en Google Cloud
  (scopes no sensibles, "In production"). Verificación JWKS local.
  `POST /api/auth/google`, `GET /api/me`, `POST /api/auth/logout`, sesión opaca +
  cookie. Página `/cuenta` mínima de prueba. *Verificar:* login real, cookie set,
  `me` devuelve usuario, logout limpia.
- **CP2 — API de follows + persistencia.** Endpoints favorito/equipos/
  competiciones, validando IDs contra ligas conocidas. *Verificar:* CRUD
  persistido en SQLite.
- **CP3 — Backup + robustez.** Cron nocturno: `.backup()` → gzip+cifrado → push a
  repo privado + email de respaldo + rotación local + alerta de fallo. Cron de
  limpieza de sesiones. **Restore probado y documentado.**
- **CP4 — Legal + apertura controlada.** `privacy.html` (RGPD) +
  `DELETE /api/account` + rate-limit en `/api/auth` + repaso de seguridad. Enlace
  de política en el login. Prerrequisito para hacer el login visible.
- **CP5 — Home personalizada.** Mejora progresiva de `index.html` (reordenar por
  seguidos), botones "seguir" en páginas de equipo/competición, "mi equipo",
  entrada de login en la topbar. Anónimo sin cambios. Flip del flag → público.

## Fuentes

- [Verify the Google ID token on your server side — Google](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token)
- [OAuth App Verification / non-sensitive scopes — Google Cloud Support](https://support.google.com/cloud/answer/13463073?hl=en)
- [OAuth 2.0 Policies — Google](https://developers.google.com/identity/protocols/oauth2/policies)
