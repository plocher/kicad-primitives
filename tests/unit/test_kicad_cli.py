"""Private kicad-cli discovery postconditions (ADR 0007)."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives._kicad_cli import KicadCliNotFoundError, resolve_kicad_cli


class ResolveKicadCliTests(unittest.TestCase):
    def test_explicit_path_and_env_and_miss(self) -> None:
        with TemporaryDirectory() as tmp:
            cli = Path(tmp) / "kicad-cli"
            cli.write_text("#!/bin/sh\n")
            cli.chmod(0o755)
            self.assertEqual(resolve_kicad_cli(cli), cli.resolve())
            with (
                patch.dict(os.environ, {"KICAD_CLI": str(cli)}, clear=False),
                patch("kicad_primitives._kicad_cli._PLATFORM_CANDIDATES", {}),
                patch("kicad_primitives._kicad_cli.shutil.which", return_value=None),
            ):
                self.assertEqual(resolve_kicad_cli(None), cli.resolve())
            with self.assertRaises(KicadCliNotFoundError):
                resolve_kicad_cli(Path(tmp) / "missing")
            with (
                patch.dict(
                    os.environ, {"KICAD_CLI": str(Path(tmp) / "missing")}, clear=False
                ),
                patch("kicad_primitives._kicad_cli._PLATFORM_CANDIDATES", {}),
                patch("kicad_primitives._kicad_cli.shutil.which", return_value=None),
                self.assertRaises(KicadCliNotFoundError),
            ):
                resolve_kicad_cli(None)
