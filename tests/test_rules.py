"""Unit coverage for deterministic bilingual fallback extraction."""
import json

import pytest

from guardian.llm import NemotronClient, TACTIC_DEFINITIONS, fixture_path
from guardian.models import Turn
from guardian.pipeline import CallSession
from guardian.rules import extract_signals
from guardian.taxonomy import TACTICS


EXAMPLES = {
    "impersonation_authority": ("This is officer Smith speaking.", "Dzień dobry tu policjant Nowak."),
    "impersonation_bank": ("I am from your bank.", "Dzwoni dział bezpieczeństwa banku do pani."),
    "impersonation_family": ("It's me your granddaughter, I had an accident.", "To ja twój wnuczek, miałem wypadek."),
    "urgency_pressure": ("You must act immediately.", "Proszę działać natychmiast teraz."),
    "secrecy_request": ("Please keep this secret.", "Proszę nikomu nie mówić."),
    "money_transfer_request": ("Please send money to us.", "Proszę przelać wszystkie pieniądze."),
    "cash_handover_courier": ("Our courier will collect the cash.", "Nasz kurier odbierze gotówkę."),
    "blik_code_request": ("Send your BLIK code please.", "Proszę wysłać kod BLIK."),
    "credentials_request": ("Please enter your password.", "Proszę podać swoje hasło."),
    "remote_access_install": ("Please install TeamViewer now.", "Proszę włączyć zdalny pulpit."),
    "safe_account": ("Use this safe account instead.", "To jest bezpieczne konto bankowe."),
}


@pytest.mark.parametrize("tactic,text", [(tactic, text) for tactic, texts in EXAMPLES.items() for text in texts])
def test_bilingual_tactics(tactic, text):
    transcript = [Turn(speaker="caller", text=text, t=0)]
    signals = extract_signals(transcript)
    assert tactic in {s.tactic for s in signals}
    assert signals == extract_signals(transcript)
    for signal in signals:
        assert signal.quote in text
        assert len(signal.quote.split()) >= 3
        assert signal.explanation == TACTIC_DEFINITIONS[signal.tactic]
    # The same patterns support ASCII Polish and case-insensitive text.
    import unicodedata
    ascii_text = "".join(c for c in unicodedata.normalize("NFD", text.replace("ł", "l")) if not unicodedata.combining(c))
    assert tactic in {s.tactic for s in extract_signals([Turn(speaker="caller", text=ascii_text.upper(), t=0)])}


def test_taxonomy_coverage():
    assert set(EXAMPLES) == set(TACTICS)


def test_short_clauses_expand_and_short_sentences_skip():
    text = "Act immediately, please do this. BLIK!"
    signals = extract_signals([Turn(speaker="caller", text=text, t=0)])
    assert [(s.tactic, s.quote) for s in signals] == [("urgency_pressure", "Act immediately, please do this.")]


def test_elder_turns_are_ignored():
    assert extract_signals([Turn(speaker="elder", text="Please send money immediately.", t=0)]) == []


@pytest.mark.parametrize("text", [
    "Reminder from your bank: appointment Tuesday.",
    "It's Tom, football on Saturday.",
    "A courier will deliver your parcel today.",
    "Your doctor's appointment is today at noon.",
    "Your grandson will visit today.",
])
def test_benign_mentions(text):
    signals = extract_signals([Turn(speaker="caller", text=text, t=0)])
    assert len({s.tactic for s in signals}) < 2


def test_outage_falls_back_without_network(monkeypatch):
    # Simulate the exception raised by the LIVE client without enabling networking.
    def outage(transcript):
        raise ConnectionError("Nemotron unavailable")

    client = NemotronClient()
    monkeypatch.setattr(client, "extract_signals", outage)
    monkeypatch.setattr(client, "advise", lambda *args: (_ for _ in ()).throw(ConnectionError()))
    class NoNetworkSearch:
        def search(self, query):
            return []
    session = CallSession(llm=client, search=NoNetworkSearch())
    verdict = session.on_turn(Turn(speaker="caller", text="Transfer your money right now.", t=0))
    assert verdict.signals_source == "rules"
    assert {s.tactic for s in verdict.signals} == {"money_transfer_request", "urgency_pressure"}
    assert session.on_turn(Turn(speaker="elder", text="Okay", t=1)) is verdict


@pytest.mark.parametrize("seeded,source", [(True, "seeded"), (False, "nemotron")])
def test_recorded_extraction_source(tmp_path, monkeypatch, seeded, source):
    monkeypatch.setenv("LIVE", "0")
    client = NemotronClient(tmp_path)
    transcript = [Turn(speaker="caller", text="Hello from your bank.", t=0)]
    path = fixture_path(tmp_path, "extract", client.extract_request(transcript))
    path.write_text(json.dumps({"content": '{"signals": []}', "seeded": seeded}))
    assert client.extract_signals(transcript) == []
    assert client.last_extract_source == source
