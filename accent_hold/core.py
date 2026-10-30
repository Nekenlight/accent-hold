"""Desktop-independent state machine. Timers and UI effects belong to adapters."""

from dataclasses import dataclass

from .variants import variants_for


@dataclass(frozen=True)
class Key:
    name: str
    code: int  # Physical identity, stable across modifier changes.
    release: bool = False
    shortcut: bool = False
    modifier: bool = False


@dataclass(frozen=True)
class Preedit:
    text: str


@dataclass(frozen=True)
class Commit:
    text: str


@dataclass(frozen=True)
class Candidates:
    values: tuple[str, ...]
    selected: int = 0


@dataclass(frozen=True)
class HideCandidates:
    pass


@dataclass(frozen=True)
class StartTimer:
    token: int
    delay_ms: int


@dataclass(frozen=True)
class CancelTimer:
    pass


Action = Preedit | Commit | Candidates | HideCandidates | StartTimer | CancelTimer


@dataclass(frozen=True)
class Result:
    handled: bool = False
    actions: tuple[Action, ...] = ()


@dataclass
class Pending:
    letter: str
    code: int
    variants: tuple[str, ...]
    token: int
    held: bool = True
    menu: bool = False
    selected: int = 0


class AccentComposer:
    def __init__(self, hold_ms: int = 500):
        if hold_ms <= 0:
            raise ValueError("hold_ms must be positive")
        self.hold_ms = hold_ms
        self.pending: Pending | None = None
        self._serial = 0
        self._consumed: set[int] = set()

    def key(self, event: Key, *, eligible: bool = True) -> Result:
        actions: list[Action] = []
        if event.release:
            if event.code not in self._consumed:
                return Result()
            self._consumed.remove(event.code)
            if self.pending and event.code == self.pending.code:
                self.pending.held = False
                if not self.pending.menu:
                    actions.extend(self._finish(self.pending.letter))
            return Result(True, tuple(actions))

        # Includes repeats after selection while the original letter is held.
        if event.code in self._consumed:
            return Result(True)
        if event.modifier and not event.shortcut:
            return Result()
        if event.shortcut:
            if self.pending:
                actions.extend(self._finish(self.pending.letter))
            return Result(False, tuple(actions))

        pending = self.pending
        if pending:
            if pending.menu:
                cycle_letter = event.name.casefold() == pending.letter.casefold()
                if cycle_letter or event.name in ("Left", "Right", "Up", "Down"):
                    delta = -1 if event.name in ("Left", "Up") else 1
                    pending.selected = (pending.selected + delta) % len(pending.variants)
                    self._consumed.add(event.code)
                    return Result(True, (Candidates(pending.variants, pending.selected),))
                index = pending.selected if event.name in ("Return", "KP_Enter") else -1
                if event.name in tuple("123456789"):
                    index = int(event.name) - 1
                if 0 <= index < len(pending.variants):
                    self._consumed.add(event.code)
                    return Result(True, tuple(self._finish(pending.variants[index])))
                if event.name == "Escape":
                    self._consumed.add(event.code)
                    return Result(True, tuple(self._finish(pending.letter)))
            actions.extend(self._finish(pending.letter))

        variants = variants_for(event.name) if len(event.name) == 1 else ()
        if eligible and variants:
            self._serial += 1
            self.pending = Pending(event.name, event.code, variants, self._serial)
            self._consumed.add(event.code)
            actions.extend((Preedit(event.name), StartTimer(self._serial, self.hold_ms)))
            return Result(True, tuple(actions))
        return Result(False, tuple(actions))

    def timeout(self, token: int) -> Result:
        pending = self.pending
        if not pending or pending.token != token or not pending.held or pending.menu:
            return Result()
        pending.menu = True
        return Result(True, (Candidates(pending.variants),))

    def choose(self, index: int) -> Result:
        pending = self.pending
        if not pending or not pending.menu or not 0 <= index < len(pending.variants):
            return Result()
        return Result(True, tuple(self._finish(pending.variants[index])))

    def reset(self) -> Result:
        """Discard uncommitted text; never commit into a different focus target."""
        self._consumed.clear()
        return Result(False, tuple(self._finish(None)))

    def _finish(self, text: str | None) -> list[Action]:
        if not self.pending:
            return []
        self.pending = None
        actions: list[Action] = [CancelTimer(), HideCandidates(), Preedit("")]
        if text is not None:
            actions.append(Commit(text))
        return actions
