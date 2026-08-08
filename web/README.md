# web/ — the download portal

A small FastAPI app where the friends sign in **with their WoW account** and get the
client, the patches and the tools. It shares no password store with anything: it
recomputes the SRP6 verifier from `acore_auth.account` and compares it to the one the
game server already wrote there.

```
browser ──► nginx :80 ──► portal :8000 ──► MySQL (SELECT only)
                 ▲              │
                 └── X-Accel-Redirect ──► /srv/wow/dist/<file>   sendfile(2), 17 GB
```

---

## 1. What the orchestrator has to do

Five things. Nothing else in the repo has to change.

### 1.1 Put the artefacts somewhere and write a manifest

```
/srv/wow/dist/
    wow335-release-20260808-1553.zip          the client pack
    wow335-release-20260808-1553.zip.sha256   (optional, reused if present)
    patch-Z.MPQ                               the DK client patch
    wow335-addons-20260808.zip                the addon pack
    wow335-gmtools-20260808.zip               AzerothAdmin + ItemBrowser
    manifest.json                             ← the portal reads only this
```

The portal never guesses a filename. Either the packaging script writes
`manifest.json` (schema: `web/manifest.example.json`), or use the reference writer:

```sh
/srv/wow/wowserver/web/tools/build-manifest.py --dist /srv/wow/dist
```

It globs the patterns in `web/artifacts.json`, takes the newest match, reuses any
`<file>.sha256` sidecar that is not older than the file, and writes `manifest.json`
atomically. `--check` prints without writing. Re-run it after every re-cut; the portal
notices the new mtime and reloads with no restart.

**Permissions.** The portal runs as uid `10001` and nginx as `nginx`, both reading
`/srv/wow/dist` through a read-only bind mount. Simplest correct thing:

```sh
chmod 755 /srv/wow/dist && chmod 644 /srv/wow/dist/*
```

### 1.2 Create the read-only MySQL user

`web/sql/grant-webapp.sql` is the statement. It must run **after** worldserver's first
boot, because worldserver is what creates `acore_auth` (see the note at the bottom of
`deploy/docker-compose.yml`). Until then the portal answers 503 with a "still starting
up" page, which is the correct thing for it to say.

```sh
set -a; . /srv/wow/wowserver/deploy/.env; set +a
sed "s/__PORTAL_DB_PASSWORD__/$PORTAL_DB_PASSWORD/" /srv/wow/wowserver/web/sql/grant-webapp.sql \
| docker compose -f /srv/wow/wowserver/deploy/docker-compose.yml exec -T mysql \
    mysql --defaults-extra-file=/etc/mysql/backup.cnf
```

The password goes in on **stdin**, never in argv — container processes show up in `ps`
on the host, which is the same reason `deploy/mysql-backup.cnf` exists.

Verify:

```sh
docker compose -f deploy/docker-compose.yml exec -T mysql \
  mysql --defaults-extra-file=/etc/mysql/backup.cnf \
  -e "SHOW GRANTS FOR 'acore_web'@'%'"
```

Expected, and nothing else:

```
GRANT USAGE ON *.* TO `acore_web`@`%`
GRANT SELECT ON `acore_auth`.* TO `acore_web`@`%`
GRANT SELECT ON `acore_characters`.* TO `acore_web`@`%`
```

### 1.3 Add two keys to `deploy/.env`

```sh
# The portal's cookie-signing secret. No default exists; the app refuses to start
# without it and refuses anything shorter than 32 characters.
#   LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 48; echo
PORTAL_SECRET_KEY=

# The password for the read-only MySQL user created in 1.2. Same generation rule as
# every other password in this file — [A-Za-z0-9] only.
PORTAL_DB_PASSWORD=
```

Both belong in `.env.example` too, with the comments above. Rotating
`PORTAL_SECRET_KEY` signs everybody out; nothing else breaks.

### 1.4 Add the two Compose services

Append to `deploy/docker-compose.yml`. Paths are relative to `deploy/`, matching how the
file already mounts `../conf`.

```yaml
  web:
    # Built on the box. The repo checkout is already here (the compose file bind-mounts
    # ../conf from it), the image is ~180 MB of prebuilt wheels, and a CX33 builds it in
    # under a minute. If it ever gets a GHCR workflow, swap this for a pinned
    # image: ghcr.io/${GHCR_OWNER}/wowserver-web:${WEB_IMAGE_TAG} the way the game
    # services are pinned.
    build: ../web
    restart: unless-stopped

    depends_on:
      mysql:
        condition: service_healthy
      # NOT worldserver. The portal is useful during the 90-minute first boot: it
      # serves the client download, which is exactly what people should be doing while
      # the world imports. Its DB pages answer 503 until the schema and the GRANT
      # exist, and say so.

    environment:
      PORTAL_SECRET_KEY:   ${PORTAL_SECRET_KEY:?set PORTAL_SECRET_KEY in deploy/.env}
      PORTAL_DB_PASSWORD:  ${PORTAL_DB_PASSWORD:?set PORTAL_DB_PASSWORD in deploy/.env}
      PORTAL_REALMLIST:    ${PORTAL_REALMLIST:?set PORTAL_REALMLIST in deploy/.env}
      PORTAL_SERVER_NAME:  ${PORTAL_SERVER_NAME:-wowserver}
      PORTAL_DB_HOST:      mysql
      PORTAL_DOWNLOAD_ROOT: /srv/wow/dist
      PORTAL_DOWNLOAD_MODE: xaccel
      # PORTAL_TLS: "1"    # only once something terminates HTTPS in front

    volumes:
      # Read-only, and it only needs to stat() the files — nginx is what reads them.
      - /srv/wow/dist:/srv/wow/dist:ro

    # The portal writes no files at all: no uploads, no cache, sessions in signed
    # cookies. Read-only root removes a whole class of "how did that get there".
    read_only: true
    tmpfs:
      - /tmp

    # No `ports:`. Nothing reaches it except nginx, over the wow network.
    networks: [wow]

  nginx:
    image: nginx:1.29-alpine
    restart: unless-stopped
    depends_on: [web]
    ports:
      # THE ONLY THING THE PORTAL PUBLISHES. 3724 and 8085 are the game's and are
      # published by the game services; this is port 80 and nothing else.
      - "80:80"
    volumes:
      - ../web/nginx/portal.conf:/etc/nginx/conf.d/default.conf:ro
      - ../web/nginx/portal-proxy.inc:/etc/nginx/conf.d/portal-proxy.inc:ro
      # The archives. nginx is the process that actually sends them.
      - /srv/wow/dist:/srv/wow/dist:ro
    networks: [wow]
```

`nginx:1.29-alpine` should be pinned by digest before this ships, the same way `mysql`
is in the same file:

```sh
docker buildx imagetools inspect nginx:1.29-alpine | head -3   # take the Digest:
```

### 1.5 Open port 80

`3724` and `8085` are already going to be open. Add `80/tcp`. Nothing else the portal
needs is reachable from outside — the app has no published port of its own.

---

## 2. Environment variables

Required — the app raises at startup and the container never becomes healthy:

| Variable | Meaning |
|---|---|
| `PORTAL_SECRET_KEY` | Signs session and CSRF cookies. ≥ 32 chars, no default. |
| `PORTAL_DB_PASSWORD` | Password for the read-only MySQL user. |
| `PORTAL_REALMLIST` | The address friends type: `167.233.128.19`. Display copy only. |

Optional, with the defaults that are right for this deploy:

| Variable | Default | Notes |
|---|---|---|
| `PORTAL_SERVER_NAME` | `wowserver` | Shown in the header and the tab title. |
| `PORTAL_DB_HOST` / `_PORT` | `mysql` / `3306` | |
| `PORTAL_DB_USER` | `acore_web` | Must match `web/sql/grant-webapp.sql`. |
| `PORTAL_DB_AUTH` / `_CHARACTERS` | `acore_auth` / `acore_characters` | |
| `PORTAL_DOWNLOAD_ROOT` | `/srv/wow/dist` | |
| `PORTAL_MANIFEST` | `<root>/manifest.json` | |
| `PORTAL_DOWNLOAD_MODE` | `xaccel` | `direct` streams through Python instead. |
| `PORTAL_XACCEL_PREFIX` | `/_dist/` | Must match the `internal` location in the nginx config. |
| `PORTAL_TLS` | `0` | `1` adds `Secure` to cookies and sends HSTS. Only under real TLS. |
| `PORTAL_SESSION_MAX_AGE` | `1209600` | 14 days. |
| `PORTAL_TRUSTED_PROXIES` | loopback + RFC1918 | Whose `X-Forwarded-For` to believe. |
| `PORTAL_LOGIN_WINDOW` | `900` | Rate-limit window, seconds. |
| `PORTAL_LOGIN_MAX_PER_IP` | `20` | Failed attempts per IP per window. |
| `PORTAL_LOGIN_MAX_PER_USER` | `8` | Failed attempts per username per window. |

---

## 3. Routes

| Method | Path | Auth | What it does |
|---|---|---|---|
| GET | `/` | — | 303 to `/downloads` |
| GET | `/login` | — | The sign-in page |
| POST | `/login` | — | Verifies the SRP6 verifier, issues the session cookie |
| POST | `/logout` | session | Clears it (CSRF-checked) |
| GET | `/downloads` | session | The manifest, plus the "how to connect" panel |
| GET | `/account` | session | Account facts, character roster, realm check (GM only) |
| GET, HEAD | `/download/{id}` | session | The artefact. `X-Accel-Redirect`, or ranged stream |
| GET | `/download/{id}/sha256` | session | `<hex>  <filename>`, for `sha256sum -c` |
| GET | `/healthz` | — | Liveness. No DB. The container healthcheck |
| GET | `/readyz` | — | DB reachable + artefact count. For a human |

Unauthenticated requests to a signed-in route get `303 → /login?next=<path>`, so a deep
link to a download survives the login.

---

## 4. How it is put together

```
app/
  main.py        app factory, middleware, error handlers
  config.py      env -> Settings, fails fast
  services.py    the wiring; one object on app.state
  deps.py        `RequiredAccount` — the only thing a new page depends on
  rendering.py   render(), and NAV: the one place navigation is listed
  routes/        auth.py, portal.py, downloads.py — one router each
  srp6.py        verifier recomputation
  db.py          connection seam
  queries.py     every SQL statement, returning dataclasses
  catalog.py     manifest read + validate + cache
  ranges.py      the ranged response for `direct` mode
  sessions.py    signed cookie, CSRF, client IP
  ratelimit.py   sliding window
  wowdata.py     race/class/GM tables and formatters
  templates/     base.html holds the whole stylesheet
```

**Adding a page** is: a function in a `routes/` module taking `RequiredAccount`, a
template extending `base.html`, and one line in `rendering.NAV`. Nothing else.

**Adding a query** is a method on `AccountRepo` returning a dataclass. Routes never see
SQL and never see a raw row.

### The password check

```
v = g ^ H(salt ‖ H(UPPER(user) ‖ ':' ‖ UPPER(pass))) mod N       N = 0x894B…9BB7, g = 7
```

`x` is the SHA1 digest read **little**-endian; the verifier is 32 bytes **little**-endian;
`UPPER` folds **only** ASCII `a-z`. Each of those three is a default in AzerothCore's own
code and each is easy to get backwards — `app/srp6.py` cites the file and line for all
of them. Comparison is `hmac.compare_digest`. Nothing is written to `acore_auth`, ever.

---

## 5. Security notes

- **The DB user cannot write.** `SELECT` on two schemas, nothing else. An injection or a
  future bug cannot change a password, promote an account or delete a character.
- **No SQL is built by string.** Every value is a `%s` parameter.
- **Login is limited twice**, per IP and per username, on failures only. A correct
  password never counts against you. nginx sheds an outer 10 r/m before the request
  becomes Python at all.
- **Usernames do not leak.** Same message, same status, same page bytes and the same
  work for "no such account" as for "wrong password" — including the log line, without
  which the two branches differed by 0.7 ms. Measured after: −0.18 ms over 120 samples.
- **Sessions carry an HMAC of the verifier.** Change a password and every existing
  session stops working on the next request.
- **CSRF** double-submit on both POSTs, including login (forced-login CSRF).
- **CSP** `default-src 'none'` with a per-response nonce for the one inline stylesheet
  and the one inline script. No CDN, no external anything — the VPS may be firewalled.
- **`next=` is path-only**, so the login page cannot be turned into an open redirect.
- **Redirects are relative paths**, so a proxy that mangles `Host` cannot send a browser
  to the wrong port or host.
- **Passwords and verifiers are never logged**, and error pages never show exception
  text (a MySQL error carries the connection string).

### Downloads

`X-Accel-Redirect` is the default: the app answers with a header and nginx sends the
file with `sendfile(2)`. The 17 GB never enters Python, and Range/resume are nginx's.
`/_dist/` is `internal`, so it cannot be fetched by guessing the URL.

`PORTAL_DOWNLOAD_MODE=direct` streams from Python instead, for a laptop or a test. It
implements Range itself: `206` + `Content-Range`, `416` for the unsatisfiable case,
`If-Range` so a re-cut mid-download restarts instead of splicing two builds together,
and `HEAD` answered without opening the file. Resume works in both modes and is not
optional — a 17 GB download over a home connection *will* be interrupted.

---

## 6. Running and testing it

```sh
# unit tests — no database, no network
docker build -t wowserver-web:test web/
docker run --rm -u 0 -v "$PWD/web/tests:/opt/portal/tests:ro" -w /opt/portal \
  wowserver-web:test python tests/test_portal.py
```

Against the real stack, once 1.1–1.4 are done:

```sh
cd /srv/wow/wowserver/deploy && docker compose up -d web nginx
curl -s localhost/healthz            # ok
curl -s localhost/readyz             # database: ok / artefacts: N
```

### If something is wrong

| Symptom | Cause |
|---|---|
| Container restarts, logs `ConfigError` | A required env var is missing or the secret is short. |
| Every page 503 "still starting up" | `acore_auth` does not exist yet, or the GRANT has not been run. |
| Downloads 404 through nginx | `PORTAL_XACCEL_PREFIX` and the `internal` location disagree, or `/srv/wow/dist` is not mounted into the **nginx** container. |
| "Not uploaded" on a row | The manifest lists a file that is not on disk. |
| Downloads page empty | No `manifest.json`. `/readyz` names the path it looked at. |
| Everybody locked out at once | `PORTAL_TRUSTED_PROXIES` does not cover the nginx container, so every request looks like one IP. |

---

## 7. Verified on 2026-08-08

Against a throwaway MySQL 8.4 with the real DDL, and the queries also run against the
live local server:

- login with the correct password; wrong password and unknown account produce
  byte-identical pages (nonce aside) and indistinguishable timing
- rate limiter trips at the budget and refuses a *correct* password while tripped
- password change invalidates a live session; the old password stops working
- missing/forged CSRF refused; `next=//evil.example` refused
- forged `X-Forwarded-For` ignored — the app logs the real peer
- `X-Accel-Redirect` through nginx: full download sha256-identical, `Range` → 206,
  interrupted download resumed with `curl -C -` to a byte-identical file
- `direct` mode: 206, 416, `If-Range`, `HEAD` without a body, resume, integrity
- `/_dist/` refused when requested directly
- MySQL stopped → 503 with a useful message, no stack trace, no credentials in the
  page; recovers by itself when MySQL comes back
- `read_only: true` root filesystem
