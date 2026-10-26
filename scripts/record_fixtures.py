"""Explicit LIVE=1 workflow for recording reviewed provider responses."""
import argparse
import json
from pathlib import Path

from guardian.config import live_enabled, load_config
from guardian.llm import NemotronClient, canonical_json, fixture_path
from guardian.models import Turn
from guardian.pipeline import CallSession
from guardian.search import TavilyClient
from guardian.taxonomy import OFFICIAL_DOMAINS  # noqa: F401  (tests build requests with it)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"


def write(out: Path, kind: str, request: dict, content: str, model: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fixture_path(out, kind, request).write_text(json.dumps({"request": request, "content": content, "seeded": False, "model": model}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class RecordingNemotronClient(NemotronClient):
    def __init__(self, out: Path, model: str) -> None:
        super().__init__(out)
        self.out = out
        self.model = model

    def _completion(self, request, kind, prompt, *, temperature=None):
        content = super()._completion(request, kind, prompt, temperature=temperature)
        write(self.out, kind, request, content, self.model)
        return content


class RecordingTavilyClient(TavilyClient):
    # Queries are fixed per tactic, so one run needs each search once. The Tavily free tier is
    # small: share responses across all sessions of a run instead of paying for repeats.
    _run_cache: dict[str, str] = {}

    def __init__(self, out: Path, model: str) -> None:
        super().__init__(out)
        self.out = out
        self.model = model

    def _response_content(self, request):
        key = canonical_json(request)
        path = fixture_path(self.out, "search", request)
        if key not in self._run_cache and path.exists() and json.loads(path.read_text(encoding="utf-8")).get("seeded") is False:
            # Already recorded live: delete the file to pay for a fresh search.
            self._run_cache[key] = json.loads(path.read_text(encoding="utf-8"))["content"]
        if key not in self._run_cache:
            self._run_cache[key] = super()._response_content(request)
            write(self.out, "search", request, self._run_cache[key], self.model)
        return self._run_cache[key]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record LIVE Guardian fixtures for review.")
    parser.add_argument("--out", type=Path, default=ROOT / "fixtures")
    parser.add_argument("--scenario", help="record only this scenario ID")
    parser.add_argument("--message", help="record only this message example ID")
    args = parser.parse_args(argv)
    config = load_config()
    if not live_enabled() or not config.get("NEBIUS_API_KEY") or not config.get("TAVILY_API_KEY"):
        raise SystemExit("Recording requires LIVE=1 plus NEBIUS_API_KEY and TAVILY_API_KEY. Key values are never printed.")
    scenarios = {path.stem: path for path in (ROOT / "scenarios").glob("*.json")}
    examples = {example["id"]: example for example in json.loads((ROOT / "messages" / "examples.json").read_text(encoding="utf-8"))}
    if args.scenario and args.scenario not in scenarios:
        raise SystemExit(f"Unknown scenario: {args.scenario}")
    if args.message and args.message not in examples:
        raise SystemExit(f"Unknown message example: {args.message}")
    # With no filter, record everything the demo can replay: calls and message examples.
    record_all = not args.scenario and not args.message
    paths = [scenarios[args.scenario]] if args.scenario else [scenarios[key] for key in sorted(scenarios)] if record_all else []
    messages = [examples[args.message]] if args.message else [examples[key] for key in sorted(examples)] if record_all else []
    model = config.get("NEMOTRON_MODEL", DEFAULT_MODEL)
    for path in paths:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        session = CallSession(RecordingNemotronClient(args.out, model), RecordingTavilyClient(args.out, model))
        for raw_turn in scenario["turns"]:
            session.on_turn(Turn(**raw_turn))
    for example in messages:
        # Same call shape as POST /api/message, so the recorded keys match what the UI replays.
        session = CallSession(RecordingNemotronClient(args.out, model), RecordingTavilyClient(args.out, model))
        session.on_turn(Turn(speaker="caller", text=example["text"], t=0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
