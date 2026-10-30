"""Ordered, single-character Latin alternatives (at most nine per letter)."""

VARIANTS = {
    "a": tuple("àáâäãåāæą"),
    "c": tuple("çćčċ"),
    "d": tuple("ďđ"),
    "e": tuple("èéêëēėęě"),
    "g": tuple("ğģġ"),
    "i": tuple("ìíîïīįı"),
    "l": tuple("łĺľ"),
    "n": tuple("ñńňņ"),
    "o": tuple("òóôöõøōœő"),
    "r": tuple("řŕŗ"),
    "s": tuple("śšşș"),
    "t": tuple("ťţț"),
    "u": tuple("ùúûüūůűų"),
    "y": tuple("ýÿ"),
    "z": tuple("źžż"),
}


def variants_for(letter: str) -> tuple[str, ...]:
    variants = VARIANTS.get(letter.lower(), ())
    if letter.isupper():
        # Some Unicode uppercase mappings collapse to the base or to each other.
        return tuple(dict.fromkeys(v.upper() for v in variants if v.upper() != letter))
    return variants
