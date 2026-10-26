"""Nebius-compatible client with deterministic replay for every request."""
import hashlib
import json
from pathlib import Path
from typing import Any

from .config import live_enabled, load_config
from .models import Signal, Turn, Verdict
from .taxonomy import TACTICS


TACTIC_DEFINITIONS = {
    "impersonation_authority": "Pretends to be police, government, or another authority.",
    "impersonation_bank": "Pretends to represent a bank or its security team.",
    "impersonation_family": "Pretends to be, or speak for, a family member.",
    "urgency_pressure": "Pressures the person to act immediately.",
    "secrecy_request": "Asks the person to keep the matter secret.",
    "money_transfer_request": "Asks the person to transfer money.",
    "cash_handover_courier": "Asks for cash to be handed to a courier.",
    "blik_code_request": "Asks for a BLIK code from a banking app.",
    "credentials_request": "Asks for passwords, login details, or other credentials.",
    "remote_access_install": "Asks the person to install remote-access software.",
    "safe_account": "Uses a supposed safe account as the destination for money.",
}
assert set(TACTIC_DEFINITIONS) == set(TACTICS), "prompt taxonomy must match TACTICS"

_TAXONOMY_PROMPT = "\n".join(f"- {name}: {definition}" for name, definition in TACTIC_DEFINITIONS.items())
EXTRACT_SYSTEM_PROMPT = f"""You extract scam evidence from phone-call transcripts for Guardian.

Use only this closed taxonomy:
{_TAXONOMY_PROMPT}

Rules:
- Consider caller turns only. A quote must be a verbatim contiguous substring of one caller utterance and contain at least 3 words.
- Do not invent tactics, quotes, or facts. Return no signals for benign calls. Assess cumulatively over the whole transcript.
- Output exactly this JSON shape: {{"signals":[{{"tactic":"...","quote":"...","explanation":"..."}}]}}.

Example scam input: caller: "I am from your bank. Install AnyDesk now so I can secure your account."
Example scam output: {{"signals":[{{"tactic":"impersonation_bank","quote":"from your bank","explanation":"Claims to represent a bank."}},{{"tactic":"remote_access_install","quote":"Install AnyDesk now so I can secure your account","explanation":"Requests remote access software."}}]}}

Example benign input: caller: "Your branch appointment is Tuesday at ten."
Example benign output: {{"signals":[]}}"""

ADVISE_SYSTEM_PROMPT = """You write practical phone-scam advice for Guardian. The input contains a verdict (level, validated signals, and official sources) and a transcript. A transcript with a single caller turn at t=0 is a text message (SMS or WhatsApp), not a call: then say "message", not "call", and do not tell them to hang up.
Return exactly JSON: {"warning":"...","relative_alert":"...","safe_action":"..."}.
Write warning, relative_alert and safe_action in the same language as the transcript (Polish transcript -> Polish). The warning must be at most 25 words, use plain language for an elderly person, and address them in the second person. relative_alert is a short message to a family member; use gender-neutral "them" and mention the detected tactic or tactics. safe_action must be concrete. Never invent facts that are absent from the verdict. For SAFE, stay calm and do not imply a scam."""


class FixtureMissing(FileNotFoundError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fixture_path(fixtures_dir: Path, kind: str, request: dict[str, Any]) -> Path:
    digest = hashlib.sha256(canonical_json(request).encode("utf-8")).hexdigest()[:16]
    return fixtures_dir / f"{kind}-{digest}.json"


def read_fixture(fixtures_dir: Path, kind: str, request: dict[str, Any]) -> str:
    path = fixture_path(fixtures_dir, kind, request)
    if not path.exists():
        raise FixtureMissing(f"missing replay fixture: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))["content"]


def fixture_is_seeded(fixtures_dir: Path, kind: str, request: dict[str, Any]) -> bool:
    """Hand-authored fixtures must never be presented as model output."""
    path = fixture_path(fixtures_dir, kind, request)
    return path.exists() and json.loads(path.read_text(encoding="utf-8")).get("seeded") is True


class NemotronClient:
    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self.fixtures_dir = fixtures_dir or Path(__file__).resolve().parents[1] / "fixtures"
        self.last_advice_seeded = False
        self.last_extract_source = "nemotron"

    @staticmethod
    def extract_request(transcript: list[Turn]) -> dict[str, Any]:
        return {"transcript": [turn.model_dump() for turn in transcript]}

    @staticmethod
    def advise_request(verdict: Verdict, transcript: list[Turn]) -> dict[str, Any]:
        # Extraction provenance is API metadata; preserve recorded advice request keys.
        return {"verdict": verdict.model_dump(mode="json", exclude={"signals_source", "advice_language"}), "transcript": [turn.model_dump() for turn in transcript]}

    def _completion(self, request: dict[str, Any], kind: str, prompt: str, *, temperature: float | None = None) -> str:
        if not live_enabled():
            return read_fixture(self.fixtures_dir, kind, request)
        # Import and instantiate only in LIVE mode: replay cannot accidentally touch a network client.
        from openai import OpenAI
        config = load_config()
        client = OpenAI(api_key=config.get("NEBIUS_API_KEY"), base_url="https://api.tokenfactory.nebius.com/v1")
        options: dict[str, Any] = {
            "model": config.get("NEMOTRON_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": canonical_json(request)}],
            "response_format": {"type": "json_object"},
        }
        if temperature is not None:
            options["temperature"] = temperature
        response = client.chat.completions.create(**options)
        return response.choices[0].message.content or "{}"

    def extract_signals(self, transcript: list[Turn]) -> list[Signal]:
        request = self.extract_request(transcript)
        self.last_extract_source = "seeded" if not live_enabled() and fixture_is_seeded(self.fixtures_dir, "extract", request) else "nemotron"
        raw = self._completion(request, "extract", EXTRACT_SYSTEM_PROMPT, temperature=0)
        try:
            payload = json.loads(raw)
            items = payload.get("signals", payload if isinstance(payload, list) else [])
            if not isinstance(items, list):
                return []
            result = []
            for item in items:
                if not isinstance(item, dict) or item.get("tactic") not in TACTICS:
                    continue
                if not all(isinstance(item.get(field), str) and item[field].strip() for field in ("tactic", "quote", "explanation")):
                    continue
                result.append(Signal(tactic=item["tactic"], quote=item["quote"], explanation=item["explanation"]))
            return result
        except (json.JSONDecodeError, TypeError, ValueError):
            return []

    def advise(self, verdict: Verdict, transcript: list[Turn]) -> dict[str, str]:
        request = self.advise_request(verdict, transcript)
        self.last_advice_seeded = not live_enabled() and fixture_is_seeded(self.fixtures_dir, "advise", request)
        raw = self._completion(request, "advise", ADVISE_SYSTEM_PROMPT)
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict) or not all(isinstance(parsed.get(k), str) and parsed[k].strip() for k in ("warning", "relative_alert", "safe_action")):
                raise ValueError("malformed advice")
            return {key: parsed[key].strip() for key in ("warning", "relative_alert", "safe_action")}
        except (json.JSONDecodeError, TypeError, ValueError):
            raise ValueError("malformed advice response")
