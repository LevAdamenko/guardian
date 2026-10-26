import json
from pathlib import Path

from guardian.advisor import _fallback, advise
from guardian.demo import main
from guardian.llm import NemotronClient
from guardian.models import Level, Turn
from guardian.pipeline import CallSession
from guardian.scorer import score
from guardian.taxonomy import is_official_domain


ROOT = Path(__file__).resolve().parents[1]


def test_all_scenarios_end_to_end(monkeypatch) -> None:
    monkeypatch.setenv("LIVE", "0")
    for path in (ROOT / "scenarios").glob("*.json"):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        session = CallSession()
        verdict = session.last_verdict
        for raw in scenario["turns"]:
            verdict = session.on_turn(Turn(**raw))
            if raw["speaker"] == "caller":
                # Bundled fixtures are recorded LIVE from Nemotron; hand-seeded advice must not ship.
                assert verdict.advice_source == "nemotron", scenario["id"]
                assert verdict.warning != _fallback(verdict)["warning"]
        if scenario["expected"] == "scam":
            assert verdict.level == Level.SCAM, scenario["id"]
            # Replay sources are recorded LIVE from Tavily and must come from official domains.
            assert verdict.sources and not any(source.seeded for source in verdict.sources)
            assert all(is_official_domain(source.url) for source in verdict.sources)
            assert len({source.url for source in verdict.sources}) == len(verdict.sources)
            assert not any("/warnings/" in source.url or "paraphrase" in source.snippet.lower() for source in verdict.sources)
        else:
            assert verdict.level != Level.SCAM, scenario["id"]


def test_demo_returns_zero(monkeypatch) -> None:
    monkeypatch.setenv("LIVE", "0")
    assert main(["--offline"]) == 0


def test_advisor_fallback_is_short_when_fixture_is_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE", "0")
    verdict = score([], [])
    message = advise(NemotronClient(tmp_path), verdict, [])
    assert message["warning"]
    assert len(message["warning"].split()) <= 25
    assert message["advice_source"] == "fallback"


def test_sources_are_capped_per_tactic(monkeypatch) -> None:
    from guardian.models import Signal, Source
    from guardian.pipeline import SOURCES_PER_TACTIC

    class FakeLLM(NemotronClient):
        def extract_signals(self, transcript):
            return [Signal(tactic="blik_code_request", quote="send me the BLIK code", explanation="x"),
                    Signal(tactic="urgency_pressure", quote="do it right now", explanation="x")]

        def advise(self, verdict, transcript):
            return {"warning": "w", "relative_alert": "r", "safe_action": "a"}

    class FakeSearch:
        def search(self, query):
            return [Source(url=f"https://policja.pl/{abs(hash(query))}/{i}", title="t", snippet="s") for i in range(5)]

    session = CallSession(llm=FakeLLM(), search=FakeSearch())
    verdict = session.on_turn(Turn(speaker="caller", text="send me the BLIK code, do it right now", t=0))
    assert SOURCES_PER_TACTIC == 2 and len(verdict.sources) == 4
    assert verdict.level == Level.SCAM
