"""A ranged file response, for deployments with no front proxy to hand the file to.

READ THIS BEFORE USING IT
-------------------------
The default and the right answer is PORTAL_DOWNLOAD_MODE=xaccel: the app authenticates
the request and answers with an `X-Accel-Redirect` header, nginx opens the file and
sends it with sendfile(2). Range, resume, throttling and keep-alive are then nginx's
problem, the file never enters the Python process, and a 17 GB download costs the app
one request's worth of work.

This module is the fallback for running the portal without that proxy (a laptop, a test,
a deployment that terminates TLS elsewhere). It streams through Python, which means one
worker thread is tied up for the length of the download and throughput is bounded by how
fast asyncio can shuttle 512 KiB blocks. That is survivable for a 4 MB patch and merely
slow for a 17 GB client.

Range support is not optional in either mode. A 17 GB download over a home connection
WILL be interrupted, and a server that answers a resume request with the whole file from
byte zero makes the download effectively impossible to finish. So: Accept-Ranges on every
response, 206 with Content-Range for a satisfiable request, 416 for a bad one, and
If-Range so a file re-cut mid-download restarts cleanly instead of splicing two builds
together into a corrupt zip.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

CHUNK_SIZE = 512 * 1024

# "bytes=START-END", "bytes=START-", "bytes=-SUFFIX". Multi-range ("bytes=0-1,5-6") is
# deliberately unmatched: no download manager needs it for a single linear file, and
# answering with the whole body is a legal response to a Range header we do not honour.
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _etag(path: Path, size: int) -> str:
    stat = path.stat()
    return f'"{size:x}-{int(stat.st_mtime):x}"'


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    """-> (start, end) inclusive, or None for 'ignore this header'.

    Raises Unsatisfiable when the header is well-formed but asks for bytes past the end,
    which is a 416 rather than a silent full-body response.
    """
    match = _RANGE_RE.match(header.strip())
    if not match:
        return None
    first, last = match.group(1), match.group(2)

    if not first:
        if not last:
            return None
        suffix = int(last)
        if suffix == 0:
            raise Unsatisfiable
        start = max(size - suffix, 0)
        return start, size - 1

    start = int(first)
    if start >= size:
        raise Unsatisfiable
    end = int(last) if last else size - 1
    end = min(end, size - 1)
    if end < start:
        raise Unsatisfiable
    return start, end


class Unsatisfiable(Exception):
    """The Range header parsed but cannot be served from this file."""


def _reader(path: Path, start: int, end: int) -> Iterator[bytes]:
    """Yield [start, end] inclusive.

    A plain synchronous generator: Starlette runs a sync iterator on the threadpool via
    iterate_in_threadpool, so the event loop is never blocked on disk I/O, and back
    pressure from a slow client naturally stalls the reads.
    """
    remaining = end - start + 1
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                # The file shrank underneath us (a re-cut mid-download). Stop rather
                # than spin; the client sees a short body and its own length check fails.
                break
            remaining -= len(chunk)
            yield chunk


def ranged_file_response(
    request: Request,
    path: Path,
    *,
    filename: str,
    media_type: str = "application/octet-stream",
) -> Response:
    size = path.stat().st_size
    etag = _etag(path, size)
    headers = {
        "accept-ranges": "bytes",
        "etag": etag,
        "content-disposition": f'attachment; filename="{filename}"',
        # Nothing about a build artefact is worth a stale cache, and a partially cached
        # 17 GB file is worse than no cache.
        "cache-control": "no-store",
    }

    range_header = request.headers.get("range")
    if range_header:
        # If-Range: only honour the Range when the client's copy is still current.
        # Without this, resuming after a new pack was published splices bytes from two
        # different zips together and the checksum fails hours later.
        if_range = request.headers.get("if-range")
        if if_range and if_range.strip() != etag:
            range_header = None

    if range_header:
        try:
            span = _parse_range(range_header, size)
        except Unsatisfiable:
            return Response(
                status_code=416,
                headers={**headers, "content-range": f"bytes */{size}"},
            )
        if span is not None:
            start, end = span
            length = end - start + 1
            partial = {
                **headers,
                "content-range": f"bytes {start}-{end}/{size}",
                "content-length": str(length),
            }
            if request.method == "HEAD":
                return Response(status_code=206, headers=partial, media_type=media_type)
            return StreamingResponse(
                _reader(path, start, end),
                status_code=206,
                headers=partial,
                media_type=media_type,
            )

    full = {**headers, "content-length": str(size)}
    if request.method == "HEAD":
        # Answer HEAD without opening the file. Download managers send HEAD first to
        # decide whether they can parallelise or resume; running the body generator for
        # them would read 17 GB off disk and throw it away.
        return Response(status_code=200, headers=full, media_type=media_type)
    return StreamingResponse(
        _reader(path, 0, size - 1) if size else iter(()),
        status_code=200,
        headers=full,
        media_type=media_type,
    )
