# Deploying to the public VPS

How this server gets from a bare Debian 13 box to three friends logged in over the internet, what
is exposed while that is true, and what to do when one of them cannot connect.

The runbook is a script: [`scripts/deploy-vps.sh`](../scripts/deploy-vps.sh). It runs **from the
dev box** and drives the VPS over SSH. It is idempotent — re-running it after fixing something is
the normal way to make progress, not a recovery move.

Everything here is specific to the release deployment. The *why* behind the pieces it calls into
lives elsewhere and is not repeated:

| For | Read |
|---|---|
| Disk/RAM/CPU sizing, MySQL tuning, backups, the weekly restart | [hosting.md](hosting.md) |
| The four databases, first boot, accounts, GM levels | [bring-up.md](bring-up.md) |
| Client setup, `realmlist.wtf` vs `Config.wtf`, the addon pack | [client.md](client.md) |
| Death Knights, `patch-Z.MPQ`, the verification checklist | [death-knights.md](death-knights.md) |

---

## 1. The target, and the two decisions that shape everything

| | |
|---|---|
| Host | Hetzner CX33 `debian-8gb-fsn1-1` |
| Public IP | **167.233.128.19** |
| OS | Debian 13 (trixie) |
| Resources | 4 vCPU / 7 GB RAM / 71 GB free |
| Access | root over SSH, key only |

**Decision 1: friends connect over the public IP.** Not Tailscale. `realmlist` is
`167.233.128.19`, and **3724 and 8085 are open to the internet**. Everything in [§5](#5-security-posture)
exists because of this line. [hosting.md §5.1](hosting.md#51-tailscale-recommended) argues for a
tailnet and is still right about the trade — it is just not the trade being made. §5 below is the
canonical statement of the posture that replaces it.

**Decision 2: distribution is a portal on the VPS.** People log in with their **WoW account** —
the same username and password they use in the game client — and get download links plus their
account details. Four separate downloads, never one 17 GB blob
([§7](#7-the-portal-and-the-four-downloads)). It lives in `web/`: FastAPI behind nginx, verifying
logins by recomputing the SRP6 verifier against `acore_auth`. It is built to be extended; this is
the first thing it does, not the only thing it will do.

### Paths

Identical to [hosting.md §7](hosting.md#7-ops), plus one:

| Path | What |
|---|---|
| `/srv/wow/wowserver` | this repo, rsynced from the dev box |
| `/srv/wow/wowserver/deploy` | the compose project directory |
| `/srv/wow/data` | client data, 3.01 GiB, fetched **on** the VPS |
| `/srv/wow/backups` | nightly dumps |
| **`/srv/wow/dist`** | **release artefacts, flat — what the portal serves** |

---

## 2. Running it

```bash
# from the dev box, in the repo
scripts/deploy-vps.sh --dry-run all      # read this before the real one
scripts/deploy-vps.sh all
```

`all` is eleven stages in a fixed order. Each is also a name you can pass on its own:

| Stage | What | Roughly |
|---|---|---|
| `sync` | rsync the repo to `/srv/wow/wowserver` | seconds |
| `provision` | timezone, unattended-upgrades, sshd key-only, docker log rotation, then `bootstrap.sh` | 2–4 min |
| `firewall` | ufw **and** the `DOCKER-USER` chain ([§5](#5-security-posture)) | seconds |
| `image` | `docker save \| ssh \| docker load`, digest verified | 3–15 min |
| `clientdata` | `bootstrap.sh --fetch-client-data` (1.1 GB down, on the VPS) | 3–8 min |
| `env` | generate `deploy/.env` on the VPS, then `preflight.sh` | seconds |
| `up` | mysql → worldserver (**the ~20 min world import**) → authserver | 20–40 min |
| `realmlist` | `UPDATE acore_auth.realmlist SET address = the public IP` | instant |
| `webapp` | `web/sql/grant-webapp.sql`, then `up -d web nginx` | 1–2 min |
| `verify` | containers, ports **from outside**, realmlist, DK data, portal | ~30 s |
| `artefacts` | rsync the downloads into `/srv/wow/dist` | **hours** (17 GB) |

`artefacts` is deliberately last. The realm is playable long before the client zip finishes
uploading, and rsync resumes — a dropped link costs the tail of one file, not the transfer.

Useful subsets:

```bash
scripts/deploy-vps.sh sync image up verify      # ship a new build
scripts/deploy-vps.sh verify                    # cheap, run it any time
scripts/deploy-vps.sh artefacts                 # resume the upload
scripts/deploy-vps.sh --verify-sha artefacts     # re-hash before a 17 GB upload
```

### What the dev box needs

`ssh`, `rsync`, `docker`, and a built image. `zstd` and `pv` are optional but wanted — `zstd`
roughly halves the image transfer, `pv` is the progress bar. The script says so if they are
missing rather than silently going slow.

### What it deliberately does not do

It does not re-solve problems other files already own, because a second copy of that logic is a
second copy to get wrong:

- **`scripts/bootstrap.sh`** — docker engine + compose plugin from Docker's own apt repo, the 4 GB
  swapfile with `vm.swappiness=10`, `/srv/wow/{data,backups}`, `/etc/cron.d/wowserver`, and the
  pinned `wowgaming/client-data` download. Called with `--no-firewall --no-tailscale`: its ufw
  block is tailnet-shaped and opens none of the public game ports, and there is no tailnet here.
- **`scripts/preflight.sh`** — the two gitignored files generated from `deploy/.env`. One of them,
  `mysql-init/01-databases.sql`, has **no second chance**: `/docker-entrypoint-initdb.d` runs once,
  on an empty data directory ([bring-up.md §6](bring-up.md#6-first-boot)).
- **`scripts/console.sh`** — the FIFO trick that gets a command into the worldserver console
  without closing its stdin. Used once, to create the SOAP GM account.

---

## 3. Secrets: which box holds what

**The VPS generates its own passwords and the dev box never learns them.** `stage_env` writes
`deploy/.env` on the VPS with freshly generated values; the rsync in `stage_sync` excludes
`.env`, `mysql-backup.cnf` and `mysql-init/01-databases.sql` in both directions, and *protects*
them from `--delete` so a fresh checkout on this side cannot wipe them on that side.

Consequence worth internalising: the local development stack's credentials are not reused on a
public host, and reading a VPS password is an explicit act —

```bash
ssh root@167.233.128.19 'cat /srv/wow/wowserver/deploy/.env'
```

Keys written there beyond [the five `.env.example` documents](../deploy/.env.example):

| Key | Value | Why |
|---|---|---|
| `GAME_BIND_ADDR` | `0.0.0.0` | the honest name for the game-port bind, used by the compose diff in [§6](#6-compose-additions) |
| `TAILSCALE_IP` | `0.0.0.0` | the name the **current** compose file still reads. Set to `0.0.0.0` the old file publishes on every interface — which for this deployment is exactly right, so it degrades *correctly* rather than silently. Also keeps `preflight.sh`'s required-variable check happy. |
| `REALM_ADDRESS` | `167.233.128.19` | goes into `acore_auth.realmlist.address` and into `PORTAL_REALMLIST` |
| `SITE_ADDRESS` | `:80` or a hostname | operator-facing record of how the site is served |
| `PORTAL_SECRET_KEY` | generated, 48 chars | session cookie signing. `web/app/config.py` refuses under 32 |
| `PORTAL_DB_PASSWORD` | generated | the `acore_web` SELECT-only MySQL user, **not** `ACORE_DB_PASSWORD` |
| `PORTAL_REALMLIST` | `167.233.128.19` | display copy: what the portal tells people to type |
| `PORTAL_MANIFEST` | `/srv/wow/dist/downloads.json` | **must be set explicitly** — see [§6.2](#62-the-download-portal) |
| `PORTAL_TLS` | `0`, or `1` with `--domain` | Secure flag on the session cookie. `1` without a certificate = nobody can log in |
| `AC_SOAP_USER` / `AC_SOAP_PASS` | `SOAPADMIN` / generated | the GM account the weekly restart cron authenticates with |

The SOAP account is created **after** the world is up, through `console.sh`, because
`AccountMgr::CreateAccount` is what computes the SRP6 salt and verifier. Hand-writing those rows
gives you an account that exists and cannot log in.

---

## 4. Shipping the image without a registry

CI builds `ghcr.io/<owner>/wowserver:<sha>` and pushes it. The VPS cannot pull it:

- a brand-new GHCR package is **private even when the repo is public** — the package inherits the
  repo's *permissions*, not its *visibility* ([hosting.md §3.6](hosting.md#36-deploy)), and
- the token available here has no `read:packages` scope, so authenticating does not help either.

So `docker compose pull` returns 403 on our own image. `stage_image` sidesteps the problem
entirely by streaming over the SSH connection it already has:

```
docker save $IMAGE | pv | zstd -3 -T0 | ssh $VPS 'zstd -d | docker load'
```

Then it **verifies**, which is the part that makes a registry-free transfer trustworthy:

```bash
docker image inspect --format '{{.Id}}' $IMAGE          # here
docker image inspect --format '{{.Id}}' $IMAGE          # there, after load
```

The image ID is the SHA-256 of the image *config*, and the config commits to every layer's diff
ID. An ID match is therefore a match on the whole image, not just its name. A truncated stream
loads a different ID or fails outright; it never loads the right one. A mismatch aborts before
anything is deployed.

The loaded image is then re-tagged `ghcr.io/<owner>/wowserver:img-<12 hex of the digest>` and
that tag is written to `IMAGE_TAG` in the VPS's `.env`. Content-addressed, so:

- re-running `stage_image` with an unchanged image is a no-op — the tag already resolves to that
  exact ID and nothing is sent;
- `--rollback` gets a list of stable, meaningful names instead of a pile of `:latest` you cannot
  tell apart.

Two tags are kept on the box, plus whatever `.env` currently points at. At 1.6 GB each, on a 71 GB
disk, that is the right number.

> **Do not run a bare `docker compose pull` on the VPS.** It will 403 on the wowserver image and
> fail the whole command. `docker compose pull mysql nginx` is fine — both come from Docker Hub.

---

## 5. Security posture

This is a public IP with a game server on it. Read this section before changing any port.

### 5.1 What is open

| Port | Bound to | Reachable from the internet | What |
|---:|---|:---:|---|
| 22 | host | **yes** | SSH, keys only, passwords disabled by `stage_provision` |
| 3724 | `0.0.0.0` (container) | **yes** | authserver. Has to be — friends dial it |
| 8085 | `0.0.0.0` (container) | **yes** | worldserver. Has to be — the realm list points at it |
| 80 | `0.0.0.0` (container) | **yes** | nginx → the portal |
| 443 | `0.0.0.0` (container) | **yes, only once TLS is set up** | nginx, see [§7.4](#74-tls) |
| 7878 | `127.0.0.1` (container) | no | SOAP. HTTP Basic **over cleartext** |
| 3306 | *not published at all* | no | MySQL. The game containers reach it by name on the `wow` compose network |
| portal, 8000 | *not published at all* | no | only nginx talks to it, as `web:8000` on the compose network |

`stage_verify` proves the bottom three are unreachable rather than assuming it — it tries to
connect to 3306 and 7878 **from the dev box** and fails the run if either answers.

### 5.2 ufw does not protect a published Docker port

This is the trap, and it is the reason this section exists.

Docker publishes a port by writing its own rules: a DNAT in `nat/PREROUTING` and an accept in
`filter/FORWARD` via the `DOCKER` chain. Both run **before** anything ufw installed, because
ufw's rules live in the `INPUT` path and container traffic is *forwarded*, not delivered locally.

The practical consequence: **`ufw status` can say `deny (incoming)` while a container port is
happily answering the internet.** "I ran ufw" is the most common false sense of security on a box
like this one. `scripts/bootstrap.sh` already carries a warning to this effect; this deployment
has to do something about it rather than just note it.

### 5.3 The three controls this deployment actually uses

**1. The bind address — strongest, because the socket is never on a public interface at all.**
No firewall is involved and none can be misconfigured. `deploy/docker-compose.yml` decides it per
published port, and the table in §5.1 is that decision. `127.0.0.1:7878:7878` means SOAP is
loopback-only *as a property of the socket*. MySQL and the portal publish nothing, which is
stronger still.

> Note that `SOAP.IP = "0.0.0.0"` in `conf/worldserver.conf` is correct and is **not** a
> contradiction: that is the bind address *inside* the container, and it has to be 0.0.0.0 or
> Docker's DNAT from the host's loopback cannot reach it. The confinement is the publish, not
> the bind. `conf/worldserver.conf` explains the whole thing at the `SOAP.IP` key.

**2. ufw — for everything that is not a container.** sshd, and whatever anyone adds later:

```
22/tcp    ssh
3724/tcp  wow authserver (public)
8085/tcp  wow worldserver (public)
80/tcp    portal http
443/tcp   portal https      # only with --domain; otherwise actively removed
default deny incoming, default allow outgoing, IPV6=yes
```

**3. The `DOCKER-USER` chain — for everything that is.** Docker creates `DOCKER-USER`, jumps to
it first from `FORWARD`, and never flushes it. It exists precisely so you can filter container
traffic, and it is the only firewall that a published port actually traverses.
`stage_firewall` installs `/usr/local/sbin/wow-docker-firewall`:

```
DOCKER-USER:
  -m conntrack --ctstate RELATED,ESTABLISHED   -> RETURN   # replies to our own outbound
  ! -i $WAN                                    -> RETURN   # container-to-container, bridge, lo
  -i $WAN -p tcp --dport 3724                  -> RETURN
  -i $WAN -p tcp --dport 8085                  -> RETURN
  -i $WAN -p tcp --dport 80                    -> RETURN
  -i $WAN -p tcp --dport 443                   -> RETURN
  -i $WAN                                      -> DROP
```

Four details that are load-bearing:

- **`$WAN` is derived, not hardcoded** (`ip -4 route show default`). Debian 13 predictable
  interface names differ between Hetzner images — `eth0` on some, `ens3` on others — and a
  hardcoded name silently matches nothing, which fails *open*.
- **`--dport` in `FORWARD` is the CONTAINER port**, because DNAT has already happened. It is only
  the same number as the public port because every publish in this stack is symmetric
  (`3724:3724`, `8085:8085`, `80:80`, `443:443`). **If you ever publish `8080:80`, put the
  container port in this list, not the host one.**
- **`DROP`, not `REJECT`.** A reject answers a port scan. A drop costs the scanner a timeout and
  tells them nothing.
- **It is a systemd unit, not a one-off `iptables -I`.** iptables rules do not survive a reboot,
  and Docker recreates `DOCKER-USER` *empty* every time the engine starts. The unit is
  `PartOf=docker.service`, so `systemctl restart docker` — or an `apt upgrade` of `docker-ce` —
  re-applies it. Without that, one engine restart quietly removes the protection and nothing
  tells you.

Inspect it any time:

```bash
ssh root@167.233.128.19 'iptables -L DOCKER-USER -n --line-numbers; systemctl status wow-docker-firewall'
```

### 5.4 What is still exposed, honestly

**Credential stuffing against 3724.** Open the auth port to the world and you get login attempts.
AzerothCore's account security is not a hardened auth service and there is no MFA.

`conf/authserver.conf` currently leaves `WrongPass.MaxCount = 0` (no lockout) and its stated
reason is *"Nothing is exposed. Ports 3724 and 8085 never appear on a public IP"*. **That premise
is no longer true.** The recommended change, and why these values:

```ini
# conf/authserver.conf
WrongPass.MaxCount = 10   # cumulative wrong passwords; reset to 0 by any successful login
WrongPass.BanType  = 1    # 1 = ban the ACCOUNT. 0 = ban the IP -- see below
WrongPass.BanTime  = 600  # 10 minutes
WrongPass.Logging  = 1    # already on
```

Verified against `AuthSession.cpp` and `LoginDatabase.cpp` in the pinned fork: `MaxCount > 0`
increments `account.failed_logins` on each wrong password, and `LOGIN_UPD_LOGONPROOF` sets it back
to `0` on a successful logon. There is **no time window** in this fork — the count is cumulative
until someone logs in successfully — which is exactly why 10 rather than 3: a friend who typos
twice a week must never trip it.

`BanType = 1` (account) rather than `0` (IP) because the IP that `authserver` sees inside Docker
is not guaranteed to be the client's. External traffic is DNATed and normally preserves the source
address, but `docker-proxy` does not, and an IP ban landing on the bridge gateway locks out
everyone at once. Banning the account has a smaller, understood failure mode: someone who knows a
friend's username can keep that one account locked out. For five people that is a nuisance, not a
breach. Check what address is actually logged before considering `BanType = 0`:

```bash
ssh root@167.233.128.19 \
  "cd /srv/wow/wowserver/deploy && docker compose exec -T worldserver \
   grep 'invalid password' /azerothcore/logs/Auth.log | tail"
```

**The portal login is a WoW password over the network.** By default it is **cleartext HTTP** —
`web/nginx/portal.conf` serves `:80` and there is no name to get a certificate for. That is the
same password that logs into the game. [§7.4](#74-tls) is the fix and the order to do it in.
Until then, the mitigations are rate limits, not encryption: `limit_req` 10r/m on `/login` in
nginx, plus the portal's own per-IP and per-username budgets.

**DDoS.** There is none. A €8/mo VPS with a public game port is one annoyed person away from being
offline, and nothing in this repo changes that. It is an accepted risk for five friends.

**SSH.** Port 22 is public and will be brute-forced within the hour. `stage_provision` writes
`/etc/ssh/sshd_config.d/99-wowserver.conf` with `PasswordAuthentication no`,
`KbdInteractiveAuthentication no` and `PermitRootLogin prohibit-password`, validated with
`sshd -t` before the reload — a bad drop-in reloaded blind is how people lock themselves out of a
remote box. Key auth already works, so this costs nothing and removes the entire attack. `fail2ban`
on top would only reduce log noise; it is not installed.

### 5.5 The one-line summary

> The game ports are public because they have to be. Everything else is unreachable because of the
> **bind address**, not because of ufw — and the one firewall that does govern published ports,
> `DOCKER-USER`, is a systemd unit so that a docker restart cannot silently disarm it.

---

## 6. Compose additions

`deploy/docker-compose.yml` needs three changes. They are stated here rather than applied, so a
half-written compose file cannot take down a running stack.

### 6.1 Rename the game-port bind (cosmetic, but do it)

```diff
   worldserver:
     ports:
-      # Tailnet address only, so a misconfigured cloud firewall cannot leak the game
-      # ports.  hosting.md 5.1
-      # GUARDED, unlike bring-up.md 5.1's table: an empty TAILSCALE_IP turns this into
-      # ":8085:8085", which Compose happily accepts as a publish on EVERY interface.
-      # That is a silent downgrade from "invisible to the internet" to "port-scannable",
-      # so it fails loudly here instead. See the deviation note in .env.example.
-      - "${TAILSCALE_IP:?set TAILSCALE_IP in deploy/.env to the output of: tailscale ip -4}:8085:8085"
+      # PUBLIC on purpose -- friends dial 167.233.128.19 directly (docs/deploying.md 1).
+      # Still ${VAR:?}-guarded and still explicit: an empty value would become ":8085:8085",
+      # which Compose accepts as a publish on every interface, and "we meant to do that" has
+      # to be a thing somebody typed, not a thing a blank line did.
+      # 0.0.0.0 here is NOT the whole story -- what actually filters this port is the
+      # DOCKER-USER chain, because ufw never sees it. docs/deploying.md 5.2.
+      - "${GAME_BIND_ADDR:?set GAME_BIND_ADDR in deploy/.env (0.0.0.0 for a public realm)}:8085:8085"
       # SOAP, loopback only. HTTP Basic over cleartext; never face it at the internet.
       - "127.0.0.1:7878:7878"
```

```diff
   authserver:
     ports:
-      - "${TAILSCALE_IP}:3724:3724"
+      - "${GAME_BIND_ADDR}:3724:3724"
```

`scripts/deploy-vps.sh` writes **both** `GAME_BIND_ADDR=0.0.0.0` and `TAILSCALE_IP=0.0.0.0` to the
VPS's `.env`, so the deploy works before and after this lands. Once it lands,
`scripts/preflight.sh`'s `REQUIRED=(... TAILSCALE_IP)` should become
`REQUIRED=(... GAME_BIND_ADDR REALM_ADDRESS)`, and `TAILSCALE_IP` can be dropped from
`deploy/.env.example` along with the deviation note at the bottom of it.

### 6.2 The download portal

The portal is `web/` — FastAPI behind nginx — and it is already written. Two services, and both
names are load-bearing.

**The FastAPI service must be called `web`.** `web/nginx/portal.conf` hardcodes
`upstream portal { server web:8000; }`. Rename the service and nginx 502s with a DNS error.

```yaml
  # ---------------------------------------------------------------------------------------
  # The download portal. Friends sign in with their WOW ACCOUNT -- the portal recomputes the
  # SRP6 verifier from the submitted password and the stored salt and compares it in constant
  # time, so there is no handshake and no write path (web/app/srp6.py).
  # docs/deploying.md 7.
  # ---------------------------------------------------------------------------------------
  web:
    # Built ON THE BOX, unlike the game image. No CI job, no registry to pull from, and the
    # build context is web/ -- see web/Dockerfile, which is a single stage of prebuilt wheels.
    build:
      context: ../web
    image: wowserver-web:local
    restart: unless-stopped
    depends_on:
      mysql:
        condition: service_healthy

    environment:
      PORTAL_SERVER_NAME:  wowserver
      # Display copy: the literal string a friend types after `set realmlist `. It is not a
      # connection setting -- the portal never talks to the game servers -- but it has to
      # agree with acore_auth.realmlist.address or the page tells people the wrong thing.
      PORTAL_REALMLIST:    ${REALM_ADDRESS:?set REALM_ADDRESS in deploy/.env}
      # config.py refuses anything under 32 characters, as a placeholder tripwire.
      PORTAL_SECRET_KEY:   ${PORTAL_SECRET_KEY:?set PORTAL_SECRET_KEY in deploy/.env}

      # NOT the `acore` user. acore_web holds SELECT on two schemas and nothing else, created
      # by web/sql/grant-webapp.sql -- see 6.4.
      PORTAL_DB_HOST:      mysql
      PORTAL_DB_USER:      acore_web
      PORTAL_DB_PASSWORD:  ${PORTAL_DB_PASSWORD:?set PORTAL_DB_PASSWORD in deploy/.env}

      PORTAL_DOWNLOAD_ROOT: /srv/wow/dist
      # EXPLICIT, and it has to be. web/app/config.py defaults PORTAL_MANIFEST to
      # <root>/manifest.json; scripts/package-extras.sh writes <out>/downloads.json. Two
      # correct halves that do not meet -- the portal would start, find no manifest, and show
      # a login page with nothing behind it.
      PORTAL_MANIFEST:     /srv/wow/dist/downloads.json
      # nginx sends the archives via X-Accel-Redirect into its `internal` /_dist/ location,
      # so the portal answers a download with a header and an empty body. `direct` makes
      # Python stream 17 GB instead; it exists for running the app without nginx.
      PORTAL_DOWNLOAD_MODE: xaccel
      PORTAL_XACCEL_PREFIX: /_dist/

      # Drives the Secure flag on the session cookie and HSTS. 1 WITHOUT a certificate in
      # front means the cookie cannot be set over plain HTTP and nobody can log in, so this
      # tracks whether a terminator actually exists -- scripts/deploy-vps.sh writes it from
      # whether --domain was passed.
      PORTAL_TLS:          ${PORTAL_TLS:-0}

    volumes:
      # Read-only, and only so the portal can stat and list. nginx sends the bytes.
      - /srv/wow/dist:/srv/wow/dist:ro

    # NO `ports:`, and this is the most important line in the block. The portal is reachable
    # only on the `wow` network, i.e. only through nginx. Publishing 8000 "just to test it"
    # puts it on a public IP, and a published Docker port does not go through ufw --
    # docs/deploying.md 5.2.

    # web/Dockerfile runs as uid 10001, writes no files, keeps no uploads and holds sessions
    # in signed cookies. Take the free hardening.
    read_only: true
    tmpfs:
      - /tmp:size=16m
    security_opt: [no-new-privileges:true]

    # web/Dockerfile already carries a HEALTHCHECK (python, /healthz, no MySQL). Compose
    # inherits it; do not restate it here or the two will drift.

    networks: [wow]

  nginx:
    # Pinned the same way mysql is: moving tag plus the multi-arch index digest it resolves
    # to. Docker Hub is anonymously pullable -- unlike our own GHCR package -- so
    # `docker compose pull nginx` genuinely works on the VPS.
    #   docker buildx imagetools inspect nginx:1.29-alpine     # to get the digest
    image: nginx:1.29-alpine@sha256:<PIN ME>
    restart: unless-stopped
    depends_on: [web]

    volumes:
      - ../web/nginx/portal.conf:/etc/nginx/conf.d/default.conf:ro
      - ../web/nginx/portal-proxy.inc:/etc/nginx/conf.d/portal-proxy.inc:ro
      # The path INSIDE the container must be /srv/wow/dist, because portal.conf's internal
      # location is `alias /srv/wow/dist/;`. Same path both sides; do not "tidy" it to /dist.
      - /srv/wow/dist:/srv/wow/dist:ro

    ports:
      # Symmetric on purpose -- the DOCKER-USER rules match on the CONTAINER port, which is
      # what survives DNAT. docs/deploying.md 5.3.
      - "0.0.0.0:80:80"
      # 443 only once something terminates TLS. portal.conf as committed serves :80 only.
      # - "0.0.0.0:443:443"

    healthcheck:
      # wget IS in nginx:alpine. This proxies through to the portal's /healthz, so a green
      # nginx means the whole chain answers -- which is the useful signal at this layer.
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

    networks: [wow]
```

No new named volumes. Both services read `/srv/wow/dist` as a host bind, which is the same
choice `/srv/wow/data` already makes and for the same reason: 17 GB of downloads has no business
being a Docker volume you cannot `ls`.

### 6.3 `deploy/.env` keys the block above needs

`scripts/deploy-vps.sh` writes all of these on the VPS. Add them to `deploy/.env.example` with
the usual "generate from `[A-Za-z0-9]` only" note:

```ini
GAME_BIND_ADDR=            # 0.0.0.0 for a public realm
REALM_ADDRESS=             # 167.233.128.19 -- must equal acore_auth.realmlist.address
PORTAL_SECRET_KEY=         # >= 32 chars, or the portal refuses to start
PORTAL_DB_PASSWORD=        # the acore_web user, NOT ACORE_DB_PASSWORD
PORTAL_TLS=0               # 1 only once a certificate is actually in front
SITE_ADDRESS=:80           # or the hostname, for the operator's own reference
```

### 6.4 The portal's MySQL user

`web/sql/grant-webapp.sql` creates `acore_web` with `SELECT` on `acore_auth` and
`acore_characters` and nothing else. `scripts/deploy-vps.sh`'s `webapp` stage applies it on every
run, substituting `PORTAL_DB_PASSWORD` and piping it in on **stdin** — the password never reaches
argv, for the same reason `deploy/mysql-backup.cnf` exists. The file is written to be re-runnable
(`CREATE USER IF NOT EXISTS` + `ALTER USER` + `REVOKE ALL`), so that is also the password-rotation
path.

This is the difference between a bug and an incident: `acore` holds `ALL PRIVILEGES` on four
schemas, and a portal authenticating as `acore` could — through any injection or any query written
in a hurry — change a password, promote an account to administrator, or delete a character.
`acore_web` physically cannot.

---

## 7. The portal and the four downloads

### 7.1 `/srv/wow/dist` — flat, and manifest-driven

```
/srv/wow/dist/
├── downloads.json                        the manifest. Written ONLY by package-extras.sh
├── wow335-release-<stamp>.zip            ~17 GB   full client, realmlist already baked in
├── patch-Z.MPQ                           ~4.4 MB  the Death Knight client patch, alone
├── wow-addons-<stamp>.zip                         the pinned addon pack
└── wow-gm-addons-<stamp>.zip                      AzerothAdmin + ItemBrowser
```

**Flat is a contract, not a preference.** Every `filename` in `downloads.json` is a *basename* —
"never a path" — and the portal resolves each one relative to the manifest's own directory. Put
the client zip in a `client/` subdirectory and every link 404s.

`downloads.json` is the single source of truth for what exists, and the portal looks artefacts up
by a stable `id` (`client-full`, `dk-patch`, `addons`, `gm-addons`, `realmlist`) rather than by
filename — filenames carry a build stamp and change on every cut. Adding a fifth download is a
`package-extras.sh` change and no portal change at all.

Nothing in the deploy path writes a second list of hashes. The manifest already carries a
`sha256` per artefact, produced by the tool that built the file; a `SHA256SUMS` maintained beside
it by a different script is a second list to drift.

**Before uploading anything, `stage_artefacts` validates the manifest against the directory:**
every entry's file must exist, its `filename` must be a basename, and its size must match `bytes`
exactly. Size is checked always because it is instant and it catches the failure that actually
happens — a truncated file. `--verify-sha` re-hashes everything instead; that is a minute on 17 GB,
which is why it is not the default.

It also compares the manifest's `realmlist` field with the IP being deployed and asks before
continuing if they differ. A client zip built against the wrong address presents to a friend as
"Unable to connect", and nobody debugs that by opening a manifest.

The rsync uses `--partial-dir=.rsync-partial` (a half-written zip must never appear in the served
directory, where the portal would happily list it), `--append-verify` (resume, but checksum the
existing prefix first, so a *changed* source re-sends in full instead of concatenating two
different builds) and `--delete` (a superseded 17 GB client zip is not something to keep by
accident on a 71 GB disk). It refuses to start unless the VPS has the payload plus 10 GB of
headroom.

### 7.2 Why nginx sends the file and Python does not

```
browser  ->  nginx  ->  web (FastAPI)         "is this person signed in?"
                <-      X-Accel-Redirect: /_dist/<file>
browser  <-  nginx      sendfile() straight off the disk
```

`/_dist/` is marked `internal` in `portal.conf`, so nginx refuses it if a *client* asks for it —
only an `X-Accel-Redirect` from the portal can reach it. The archives are therefore behind the
login even though the portal never opens them. A download costs the portal one request; range
requests, resume, keep-alive and the 17 GB of I/O are handled by code written for exactly that.

This is also why `PORTAL_DOWNLOAD_MODE` must stay `xaccel` in production. `direct` makes a
single-worker uvicorn stream 17 GB, and that worker is also the one serving everybody's login.

### 7.3 The Death Knight patch is a first-class download

AzerothCore marks every `Spell.dbc` Description locale `FT_NA` and never reads it, so the server
*physically cannot* send a tooltip. A friend missing `patch-Z.MPQ` does not get a slightly wrong
tooltip — spell 90000 does not exist in their client at all, so their Death Knight's only ability
has no name, no icon and no spellbook entry. That is why it is 4.4 MB on its own page and not
buried inside a 17 GB zip. [death-knights.md §8](death-knights.md) has the full failure mode.
Their check:

```
/dump GetSpellInfo(90000)      -->  "Icy Touch", "Rank 1"
```

### 7.4 TLS

`web/nginx/portal.conf` as committed serves **plain HTTP on :80**, deliberately: friends connect by
IP and there is no name to get a certificate for. People type a **WoW account password** into that
page — the same password that logs into the game — so this is a real cost, not a theoretical one.
Two things reduce it today, neither of which is encryption: the portal rate-limits logins per IP
and per username (`PORTAL_LOGIN_MAX_PER_IP` 20, `PORTAL_LOGIN_MAX_PER_USER` 8 per 15 min) and nginx
sheds a flood before it becomes a Python request (`limit_req` 10r/m on `/login`).

To fix it properly you need a *name*. You do not need to buy one:

```
167-233-128-19.sslip.io       ->  167.233.128.19, no account, no setup
```

`sslip.io` is on the **Public Suffix List**, so each subdomain gets its own Let's Encrypt
rate-limit bucket rather than sharing one exhausted global one. With a name in hand:

1. add a certbot (or `nginx` + ACME) terminator and the 443 server block — `portal.conf`'s header
   says exactly this,
2. uncomment the `443:443` publish,
3. `scripts/deploy-vps.sh --domain 167-233-128-19.sslip.io firewall webapp verify`, which opens
   443 in ufw, adds it to the allowed `DOCKER-USER` ports, and sets `PORTAL_TLS=1`.

**Order matters.** `PORTAL_TLS=1` marks the session cookie `Secure`, which a browser will not set
over plain HTTP — so turning it on before the certificate exists means nobody can log in at all.
`--domain` is the last step, not the first.

---

## 8. First boot, and how to watch it

`stage_up` starts things in the order [bring-up.md §2.4](bring-up.md#24-do-not-copy-azerothcores-own-compose-topology)
requires — **worldserver owns the migrations for all four schemas**, including `acore_playerbots`
which upstream's `dbimport` tool never touches, and authserver runs with updates disabled and waits
for worldserver to be healthy.

| Stage | Log signal |
|---|---|
| Populate | `Database acore_world is empty, auto populating it...` |
| Update | `Updating acore_world database...` |
| Playerbots pool | `Updating acore_playerbots database...` |
| DBC | `>> Initialized N Data Stores in M ms` |
| World ready | `WORLD: World Initialized In N Minutes M Seconds` |
| Listener up | `... (worldserver-daemon) ready...` |

The script prints each new last-log-line while it waits, because the import is silent for minutes
at a time and a frozen cursor for twenty minutes is indistinguishable from a hang. If it exits
non-zero it dumps the last 60 lines first. **Do not restart worldserver mid-import** — it starts
the import again from scratch.

Watch it yourself in another terminal:

```bash
ssh root@167.233.128.19 'cd /srv/wow/wowserver/deploy && docker compose logs -f worldserver'
```

During the entire import the realm **appears in the list and refuses connections**. That is
correct: worldserver sets `VERSION_MISMATCH` on the realm flag while booting and clears it when
the world is up.

### The realmlist row

```sql
UPDATE acore_auth.realmlist
SET address = '167.233.128.19', port = 8085, gamebuild = 12340
WHERE id = 1;
```

`localAddress` and `localSubnetMask` are **deliberately not touched**. Their shipped defaults
(`127.0.0.1` / `255.255.255.0`) already produce the right answer:
`Realm::GetAddressForClient` checks whether the client's IP falls inside
`localAddress/localSubnetMask` — `127.0.0.0/24` cannot contain a friend's public IP, so it falls
through and hands out `address`, while a client run on the VPS itself still correctly gets
loopback. Exactly one column is wrong out of the box; fix that one.
[hosting.md §5.2](hosting.md#52-the-realmlist-gotcha--the-one-everybody-gets-wrong) is the
canonical explanation.

---

## 9. Verification

`stage_verify` runs from the dev box, which is the only vantage point that answers the question
that matters. `ss -ltnp` on the VPS tells you a socket is bound; it tells you nothing about the
cloud firewall, ufw, or `DOCKER-USER` sitting between that socket and a friend.

| Check | Pass |
|---|---|
| `mysql`, `worldserver`, `authserver` containers | `running` |
| 3724/tcp from outside | connects |
| 8085/tcp from outside | connects |
| **3306/tcp from outside** | **refused/timeout** |
| **7878/tcp from outside** | **refused/timeout** |
| `realmlist.address` / `.port` / `.gamebuild` | `167.233.128.19` / `8085` / `12340` |
| `realmlist.flag` | `0` (joinable; `2` = still loading) |
| `spell_dbc` row `90000` | `1` — Icy Touch rank 1 exists |
| `playercreateinfo WHERE class=6` | `10` — all ten races can roll a DK |
| `playercreateinfo WHERE class=6 AND map=609` | `0` — none of them start in Acherus |
| worldserver `/proc/net/tcp` has `:1F95` | `1` (8085 in hex) |
| `GET http://167.233.128.19/` | 2xx or 3xx (a redirect to `/login` is a pass) |
| `GET http://167.233.128.19/healthz` | `200` — answered without touching MySQL, so it separates "the app is down" from "its database is" |
| `downloads.json` on the VPS | at least one artefact — a login page with nothing behind it still reads as a working deploy |

Any failure exits non-zero and points here. The full in-game acceptance ladder for Death Knights
is [death-knights.md §7](death-knights.md); the three rows above are the "did the SQL apply at all"
subset that can be checked without a client.

---

## 10. When a friend cannot connect

Ask for the **exact** message and where it appears. The three failures below look similar and have
nothing to do with each other.

| What they see | Almost always | Check |
|---|---|---|
| **"Unable to connect"** at the login screen, before typing anything | 3724 unreachable, or their `realmlist.wtf` is wrong | `nc -vz 167.233.128.19 3724` from *their* machine. Then: `Data/enUS/realmlist.wtf` must be `set realmlist 167.233.128.19` **and** `WTF/Config.wtf` must be `SET realmList "167.233.128.19"` — two files, two syntaxes, both have to agree ([client.md §2](client.md#2-pointing-it-at-the-server)) |
| Login succeeds, then **"Unable to connect"** | wrong client build. Not a network fault, despite reading like one | login screen bottom-left must say `3.3.5a (12340)` |
| Realm is listed but **greyed out / "currently down"** | worldserver is not up yet (or at all) | `realmlist.flag` — `2` is `VERSION_MISMATCH`, i.e. still booting. Wait, or `docker compose ps worldserver` |
| **Hangs forever at "Logging in to game server"** | **the classic.** `realmlist.address` is wrong, or 8085 is blocked | `SELECT address, port FROM acore_auth.realmlist;` must be `167.233.128.19` / `8085`. Then `nc -vz 167.233.128.19 8085`. [hosting.md §5.2](hosting.md#52-the-realmlist-gotcha--the-one-everybody-gets-wrong) |
| **"Account does not exist"** with a password they are sure of | it is a wrong-password answer — AC returns `WOW_FAIL_UNKNOWN_ACCOUNT` for both | passwords are **upper-cased before hashing**, so they are case-insensitive; the cap is 16 characters. Grep `Auth.log` for `invalid password` |
| **"Account suspended/banned"** out of nowhere | `WrongPass` lockout ([§5.4](#54-what-is-still-exposed-honestly)), if it has been enabled | `SELECT * FROM acore_auth.account_banned WHERE active = 1;` |
| Everything works, **Death Knight has an unnamed, iconless ability** | they are missing `Data/patch-Z.MPQ` | `/dump GetSpellInfo(90000)` in their client → must be `"Icy Touch", "Rank 1"`. Send them the 4.4 MB file, not the 17 GB one |
| Character list is empty after a restore | `acore_characters` restored, `realmlist.id` no longer matches `RealmID` | `RealmID = 1` in `conf/worldserver.conf`, `realmlist.id = 1` |
| Site loads, login rejected, game login works | the portal is reading the wrong database, or `acore_web` lost its grant | `SHOW GRANTS FOR 'acore_web'@'%';` — wanted: `SELECT` on `acore_auth` and `acore_characters`. Re-apply with `scripts/deploy-vps.sh webapp` |
| Site loads, logs in, **no downloads listed** | `downloads.json` is missing, empty, or `PORTAL_MANIFEST` points at `manifest.json` | `ls -l /srv/wow/dist/downloads.json`, then `grep PORTAL_MANIFEST deploy/.env` — it must be the `downloads.json` path, not the default |
| A download 404s | the manifest lists a filename the directory does not have, or somebody nested the files in subdirectories | `scripts/deploy-vps.sh artefacts` validates exactly this before uploading; run it |

First three commands for anything not in the table:

```bash
scripts/deploy-vps.sh verify
ssh root@167.233.128.19 'cd /srv/wow/wowserver/deploy && docker compose ps && docker compose logs --tail=80 worldserver authserver'
ssh root@167.233.128.19 'ufw status verbose; iptables -L DOCKER-USER -n'
```

If `verify` says 3724 is unreachable but the container is running, the order to suspect is:
**Hetzner's own cloud firewall** (it is outside the box and nothing on the box can see it) → the
`DOCKER-USER` chain → the compose bind address → ufw. ufw is last on that list on purpose; see
[§5.2](#52-ufw-does-not-protect-a-published-docker-port).

---

## 11. Rollback and teardown

### Roll back to a previous image

```bash
scripts/deploy-vps.sh --rollback                    # list the tags on the box
scripts/deploy-vps.sh --rollback img-8cb5e29e5f84
```

It broadcasts `server restart 60` over SOAP first so anyone online gets a countdown and their
character is saved, waits it out, rewrites `IMAGE_TAG` in the VPS's `.env` and brings the two game
services back.

**The database is not rolled back.** If the image you are leaving applied world-DB migrations,
those rows are still there. An older binary usually tolerates that, but check the worldserver log
for `Table ... doesn't exist` before declaring victory. `acore_world` is reproducible from source
([hosting.md §7.3](hosting.md#73-backups) is why it is not in the nightly backup), so the nuclear
option is dropping it and letting the older image re-import.

### Stop everything, keep the data

```bash
scripts/deploy-vps.sh --teardown
```

`.server shutdown 60` over SOAP, then `docker compose down --remove-orphans`. **Named volumes
survive** — `mysql-data` is twenty minutes of world import plus every character anyone has. Bring
it back with:

```bash
scripts/deploy-vps.sh up realmlist verify
```

### Destroy it

```bash
scripts/deploy-vps.sh --teardown --purge
```

Offers to run `scripts/backup.sh` first, then makes you type `TEARDOWN`, then
`docker compose down -v`, `rm -rf /srv/wow`, and removes `/etc/cron.d/wowserver` and the
`wow-docker-firewall` unit. Docker, swap and ufw are left installed, so a re-deploy is fast.

---

## 12. Day two

None of this is new; it is the list of things that are now somebody's problem.

| Cadence | What | Owner |
|---|---|---|
| nightly 05:17 | dumps of `acore_auth` + `acore_characters` + `acore_playerbots` (**not** `acore_world`) | `scripts/backup.sh` via `/etc/cron.d/wowserver` |
| every 15 min | RSS / swap / grid-creep sample | `scripts/health.sh` |
| **weekly, Tue 06:00** | **`server restart 300`** | `scripts/soap-cmd.sh` |
| after any deploy | `scripts/deploy-vps.sh verify` | you |

The weekly restart is a **requirement**. AzerothCore never unloads a map grid once it is loaded, so
`worldserver` RSS is monotonic within an uptime and only a process restart returns it. A missed
week is an incident. `hosting.md` §7.6 has the argument; `health.sh --report` has the evidence for
whether weekly is still the right cadence.

Two things that are *not* automated and should stay that way:

- **`unattended-upgrades` does not reboot.** An unattended reboot at 06:00 is a worldserver killed
  without a `.server shutdown`, i.e. every character rolled back to its last periodic save.
- **Docker engine upgrades are manual.** `download.docker.com` is not in the allowed origin list,
  by design — the engine must not restart itself under a running realm. Upgrade it after a
  `.server shutdown 300`, and remember that a docker restart re-runs `wow-docker-firewall`
  (that is what `PartOf=docker.service` is for) so the firewall comes back with it.
