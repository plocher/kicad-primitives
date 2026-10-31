"""Native KiCad 10 source gates, independent of an installed KiCad executable."""

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.projects import Project
from kicad_primitives.schematics import UnsupportedSchematicOperationError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/schematics/attribute-edit"


class NativeSchematicTests(unittest.TestCase):
    def test_native_noop_and_targeted_update_preserve_all_other_source(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for path in FIXTURE.glob("*.kicad_*"):
                shutil.copyfile(path, root / path.name)
            project = Project.open(root)
            schematic = project.schematic().files[0]
            original = schematic.path.read_bytes()
            self.assertEqual(schematic.version, 20260306)
            self.assertEqual(schematic.to_bytes(), original)
            symbol = schematic.symbol("R3")
            symbol.set_attribute("Value", "5k6")
            self.assertFalse(project.is_modified)
            symbol.set_attribute("Value", "22K")
            self.assertEqual(schematic.to_bytes(), original.replace(b'"5k6"', b'"22K"'))
            self.assertEqual(schematic.path.read_bytes(), original)
            with self.assertRaises(UnsupportedSchematicOperationError):
                schematic.symbol("#PWR01").set_attribute("Value", "+3V3")
