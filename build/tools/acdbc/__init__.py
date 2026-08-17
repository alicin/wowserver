"""acdbc -- the class-agnostic half of this repo's DBC tooling.

WHY THIS PACKAGE EXISTS, AND WHY IT IS NOT INSIDE A MODULE ANY MORE
------------------------------------------------------------------
These three files were written for `mod-dk-lowlevel` and lived in its `tools/` directory. They
are not DK-specific and never were -- `dbclib` is a WDBC reader/writer, `dbc_tables` is the
column layout of the world-DB `*_dbc` override tables, and `mpqlib` is StormLib plus a model of
the client's archive priority order. Nothing in any of them mentions a class.

The thing that forced the move is `patch-Z.MPQ`. MPQ resolution is whole-file per archived path
by archive priority (`mpqlib.resolve`), so **two archives cannot both supply `Spell.dbc`** --
the higher-priority one wins outright and the other's records are simply not there. `patch-Z` is
already the top of the resolved chain, so a second feature cannot be given a second slot either:
`patch-Y.MPQ` would be silently invisible, and a second generator writing `patch-Z.MPQ` would
silently delete every Death Knight rank. There is exactly one archive, therefore exactly one
place that may build it, therefore these libraries have to be shared rather than owned.

    build/tools/acdbc/                     <- here: no class knowledge
    build/modules/mod-dk-lowlevel/tools/   <- dk_spec.py + dkspells.py
    build/modules/mod-demon-hunter/tools/  <- dh_spec.py + dhspells.py, builds the archive last

`dkspells.py --no-mpq` writes its patched DBCs to `<out>/dbc/` and stops; `dhspells.py` reads
*that directory* rather than `/srv/wow/data/dbc`, appends its own records, and builds the single
archive from the union. `scripts/build-client-patch.sh` runs the two in that order.

Consumers add `build/tools` to `sys.path` and import the package:

    sys.path.insert(0, os.path.join(REPO_ROOT, "build", "tools"))
    from acdbc import dbclib, dbc_tables, mpqlib

The regression test for this move is that `dkspells.py --check` still reports the same 1283
passing invariants and the committed DK migrations still regenerate byte-identically. If either
changes, the move broke something.
"""

from . import dbc_tables, dbclib, gametable, mpqlib  # noqa: F401

__all__ = ["dbclib", "dbc_tables", "gametable", "mpqlib"]
