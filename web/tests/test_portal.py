"""Tests for the parts that are easy to get subtly, silently wrong.

Run from web/:   python3 -m pytest tests -q
(or without pytest:  python3 tests/test_portal.py)

The three things under test are the three that fail quietly in production:
  * SRP6 byte order — a wrong endianness produces a plausible-looking verifier and
    every login fails with no clue why.
  * Range parsing — a wrong 416/206 boundary makes a 17 GB resume restart from zero,
    which nobody notices until the third failed download.
  * Manifest validation — a bad entry must be dropped, not crash the page or escape
    the download root.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import srp6  # noqa: E402
from app.catalog import CatalogStore  # noqa: E402
from app.ranges import Unsatisfiable, _parse_range  # noqa: E402
from app.wowdata import filesize, played  # noqa: E402


class TestSrp6(unittest.TestCase):
    def test_upper_latin_matches_utf8toupperonlylatin(self):
        # AzerothCore uppercases ONLY U+0061..U+007A (Util.h isBasicLatinCharacter).
        self.assertEqual(srp6.upper_latin("ali"), b"ALI")
        self.assertEqual(srp6.upper_latin("Ali99_x"), b"ALI99_X")
        # str.upper() would give b"SS" here and b"I" for the dotless i, changing both
        # the bytes and the length of the string that gets hashed.
        self.assertEqual(srp6.upper_latin("ß"), "ß".encode())
        self.assertEqual(srp6.upper_latin("ı"), "ı".encode())

    def test_verifier_is_32_bytes_little_endian(self):
        salt = bytes(range(32))
        verifier = srp6.calculate_verifier("ALI", "HUNTER2", salt)
        self.assertEqual(len(verifier), 32)
        # Recomputing from the little-endian bytes must give back the same integer.
        self.assertEqual(
            int.from_bytes(verifier, "little"),
            pow(srp6.G, self._x("ALI", "HUNTER2", salt), srp6.N),
        )

    @staticmethod
    def _x(user: str, password: str, salt: bytes) -> int:
        import hashlib

        inner = hashlib.sha1(f"{user}:{password}".encode()).digest()
        return int.from_bytes(hashlib.sha1(salt + inner).digest(), "little")

    def test_case_folding_is_applied_to_both_fields(self):
        salt = b"\x11" * 32
        reference = srp6.calculate_verifier("ALI", "SECRET", salt)
        self.assertEqual(srp6.calculate_verifier("ali", "secret", salt), reference)
        self.assertEqual(srp6.calculate_verifier("Ali", "SeCrEt", salt), reference)

    def test_verify_password(self):
        salt = b"\x42" * 32
        verifier = srp6.calculate_verifier("ali", "correct horse", salt)
        self.assertTrue(srp6.verify_password("ali", "correct horse", salt, verifier))
        self.assertTrue(srp6.verify_password("ALI", "CORRECT HORSE", salt, verifier))
        self.assertFalse(srp6.verify_password("ali", "correct horsf", salt, verifier))
        self.assertFalse(srp6.verify_password("bob", "correct horse", salt, verifier))
        # A truncated column must be rejected, not raise.
        self.assertFalse(srp6.verify_password("ali", "correct horse", salt, verifier[:31]))
        self.assertFalse(srp6.verify_password("ali", "correct horse", salt[:31], verifier))


class TestRangeParsing(unittest.TestCase):
    SIZE = 1000

    def test_full_and_open_ranges(self):
        self.assertEqual(_parse_range("bytes=0-499", self.SIZE), (0, 499))
        self.assertEqual(_parse_range("bytes=500-", self.SIZE), (500, 999))
        self.assertEqual(_parse_range("bytes=0-", self.SIZE), (0, 999))

    def test_suffix_range(self):
        self.assertEqual(_parse_range("bytes=-200", self.SIZE), (800, 999))
        # A suffix longer than the file is the whole file, not an error.
        self.assertEqual(_parse_range("bytes=-5000", self.SIZE), (0, 999))

    def test_end_is_clamped(self):
        # The common resume case: the client asks for more than is there.
        self.assertEqual(_parse_range("bytes=900-99999", self.SIZE), (900, 999))

    def test_unsatisfiable(self):
        with self.assertRaises(Unsatisfiable):
            _parse_range("bytes=1000-", self.SIZE)
        with self.assertRaises(Unsatisfiable):
            _parse_range("bytes=-0", self.SIZE)
        with self.assertRaises(Unsatisfiable):
            _parse_range("bytes=500-400", self.SIZE)

    def test_headers_we_ignore(self):
        # Multi-range and junk both mean "send the whole thing", not 416.
        self.assertIsNone(_parse_range("bytes=0-10,20-30", self.SIZE))
        self.assertIsNone(_parse_range("items=0-10", self.SIZE))
        self.assertIsNone(_parse_range("bytes=-", self.SIZE))


class TestCatalog(unittest.TestCase):
    """Against the schema-1 contract in scripts/package-extras.sh's header."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _store(self, manifest: dict) -> CatalogStore:
        path = self.root / "downloads.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return CatalogStore(path, self.root)

    def test_reads_a_contract_shaped_entry(self):
        (self.root / "dk-patch-20260808-1553.zip").write_bytes(b"x" * 64)
        catalog = self._store(
            {
                "schema": 1,
                "generated": "2026-08-08T16:12:03+03:00",
                "realmlist": "167.233.128.19",
                "repo": "a0f4041",
                "artifacts": [
                    {
                        "id": "dk-patch",
                        "kind": "patch",
                        "title": "Death Knight spell patch",
                        "filename": "dk-patch-20260808-1553.zip",
                        "bytes": 64,
                        "size_human": "64 B",
                        "sha256": "a" * 64,
                        "description": "First paragraph.\n\nSecond paragraph.",
                        "audience": "Anyone using their own client.",
                        "install": "<WoW>\\Data\\",
                        "contains": ["patch-Z.MPQ", "README-dk-patch.txt"],
                        "order": 20,
                        "built": "2026-08-08T16:12:03+03:00",
                        "stamp": "20260808-1553",
                    }
                ],
            }
        ).load()
        self.assertIsNone(catalog.error)
        self.assertEqual(catalog.realmlist, "167.233.128.19")
        self.assertEqual(catalog.repo, "a0f4041")
        self.assertIsNotNone(catalog.generated)

        artifact = catalog.artifacts[0]
        self.assertEqual(artifact.title, "Death Knight spell patch")
        self.assertEqual(artifact.size_human, "64 B")  # the writer's, not ours
        self.assertEqual(artifact.quality, "rare")
        self.assertEqual(artifact.paragraphs, ["First paragraph.", "Second paragraph."])
        self.assertEqual(artifact.contains, ("patch-Z.MPQ", "README-dk-patch.txt"))
        self.assertTrue(artifact.available)

    def test_sorted_by_order_and_gm_addons_stands_out(self):
        for name in ("a.zip", "b.zip", "c.zip"):
            (self.root / name).write_bytes(b"x")
        catalog = self._store(
            {
                "artifacts": [
                    {"id": "addons", "kind": "addons", "filename": "b.zip",
                     "sha256": "b" * 64, "order": 30},
                    {"id": "client-full", "kind": "client", "filename": "a.zip",
                     "sha256": "a" * 64, "order": 10},
                    {"id": "gm-addons", "kind": "addons", "filename": "c.zip",
                     "sha256": "c" * 64, "order": 40},
                ]
            }
        ).load()
        self.assertEqual([a.id for a in catalog.artifacts], ["client-full", "addons", "gm-addons"])
        # Same `kind`, different colour: `kind` cannot say "GM only", the id can.
        self.assertEqual(catalog.get("addons").quality, "uncommon")
        self.assertEqual(catalog.get("gm-addons").quality, "legendary")

    def test_stale_size_is_overridden_by_the_disk(self):
        (self.root / "pack.zip").write_bytes(b"x" * 64)
        catalog = self._store(
            {"artifacts": [{"id": "pack", "filename": "pack.zip", "bytes": 999,
                            "size_human": "999 B", "sha256": "a" * 64}]}
        ).load()
        artifact = catalog.artifacts[0]
        self.assertEqual(artifact.size, 64)
        # The writer's size_human described the stale byte count, so it goes too.
        self.assertEqual(artifact.size_human, "64 B")

    def test_drops_traversal_and_malformed_entries(self):
        (self.root / "ok.zip").write_bytes(b"x")
        catalog = self._store(
            {
                "artifacts": [
                    {"id": "esc", "filename": "../../etc/passwd", "sha256": "a" * 64},
                    {"id": "sub", "filename": "nested/ok.zip", "sha256": "a" * 64},
                    {"id": "BAD ID", "filename": "ok.zip", "sha256": "a" * 64},
                    {"id": "shorthash", "filename": "ok.zip", "sha256": "abc"},
                    {"id": "nofile", "sha256": "a" * 64},
                    {"id": "ok", "filename": "ok.zip", "sha256": "b" * 64},
                    {"id": "ok", "filename": "ok.zip", "sha256": "c" * 64},  # duplicate
                ]
            }
        ).load()
        self.assertEqual([a.id for a in catalog.artifacts], ["ok"])
        self.assertEqual(catalog.artifacts[0].sha256, "b" * 64)

    def test_missing_file_is_listed_but_not_available(self):
        catalog = self._store(
            {"artifacts": [{"id": "gone", "filename": "gone.zip", "sha256": "a" * 64}]}
        ).load()
        self.assertEqual(len(catalog.artifacts), 1)
        self.assertFalse(catalog.artifacts[0].available)

    def test_a_newer_schema_still_renders_but_warns(self):
        (self.root / "ok.zip").write_bytes(b"x")
        catalog = self._store(
            {"schema": 99,
             "artifacts": [{"id": "ok", "filename": "ok.zip", "sha256": "a" * 64}]}
        ).load()
        self.assertEqual(len(catalog.artifacts), 1)
        self.assertTrue(catalog.warnings)

    def test_absent_and_broken_manifests_give_an_empty_catalog(self):
        store = CatalogStore(self.root / "nope.json", self.root)
        self.assertEqual(store.load().artifacts, ())
        self.assertIn("No manifest", store.load().error)

        broken = self.root / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        self.assertEqual(CatalogStore(broken, self.root).load().artifacts, ())

    def test_reloads_when_the_file_changes(self):
        (self.root / "a.zip").write_bytes(b"x")
        (self.root / "b.zip").write_bytes(b"xx")
        path = self.root / "downloads.json"
        store = CatalogStore(path, self.root)

        path.write_text(
            json.dumps({"artifacts": [{"id": "a", "filename": "a.zip", "sha256": "a" * 64}]}),
            encoding="utf-8",
        )
        self.assertEqual([a.id for a in store.load().artifacts], ["a"])

        path.write_text(
            json.dumps({"artifacts": [{"id": "b", "filename": "b.zip", "sha256": "b" * 64}]}),
            encoding="utf-8",
        )
        # A same-second rewrite is why the store keys on (mtime, size), not mtime alone.
        self.assertEqual([a.id for a in store.load().artifacts], ["b"])


class TestFormatting(unittest.TestCase):
    def test_played(self):
        self.assertEqual(played(0), "never played")
        self.assertEqual(played(90), "1m")
        self.assertEqual(played(3 * 3600 + 20 * 60), "3h 20m")
        self.assertEqual(played(4 * 86400 + 12 * 3600), "4d 12h")

    def test_filesize(self):
        self.assertEqual(filesize(512), "512 B")
        self.assertEqual(filesize(4613698), "4.4 MiB")
        self.assertEqual(filesize(17786114101), "16.6 GiB")


if __name__ == "__main__":
    unittest.main(verbosity=2)
