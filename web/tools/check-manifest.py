#!/usr/bin/env python3
"""check-manifest.py -- read a downloads.json exactly as the portal does, and say so.

usage:  web/tools/check-manifest.py [--dist DIR] [--manifest FILE]

  --dist      directory the files live in   (default /srv/wow/dist)
  --manifest  the manifest                  (default <dist>/downloads.json)

WHY THIS EXISTS, AND WHY IT IS NOT A WRITER
scripts/package-extras.sh is the only thing that writes downloads.json; a second writer
would be two sources of truth for the same file, which is the drift this whole
arrangement exists to avoid. But "did the manifest come out right" is a question worth
answering without a browser and a login, and the only answer that counts is the one the
portal's own reader gives. So this imports app.catalog and prints what the page would
show — same validation, same dropped rows, same warnings.

Run it after every cut, and after every rsync to the VPS. The rsync is the interesting
one: the manifest is small and lands first, so a manifest whose files are still in
flight is the normal mid-transfer state, and this is how you see it.

Exit codes:  0 every artefact is servable
             1 the manifest is unusable, or an artefact's file is missing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.catalog import CatalogStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--dist", default="/srv/wow/dist")
    parser.add_argument("--manifest", default=None)
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args()

    if args.help:
        print(__doc__)
        return 0

    dist = Path(args.dist).resolve()
    manifest = Path(args.manifest) if args.manifest else dist / "downloads.json"

    catalog = CatalogStore(manifest, dist).load()

    print(f"manifest : {manifest}")
    print(f"files    : {dist}")
    print(f"realmlist: {catalog.realmlist or '(not recorded)'}")
    print(f"repo     : {catalog.repo or '(unknown)'}")
    print(f"generated: {catalog.generated or '(not recorded)'}")
    for warning in catalog.warnings:
        print(f"WARNING  : {warning}")

    if catalog.error:
        print(f"\nERROR: {catalog.error}", file=sys.stderr)
        return 1

    print(f"\n{len(catalog.artifacts)} artefact(s), in page order:\n")
    missing = 0
    for artifact in catalog.artifacts:
        mark = "ok " if artifact.available else "GONE"
        if not artifact.available:
            missing += 1
        print(f"  [{mark}] {artifact.order:>4}  {artifact.id:<12} {artifact.quality:<10} "
              f"{artifact.size_human:>10}  {artifact.filename}")
        print(f"           {artifact.sha256}")
        if artifact.audience:
            print(f"           {artifact.audience}")
        print()

    if missing:
        print(f"{missing} artefact(s) listed but not on disk — the portal will show them "
              f"as 'Not uploaded'.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
