# Accent Hold

macOS-style press-and-hold accents for **GNOME on Wayland**, built with Python,
PyGObject and IBus. This prototype uses the native IBus candidate panel; no
GNOME Shell extension is required.

## Screenshots

Accent choices after holding `e`:

![Native IBus accent picker showing alternatives for e](docs/images/accent-picker-e.png)

Selecting an alternative for `i`:

![Native IBus accent picker with an alternative for i highlighted](docs/images/accent-picker-i.png)

## Usage

Hold `e` for **500 ms** to open `è é ê ë ē ė ę ě`, then release it. Choose an
accent with a displayed number, the arrow keys followed by Enter, or a left
click. You can also **press the same letter again to cycle through accents**:
each new press advances one position, wrapping around after the last candidate.
Press Enter to confirm. Continuing to hold a key does not cycle automatically.

For example: hold `e` (highlighting `è`), release it, press `e` again
(highlighting `é`), then press Enter. Uppercase letters offer uppercase accents,
even if you release Shift before cycling.

Escape keeps the original letter. An ordinary key closes the menu, keeps the
original letter and continues typing. A quick tap appears immediately as
**preedit text** and is committed on release or before the next key; some
applications underline this temporary composition.

Only letters with alternatives lose their normal key repeat. Ctrl, Alt and
Super shortcuts pass through to IBus's simple engine, while AltGr can still
produce characters from the current layout. Dead keys and Compose sequences
are handled by IBus's simple engine.

## Requirements

- Python **3.10+**
- PyGObject and IBus 1.5 with GObject introspection data
- A running IBus session and applications that support text composition and
  forward key-release events

Use your distribution's system Python and PyGObject packages. A virtual
environment may not include the desktop's GObject introspection bindings.

## Install

Run these commands in a terminal inside your GNOME session:

```sh
git clone https://github.com/Nekenlight/accent-hold.git
cd accent-hold
python3 run.py --check
python3 tools/install.py install --dry-run
python3 tools/install.py install --refresh-cache
```

The installer places the engine in `~/.local/libexec/accent-hold/` and its IBus
descriptor in `~/.local/share/ibus/component/accent-hold.xml`. It rebuilds the
user's IBus registry cache, including system engines and additional component
paths. It does not install packages or change system files, input sources or
the selected keyboard layout.

**Log out and back in**, then open GNOME Settings → Keyboard → Input Sources →
Add. Find **Accent Hold**, possibly under English or other input sources, and
select it from the input-source menu. Keep your regular input source available
so you can switch back with Super+Space.

Check the active engine with `ibus engine`; the expected output is `accent-hold`.
The engine requests IBus's `default` layout and interprets received symbols
rather than assuming QWERTY positions. Physical AZERTY/QWERTZ keyboards and
multiple-layout configurations still need desktop testing. Number shortcuts use
the **produced digits**, so some layouts require Shift; arrows and mouse
selection are also available.

Installing the same version again is safe. The installer refuses to overwrite
unmanaged files, local changes or a different version. To update this prototype,
uninstall the previous version first, then install the new one.

## Uninstall

Switch to your regular input source and remove Accent Hold from GNOME's input
sources, then run:

```sh
python3 tools/install.py uninstall --dry-run
python3 tools/install.py uninstall --refresh-cache
```

Log out and back in to unload the engine. Only unchanged files recorded in the
installation manifest are removed. Additional files, including Python bytecode
caches, are left alone. The IBus cache is rebuilt; input-source preferences are
not rewritten. Use `--prefix` to test installation in a temporary directory.

## Compatibility and games

This is a prototype, not a universal keyboard interceptor. Applications that
bypass input methods are outside its coverage. Clients without preedit support
keep ordinary input without the accent picker. Fields identified as passwords
or PINs do not activate it. IBus/GNOME positions the panel using information
provided by the application.

**There is no automatic game detection or per-application exclusion yet.** A
game that forwards keys to an input-method context with preedit support could
trigger the picker. Switch to your regular input source before playing.
Terminals, Vim, games, remote sessions and other compositors are outside the
initial compatibility target.

Focus loss, reset or engine deactivation closes the menu and discards any
**uncommitted** letter to avoid inserting text into a different target.

See [validation coverage and the manual test checklist](docs/validation.md)
for the distinction between protocol tests and graphical application testing.

## Development

The logic and installer tests use the standard library and temporary folders:

```sh
python3 -m unittest discover -s tests -v
```

Integration tests run a **real IBus daemon on an isolated D-Bus session**, without
a display or changes to the desktop's input sources:

```sh
python3 tests/integration_ibus.py
python3 tests/integration_ibus.py --installed
```

These tests require `dbus-run-session`, `ibus-daemon` and PyGObject. The second
mode also checks file installation, the registry cache and automatic launch
through the XML descriptor, using an installation path containing spaces.

For temporary development registration, `python3 run.py --register` registers
the engine with the current IBus daemon until the process exits. Add
`--diagnostics` to print aggregate press, release, menu and commit counters at
exit. Typed text is not included; there is no keystroke log by default.

The code is separated into:

- `accent_hold/core.py`: a desktop-independent state machine accepting key,
  timeout, candidate-selection and reset events. It emits preedit, commit,
  candidate-display and timer actions.
- `accent_hold/variants.py`: ordered Latin alternatives, at most nine per letter.
- `accent_hold/ibus_engine.py`: IBus symbol/modifier translation, GLib timers,
  native candidate rendering and delegation to IBus's simple engine.

A future Fcitx5 adapter can reuse the core contract and accent tables, with its
own integration work. KDE, Sway and Hyprland support has not been validated.

API references: [IBus Engine](https://ibus.github.io/docs/ibus-1.5/IBusEngine.html)
and [GNOME Shell's IBus integration](https://gitlab.gnome.org/GNOME/gnome-shell/-/blob/main/js/misc/inputMethod.js).

## License

[MIT](LICENSE). An independent implementation inspired by the macOS interaction,
with no affiliation with Apple.
