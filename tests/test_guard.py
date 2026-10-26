import pytest

from guardian.models import Level, Signal, Source, Verdict


def signal(tactic: str) -> Signal:
    return Signal(tactic=tactic, quote="three caller words", explanation="test")


def official() -> Source:
    return Source(url="https://policja.pl/warning", snippet="Official warning")


def test_scam_with_one_tactic_is_rejected() -> None:
    with pytest.raises(ValueError, match="SCAM requires"):
        Verdict(level=Level.SCAM, score=10, signals=[signal("blik_code_request")], sources=[official()])


def test_scam_without_official_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="SCAM requires"):
        Verdict(level=Level.SCAM, score=10, signals=[signal("blik_code_request"), signal("urgency_pressure")], sources=[Source(url="https://example.com/x", snippet="no")])


def test_lookalike_domain_does_not_count_as_official() -> None:
    with pytest.raises(ValueError, match="SCAM requires"):
        Verdict(level=Level.SCAM, score=10, signals=[signal("blik_code_request"), signal("urgency_pressure")], sources=[Source(url="https://policja.pl.evil.com/x", snippet="lookalike")])
