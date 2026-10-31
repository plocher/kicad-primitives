"""Fingerprint checks: stat first, hash only when size matches but the stamp does not."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives._symbol_persist import Fingerprint


class FingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "file.kicad_sch"
        self.path.write_bytes(b"(kicad_sch original)")
        self.fingerprint, raw = Fingerprint.read(self.path)
        self.assertEqual(raw, b"(kicad_sch original)")

    def test_same_size_and_stamp_is_unchanged_without_a_read(self) -> None:
        with patch.object(Path, "read_bytes", side_effect=AssertionError("read")):
            self.assertTrue(self.fingerprint.matches_path(self.path))

    def test_different_size_is_changed_without_a_read(self) -> None:
        self.path.write_bytes(b"(kicad_sch original plus more)")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("read")):
            self.assertFalse(self.fingerprint.matches_path(self.path))

    def test_same_size_new_stamp_falls_back_to_the_hash(self) -> None:
        info = self.path.stat()
        os.utime(self.path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        self.assertIsNone(self.fingerprint.quick(self.path.stat()))
        self.assertTrue(self.fingerprint.matches_path(self.path))  # touched only
        self.path.write_bytes(b"(kicad_sch ORIGINAL)")
        self.assertFalse(self.fingerprint.matches_path(self.path))

    def test_bytes_only_fingerprint_always_hashes(self) -> None:
        plain = Fingerprint.of(b"(kicad_sch original)")
        self.assertIsNone(plain.stamp)
        self.assertTrue(plain.matches_path(self.path))


if __name__ == "__main__":
    unittest.main()
