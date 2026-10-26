from . import rules
from .advisor import advise
from .evidence import validate_signals
from .llm import NemotronClient
from .models import Turn, Verdict
from .scorer import score
from .search import TavilyClient
from .taxonomy import TACTIC_QUERIES

SOURCES_PER_TACTIC = 2


class CallSession:
    """Stateful orchestration; extraction/scoring remain pure and app-friendly."""
    def __init__(self, llm: NemotronClient | None = None, search: TavilyClient | None = None) -> None:
        self.llm = llm or NemotronClient()
        self.search = search or TavilyClient()
        self.transcript: list[Turn] = []
        self._source_cache: dict[str, list] = {}
        self.last_verdict = score([], [])
        self.family_alerted = False

    def on_turn(self, turn: Turn) -> Verdict:
        self.transcript.append(turn)
        if turn.speaker != "caller":
            return self.last_verdict
        try:
            raw_signals = self.llm.extract_signals(self.transcript)
            signals_source = self.llm.last_extract_source
        except Exception:
            raw_signals = rules.extract_signals(self.transcript)
            signals_source = "rules"
        signals = validate_signals(raw_signals, self.transcript)
        for tactic in sorted({signal.tactic for signal in signals}):
            if tactic not in self._source_cache:
                try:
                    self._source_cache[tactic] = self.search.search(TACTIC_QUERIES[tactic])
                except Exception:
                    self._source_cache[tactic] = []
        sources = []
        for tactic in sorted({s.tactic for s in signals}):
            # One page often covers several tactics; show it once, with the first tactic's snippet.
            # Only the top results per tactic: lower-ranked hits are often only loosely related.
            fresh = [source for source in self._source_cache.get(tactic, []) if source.url not in {seen.url for seen in sources}]
            sources += fresh[:SOURCES_PER_TACTIC]
        verdict = score(signals, sources)
        verdict.signals_source = signals_source
        texts = advise(self.llm, verdict, self.transcript)
        self.last_verdict = verdict.model_copy(update=texts)
        return self.last_verdict
