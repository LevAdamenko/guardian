"""Tavily adapter with replay and a second independent domain filter."""
import json
from pathlib import Path

from .config import live_enabled, load_config
from .llm import FixtureMissing, canonical_json, fixture_is_seeded, read_fixture
from .models import Source
from .taxonomy import OFFICIAL_DOMAINS, is_official_domain


class TavilyClient:
    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self.fixtures_dir = fixtures_dir or Path(__file__).resolve().parents[1] / "fixtures"

    @staticmethod
    def request(query: str, include_domains: set[str] | frozenset[str]) -> dict[str, object]:
        return {"query": query, "include_domains": sorted(include_domains), "max_results": 5, "search_depth": "basic"}

    def _response_content(self, request: dict[str, object]) -> str:
        if not live_enabled():
            return read_fixture(self.fixtures_dir, "search", request)
        import httpx
        response = httpx.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {load_config().get('TAVILY_API_KEY', '')}"}, json=request, timeout=20)
        response.raise_for_status()
        return canonical_json(response.json())

    def search(self, query: str, include_domains: set[str] | frozenset[str] = OFFICIAL_DOMAINS) -> list[Source]:
        request = self.request(query, include_domains)
        payload = json.loads(self._response_content(request))
        seeded = not live_enabled() and fixture_is_seeded(self.fixtures_dir, "search", request)
        sources: list[Source] = []
        for result in payload.get("results", []) if isinstance(payload, dict) else []:
            if not isinstance(result, dict):
                continue
            url = result.get("url", "")
            snippet = (result.get("content") or result.get("snippet") or "").strip()
            if url and snippet and is_official_domain(url):
                sources.append(Source(url=url, title=result.get("title", ""), snippet=snippet, seeded=seeded))
        return sources
