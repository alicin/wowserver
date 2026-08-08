"""Serving the artefacts themselves.

Two modes, chosen by PORTAL_DOWNLOAD_MODE:

  xaccel (default, and what the VPS runs)
      The app authenticates the request and replies with an empty body and an
      `X-Accel-Redirect` pointing at an `internal` nginx location. nginx re-runs its own
      static handler for that path and sends the file with sendfile(2) — so Range,
      resume, keep-alive and rate limiting are all nginx's, and 17 GB never touches
      Python. The location is `internal`, so the file cannot be fetched by guessing its
      URL: only a response from this app can name it.

  direct
      The app streams the bytes itself, with full Range support. See ranges.py for why
      this is the fallback and not the default.

Both modes require a signed-in account, and both take the filename from the manifest
rather than from the URL.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse, RedirectResponse

from ..deps import RequiredAccount, ServicesDep
from ..ranges import ranged_file_response

log = logging.getLogger("portal.downloads")

router = APIRouter()


def _artifact_or_404(svc: ServicesDep, artifact_id: str):
    artifact = svc.catalog.load().get(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such download.")
    if not artifact.available:
        # The manifest promised a file that is not on disk. 503, not 404: the artefact
        # is real and is expected back, the release is just half-published.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="That file is listed but is not on the server yet.",
        )
    return artifact


def _resolved_path(svc: ServicesDep, filename: str):
    """Join to the download root and prove the result is still inside it.

    catalog.py already rejects any `file` that is not a bare name, so this is the second
    of two independent checks. Path traversal is the one bug in a download endpoint that
    turns a file server into a credential leak, and it is worth being boring about.
    """
    root = svc.settings.download_root
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        log.error("refusing to serve %r: resolved to %s, outside %s", filename, path, root)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such download.")
    return path


# HEAD as well as GET: every download manager sends HEAD first to learn the size and
# whether Accept-Ranges is offered, and decides from that whether resume is possible.
@router.api_route("/download/{artifact_id}", methods=["GET", "HEAD"], name="download")
def download(request: Request, svc: ServicesDep, account: RequiredAccount, artifact_id: str):
    artifact = _artifact_or_404(svc, artifact_id)
    path = _resolved_path(svc, artifact.filename)

    log.info(
        "account id=%d fetching %s (%d bytes)", account.id, artifact.filename, artifact.size
    )

    if svc.settings.download_mode == "redirect":
        # This deployment terminates TLS with CADDY, not nginx, and Caddy has no
        # X-Accel-Redirect equivalent. It does already serve /files/ as a plain static root with
        # native Range support, which is exactly what a 16.6 GB download needs -- so the right
        # move is to hand the transfer over rather than reimplement it.
        #
        # The tradeoff, stated plainly: /files/ is world-readable, so this URL is not secret and
        # the login does not gate the bytes. That is deliberate for this server -- the files are
        # a public game client we want friends to get easily, the account page behind the login
        # is the part worth protecting, and streaming 16.6 GB through Python to pretend otherwise
        # would cost real reliability (no sendfile, no kernel-level ranges) for no real secrecy.
        # Switch to xaccel + nginx if the files ever need to be genuinely private.
        return RedirectResponse(
            url="/files/" + quote(artifact.filename),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if svc.settings.download_mode == "xaccel":
        # quote() because the internal location is a URI, not a path: a filename with a
        # space or a '+' must survive nginx's own parsing of the redirect target.
        target = svc.settings.xaccel_prefix + quote(artifact.filename)
        return Response(
            status_code=200,
            headers={
                "x-accel-redirect": target,
                "content-disposition": f'attachment; filename="{artifact.filename}"',
                "content-type": "application/octet-stream",
                # nginx strips its own buffering for internal redirects, but say it
                # anyway: nothing here should ever be buffered in memory.
                "x-accel-buffering": "no",
                "cache-control": "no-store",
            },
        )

    return ranged_file_response(request, path, filename=artifact.filename)


@router.get("/download/{artifact_id}/sha256", name="download_sha256")
def download_sha256(request: Request, svc: ServicesDep, account: RequiredAccount, artifact_id: str):
    """The checksum as a file `sha256sum -c` can read directly.

    The page prints the hash too, but nobody verifies a 17 GB download by comparing 64
    characters by eye. This makes it one command:
        curl -O <url> && sha256sum -c <file>.sha256
    """
    artifact = svc.catalog.load().get(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such download.")
    body = f"{artifact.sha256}  {artifact.filename}\n"
    return PlainTextResponse(
        body,
        headers={
            "content-disposition": f'attachment; filename="{artifact.filename}.sha256"',
            "cache-control": "no-store",
        },
    )
