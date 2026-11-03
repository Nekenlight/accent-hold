import contextlib
import json
import io
from pathlib import Path
import shlex
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools.install import COMPONENT, GNOME_SERVICE, INSTALL_DIR, MANIFEST, main


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="accent-install-")
        self.addCleanup(self.temp.cleanup)
        # Exercise XML and command-line escaping, too.
        self.prefix = Path(self.temp.name) / "user's files & accents"

    def run_installer(self, action, *flags):
        with contextlib.redirect_stdout(io.StringIO()):
            return main([action, "--prefix", str(self.prefix), *flags])

    def test_dry_run_writes_nothing(self):
        self.run_installer("install", "--dry-run")
        self.assertFalse(self.prefix.exists())

    def test_install_idempotence_and_uninstall(self):
        self.run_installer("install")
        manifest = (self.prefix / MANIFEST).read_bytes()
        self.run_installer("install")
        self.assertEqual((self.prefix / MANIFEST).read_bytes(), manifest)
        component = ET.parse(self.prefix / COMPONENT).getroot()
        self.assertEqual(component.findtext("engines/engine/layout"), "default")
        self.assertEqual(shlex.split(component.findtext("exec"))[1],
                         str(self.prefix / INSTALL_DIR / "run.py"))
        self.run_installer("uninstall", "--dry-run")
        self.assertTrue((self.prefix / COMPONENT).is_file())
        self.run_installer("uninstall")
        self.assertFalse((self.prefix / COMPONENT).exists())
        self.assertFalse((self.prefix / INSTALL_DIR).exists())

    def test_unowned_files_are_not_overwritten(self):
        target = self.prefix / COMPONENT
        target.parent.mkdir(parents=True)
        target.write_text("another engine")
        with self.assertRaises(ValueError):
            self.run_installer("install")
        self.assertEqual(target.read_text(), "another engine")
        self.assertFalse((self.prefix / MANIFEST).exists())

    def test_gnome_discovers_components_without_existing_cache(self):
        self.run_installer("install")
        service = (self.prefix / GNOME_SERVICE).read_text()
        self.assertIn(str(self.prefix / "share/ibus/component"), service)
        self.assertIn("--cache=refresh", service)
        self.assertIn("--panel disable", service)

    def test_legacy_installation_can_be_uninstalled(self):
        self.run_installer("install")
        (self.prefix / GNOME_SERVICE).unlink()
        marker = self.prefix / MANIFEST
        manifest = json.loads(marker.read_text())
        del manifest[str(GNOME_SERVICE)]
        marker.write_text(json.dumps(manifest))
        self.run_installer("uninstall")
        self.assertFalse(marker.exists())

    def test_modified_files_are_preserved_on_uninstall(self):
        self.run_installer("install")
        target = self.prefix / INSTALL_DIR / "accent_hold/core.py"
        target.write_text("local changes")
        with self.assertRaises(ValueError):
            self.run_installer("uninstall")
        self.assertEqual(target.read_text(), "local changes")
        self.assertTrue((self.prefix / COMPONENT).exists())

    def test_untracked_files_are_preserved(self):
        self.run_installer("install")
        target = self.prefix / INSTALL_DIR / "notes.txt"
        target.write_text("keep me")
        self.run_installer("uninstall")
        self.assertEqual(target.read_text(), "keep me")
        self.assertFalse((self.prefix / MANIFEST).exists())


if __name__ == "__main__":
    unittest.main()
