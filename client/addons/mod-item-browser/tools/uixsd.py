#!/usr/bin/env python3
"""Write the client's own Interface\\FrameXML\\UI.xsd out of its MPQ chain.

    uixsd.py <client Data dir> <output path>

Used by tools/selftest.sh to validate this addon's UI.xml against the schema THIS client
parses with, rather than against a copy of a schema from somewhere on the internet. WoW's
answer to XML it dislikes is to skip the file in silence, so a layout mistake is otherwise
indistinguishable in game from an addon that failed to load.

Exits non-zero, quietly, when there is no readable client: the caller says so and carries on.
"""
import importlib.util
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
UI_XSD = "Interface\\FrameXML\\UI.xsd"


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    client, out = sys.argv[1], sys.argv[2]
    if not os.path.isdir(client):
        return 1
    # The MPQ reader lives in the generator; there is no second copy of it here.
    spec = importlib.util.spec_from_file_location("itemdb", os.path.join(TOOLS, "itemdb.py"))
    itemdb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(itemdb)
    for path in itemdb.mpq_chain(client):
        try:
            blob = itemdb.MpqArchive(path).read(UI_XSD)
        except Exception:                                                    # noqa: BLE001
            continue
        if blob:
            with open(out, "wb") as fh:
                fh.write(blob)
            print("   UI.xsd <- %s (%d bytes)" % (os.path.basename(path), len(blob)))
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
