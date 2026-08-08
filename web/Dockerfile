# web/Dockerfile -- the download portal.
#
# Build context is web/. From the repo root:
#     docker build -t ghcr.io/<owner>/wowserver-web:<sha> web/
#
# Single stage on purpose. Every dependency is a pure-Python or prebuilt wheel
# (requirements.txt explains why PyMySQL and not mysqlclient), so there is nothing to
# compile and a builder stage would only add a layer that copies site-packages.

# Pinned by digest, the same rule deploy/docker-compose.yml applies to mysql. The tag
# is 3.13-slim as of 2026-08-08; bump both halves together.
FROM python:3.13-slim@sha256:9662417aace5ae7b8e2609cce472b72a8958e134ba372808abe9cc1a0c0125e6

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/portal

# Requirements first so a code change does not re-resolve and re-download the wheels.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# A fixed uid, not a name, because the interesting permission is on the HOST: the
# portal reads /srv/wow/dist through a bind mount, and the orchestrator needs a number
# to chmod against. 10001 is outside Debian's system range and will not collide.
#
# Read-only is enough for everything the portal does — it writes no files, keeps no
# uploads and holds sessions in signed cookies — so the Compose service can and should
# run with read_only: true.
# Not --system: that reserves uids below SYS_UID_MAX (999) and warns when handed
# 10001. A plain user with an explicit uid is what is wanted here.
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin portal
USER 10001

EXPOSE 8000

# No curl and no wget in a slim image, so the probe is the interpreter that is already
# here. /healthz deliberately does not touch MySQL: see routes/portal.py.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

# --workers 1 is load-bearing, not a default left alone: the login rate limiter is an
#   in-memory dict (app/ratelimit.py), and a second worker would give an attacker a
#   second, independent budget.
# --proxy-headers, and it is NOT optional here. This deployment terminates TLS at Caddy and
#   proxies plain HTTP to 127.0.0.1:8000. Without proxy headers the app believes its scheme is
#   http, so Starlette's url_for() emits ABSOLUTE http:// URLs -- including the login <form
#   action>. The browser then flags the page as insecure AND silently blocks the POST as mixed
#   active content, which presents as "the login button does nothing". Both symptoms, one cause.
#   Caddy's reverse_proxy sets X-Forwarded-Proto/For/Host by default, so this is all it takes.
#
#   The original --no-proxy-headers existed so the login rate limiter could see the true peer
#   address rather than uvicorn's rewrite. That limiter is deliberately disabled on this server
#   (app/ratelimit.py -- three friends, not a bank), so the reason no longer applies. If it is
#   ever re-enabled, read the peer from X-Forwarded-For explicitly rather than turning this off.
#
# --forwarded-allow-ips=* is safe BECAUSE of how the port is published: compose binds
#   127.0.0.1:8000, so the only thing that can reach uvicorn is Caddy on the host. Nothing
#   untrusted is in a position to forge these headers.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--no-server-header", \
     "--timeout-keep-alive", "30"]
