#!/usr/bin/env python3
"""Unlock custom FrameXML/GlueXML in a 3.3.5a client by neutralising the two UI signature checks.

WHY THIS EXISTS
---------------
`docs/demon-hunters.md` 2 has the full argument; the short version is that a new playable class
is unreachable without it. `ChrClasses.dbc` ships exactly ten records and
`Interface\\GlueXML\\CharacterCreate.lua:3` says `MAX_CLASSES_PER_RACE = 10`. `GetAvailableClasses`
returns one triple per ChrClasses row and `CharacterCreateEnumerateClasses` *disables* the
race-invalid ones rather than filtering them, so an eleventh row makes `numClasses` 11, trips

    if ( CharacterCreate.numClasses > MAX_CLASSES_PER_RACE ) then
        message("Too many classes!  Update MAX_CLASSES_PER_RACE");
        return;

and leaves every class button unconfigured -- character creation breaks for every race, not just
the two that gain a class. `CharacterCreate.xml` also declares exactly ten
`CharacterCreateClassButton` frames, so an eleventh button has to be authored too.

Both of those files live inside the GlueXML TOC tree, and that tree is RSA-signed.

WHAT THE CLIENT ACTUALLY CHECKS, AND WHY THE REPO USED TO HAVE THIS WRONG
------------------------------------------------------------------------
`build/modules/mod-dk-lowlevel/tools/mpqlib.py` and `docs/client.md` both used to say the
client's only integrity check was over `Interface\\FrameXML\\FrameXML.toc` + `Bindings.xml`.
That recon found one of two checks. There is a second, structurally identical check over
`Interface\\GlueXML\\GlueXML.toc`, and it is the one that matters here. Disassembled from this
install's `Wow.exe`:

    ; --- GlueXML, 0x004da7d2 ---                    ; --- FrameXML, 0x0052abc2 ---
    push 0x9e2c28        ; 2048-bit RSA key blob     push 0x9e2c28
    push 0x9f4320        ; "...\\GlueXML.toc"         push 0xa02fcc   ; "...\\FrameXML.toc"
    call 0x8165e0        ; verify -> eax             call 0x8165e0
    add  esp,0x14                                    add  esp,0x18
    cmp  eax,3                                       cmp  eax,3
    ja   0x004da81e      ; -> epilogue, ret          ja   0x0052ac12
    jmp  [eax*4+0x4da9b4]                            jmp  [eax*4+0x52aeb4]

      case 0 -> "GlueXML missing signature"     \\
      case 1 -> "GlueXML has corrupt signature"  >  log, fall through to the epilogue
      case 2 -> "GlueXML is modified or corrupt" /
      case 3 -> 0x004da835 -> call 0x814340      -- THE ONLY PATH THAT LOADS THE TOC

The TOC path string is pushed exactly twice in the whole binary: once to verify it, once to load
it, and the load is reachable only from case 3. So a modified GlueXML does not merely log a
warning -- the glue UI is never loaded at all. Same shape for FrameXML.

THE PATCH
---------
Replace the twelve bytes `cmp eax,3 / ja short / jmp [eax*4+table]` with an unconditional
`jmp rel32` straight to that site's case-3 target, NOP-padded to keep every following
instruction at its original address:

    83 f8 03 77 34 ff 24 85 <table:4>   ->   e9 <rel32:4> 90 90 90 90 90 90 90

Nothing is relocated, no section grows, no offset moves, and the verify call itself still runs
(its return value is simply ignored) so a genuinely corrupt archive still logs to
`Logs\\{Glue,Frame}XML.log`. This is the smallest edit that reaches the load path.

Both checks are patched, not just GlueXML. The in-game half of the class -- `CLASS_ICON_TCOORDS`,
`RAID_CLASS_COLORS`, `CLASS_SORT_ORDER` -- could in principle come from an addon instead, because
those are ordinary FrameXML globals and addons load afterwards. It is left as a file override
because `Constants.lua` computes `MAX_CLASSES = #CLASS_SORT_ORDER` at load time and several
FrameXML files iterate `CLASS_SORT_ORDER` while loading, i.e. before any addon exists. Patching
one check and not the other would make that distinction a silent trap for whoever comes next.

SCOPE, AND WHAT IS DELIBERATELY NOT TOUCHED
-------------------------------------------
Only these two checks. Not the Warden client, not the connection handshake, not the archive
loader, not the `(signature)` MPQ check (`SFileVerifyArchive` already returns ERROR_NO_SIGNATURE
on every Blizzard archive in this install, so unsigned custom MPQs were always normal). Files
outside the two TOC trees -- `DBFilesClient\\*`, `Interface\\Icons\\*`, the character-create
class atlas -- were never signed and are the reason the Death Knight feature works on a stock
binary today.

USAGE
-----
    client/tools/patch-wow-exe.py --check          # report state, write nothing
    client/tools/patch-wow-exe.py                  # patch in place, keeping a .orig backup
    client/tools/patch-wow-exe.py --revert         # restore from the recorded original bytes

Idempotent: patching an already-patched binary is a no-op that exits 0. Refuses outright if the
bytes at either site are neither the stock pattern nor our patch, which is what happens if you
point it at a different client build.
"""

import argparse
import hashlib
import os
import shutil
import struct
import sys

DEFAULT_EXE = "/home/ali/games/wow-3.3.5a/ChromieCraft_3.3.5a/Wow.exe"

# The stock 3.3.5a.12340 client this repo is built against. Recorded rather than enforced: a
# different-but-compatible build should still patch, so the hash is a report, not a gate. The
# gate is the twelve-byte pattern at each site, which is far more specific than a file hash and
# cannot match by accident.
KNOWN_STOCK_MD5 = "45892bdedd0ad70aed4ccd22d9fb5984"
KNOWN_STOCK_SIZE = 7704216

IMAGE_BASE = 0x400000


class Site:
    """One signature check: where it is, what it looks like, and where its success path starts.

    `patch_va` is the address of the `cmp eax,3`; `success_va` is jump-table entry 3, read out
    of the binary at runtime rather than hardcoded so a wrong table address cannot silently
    produce a jump into the middle of an instruction.
    """

    def __init__(self, name, patch_va, table_va, log_name):
        self.name = name
        self.patch_va = patch_va
        self.table_va = table_va
        self.log_name = log_name

    # 83 f8 03  cmp eax,3
    # 77 34     ja   short <epilogue>
    # ff 24 85  jmp  [eax*4+disp32]   <- the four disp32 bytes differ per site, so match a prefix
    STOCK_PREFIX = bytes.fromhex("83f8037734ff2485")
    LENGTH = 12

    def stock_bytes(self):
        return self.STOCK_PREFIX + struct.pack("<I", self.table_va)

    def patched_bytes(self, success_va):
        rel = success_va - (self.patch_va + 5)
        assert -0x80000000 <= rel <= 0x7FFFFFFF, f"{self.name}: rel32 out of range"
        return b"\xe9" + struct.pack("<i", rel) + b"\x90" * (self.LENGTH - 5)


SITES = (
    Site("GlueXML", 0x004DA7E5, 0x004DA9B4, "Logs\\GlueXML.log"),
    Site("FrameXML", 0x0052ABD9, 0x0052AEB4, "Logs\\FrameXML.log"),
)


# --------------------------------------------------------------------------------- PE layout --

def sections(blob):
    """[(name, virtual_address, virtual_size, raw_offset, raw_size)] from the PE headers.

    Computed, never assumed: the whole tool is address arithmetic, and a hardcoded
    .text base is the one mistake that would corrupt a binary while looking like it worked.
    """
    e_lfanew = struct.unpack_from("<I", blob, 0x3C)[0]
    assert blob[e_lfanew:e_lfanew + 4] == b"PE\0\0", "not a PE image"
    nsec = struct.unpack_from("<H", blob, e_lfanew + 6)[0]
    optsz = struct.unpack_from("<H", blob, e_lfanew + 20)[0]
    base = struct.unpack_from("<I", blob, e_lfanew + 24 + 28)[0]
    assert base == IMAGE_BASE, f"unexpected image base 0x{base:x}"
    out = []
    for i in range(nsec):
        o = e_lfanew + 24 + optsz + i * 40
        name = blob[o:o + 8].rstrip(b"\0").decode("ascii", "replace")
        vsz, va, rsz, raw = struct.unpack_from("<IIII", blob, o + 8)
        out.append((name, va, vsz, raw, rsz))
    return out


def va_to_off(blob, va):
    for _name, va0, vsz, raw, rsz in sections(blob):
        lo = IMAGE_BASE + va0
        if lo <= va < lo + max(vsz, rsz):
            off = raw + (va - lo)
            if off < len(blob):
                return off
    raise ValueError(f"VA 0x{va:08x} is not inside any section")


# ------------------------------------------------------------------------------ examination --

def classify(blob, site):
    """'stock' | 'patched' | 'unknown', plus the bytes actually found."""
    off = va_to_off(blob, site.patch_va)
    found = blob[off:off + site.LENGTH]
    if found == site.stock_bytes():
        return "stock", found, off
    success_va = struct.unpack_from("<I", blob, va_to_off(blob, site.table_va) + 3 * 4)[0]
    if found == site.patched_bytes(success_va):
        return "patched", found, off
    return "unknown", found, off


def success_target(blob, site):
    """Jump-table entry 3 -- the branch that reaches the TOC load."""
    off = va_to_off(blob, site.table_va)
    targets = [struct.unpack_from("<I", blob, off + i * 4)[0] for i in range(4)]
    for i, t in enumerate(targets):
        # Every entry must land inside .text and after the dispatch itself, or the table
        # address is wrong and we are reading data as code.
        if not (site.patch_va < t < site.patch_va + 0x400):
            raise ValueError(
                f"{site.name}: jump-table entry {i} = 0x{t:08x} is not a plausible local "
                f"target for a dispatch at 0x{site.patch_va:08x}; wrong table address?")
    return targets[3], targets


def report(blob, path):
    print(f"{path}")
    print(f"  size {len(blob)} bytes   md5 {hashlib.md5(blob).hexdigest()}"
          + ("   (known stock 3.3.5a.12340)"
             if hashlib.md5(blob).hexdigest() == KNOWN_STOCK_MD5 else ""))
    states = {}
    for site in SITES:
        state, found, off = classify(blob, site)
        states[site.name] = state
        succ, targets = success_target(blob, site)
        print(f"  {site.name:9s} check at 0x{site.patch_va:08x} (file 0x{off:06x}): {state}")
        print(f"    bytes    {found.hex(' ')}")
        print(f"    dispatch case0=0x{targets[0]:08x} case1=0x{targets[1]:08x} "
              f"case2=0x{targets[2]:08x} case3=0x{targets[3]:08x}  <- success")
        if state == "stock":
            print(f"    would be {site.patched_bytes(succ).hex(' ')}   (jmp 0x{succ:08x})")
    return states


# ------------------------------------------------------------------------------------ apply --

def apply(blob, revert=False):
    out = bytearray(blob)
    changed = []
    for site in SITES:
        state, _found, off = classify(blob, site)
        succ, _ = success_target(blob, site)
        want = site.stock_bytes() if revert else site.patched_bytes(succ)
        if state == "unknown":
            raise SystemExit(
                f"refusing to touch {site.name}: the twelve bytes at 0x{site.patch_va:08x} are "
                f"neither the stock pattern nor this tool's patch. This is not the client build "
                f"this tool was written against, or something else already edited it.")
        if (state == "patched") == (not revert):
            continue  # already in the requested state
        out[off:off + site.LENGTH] = want
        changed.append(site.name)
    return bytes(out), changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--exe", default=DEFAULT_EXE, help=f"path to Wow.exe (default {DEFAULT_EXE})")
    ap.add_argument("--check", action="store_true", help="report state and exit; write nothing")
    ap.add_argument("--revert", action="store_true", help="restore the stock bytes")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip writing <exe>.orig (the tool can always revert from the bytes "
                         "themselves, so the backup is convenience, not the undo mechanism)")
    args = ap.parse_args(argv)

    if not os.path.exists(args.exe):
        raise SystemExit(f"no such file: {args.exe}")
    blob = open(args.exe, "rb").read()

    states = report(blob, args.exe)
    if args.check:
        bad = [n for n, s in states.items() if s == "unknown"]
        return 2 if bad else 0

    out, changed = apply(blob, revert=args.revert)
    if not changed:
        print(f"\nnothing to do -- already {'stock' if args.revert else 'patched'}.")
        return 0

    if not args.revert and not args.no_backup:
        backup = args.exe + ".orig"
        if not os.path.exists(backup):
            shutil.copy2(args.exe, backup)
            print(f"\nbackup written: {backup}")

    # Write via a temporary file in the same directory and rename, so an interrupted run can
    # never leave a half-written executable. os.replace is atomic within a filesystem.
    tmp = args.exe + ".tmp"
    with open(tmp, "wb") as f:
        f.write(out)
    shutil.copystat(args.exe, tmp)
    os.replace(tmp, args.exe)

    print(f"\n{'reverted' if args.revert else 'patched'}: {', '.join(changed)}")
    print(f"  new size {len(out)} bytes (unchanged: {len(out) == len(blob)})")
    print(f"  new md5  {hashlib.md5(out).hexdigest()}")
    print("\nre-reading to confirm:")
    report(open(args.exe, "rb").read(), args.exe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
