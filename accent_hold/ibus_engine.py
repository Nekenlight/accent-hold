"""IBus adapter. No clipboard, synthetic Backspace or raw device access."""

import argparse
import collections
import json
import itertools
import signal
import sys

import gi

gi.require_version("IBus", "1.0")
from gi.repository import GLib, IBus  # noqa: E402

from . import __version__
from .core import (
    AccentComposer, CancelTimer, Candidates, Commit, ForwardKey, HideCandidates,
    Key, Preedit, Result, StartTimer,
)

ENGINE_NAME = "accent-hold"
BUS_NAME = "org.freedesktop.IBus.AccentHold"
SHORTCUT_MASK = (
    IBus.ModifierType.CONTROL_MASK | IBus.ModifierType.MOD1_MASK
    | IBus.ModifierType.SUPER_MASK | IBus.ModifierType.HYPER_MASK
    | IBus.ModifierType.META_MASK
)
SHIFT_KEYS = {IBus.KEY_Shift_L, IBus.KEY_Shift_R, IBus.KEY_Caps_Lock}
SHORTCUT_KEYS = {
    IBus.KEY_Control_L, IBus.KEY_Control_R, IBus.KEY_Alt_L, IBus.KEY_Alt_R,
    IBus.KEY_Super_L, IBus.KEY_Super_R, IBus.KEY_Meta_L, IBus.KEY_Meta_R,
    IBus.KEY_Hyper_L, IBus.KEY_Hyper_R,
}
# A terminal's password prompts usually retain TERMINAL, rather than switching
# to PASSWORD. Never defer/replay its keys or open candidates over secret input.
PASSTHROUGH_PURPOSES = {
    IBus.InputPurpose.PASSWORD, IBus.InputPurpose.PIN, IBus.InputPurpose.TERMINAL,
}


class AccentEngine(IBus.EngineSimple):
    __gtype_name__ = "AccentHoldEngine"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.composer = AccentComposer()
        self._timer = 0
        self._caps = 0
        self._purpose = IBus.InputPurpose.FREE_FORM
        self._diagnostics = collections.Counter()
        self.connect("destroy", self._on_destroy)

    def _apply(self, result: Result) -> bool:
        for action in result.actions:
            if isinstance(action, CancelTimer):
                if self._timer:
                    GLib.source_remove(self._timer)
                    self._timer = 0
            elif isinstance(action, StartTimer):
                self._timer = GLib.timeout_add(action.delay_ms, self._timeout, action.token)
            elif isinstance(action, Preedit):
                self.update_preedit_text_with_mode(
                    IBus.Text.new_from_string(action.text), len(action.text), bool(action.text),
                    IBus.PreeditFocusMode.CLEAR,
                )
            elif isinstance(action, Commit):
                self.commit_text(IBus.Text.new_from_string(action.text))
                self._diagnostics["commits"] += 1
            elif isinstance(action, ForwardKey):
                key = action.key
                code = key.code if key.code < 0x10000 else 0
                self.forward_key_event(key.keyval, code, key.state)
            elif isinstance(action, Candidates):
                table = IBus.LookupTable.new(9, action.selected, True, True)
                table.set_orientation(IBus.Orientation.HORIZONTAL)
                for index, value in enumerate(action.values):
                    table.append_candidate(IBus.Text.new_from_string(value))
                    table.append_label(IBus.Text.new_from_string(str(index + 1)))
                self.update_lookup_table(table, True)
            elif isinstance(action, HideCandidates):
                self.hide_lookup_table()
        return result.handled

    def _timeout(self, token):
        self._timer = 0
        result = self.composer.timeout(token)
        if result.handled:
            self._diagnostics["menus"] += 1
        self._apply(result)
        return GLib.SOURCE_REMOVE

    def do_process_key_event(self, keyval, keycode, state):
        release = bool(state & IBus.ModifierType.RELEASE_MASK)
        self._diagnostics["releases" if release else "presses"] += 1
        char = IBus.keyval_to_unicode(keyval)
        name = char if char and char.isprintable() else IBus.keyval_name(keyval) or ""
        event = Key(
            name, keycode or (0x10000 + IBus.keyval_to_lower(keyval)), release,
            bool(state & SHORTCUT_MASK) or keyval in SHORTCUT_KEYS,
            keyval in SHIFT_KEYS,
            keyval, state,
        )
        # Finish our composition first, then let EngineSimple process dead keys,
        # Compose and Unicode sequences before starting any new accent hold.
        if self._apply(self.composer.key(event, eligible=False)):
            return True
        if IBus.EngineSimple.do_process_key_event(self, keyval, keycode, state):
            return True
        can_preedit = bool(self._caps & IBus.Capabilite.PREEDIT_TEXT)
        # These clients cannot receive deferred ordinary key events.
        can_forward = not bool(self._caps & IBus.Capabilite.SYNC_PROCESS_KEY)
        passthrough = self._purpose in PASSTHROUGH_PURPOSES
        return self._apply(self.composer.key(
            event, eligible=can_preedit and can_forward and not passthrough,
        ))

    def do_candidate_clicked(self, index, button, state):
        if button == 1:
            self._apply(self.composer.choose(index))

    def do_cursor_up(self):
        if self.composer.pending and self.composer.pending.menu:
            self._apply(self.composer.key(Key("Left", -1)))
            self._apply(self.composer.key(Key("Left", -1, release=True)))

    def do_cursor_down(self):
        if self.composer.pending and self.composer.pending.menu:
            self._apply(self.composer.key(Key("Right", -1)))
            self._apply(self.composer.key(Key("Right", -1, release=True)))

    def do_set_capabilities(self, caps):
        self._caps = caps
        if not caps & IBus.Capabilite.PREEDIT_TEXT or caps & IBus.Capabilite.SYNC_PROCESS_KEY:
            self._apply(self.composer.reset())
        IBus.EngineSimple.do_set_capabilities(self, caps)

    def do_set_content_type(self, purpose, hints):
        self._purpose = purpose
        if purpose in PASSTHROUGH_PURPOSES:
            self._apply(self.composer.reset())
        IBus.EngineSimple.do_set_content_type(self, purpose, hints)

    def do_focus_out(self):
        self._apply(self.composer.reset())
        IBus.EngineSimple.do_focus_out(self)

    def do_reset(self):
        self._apply(self.composer.reset())
        IBus.EngineSimple.do_reset(self)

    def do_disable(self):
        self._apply(self.composer.reset())
        IBus.EngineSimple.do_disable(self)

    def _on_destroy(self, _engine):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self.composer.reset()


def component(command_line=""):
    result = IBus.Component.new(
        BUS_NAME, "Press-and-hold Latin accents", __version__, "MIT", "Accent Hold contributors",
        "", command_line, "",
    )
    result.add_engine(IBus.EngineDesc.new(
        ENGINE_NAME, "Accent Hold", "Hold a letter to choose an accent", "en", "MIT",
        "Accent Hold contributors", "input-keyboard", "default",
    ))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="IBus press-and-hold accents")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ibus", action="store_true", help="Launched by IBus")
    mode.add_argument("--register", action="store_true", help="Register for this IBus session only")
    mode.add_argument("--check", action="store_true", help="Check dependencies and IBus connectivity")
    parser.add_argument("--diagnostics", action="store_true", help="Print aggregate counters at exit; no typed text")
    args = parser.parse_args(argv)
    IBus.init()
    bus = IBus.Bus.new()
    if not bus.is_connected():
        print("IBus is unavailable. Run this command in a terminal inside your GNOME session.", file=sys.stderr)
        return 1
    if args.check:
        print(f"Accent Hold {__version__}; IBus connected; PyGObject available")
        return 0
    loop = GLib.MainLoop()
    engines = {}
    engine_ids = itertools.count(1)
    total = collections.Counter()
    factory = IBus.Factory.new(bus.get_connection())

    def engine_destroyed(engine, path):
        total.update(engine._diagnostics)
        engines.pop(path, None)

    def create_engine(_factory, name):
        if name != ENGINE_NAME:
            return None
        path = f"/org/freedesktop/IBus/AccentHold/Engine/{next(engine_ids)}"
        engine = AccentEngine(
            connection=bus.get_connection(),
            object_path=path,
            engine_name=ENGINE_NAME,
        )
        engines[path] = engine
        engine.connect("destroy", engine_destroyed, path)
        return engine

    factory.connect("create-engine", create_engine)
    bus.connect("disconnected", lambda _bus: loop.quit())
    if args.ibus:
        # DO_NOT_QUEUE: don't leave an idle duplicate behind.
        if bus.request_name(BUS_NAME, 4) != 1:
            print("Accent Hold is already running.", file=sys.stderr)
            return 1
    elif not bus.register_component(component()):
        print("Could not register Accent Hold.", file=sys.stderr)
        return 1
    for signum in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
    finally:
        for engine in tuple(engines.values()):
            engine.destroy()
        factory.destroy()
        if args.diagnostics:
            print(json.dumps(dict(total)), file=sys.stderr)
    return 0
