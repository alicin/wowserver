"""The download catalogue: read from downloads.json, never from the code.

WHO WRITES IT
-------------
`scripts/package-extras.sh`, and only that script — its header is the normative
contract and this module is the reader half of it. Names, sizes and checksums change on
every re-cut, so anything hardcoded here would be wrong the first time somebody cuts a
release, and wrong in the worst way: a page confidently showing last week's sha256 next
to this week's file.

THE FIELDS THIS READS  (schema 1)
---------------------------------
top level   schema, generated, realmlist, repo, artifacts[]
artifact    id, kind, title, filename, bytes, size_human, sha256,
            description, audience, install, contains[], order, built, stamp

Per the contract, unknown keys are ignored and adding a field is not breaking, so the
writer can grow without touching this file. Anything that fails validation is logged
and dropped rather than taking the page down — one bad row must not stop the other four
files being downloadable, which is the opposite of what a schema exception would do.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import wowdata

log = logging.getLogger("portal.catalog")

SCHEMA = 1

# Artefact ids appear in URLs. Keep them to a shape that cannot be confused with a path.
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# The categorical accent scale is WoW's own item-quality colours. Not decoration: every
# player already reads these as a ranking, so the categories need no legend.
KIND_QUALITY: dict[str, str] = {
    "client": "epic",
    "patch": "rare",
    "addons": "uncommon",
    "config": "common",
}
# `kind` cannot say "this one is not for you" — gm-addons and the ordinary addon pack
# are both kind=addons. Legendary orange marks the artefact that only a GM can use, so
# the one row a friend should scroll past is the one that looks different.
ID_QUALITY: dict[str, str] = {
    "gm-addons": "legendary",
}
DEFAULT_QUALITY = "poor"


@dataclass(frozen=True)
class Artifact:
    id: str
    title: str
    filename: str
    size: int
    size_human: str
    sha256: str
    kind: str
    description: str
    audience: str
    """One sentence: who needs this file. The most useful line on the page."""
    install: str
    contains: tuple[str, ...]
    order: int
    stamp: str
    available: bool
    """False when the manifest lists a file that is not on disk — shown, but not
    offered, so a half-finished rsync is visible instead of a 404 on click."""

    @property
    def quality(self) -> str:
        return ID_QUALITY.get(self.id) or KIND_QUALITY.get(self.kind, DEFAULT_QUALITY)

    @property
    def sha256_short(self) -> str:
        return self.sha256[:16]

    @property
    def paragraphs(self) -> list[str]:
        """`description` is multi-line plain text, safe to render as <p> per the contract."""
        return [block.strip() for block in self.description.split("\n\n") if block.strip()]


@dataclass(frozen=True)
class Catalog:
    artifacts: tuple[Artifact, ...] = ()
    generated: datetime | None = None
    realmlist: str = ""
    """What the shipped client pack was built to point at. If this and
    PORTAL_REALMLIST disagree, the pack sends people somewhere else."""
    repo: str = ""
    error: str | None = None
    """Human-readable reason the catalogue is empty, for the empty state."""
    warnings: tuple[str, ...] = field(default=())

    def get(self, artifact_id: str) -> Artifact | None:
        for artifact in self.artifacts:
            if artifact.id == artifact_id:
                return artifact
        return None


class CatalogStore:
    """Reads the manifest, caches it, reloads when it changes on disk.

    Reload is keyed on (mtime, size) rather than a timer, so re-running the packaging
    script updates the page on the next request with no restart and no polling. Size is
    in the key because two writes inside one filesystem timestamp tick are possible and
    a missed reload would serve a stale checksum.
    """

    def __init__(self, manifest_path: Path, download_root: Path) -> None:
        self._path = manifest_path
        self._root = download_root
        self._lock = threading.Lock()
        self._stamp: tuple[float, int] | None = None
        self._cached = Catalog(error="No manifest yet.")
        if manifest_path.parent.resolve() != download_root:
            # The contract says the manifest travels next to the files it describes.
            # If it does not, filenames still resolve against the serving root (which
            # is what nginx aliases), but say so — it is a misconfiguration.
            log.warning(
                "manifest %s is not inside the download root %s; filenames resolve "
                "against the root",
                manifest_path,
                download_root,
            )

    def load(self) -> Catalog:
        try:
            stat = self._path.stat()
            stamp = (stat.st_mtime, stat.st_size)
        except OSError:
            with self._lock:
                self._stamp = None
                self._cached = Catalog(
                    error=f"No manifest at {self._path}. Run scripts/package-extras.sh."
                )
                return self._cached

        with self._lock:
            if stamp != self._stamp:
                self._cached = self._parse()
                self._stamp = stamp
            return self._cached

    # -- internals -------------------------------------------------------------

    def _parse(self) -> Catalog:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.error("manifest %s is unreadable: %s", self._path, exc)
            return Catalog(error=f"The manifest could not be read: {exc}")

        if not isinstance(raw, dict):
            return Catalog(error="The manifest must be a JSON object.")

        warnings: list[str] = []
        schema = raw.get("schema")
        if isinstance(schema, int) and schema > SCHEMA:
            # Best effort rather than refusal. A newer writer only breaks us if it
            # changed a field's meaning, and going dark on every download because of a
            # version bump is worse than rendering a row slightly wrong.
            message = f"manifest schema {schema} is newer than this portal's {SCHEMA}"
            log.warning("%s; reading it anyway", message)
            warnings.append(message)

        artifacts: list[Artifact] = []
        seen: set[str] = set()
        for index, entry in enumerate(raw.get("artifacts") or []):
            artifact = self._artifact(entry, index)
            if artifact is None:
                continue
            if artifact.id in seen:
                log.error("manifest entry %d: duplicate id %r, skipped", index, artifact.id)
                continue
            seen.add(artifact.id)
            artifacts.append(artifact)

        # The writer promises `artifacts` is already sorted by `order`. Sorting again is
        # free and means a hand-edited manifest still renders in a sensible order.
        artifacts.sort(key=lambda a: a.order)

        return Catalog(
            artifacts=tuple(artifacts),
            generated=_timestamp(raw.get("generated")),
            realmlist=str(raw.get("realmlist") or ""),
            repo=str(raw.get("repo") or ""),
            error=None if artifacts else "The manifest lists no artefacts.",
            warnings=tuple(warnings),
        )

    def _artifact(self, entry: object, index: int) -> Artifact | None:
        def bad(reason: str) -> None:
            log.error("manifest entry %d skipped: %s", index, reason)

        if not isinstance(entry, dict):
            bad("not an object")
            return None

        artifact_id = str(entry.get("id", "")).strip().lower()
        if not ID_RE.match(artifact_id):
            bad(f"id {artifact_id!r} is not [a-z0-9][a-z0-9._-]*")
            return None

        filename = str(entry.get("filename", "")).strip()
        # The contract says `filename` is a basename, never a path. The manifest is
        # generated by a script and scripts have bugs, so that promise is checked here,
        # once, instead of being defended against at every use site.
        if not filename or filename != Path(filename).name or filename.startswith("."):
            bad(f"filename {filename!r} must be a plain basename")
            return None

        sha = str(entry.get("sha256", "")).strip().lower()
        if not SHA256_RE.match(sha):
            bad(f"sha256 for {filename!r} is not 64 hex characters")
            return None

        path = self._root / filename
        try:
            actual_size = path.stat().st_size
            available = True
        except OSError:
            actual_size = 0
            available = False
            log.warning("manifest lists %s but it is not in %s", filename, self._root)

        declared = entry.get("bytes")
        size = int(declared) if isinstance(declared, int) and declared >= 0 else actual_size
        size_human = str(entry.get("size_human") or "").strip()
        if available and isinstance(declared, int) and declared != actual_size:
            # Trust the disk for display, but say so — a mismatch means the manifest and
            # the file came from different runs, which makes the sha256 a lie too. The
            # writer's pre-formatted size_human is discarded with it.
            log.warning(
                "%s is %d bytes on disk but the manifest says %d; showing the file",
                filename, actual_size, declared,
            )
            size, size_human = actual_size, ""

        return Artifact(
            id=artifact_id,
            title=str(entry.get("title") or filename),
            filename=filename,
            size=size,
            # size_human comes pre-formatted so the page cannot disagree with the
            # script about what "4.4 MB" means. Only compute one if it is absent.
            size_human=size_human or wowdata.filesize(size),
            sha256=sha,
            kind=str(entry.get("kind") or "").strip().lower(),
            description=str(entry.get("description") or "").strip(),
            audience=str(entry.get("audience") or "").strip(),
            install=str(entry.get("install") or "").strip(),
            contains=tuple(str(c) for c in (entry.get("contains") or []) if str(c).strip()),
            order=int(entry["order"]) if isinstance(entry.get("order"), int) else 10_000 + index,
            stamp=str(entry.get("stamp") or ""),
            available=available,
        )


def _timestamp(value: object) -> datetime | None:
    """ISO-8601 with an offset, per the contract. Rendered in that local time.

    tzinfo is dropped rather than converted: the offset the packaging box wrote is the
    wall clock somebody will compare against "when did I cut that pack", and converting
    it to UTC would make the page disagree with their shell history.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None
