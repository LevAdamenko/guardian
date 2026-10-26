"""Offline command-line demonstration for judges and CI."""
import argparse
import json
import os
from pathlib import Path

from .models import Level, Turn
from .pipeline import CallSession


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="run replay fixtures (the default)")
    args = parser.parse_args(argv)
    if args.offline:
        os.environ["LIVE"] = "0"
    root = Path(__file__).resolve().parents[1]
    scam_detected = 0
    false_alarms = 0
    for path in sorted((root / "scenarios").glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        session = CallSession()
        first_caution = first_scam = None
        final = session.last_verdict
        for index, raw_turn in enumerate(scenario["turns"], start=1):
            final = session.on_turn(Turn(**raw_turn))
            if final.level in (Level.CAUTION, Level.SCAM) and first_caution is None:
                first_caution = index
            if final.level == Level.SCAM and first_scam is None:
                first_scam = index
        expected_scam = scenario["expected"] == "scam"
        scam_detected += int(expected_scam and final.level == Level.SCAM)
        false_alarms += int(not expected_scam and final.level == Level.SCAM)
        tactics = "; ".join(f"{s.tactic}: {s.quote}" for s in final.signals) or "none"
        urls = ", ".join(source.url for source in final.sources) or "none"
        print(f"{scenario['id']}: {final.level.value}; CAUTION turn={first_caution}; SCAM turn={first_scam}")
        print(f"  tactics: {tactics}")
        print(f"  sources: {urls}")
    print(f"scams detected: {scam_detected}/4, false alarms: {false_alarms}/2")
    return 0 if scam_detected == 4 and false_alarms == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
