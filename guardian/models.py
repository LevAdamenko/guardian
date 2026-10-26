from enum import Enum
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from .taxonomy import TACTICS, is_official_domain


class Turn(BaseModel):
    speaker: Literal["caller", "elder"]
    text: str
    t: float


class Signal(BaseModel):
    tactic: str
    quote: str
    explanation: str
    turn_index: int | None = None

    @field_validator("tactic")
    @classmethod
    def tactic_is_closed(cls, tactic: str) -> str:
        if tactic not in TACTICS:
            raise ValueError("unknown tactic")
        return tactic


class Source(BaseModel):
    url: str
    title: str = ""
    snippet: str
    domain: str = ""
    # True when the result comes from a hand-picked replay fixture, not from Tavily.
    seeded: bool = False

    @model_validator(mode="after")
    def derive_domain(self) -> "Source":
        # The URL, not a caller-supplied label, is the security boundary.
        self.domain = (urlparse(self.url).hostname or "").casefold()
        return self


class Level(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    SCAM = "SCAM"


class Verdict(BaseModel):
    level: Level
    score: int
    signals: list[Signal] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warning: str = ""
    relative_alert: str = ""
    safe_action: str = ""
    signals_source: Literal["nemotron", "seeded", "rules"] = "rules"
    advice_source: Literal["nemotron", "seeded", "fallback"] = "fallback"
    advice_language: Literal["en", "pl"] = "en"

    @model_validator(mode="after")
    def scam_requires_independent_evidence(self) -> "Verdict":
        """The final invariant: an unsupported SCAM object cannot exist."""
        if self.level == Level.SCAM:
            tactics = {signal.tactic for signal in self.signals if signal.quote.strip()}
            official = any(is_official_domain(source.domain) for source in self.sources)
            if len(tactics) < 2 or not official:
                raise ValueError("SCAM requires two validated tactics and an official source")
        return self
