"""Language detection for elderly advice and spoken warnings."""
import re
from typing import Literal

POLISH_DIACRITICS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")

COMMON_POLISH_WORDS = {
    "jest",
    "nie",
    "pan",
    "pani",
    "się",
    "sie",
    "że",
    "ze",
    "babciu",
    "dziadku",
    "policja",
    "pieniądze",
    "pieniadze",
    "pieniędzy",
    "pieniedzy",
    "konto",
    "przelew",
    "kod",
    "proszę",
    "prosze",
    "szybko",
    "wnuczek",
    "wnuczka",
    "bank",
}


def detect_language(text: str) -> Literal["en", "pl"]:
    """Detect whether text is Polish ("pl") or English ("en")."""
    if any(char in POLISH_DIACRITICS for char in text):
        return "pl"
    words = re.findall(r"\b\w+\b", text.casefold())
    matches = [w for w in words if w in COMMON_POLISH_WORDS]
    unique_matches = set(matches)
    if len(unique_matches) >= 2 or any(matches.count(w) >= 2 for w in unique_matches if w not in {"bank", "pan"}):
        return "pl"
    return "en"
