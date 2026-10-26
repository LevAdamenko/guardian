"""Deterministic bilingual evidence extraction for unavailable model responses."""
import re
import unicodedata

from .llm import TACTIC_DEFINITIONS
from .models import Signal, Turn


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold().replace("ł", "l"))
                   if unicodedata.category(c) != "Mn")


_PATTERNS = {
    "impersonation_authority": r"\b(?:police|officer|investigator|prosecutor|policja|policjant\w*|prokurator\w*|cbsp)\b",
    "impersonation_bank": r"\b(?:from your bank|bank(?:'s)? security department|dzial bezpieczenstwa banku|konsultant banku)\b",
    "urgency_pressure": r"\b(?:right now|immediately|urgently|today|within \d+ hours?|natychmiast|pilnie|szybko|dzisiaj)\b",
    "secrecy_request": r"\b(?:don['’]?t tell|do not tell|keep (?:this|it) (?:a )?secret|nikomu\b[^.!?;]*\b(?:mow\w*|powiedz\w*)|tajemnic\w*)\b",
    "money_transfer_request": r"\b(?:transfer|send money|send\b[^.!?;]*\bmoney|wire|przelej|przelac|przelew\w*|wplac\w*)\b",
    "cash_handover_courier": r"\b(?:courier|pick up the cash|kurier\w*|odbierze gotowke)\b",
    "blik_code_request": r"\bblik\b",
    "credentials_request": r"\b(?:password|pin|cvv|card number|login|log in|hasl\w*|kod(?!\s+blik\b)|numer karty)\b",
    "remote_access_install": r"\b(?:anydesk|teamviewer|quicksupport|remote access|zdalny pulpit|zainstaluj)\b",
    "safe_account": r"\b(?:safe account|secure account|bezpieczne konto)\b",
}
_PATTERNS = {name: re.compile(pattern) for name, pattern in _PATTERNS.items()}
_FAMILY = re.compile(r"\b(?:grandson|granddaughter|it['’]?s me|wnuczek|wnuczka|to ja)\b")
_TROUBLE = re.compile(r"\b(?:trouble|accident|help|need money|danger|arrest\w*|wypad\w*|pomoc\w*|potrzeb\w*|klopot\w*|problem\w*)\b")


def _word_count(text: str) -> int:
    return min(len(text.split()), len(re.findall(r"\b\w+\b", text)))


def extract_signals(transcript: list[Turn]) -> list[Signal]:
    """Return verbatim caller clauses, expanding short clauses to their sentence.

    Folding is used only for matching; quotes always retain the original spelling.
    Family identity requires trouble elsewhere in the same caller utterance.
    """
    result = []
    for index, turn in enumerate(transcript):
        if turn.speaker != "caller":
            continue
        folded_turn = _fold(turn.text)
        trouble = bool(_TROUBLE.search(folded_turn))
        cash_context = bool(re.search(r"\b(?:cash|money|gotow\w*|pieniedz\w*|pieniadz\w*)\b", folded_turn))
        for sentence_match in re.finditer(r"[^.!?\n]+(?:[.!?]+|$)", turn.text):
            sentence = sentence_match.group().strip()
            for clause in re.split(r"[,;:]", sentence):
                clause = clause.strip()
                folded = _fold(clause)
                tactics = [name for name, pattern in _PATTERNS.items() if pattern.search(folded)]
                if not cash_context and "cash_handover_courier" in tactics:
                    tactics.remove("cash_handover_courier")
                if trouble and _FAMILY.search(folded):
                    tactics.append("impersonation_family")
                quote = clause if _word_count(clause) >= 3 else sentence
                if _word_count(quote) < 3:
                    continue
                for tactic in tactics:
                    signal = Signal(tactic=tactic, quote=quote,
                                    explanation=TACTIC_DEFINITIONS[tactic], turn_index=index)
                    if signal not in result:
                        result.append(signal)
    return result
