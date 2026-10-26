"""Frozen acceptance test (written by the reviewer, do not edit): unseen text in replay mode.

None of these texts has a recorded Nemotron fixture, so replay must fall back to the offline
rule-based detector. Sources still come from the recorded live Tavily fixtures, so a SCAM
verdict stays evidence-gated. Benign texts must never become SCAM.
"""
import json
from pathlib import Path

import pytest

from guardian.models import Level, Turn
from guardian.pipeline import CallSession

ROOT = Path(__file__).resolve().parents[1]

SCAMS = [
    "Grandma, it's me, your grandson. I had an accident and I need money right now. A courier will come to pick up the cash, please don't tell mum.",
    "This is officer Nowak from the Central Bureau of Investigation. Your savings are in danger, you must transfer them to a safe account today.",
    "Hello, I'm calling from your bank's security department. Please install AnyDesk so we can protect your account.",
    "Dzień dobry, tu policja, CBŚP. Pani pieniądze są zagrożone, proszę natychmiast przelać je na bezpieczne konto i nikomu o tym nie mówić.",
    "Cześć babciu, to ja, twój wnuczek. Miałem wypadek, potrzebuję pilnie pieniędzy, przyjdzie po nie kurier.",
    "Hej, tu Ania, pilnie potrzebuję pomocy, wyślij mi kod BLIK z aplikacji bankowej.",
    "Your account has been suspended. Log in at http://secure-bank-login.example and enter your password and PIN within 2 hours.",
]

BENIGN = [
    "Hi Grandpa, it's Tom. Are we still on for the football match on Saturday?",
    "Reminder from your bank: your branch appointment is on Tuesday at 10:00.",
    "Dzień dobry, przypominam o wizycie u lekarza w czwartek o 9:00.",
    "Your parcel will be delivered tomorrow between 9 and 12. No action needed.",
    "Mum, I'll be late tonight, the train is delayed. Love you.",
]


def check(text: str):
    return CallSession().on_turn(Turn(speaker="caller", text=text, t=0))


@pytest.mark.parametrize("text", SCAMS)
def test_unseen_scam_is_caught_offline(monkeypatch, text: str) -> None:
    monkeypatch.setenv("LIVE", "0")
    verdict = check(text)
    assert verdict.signals_source == "rules"
    assert verdict.level == Level.SCAM, [s.tactic for s in verdict.signals]
    assert all(s.quote in text for s in verdict.signals)
    assert verdict.sources and not any(source.seeded for source in verdict.sources)
    assert verdict.advice_source == "fallback"


@pytest.mark.parametrize("text", BENIGN)
def test_unseen_benign_text_is_not_an_alarm(monkeypatch, text: str) -> None:
    monkeypatch.setenv("LIVE", "0")
    verdict = check(text)
    assert verdict.signals_source == "rules"
    assert verdict.level != Level.SCAM, [s.tactic for s in verdict.signals]


def test_recorded_examples_still_use_nemotron(monkeypatch) -> None:
    monkeypatch.setenv("LIVE", "0")
    for example in json.loads((ROOT / "messages" / "examples.json").read_text(encoding="utf-8")):
        assert check(example["text"]).signals_source == "nemotron", example["id"]
    scenario = json.loads((ROOT / "scenarios" / "fake_police.json").read_text(encoding="utf-8"))
    session = CallSession()
    for raw in scenario["turns"]:
        verdict = session.on_turn(Turn(**raw))
    assert verdict.signals_source == "nemotron" and verdict.level == Level.SCAM


def test_api_message_explains_offline_rules(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from guardian.app import app
    monkeypatch.setenv("LIVE", "0")
    body = TestClient(app).post("/api/message", json={"text": SCAMS[5]}).json()
    assert body["verdict"]["level"] == "SCAM"
    assert "rule" in body["note"].lower() and "SAFE" not in body["note"]
