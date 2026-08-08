#!/usr/bin/env python3
"""StormLib via ctypes, plus a model of how Wow.exe 3.3.5a picks which archive wins.

Folded from the two proven recon helpers (.work/notes/mkmpq.py, .work/notes/mpq/stormlib.py,
.work/notes/mpq/resolve.py) with the DESIGN.md section 6 flag rules baked in as the defaults,
because every one of them is a silent-failure mode:

  * MPQ_CREATE_ARCHIVE_V2 (0x01000000), NOT V1 (0x00000000). StormLib's "V1" writes
    formatVersion=0 / headerSize=32; every stock archive in this install is
    formatVersion=1 / headerSize=44. Note that StormLib's own constant NAMES are off by one
    from the header value they produce -- .work/notes/mkmpq.py had to carry a comment saying
    "MPQ_CREATE_ARCHIVE_V1 ... actually V2". write_patch() asserts the bytes that came out
    rather than trusting the constant.
  * Stored paths use BACKSLASHES: 'DBFilesClient\\Spell.dbc'. SFileHasFile with a forward
    slash returns False, so a forward-slashed archive looks perfectly fine to every tool and
    is simply never read by the client.
  * NO (attributes) file. MPQ_CREATE_ATTRIBUTES stores the source file's mtime, which makes
    the archive differ on every rebuild from identical inputs and destroys reproducibility.
  * Unsigned is fine. SFileVerifyArchive returns ERROR_NO_SIGNATURE on every Blizzard archive
    in this install, and the client's only integrity check is an RSA check over
    Interface\\FrameXML\\FrameXML.toc + Bindings.xml, which DBFilesClient\\* never touches.
"""

import ctypes
import os
import re
import struct

_LIB = os.environ.get("STORMLIB", "/usr/lib/libstorm.so.9")

MPQ_CREATE_LISTFILE = 0x00100000
MPQ_CREATE_ATTRIBUTES = 0x00200000
MPQ_CREATE_ARCHIVE_V1 = 0x00000000
MPQ_CREATE_ARCHIVE_V2 = 0x01000000

MPQ_FILE_COMPRESS = 0x00000200
MPQ_FILE_REPLACEEXISTING = 0x80000000
MPQ_COMPRESSION_ZLIB = 0x02

MPQ_OPEN_READ_ONLY = 0x00000100
SFILE_OPEN_FROM_MPQ = 0x00000000

HANDLE = ctypes.c_void_p
DWORD = ctypes.c_uint32

_S = None


def storm():
    """Load StormLib lazily so `--check` works on a machine without it."""
    global _S
    if _S is not None:
        return _S
    s = ctypes.CDLL(_LIB)
    s.SFileOpenArchive.argtypes = [ctypes.c_char_p, DWORD, DWORD, ctypes.POINTER(HANDLE)]
    s.SFileOpenArchive.restype = ctypes.c_bool
    s.SFileCreateArchive.argtypes = [ctypes.c_char_p, DWORD, DWORD, ctypes.POINTER(HANDLE)]
    s.SFileCreateArchive.restype = ctypes.c_bool
    s.SFileCloseArchive.argtypes = [HANDLE]
    s.SFileCloseArchive.restype = ctypes.c_bool
    s.SFileFlushArchive.argtypes = [HANDLE]
    s.SFileFlushArchive.restype = ctypes.c_bool
    s.SFileAddFileEx.argtypes = [HANDLE, ctypes.c_char_p, ctypes.c_char_p, DWORD, DWORD, DWORD]
    s.SFileAddFileEx.restype = ctypes.c_bool
    s.SFileHasFile.argtypes = [HANDLE, ctypes.c_char_p]
    s.SFileHasFile.restype = ctypes.c_bool
    s.SFileOpenFileEx.argtypes = [HANDLE, ctypes.c_char_p, DWORD, ctypes.POINTER(HANDLE)]
    s.SFileOpenFileEx.restype = ctypes.c_bool
    s.SFileGetFileSize.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
    s.SFileGetFileSize.restype = DWORD
    s.SFileReadFile.argtypes = [HANDLE, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD),
                                ctypes.c_void_p]
    s.SFileReadFile.restype = ctypes.c_bool
    s.SFileCloseFile.argtypes = [HANDLE]
    s.SFileCloseFile.restype = ctypes.c_bool
    s.SErrGetLastError.argtypes = []
    s.SErrGetLastError.restype = DWORD
    _S = s
    return _S


def _err(msg):
    raise OSError(f"{msg}: StormLib error {storm().SErrGetLastError()}")


class Mpq:
    def __init__(self, handle, path):
        self.h = handle
        self.path = path

    @classmethod
    def open(cls, path, read_only=True):
        h = HANDLE()
        flags = MPQ_OPEN_READ_ONLY if read_only else 0
        if not storm().SFileOpenArchive(str(path).encode(), 0, flags, ctypes.byref(h)):
            _err(f"SFileOpenArchive({path})")
        return cls(h, str(path))

    @classmethod
    def create(cls, path, max_files=64):
        if os.path.exists(path):
            os.unlink(path)  # rebuild from scratch; appending would keep stale entries
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        h = HANDLE()
        # LISTFILE yes (so `mpq --list` and StormLib's own enumeration work), ATTRIBUTES no.
        flags = MPQ_CREATE_ARCHIVE_V2 | MPQ_CREATE_LISTFILE
        if not storm().SFileCreateArchive(str(path).encode(), flags, max_files,
                                          ctypes.byref(h)):
            _err(f"SFileCreateArchive({path})")
        return cls(h, str(path))

    def add(self, local_path, archived_name, compress=True):
        assert "/" not in archived_name, (
            f"MPQ-internal paths must use backslashes, got {archived_name!r}. "
            "SFileHasFile (and the client) return False for forward-slashed names.")
        flags = MPQ_FILE_REPLACEEXISTING
        comp = 0
        if compress:
            flags |= MPQ_FILE_COMPRESS
            comp = MPQ_COMPRESSION_ZLIB
        if not storm().SFileAddFileEx(self.h, str(local_path).encode(),
                                      archived_name.encode(), flags, comp, comp):
            _err(f"SFileAddFileEx({local_path} -> {archived_name})")

    def has(self, archived_name):
        return bool(storm().SFileHasFile(self.h, archived_name.encode()))

    def read(self, archived_name):
        fh = HANDLE()
        if not storm().SFileOpenFileEx(self.h, archived_name.encode(), SFILE_OPEN_FROM_MPQ,
                                       ctypes.byref(fh)):
            _err(f"SFileOpenFileEx({archived_name})")
        try:
            hi = DWORD(0)
            lo = storm().SFileGetFileSize(fh, ctypes.byref(hi))
            size = lo | (hi.value << 32)
            buf = ctypes.create_string_buffer(size)
            got = DWORD(0)
            if not storm().SFileReadFile(fh, buf, size, ctypes.byref(got), None):
                # some StormLib builds return false at EOF even on a complete read
                if got.value != size:
                    _err(f"SFileReadFile({archived_name}) got {got.value}/{size}")
            return buf.raw[:got.value]
        finally:
            storm().SFileCloseFile(fh)

    def flush(self):
        storm().SFileFlushArchive(self.h)

    def close(self):
        if self.h:
            storm().SFileCloseArchive(self.h)
            self.h = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def header_info(path):
    """(headerSize, formatVersion) straight out of the MPQ header bytes.

    Read rather than assumed: StormLib's MPQ_CREATE_ARCHIVE_V* constant names do not line up
    with the formatVersion they produce, so the only trustworthy check is the file itself.
    """
    with open(path, "rb") as f:
        head = f.read(32)
    assert head[:4] == b"MPQ\x1a", f"{path}: not an MPQ archive"
    header_size, _archive_size = struct.unpack_from("<II", head, 4)
    fmt_version, _block_size = struct.unpack_from("<HH", head, 12)
    return header_size, fmt_version


def write_patch(out_path, entries, max_files=64):
    """Build a patch archive. `entries` is [(local_path, 'DBFilesClient\\Name.dbc'), ...].

    Returns [(archived_name, size)] read back OUT of the finished archive, so the caller can
    hash what the client will actually see instead of what we meant to put there.
    """
    with Mpq.create(out_path, max_files=max_files) as m:
        for local, name in entries:
            m.add(local, name)
        m.flush()

    header_size, fmt_version = header_info(out_path)
    # Stock 3.3.5a archives are headerSize=44 / formatVersion=1. A V1 archive (32/0) opens
    # fine in every tool and is simply ignored by the client.
    assert (header_size, fmt_version) == (44, 1), (
        f"{out_path}: wrote headerSize={header_size} formatVersion={fmt_version}, "
        "expected 44/1 (MPQ v2). Check MPQ_CREATE_ARCHIVE_V2.")

    read_back = []
    with Mpq.open(out_path) as m:
        assert not m.has("(attributes)"), (
            f"{out_path}: contains (attributes); it stores mtimes and breaks reproducible "
            "builds. Drop MPQ_CREATE_ATTRIBUTES.")
        for _local, name in entries:
            assert m.has(name), f"{out_path}: {name} missing after write"
            read_back.append((name, m.read(name)))
    return read_back


# ---------------------------------------------------------------------------------------
# Client archive-priority model (`dkspells.py --verify`)
#
# Derived from Wow.exe by disassembly in .work/notes/mpq/resolve.py and re-verified in
# DESIGN.md section 0.1:
#   PatchFiles table @0x405ab0 -- pass 0 collects the wildcard slots Data\patch-?.MPQ then
#     Data\<loc>\patch-<loc>-?.MPQ and qsorts them with the comparator @0x401200, which is
#     -_strnicmp, i.e. DESCENDING case-insensitive; pass 1 appends the two plain slots.
#   consumer @0x405dd0 -- walks that array LAST to FIRST calling SFileOpenArchive(name,
#     priority=ebx, ...) with ebx starting at 0x40 and ++ on every success.
#   registry insert @0x43e6a0 -- red-black insert keyed on priority with `setg`
#     (std::greater), so the tree is walked HIGHEST priority first => higher number wins.
# ---------------------------------------------------------------------------------------

BASE_TIER = [
    "{loc}/lichking-speech-{loc}.MPQ", "{loc}/expansion-speech-{loc}.MPQ",
    "{loc}/lichking-locale-{loc}.MPQ", "{loc}/expansion-locale-{loc}.MPQ",
    "{loc}/speech-{loc}.MPQ", "{loc}/locale-{loc}.MPQ",
    "common-2.MPQ", "common.MPQ", "lichking.MPQ", "expansion.MPQ",
]


def chain(data_dir, loc="enUS"):
    """[(priority, relative path)], lowest priority first."""
    out = []
    p = 1
    for tmpl in BASE_TIER:
        rel = tmpl.format(loc=loc)
        if os.path.exists(os.path.join(data_dir, rel)):
            out.append((p, rel))
            p += 1

    collected = []
    for rel in sorted(os.listdir(data_dir)):
        if re.fullmatch(r"patch-.\.MPQ", rel, re.I):
            collected.append("Data\\" + rel)
    ldir = os.path.join(data_dir, loc)
    if os.path.isdir(ldir):
        for rel in sorted(os.listdir(ldir)):
            if re.fullmatch(rf"patch-{loc}-.\.MPQ", rel, re.I):
                collected.append(f"Data\\{loc}\\" + rel)
    collected.sort(key=lambda s: s.lower(), reverse=True)
    collected.append("Data\\patch.MPQ")
    collected.append(f"Data\\{loc}\\patch-{loc}.MPQ")

    prio = 0x40
    for name in reversed(collected):
        rel = name[len("Data\\"):].replace("\\", "/")
        if os.path.exists(os.path.join(data_dir, rel)):
            out.append((prio, rel))
            prio += 1

    if os.path.exists(os.path.join(data_dir, "alternate.MPQ")):
        out.append((prio, "alternate.MPQ"))
    return out


def resolve(data_dir, archived_name, loc="enUS"):
    """Which archive does the client read `archived_name` (backslashed) from?"""
    for prio, rel in sorted(chain(data_dir, loc), reverse=True):
        with Mpq.open(os.path.join(data_dir, rel)) as m:
            if m.has(archived_name):
                return prio, rel
    return None, None
