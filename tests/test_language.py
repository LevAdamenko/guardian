import json
from pathlib import Path

from guardian.advisor import _fallback, advise
from guardian.language import detect_language
from guardian.llm import NemotronClient
from guardian.models import Level, Signal, Source, Turn, Verdict
from guardian.pipeline import CallSession

ROOT = Path(__file__).resolve().parents[1]


def test_detect_language_en():
    assert detect_language("Hello, this is a call from your bank to verify an appointment.") == "en"
    assert detect_language("I need to check my balance at the branch.") == "en"
    assert detect_language("Good afternoon, how can I help you today?") == "en"
    assert detect_language("") == "en"


def test_detect_language_pl_with_diacritics():
    assert detect_language("To wygląda na oszustwo. Rozłącz się teraz.") == "pl"
    assert detect_language("Dzień dobry, z tej strony policja.") == "pl"
    assert detect_language("Proszę natychmiast przelać pieniądze na bezpieczne konto.") == "pl"
    assert detect_language("Zadzwoń do banku i zablokuj kartę.") == "pl"


def test_detect_language_pl_without_diacritics():
    assert detect_language("Babciu, to ja, wnuczek, potrzebuje pieniedzy szybko") == "pl"
    assert detect_language("Prosze zrob przelew na to konto bankowe") == "pl"
    assert detect_language("Dzwoni policja w sprawie pana pieniedzy") == "pl"


def test_polish_scam_fallback_callsession():
    session = CallSession()
    # A Polish text flagged by rules with authority, urgency, safe account, and money transfer
    turn = Turn(
        speaker="caller",
        text="Dzwoni policjant z CBSP. Prosze natychmiast przelac pieniadze na bezpieczne konto.",
        t=0.0,
    )
    verdict = session.on_turn(turn)
    assert verdict.level == Level.SCAM
    assert verdict.signals_source == "rules"
    assert verdict.advice_source == "fallback"
    assert verdict.advice_language == "pl"
    assert detect_language(verdict.warning) == "pl"
    assert "oszustwo" in verdict.warning.lower()
    assert len(verdict.warning.split()) <= 25
    assert verdict.safe_action
    assert detect_language(verdict.safe_action) == "pl"
    assert verdict.relative_alert
    assert "Guardian wykrył ryzyko" in verdict.relative_alert


def test_english_scam_fallback_callsession():
    session = CallSession()
    # An English text that is not in recorded fixtures, triggering rules and fallback
    turn = Turn(
        speaker="caller",
        text="This is officer Smith from the police. Transfer your money immediately to our safe account.",
        t=0.0,
    )
    verdict = session.on_turn(turn)
    assert verdict.level == Level.SCAM
    assert verdict.signals_source == "rules"
    assert verdict.advice_source == "fallback"
    assert verdict.advice_language == "en"
    assert "This looks like a scam" in verdict.warning
    assert len(verdict.warning.split()) <= 25


def test_advise_request_excludes_advice_language():
    verdict_pl = Verdict(
        level=Level.CAUTION,
        score=5,
        warning="Be careful.",
        relative_alert="Alert.",
        safe_action="Action.",
        advice_source="fallback",
        advice_language="pl",
    )
    transcript = [Turn(speaker="caller", text="Hello", t=0.0)]
    req_pl = NemotronClient.advise_request(verdict_pl, transcript)

    # Must exclude advice_language and signals_source
    assert "advice_language" not in req_pl["verdict"]
    assert "signals_source" not in req_pl["verdict"]

    verdict_en = verdict_pl.model_copy(update={"advice_language": "en"})
    req_en = NemotronClient.advise_request(verdict_en, transcript)
    assert req_pl == req_en


def test_scenarios_replay_unbroken():
    scenarios_dir = ROOT / "scenarios"
    scam_scenarios = {"blik_friend", "fake_bank_anydesk", "fake_police", "grandson_accident"}

    for path in sorted(scenarios_dir.glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        session = CallSession()
        last_verdict = None
        for turn_data in scenario["turns"]:
            last_verdict = session.on_turn(Turn(**turn_data))

        assert last_verdict is not None
        if scenario["id"] in scam_scenarios:
            assert last_verdict.level == Level.SCAM
            assert last_verdict.advice_source != "fallback", f"Advice source was fallback for {scenario['id']}"
            assert last_verdict.advice_language == "en"


def test_fallback_polish_and_english_levels():
    for level in (Level.SAFE, Level.CAUTION, Level.SCAM):
        signals = []
        sources = []
        if level == Level.CAUTION:
            signals = [Signal(tactic="impersonation_authority", quote="policjant", explanation="Claims authority")]
        elif level == Level.SCAM:
            signals = [
                Signal(tactic="impersonation_authority", quote="policjant", explanation="Claims authority"),
                Signal(tactic="money_transfer_request", quote="przelac pieniadze", explanation="Money transfer"),
            ]
            sources = [Source(url="https://policja.pl/warning", snippet="official warning")]

        v = Verdict(
            level=level,
            score=0 if level == Level.SAFE else (5 if level == Level.CAUTION else 10),
            signals=signals,
            sources=sources,
        )
        fb_pl = _fallback(v, language="pl")
        assert fb_pl["advice_language"] == "pl"
        assert len(fb_pl["warning"].split()) <= 25
        fb_en = _fallback(v, language="en")
        assert fb_en["advice_language"] == "en"
        assert len(fb_en["warning"].split()) <= 25
        if level != Level.SAFE:
            assert "impersonation authority" in fb_pl["relative_alert"]
            assert "impersonation authority" in fb_en["relative_alert"]
