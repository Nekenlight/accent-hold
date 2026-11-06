import unittest

from accent_hold.core import (
    AccentComposer, CancelTimer, Candidates, Commit, ForwardKey, HideCandidates,
    Key, Preedit, StartTimer,
)
from accent_hold.variants import VARIANTS, variants_for


class ComposerTests(unittest.TestCase):
    def setUp(self):
        self.core = AccentComposer()

    def press(self, name="e", code=26, **kwargs):
        return self.core.key(Key(name, code, **kwargs))

    def release(self, name="e", code=26):
        return self.press(name, code, release=True)

    def menu(self, name="e", code=26):
        start = self.press(name, code)
        token = next(a.token for a in start.actions if isinstance(a, StartTimer))
        return self.core.timeout(token)

    def commits(self, result):
        return [a.text for a in result.actions if isinstance(a, Commit)]

    def test_quick_tap_forwards_keys_without_composition(self):
        start = self.press()
        self.assertTrue(start.handled)
        self.assertFalse(any(isinstance(a, Preedit) for a in start.actions))
        self.assertIn(StartTimer(1, 500), start.actions)
        self.assertEqual(self.commits(start), [])
        end = self.release()
        self.assertEqual(self.commits(end), [])
        self.assertEqual([a.key for a in end.actions if isinstance(a, ForwardKey)],
                         [Key("e", 26), Key("e", 26, release=True)])
        self.assertFalse(any(isinstance(a, Preedit) for a in end.actions))
        self.assertIn(CancelTimer(), end.actions)

    def forwarded(self, result):
        return [a.key.name for a in result.actions
                if isinstance(a, ForwardKey) and not a.key.release]

    def test_fast_typing_preserves_order(self):
        output = []
        for name, code in [("e", 26), ("a", 38), ("e", 26)]:
            output.extend(self.forwarded(self.press(name, code)))
            output.extend(self.forwarded(self.release(name, code)))
        self.assertEqual("".join(output), "eae")

    def test_forwarding_preserves_press_and_release_metadata(self):
        press = Key("a", 38, keyval=97, state=16)
        release = Key("a", 38, release=True, keyval=97, state=1 << 30)
        self.core.key(press)
        self.assertEqual(self.core.key(release).actions,
                         (CancelTimer(), ForwardKey(press), ForwardKey(release)))

    def test_uppercase_taps_commit_exact_case_without_forwarding_or_preedit(self):
        for letter in VARIANTS:
            with self.subTest(letter=letter):
                self.core.key(Key(letter.upper(), 38, keyval=ord(letter.upper()), state=1))
                self.release("Shift_L", 50)
                result = self.release(letter, 38)
                self.assertEqual(result.actions, (CancelTimer(), Commit(letter.upper())))
                self.assertIsNone(self.core.pending)

    def test_overlapping_uppercase_commits_once_and_swallows_release(self):
        self.press("A", 38)
        result = self.press("e", 26)
        self.assertEqual(self.commits(result), ["A"])
        self.assertEqual(self.forwarded(result), [])
        self.assertEqual(self.release("a", 38).actions, ())
        self.assertEqual(self.forwarded(self.release("e", 26)), ["e"])

    def test_overlapping_forwarded_key_suppresses_repeat_until_release(self):
        self.press()
        self.press("a", 38)
        self.assertEqual(self.press().actions, ())
        self.assertEqual(self.release().actions, (ForwardKey(Key("e", 26, release=True)),))
        self.assertEqual(self.forwarded(self.release("a", 38)), ["a"])

    def test_rolling_keys_forward_before_next_timer(self):
        self.press()
        result = self.press("a", 38)
        self.assertLess(result.actions.index(ForwardKey(Key("e", 26))),
                        result.actions.index(StartTimer(2, 500)))
        self.release("e", 26)
        self.assertEqual(self.forwarded(self.release("a", 38)), ["a"])

    def test_identical_letters_after_release_are_not_repeat(self):
        self.press()
        first = self.release()
        self.press()
        second = self.release()
        self.assertEqual(self.forwarded(first) + self.forwarded(second), ["e", "e"])

    def test_repeats_before_and_after_timeout_are_absorbed(self):
        self.press()
        for _ in range(8):
            self.assertEqual(self.press().actions, ())
        self.assertTrue(self.core.timeout(1).handled)
        for _ in range(8):
            self.assertEqual(self.press().actions, ())
        self.assertEqual(self.commits(self.release()), [])
        self.assertTrue(self.core.pending.menu)

    def test_number_selects_and_swallows_release(self):
        self.menu()
        result = self.press("2", 11)
        self.assertEqual(self.commits(result), ["é"])
        self.assertTrue(self.release("2", 11).handled)
        self.assertTrue(self.press().handled)  # Initial letter still held.
        self.assertEqual(self.press().actions, ())
        self.release()
        self.assertIn(StartTimer(2, 500), self.press().actions)

    def test_release_keeps_menu_and_mouse_selection_works(self):
        self.menu()
        self.release()
        self.assertEqual(self.commits(self.core.choose(2)), ["ê"])
        self.assertFalse(self.core.choose(2).handled)

    def test_arrows_wrap_and_enter_selects(self):
        self.menu()
        self.release()
        result = self.press("Left", 113)
        self.assertIn(Candidates(variants_for("e"), 7), result.actions)
        self.release("Left", 113)
        self.assertEqual(self.commits(self.press("Return", 36)), ["ě"])

    def test_same_letter_cycles_and_wraps_without_committing(self):
        self.menu()
        self.release()
        for index in range(1, len(variants_for("e")) + 1):
            result = self.press()
            self.assertTrue(result.handled)
            self.assertEqual(result.actions, (Candidates(variants_for("e"), index % 8),))
            self.assertTrue(self.release().handled)
        self.assertEqual(self.commits(self.press("Return", 36)), ["è"])

    def test_cycling_requires_distinct_presses_not_autorepeat(self):
        self.menu()
        self.release()
        self.press()
        for _ in range(8):
            self.assertEqual(self.press().actions, ())
        self.release()
        self.assertEqual(self.commits(self.press("Return", 36)), ["é"])

    def test_cycling_uppercase_after_shift_release_and_cancel(self):
        self.menu("E")
        self.release("e")
        result = self.press("e")
        self.assertIn(Candidates(variants_for("E"), 1), result.actions)
        self.release("e")
        self.assertEqual(self.commits(self.press("Escape", 9)), ["E"])

    def test_escape_and_ordinary_typing_keep_base(self):
        self.menu()
        self.release()
        self.assertEqual(self.commits(self.press("Escape", 9)), ["e"])
        self.release("Escape", 9)
        self.menu()
        self.release()
        result = self.press("b", 56)
        self.assertFalse(result.handled)
        self.assertEqual(self.commits(result), ["e"])

    def test_unsupported_number_is_forwarded(self):
        self.menu()
        result = self.press("9", 18)
        self.assertFalse(result.handled)
        self.assertEqual(self.commits(result), ["e"])

    def test_uppercase_and_shift_release(self):
        self.menu("E")
        self.assertFalse(self.press("Shift_L", 50, modifier=True).handled)
        self.assertFalse(self.release("Shift_L", 50).handled)
        self.release("e")  # Same physical key, different symbol after Shift.
        self.assertEqual(self.commits(self.core.choose(1)), ["É"])

    def test_shortcut_flushes_base_and_passes(self):
        self.press()
        result = self.press("c", 54, shortcut=True)
        self.assertFalse(result.handled)
        self.assertEqual(self.forwarded(result), ["e"])
        self.assertFalse(self.press("e", 26, shortcut=True).actions)

    def test_reset_cancels_without_committing_or_stale_timer(self):
        self.press()
        result = self.core.reset()
        self.assertEqual(self.commits(result), [])
        self.assertEqual(result.actions, (CancelTimer(),))
        self.assertFalse(self.core.timeout(1).handled)
        self.press("a", 38)
        self.assertFalse(self.core.timeout(1).handled)
        self.assertTrue(self.core.timeout(2).handled)

    def test_missing_capability_does_not_intercept(self):
        result = self.core.key(Key("e", 26), eligible=False)
        self.assertFalse(result.handled)
        self.assertEqual(result.actions, ())

    def test_tables_fit_number_shortcuts_and_uppercase(self):
        for base, values in VARIANTS.items():
            for letter in (base, base.upper()):
                variants = variants_for(letter)
                self.assertLessEqual(len(variants), 9)
                self.assertEqual(len(variants), len(set(variants)))
                self.assertNotIn(letter, variants)
                self.assertTrue(all(len(v) == 1 for v in variants))


if __name__ == "__main__":
    unittest.main()
