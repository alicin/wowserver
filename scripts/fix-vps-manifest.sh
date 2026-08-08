#!/usr/bin/env bash
# fix-vps-manifest.sh -- repoint downloads.json at the client zip that actually exists ON THE VPS.
#
# Run this after ANY rsync of dist/ to the server. The manifest is generated on the dev box, but
# the 16.6 GB client zip is built ON the VPS (scripts/vps-build-client.sh) because the dev box
# uploads at ~1 MB/s and the VPS pulls the torrent at ~180 MB/s. So the dev-box manifest names a
# file that only exists on the dev box, and syncing it makes the full-client entry 404 -- which
# looks, from the portal, like the download simply disappeared. It has bitten once.
set -euo pipefail
HOST="${1:-root@167.233.128.19}"
ssh -o BatchMode=yes "$HOST" 'cd /srv/wow/dist && python3 - <<PY
import json, os, glob, datetime
m=json.load(open("downloads.json"))
cands=[f for f in glob.glob("wow335-*.zip") if os.path.exists(f)]
if not cands: raise SystemExit("fix-vps-manifest: no wow335-*.zip on the server")
real=max(cands, key=os.path.getmtime); size=os.path.getsize(real)
sha=open(real+".sha256").read().split()[0]
for a in m["artifacts"]:
    if a["id"]=="client-full":
        a.update(filename=real, bytes=size, sha256=sha,
                 size_human=f"{size/1073741824:.2f} GB",
                 built=datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
json.dump(m, open("downloads.json","w"), indent=2)
missing=[a["id"] for a in m["artifacts"] if not os.path.exists(a["filename"])]
print("  client-full ->", real)
print("  unresolved entries:", missing or "none")
raise SystemExit(1 if missing else 0)
PY'
