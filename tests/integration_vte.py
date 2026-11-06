#!/usr/bin/env python3
"""GTK3/VTE input and real PTY tests with an isolated IBus session.

Requires an accessible X11/XWayland display (or xvfb-run), GTK3, VTE and IBus.
Uses an offscreen widget and public test strings, never sudo or real passwords.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def isolated():
    with tempfile.TemporaryDirectory(prefix="accent-vte-") as directory:
        root = Path(directory)
        env = dict(os.environ, IBUS_ADDRESS=f"unix:path={root}/ibus.sock",
                   GTK_IM_MODULE="ibus", GDK_BACKEND="x11",
                   GSETTINGS_BACKEND="memory", NO_AT_BRIDGE="1", GIO_USE_VFS="local",
                   PYTHONWARNINGS="ignore::DeprecationWarning:gi.events")
        for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            target = root / name
            target.mkdir()
            env[name] = str(target)
        env.pop("IBUS_USE_PORTAL", None)
        return subprocess.run(
            ["dbus-run-session", "--", sys.executable, "-B", __file__, "--isolated"],
            env=env, cwd=ROOT, timeout=30,
        ).returncode


if "--isolated" not in sys.argv:
    raise SystemExit(isolated())

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Vte", "2.91")
gi.require_version("IBus", "1.0")
from gi.repository import Gdk, GLib, Gtk, IBus, Vte


def pump(seconds=0.03):
    until = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < until:
        while context.pending():
            context.iteration(False)
        time.sleep(0.002)


class TerminalInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daemon = subprocess.Popen([
            "ibus-daemon", "--single", "--panel=disable", "--config=disable",
            "--emoji-extension=disable", "--cache=none",
            "--address=" + os.environ["IBUS_ADDRESS"],
        ], stdout=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop, cls.daemon)
        socket = Path(os.environ["IBUS_ADDRESS"].split("=", 1)[1])
        deadline = time.monotonic() + 3
        while not socket.exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("Isolated IBus did not start")
            time.sleep(0.01)
        IBus.init()
        cls.bus = IBus.Bus.new()
        cls.engine = subprocess.Popen([
            sys.executable, "-B", str(ROOT / "run.py"), "--register", "--diagnostics",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        cls.addClassCleanup(cls.stop, cls.engine)
        deadline = time.monotonic() + 3
        while not any(e.get_name() == "accent-hold" for e in cls.bus.list_active_engines()):
            if time.monotonic() >= deadline:
                raise RuntimeError("Accent Hold did not register")
            pump()
        if not cls.bus.set_global_engine("accent-hold"):
            raise RuntimeError("Accent Hold could not be selected")

    @staticmethod
    def stop(process):
        process.terminate()
        try:
            _, errors = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            _, errors = process.communicate()
        if errors and ("Traceback" in errors or "CRITICAL" in errors):
            raise AssertionError(errors)
        if process.stderr:
            diagnostics = json.loads(errors.strip().splitlines()[-1])
            if not diagnostics.get("presses") or diagnostics.get("menus") or diagnostics.get("commits"):
                raise AssertionError(f"Expected real terminal keys with native input only: {diagnostics}")

    def setUp(self):
        self.window = Gtk.OffscreenWindow()
        self.terminal = Vte.Terminal()
        self.window.add(self.terminal)
        self.window.show_all()
        self.addCleanup(self.window.destroy)
        self.keyboard = Gdk.Display.get_default().get_default_seat().get_keyboard()
        self.pty = self.terminal.pty_new_sync(Vte.PtyFlags.DEFAULT, None)
        self.fd = os.open(os.ptsname(self.pty.get_fd()), os.O_RDWR | os.O_NONBLOCK)
        self.addCleanup(os.close, self.fd)
        self.terminal.set_pty(self.pty)
        self.terminal.grab_focus()
        focus = Gdk.Event.new(Gdk.EventType.FOCUS_CHANGE)
        focus.window = self.terminal.get_window()
        focus.in_ = True
        focus.set_device(self.keyboard)
        self.terminal.event(focus)
        pump(0.2)

    def key(self, name, code, *, release=False, shift=False):
        event = Gdk.Event.new(Gdk.EventType.KEY_RELEASE if release else Gdk.EventType.KEY_PRESS)
        event.window = self.terminal.get_window()
        event.send_event = True
        event.time = Gdk.CURRENT_TIME
        event.keyval = Gdk.keyval_from_name(name)
        event.hardware_keycode = code
        event.state = int(Gdk.ModifierType.SHIFT_MASK) if shift else 0
        event.group = 0
        event.set_device(self.keyboard)
        self.terminal.event(event)
        pump()

    def check_input(self, *, canonical, echo):
        attrs = termios.tcgetattr(self.fd)
        attrs[3] = (attrs[3] | termios.ICANON) if canonical else (attrs[3] & ~termios.ICANON)
        attrs[3] = (attrs[3] | termios.ECHO) if echo else (attrs[3] & ~termios.ECHO)
        termios.tcsetattr(self.fd, termios.TCSAFLUSH, attrs)
        for name, code, shift in (("A", 38, True), ("e", 26, False),
                                  ("b", 56, False), ("C", 54, True),
                                  ("1", 10, False), ("exclam", 10, True)):
            self.key(name, code, shift=shift)
            self.key(name, code, release=True, shift=shift)
        # Releasing Shift before E must preserve its uppercase symbol. Holding
        # past the accent timeout must still send E before the key is released.
        self.key("E", 26, shift=True)
        self.key("Shift_L", 50, release=True)
        pump(0.55)
        self.key("Return", 36)
        self.key("Return", 36, release=True)
        pump(0.1)
        received = b""
        while True:
            try:
                received += os.read(self.fd, 4096)
            except BlockingIOError:
                break
        self.assertEqual(received, b"AebC1!E\n")
        self.key("e", 26, release=True)
        if not echo:
            displayed = self.terminal.get_text_format(Vte.Format.TEXT)
            self.assertEqual(displayed.strip(), "")

    def test_shell_input(self):
        self.check_input(canonical=False, echo=True)

    def test_canonical_input(self):
        self.check_input(canonical=True, echo=True)

    def test_sudo_style_hidden_input(self):
        self.check_input(canonical=True, echo=False)


unittest.main(argv=[sys.argv[0]], verbosity=2)
