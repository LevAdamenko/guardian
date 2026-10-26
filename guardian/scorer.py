"""Pure, explainable scoring. Thresholds are deliberately conservative."""
from .models import Level, Signal, Source, Verdict
from .taxonomy import COMBINATION_BONUSES, TACTICS, is_official_domain

CAUTION_THRESHOLD = 3
SCAM_THRESHOLD = 6


def score(signals: list[Signal], sources: list[Source]) -> Verdict:
    """Score each tactic once; >=3 cautions, >=6 may be SCAM only with the model guard evidence."""
    tactics = {signal.tactic for signal in signals}
    total = sum(TACTICS[tactic] for tactic in tactics)
    total += sum(bonus for required, bonus in COMBINATION_BONUSES if required <= tactics)
    if total < CAUTION_THRESHOLD:
        level = Level.SAFE
    elif total < SCAM_THRESHOLD:
        level = Level.CAUTION
    elif len(tactics) >= 2 and any(is_official_domain(source.domain) for source in sources):
        level = Level.SCAM
    else:
        level = Level.CAUTION
    return Verdict(level=level, score=total, signals=signals, sources=sources)
