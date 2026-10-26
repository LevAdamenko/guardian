"""Deterministic verification of model-proposed evidence."""
import re
import unicodedata

from .models import Signal, Turn
from .taxonomy import TACTICS


def normalise(text: str) -> str:
    text = text.casefold()
    text = "".join(" " if unicodedata.category(char).startswith("P") else char for char in text)
    return re.sub(r"\s+", " ", text).strip()


def verbatim_span(quote: str, text: str) -> str | None:
    """Map a normalised quote back to the exact characters the caller said."""
    chars: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        piece = " " if unicodedata.category(char).startswith("P") else char.casefold()
        for part in piece:
            if part.isspace():
                if not chars or chars[-1] == " ":
                    continue
                part = " "
            chars.append(part)
            origin.append(index)
    at = "".join(chars).find(quote)
    if not quote or at < 0:
        return None
    return text[origin[at]:origin[at + len(quote) - 1] + 1]


def validate_signal(signal: Signal, transcript: list[Turn]) -> Signal | None:
    quote = normalise(signal.quote)
    if signal.tactic not in TACTICS or len(quote.split()) < 3:
        return None
    for index, turn in enumerate(transcript):
        if turn.speaker == "caller" and quote in normalise(turn.text):
            # The UI highlights by exact substring, so store what was actually said.
            exact = verbatim_span(quote, turn.text) or signal.quote
            return signal.model_copy(update={"turn_index": index, "quote": exact})
    return None


def validate_signals(signals: list[Signal], transcript: list[Turn]) -> list[Signal]:
    """Keep only closed-taxonomy quotes actually spoken by the caller."""
    result: list[Signal] = []
    seen: set[tuple[str, str]] = set()
    for signal in signals:
        valid = validate_signal(signal, transcript)
        key = (valid.tactic, normalise(valid.quote)) if valid else None
        if valid and key not in seen:
            result.append(valid)
            seen.add(key)
    return result
