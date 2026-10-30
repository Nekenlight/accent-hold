#!/usr/bin/env python3
"""Real IBus/D-Bus protocol tests, entirely outside the desktop session.

Run: /usr/bin/python tests/integration_ibus.py
Requires dbus-run-session, ibus-daemon and PyGObject; no display required.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def isolated():
    with tempfile.TemporaryDirectory(prefix="accent-ibus-") as directory:
        root = Path(directory)
        env = dict(os.environ)
        for name, relative in {
            "XDG_RUNTIME_DIR": "run", "XDG_CACHE_HOME": "cache", "XDG_CONFIG_HOME": "config",
            "XDG_DATA_HOME": "data",
        }.items():
            target = root / relative
            target.mkdir(mode=0o700)
            env[name] = str(target)
        env.update(IBUS_ADDRESS=f"unix:path={root}/ibus.sock", GSETTINGS_BACKEND="memory")
        env["PYTHONWARNINGS"] = "ignore::DeprecationWarning:gi.events"
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "IBUS_USE_PORTAL"):
            env.pop(name, None)
        return subprocess.run(
            ["dbus-run-session", "--", sys.executable, "-B", __file__, "--isolated", *sys.argv[1:]],
            env=env, cwd=ROOT, timeout=45,
        ).returncode


if "--isolated" not in sys.argv:
    raise SystemExit(isolated())

import gi

gi.require_version("IBus", "1.0")
from gi.repository import GLib, IBus

from accent_hold.ibus_engine import ENGINE_NAME


def pump_until(condition, timeout=3):
    deadline = time.monotonic() + timeout
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("Timeout waiting for IBus signal")


def pump_for(seconds):
    deadline = time.monotonic() + seconds
    pump_until(lambda: time.monotonic() >= deadline, seconds + 1)


class RealIBusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        installed = "--installed" in sys.argv
        if installed:
            prefix = Path(os.environ["XDG_DATA_HOME"]).parent / "installed files"
            installation = subprocess.run([
                sys.executable, "-B", str(ROOT / "tools/install.py"), "install",
                "--prefix", str(prefix), "--refresh-cache",
            ], check=True, capture_output=True, text=True)
            if installation.stderr:
                raise AssertionError(installation.stderr)
        cls.daemon = subprocess.Popen([
            "ibus-daemon", "--single", "--panel=disable", "--config=disable",
            "--emoji-extension=disable", "--cache=" + ("auto" if installed else "none"),
            "--address=" + os.environ["IBUS_ADDRESS"],
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        cls.addClassCleanup(cls.stop, cls.daemon)
        socket = Path(os.environ["IBUS_ADDRESS"].split("=", 1)[1])
        pump_until(socket.exists)
        IBus.init()
        cls.bus = IBus.Bus.new()
        if not cls.bus.is_connected():
            raise RuntimeError("Isolated IBus did not connect")
        if installed:
            pump_until(lambda: any(e.get_name() == ENGINE_NAME for e in cls.bus.list_engines()))
        else:
            cls.engine = subprocess.Popen(
                [sys.executable, "-B", str(ROOT / "run.py"), "--register", "--diagnostics"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            )
            cls.addClassCleanup(cls.stop, cls.engine)
            # Active components are dynamic registrations, unlike the cached
            # inventory returned by list_engines(). This older API is needed here.
            pump_until(lambda: any(e.get_name() == ENGINE_NAME for e in cls.bus.list_active_engines()))

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
        try:
            _, errors = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            _, errors = process.communicate()
        if errors:
            print(errors.strip(), file=sys.stderr)
        if "Traceback" in (errors or "") or "CRITICAL" in (errors or ""):
            raise AssertionError("IBus process emitted an exception or critical error")

    def setUp(self):
        self.commits = []
        self.preedits = []
        self.lookups = []
        self.context = self.bus.create_input_context("accent-hold-integration")
        self.context.set_capabilities(int(IBus.Capabilite.PREEDIT_TEXT | IBus.Capabilite.FOCUS
                                          | IBus.Capabilite.LOOKUP_TABLE))
        # Inspect wire values, avoiding borrowed/floating IBus.Text objects in
        # PyGObject client-side signal callbacks.
        self.context.connect("g-signal", self.on_wire_signal)
        self.context.set_content_type(IBus.InputPurpose.FREE_FORM, 0)
        self.context.focus_in()
        self.assertTrue(self.bus.set_global_engine(ENGINE_NAME))

        def selected():
            engine = self.context.get_engine()
            return engine is not None and engine.get_name() == ENGINE_NAME

        pump_until(selected)
        pump_for(0.03)
        self.commits.clear()
        self.preedits.clear()
        self.lookups.clear()

    def on_wire_signal(self, _context, _sender, name, parameters):
        values = parameters.unpack()
        if name == "CommitText":
            self.commits.append(values[0][2])
        elif name in ("UpdatePreeditText", "UpdatePreeditTextWithMode"):
            self.preedits.append((values[0][2], values[2]))
        elif name == "UpdateLookupTable":
            self.lookups.append((tuple(text[2] for text in values[0][7]), values[1]))

    def tearDown(self):
        self.context.focus_out()
        self.context.destroy()
        pump_for(0.03)

    def key(self, name, code=26, release=False, modifiers=0):
        value = IBus.keyval_from_name(name)
        state = modifiers | (IBus.ModifierType.RELEASE_MASK if release else 0)
        result = self.context.process_key_event(value, code, int(state))
        pump_for(0.015)
        return result

    def open_menu(self, name="e", code=26):
        self.assertTrue(self.key(name, code))
        pump_until(lambda: self.lookups and self.lookups[-1][1])

    def test_quick_release_and_rapid_repetition(self):
        for _ in range(2):
            self.assertTrue(self.key("e"))
            pump_until(lambda: ("e", True) in self.preedits)
            self.assertTrue(self.key("e", release=True))
        pump_until(lambda: len(self.commits) == 2)
        self.assertEqual(self.commits, ["e", "e"])
        self.assertEqual(self.preedits[-1], ("", False))
        pump_for(0.55)
        self.assertFalse(any(visible for _, visible in self.lookups))

    def test_hold_repeat_release_and_number(self):
        self.open_menu()
        self.assertEqual(self.lookups[-1][0][1], "é")
        for _ in range(3):
            self.assertTrue(self.key("e"))
        self.assertTrue(self.key("e", release=True))
        self.assertEqual(self.commits, [])
        self.assertTrue(self.key("2", 11))
        self.assertTrue(self.key("2", 11, release=True))
        pump_until(lambda: self.commits)
        self.assertEqual(self.commits, ["é"])

    def test_shift_and_arrow_selection(self):
        self.open_menu("E")
        self.assertTrue(self.key("e", release=True))
        self.assertTrue(self.key("Right", 114))
        self.key("Right", 114, release=True)
        self.assertTrue(self.key("Return", 36))
        self.assertEqual(self.commits, ["É"])

    def test_same_letter_cycles_without_repeat_or_extra_text(self):
        self.open_menu()
        self.key("e", release=True)
        self.assertTrue(self.key("e"))
        updates = len(self.lookups)
        for _ in range(3):
            self.assertTrue(self.key("e"))
        self.assertEqual(len(self.lookups), updates)
        self.assertEqual(self.commits, [])
        self.assertTrue(self.key("e", release=True))
        self.assertTrue(self.key("Return", 36))
        self.assertEqual(self.commits, ["é"])

    def test_rolling_typing_and_passthrough(self):
        self.assertTrue(self.key("e"))
        self.assertTrue(self.key("a", 38))
        self.assertTrue(self.key("e", release=True))
        self.assertTrue(self.key("a", 38, release=True))
        self.assertFalse(self.key("b", 56))
        self.assertEqual(self.commits, ["e", "a"])

    def test_escape_and_shortcut(self):
        self.open_menu()
        self.key("e", release=True)
        self.assertTrue(self.key("Escape", 9))
        self.key("Escape", 9, release=True)
        self.assertEqual(self.commits, ["e"])
        self.assertFalse(self.key("e", modifiers=int(IBus.ModifierType.CONTROL_MASK)))
        self.assertEqual(self.commits, ["e"])

    def test_reset_and_focus_out_cancel_timer(self):
        self.key("e")
        self.context.reset()
        pump_for(0.6)
        self.assertEqual(self.commits, [])
        self.assertFalse(any(visible for _, visible in self.lookups))
        self.key("e")
        self.context.focus_out()
        pump_for(0.6)
        self.assertEqual(self.commits, [])
        self.assertFalse(any(visible for _, visible in self.lookups))

    def test_dead_key_and_compose_are_preserved(self):
        self.assertTrue(self.key("dead_acute", 48))
        self.assertTrue(self.key("e"))
        self.key("e", release=True)
        pump_until(lambda: self.commits)
        self.assertEqual(self.commits, ["é"])
        self.assertTrue(self.key("Multi_key", 135))
        self.assertTrue(self.key("apostrophe", 48))
        self.assertTrue(self.key("e"))
        pump_until(lambda: len(self.commits) == 2)
        self.assertEqual(self.commits, ["é", "é"])
        self.assertFalse(any(visible for _, visible in self.lookups))

    def test_missing_preedit_and_password_pass_through(self):
        self.context.set_capabilities(int(IBus.Capabilite.FOCUS))
        pump_for(0.03)
        self.assertFalse(self.key("e"))
        self.context.set_capabilities(int(IBus.Capabilite.PREEDIT_TEXT | IBus.Capabilite.FOCUS))
        self.context.set_content_type(IBus.InputPurpose.PASSWORD, 0)
        pump_for(0.03)
        self.assertFalse(self.key("e"))
        self.assertEqual(self.commits, [])


unittest.main(argv=[sys.argv[0]], verbosity=2)
