from guardian.evidence import validate_signals
from guardian.models import Signal, Turn


def test_hallucinated_and_elder_quotes_are_dropped() -> None:
    transcript = [Turn(speaker="caller", text="Please send the BLIK code today", t=1), Turn(speaker="elder", text="I will install AnyDesk now", t=2)]
    signals = [
        Signal(tactic="blik_code_request", quote="give me your password now", explanation="hallucinated"),
        Signal(tactic="remote_access_install", quote="I will install AnyDesk now", explanation="elder said it"),
    ]
    assert validate_signals(signals, transcript) == []


def test_normalised_punctuation_case_match_is_accepted() -> None:
    transcript = [Turn(speaker="caller", text="PLEASE, send the BLIK code today!", t=1)]
    signal = Signal(tactic="blik_code_request", quote="please send THE blik code today", explanation="request")
    validated = validate_signals([signal], transcript)
    assert len(validated) == 1
    assert validated[0].turn_index == 0


def test_quote_is_rewritten_to_the_verbatim_caller_text() -> None:
    from guardian.evidence import validate_signal
    from guardian.models import Signal, Turn

    transcript = [Turn(speaker="caller", text="Hello!  Please, give me the BLIK code — now.", t=0)]
    signal = Signal(tactic="blik_code_request", quote="please give me the blik code", explanation="x")
    valid = validate_signal(signal, transcript)
    assert valid is not None
    assert valid.quote == "Please, give me the BLIK code"
    assert valid.quote in transcript[0].text
