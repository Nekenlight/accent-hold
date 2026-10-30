# Validation

Automated integration tests use a real IBus daemon on an isolated D-Bus session
without a display. They validate protocol behavior, not graphical rendering or
compatibility with every application.

## Automated coverage

| Behavior | Coverage |
|---|---|
| Quick taps, fast typing, overlapping keys and repeated identical letters | Core tests |
| Uppercase variants, numbers, arrows, direct selection and Escape | Core tests |
| Same-letter cycling, wraparound, Shift release and cancellation | Core tests |
| Timers, reset, stale expiration and missing preedit capability | Core tests |
| Installation, idempotence, uninstall and preservation of modified or added files | Temporary-directory installer tests |
| Key presses/releases, preedit signals and Unicode commits | Real IBus/D-Bus integration |
| Long press, suppressed repeat and selection after release | Real IBus/D-Bus integration |
| Same-letter cycling without autorepeat or extra text | Real IBus/D-Bus integration |
| Uppercase, arrows followed by Enter, Escape and Ctrl shortcuts | Real IBus/D-Bus integration |
| Dead keys and Compose | Real IBus simple engine |
| Reset/focus loss during a hold without a late commit | Real IBus/D-Bus integration |
| Password context and a client without preedit support | Real IBus/D-Bus integration |
| Installed XML descriptor, user registry cache and on-demand launch | Temporary installation and isolated IBus daemon |

Run from the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 tests/integration_ibus.py
python3 tests/integration_ibus.py --installed
```

The standard suite contains **23 tests**. Each integration mode runs **9
scenarios**. The test client sends synthetic symbols and releases through the
real protocol; this does not prove that a particular application forwards the
same events or that its candidate panel renders correctly.

## Graphical testing still needed

| Target | Status |
|---|---|
| GTK: GNOME Text Editor and GNOME search fields | Not verified graphically |
| Qt: Kate or a comparable text field | Not verified graphically |
| Firefox: input, textarea and contenteditable | Not verified graphically |
| Chromium: input, textarea and contenteditable | Not verified graphically |
| Electron: messaging or document fields | Not verified graphically |
| Physical AZERTY/QWERTZ keyboards, AltGr and multiple layouts | Not verified on physical keyboards |
| Native-panel clicks, positioning and display scaling | Not verified graphically; direct selection is covered in core tests |

## Manual checklist

For each target, record the application version, native Wayland or XWayland
session, and keyboard layout. Keep the normal input source available, select
Accent Hold, then check:

1. Type `ee cafe aeiou` quickly: no lost, duplicated or reordered characters.
2. Hold `e`: one temporary `e` appears, followed by the panel after about 500 ms,
   without a stream of `eeee`. Release the key: the menu stays open.
3. Choose `2`: the result is exactly `é`. Repeat using Right then Enter, then a
   mouse click on `é`.
4. Hold and release `e`, then tap `e` again: the highlight advances to `é`.
   Repeated taps cycle and wrap. Holding continuously does not advance it.
   Enter confirms exactly one accented character.
5. Hold `E` with Shift, then release Shift before the letter: select `É` without
   inserting another letter. Repeat using same-letter cycling after Shift release.
6. Hold `e`, then Escape: one `e` remains. Repeat and type `b`: the result is `eb`.
7. Check Ctrl+A/C/V, Alt/Super shortcuts, dead keys and Compose if configured.
8. Hold `e` and switch windows before and after the menu opens: no lingering
   panel or late insertion in the new window.
9. Check digits, punctuation and AltGr characters. Letters without variants and
   Backspace should still repeat normally.

A client that does not forward key releases does not meet the prototype's
requirements. Switch back to the regular input source and record the
incompatibility. Terminals, Vim, games, remote fields and other compositors are
outside the initial acceptance criteria. There is no automatic game exclusion.
