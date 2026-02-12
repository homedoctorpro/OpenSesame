from __future__ import annotations

import asyncio
from functools import partial

from duckduckgo_search import DDGS

from app.models.schemas import ProfileData, ResearchResult


def _search_sync(query: str, max_results: int) -> list[str]:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [r.get("body", "") for r in results if r.get("body")]
    except Exception:
        return []


async def _search_async(query: str, max_results: int = 3) -> ResearchResult:
    loop = asyncio.get_running_loop()
    snippets = await loop.run_in_executor(
        None, partial(_search_sync, query, max_results)
    )
    return ResearchResult(query=query, snippets=snippets)


def _build_queries(profile: ProfileData, depth: str) -> list[str]:
    name = profile.name.strip()
    headline = profile.headline.strip()
    if not name:
        return []

    if depth == "light":
        return []

    queries = []
    # Primary query — always included for medium/deep
    if headline:
        queries.append(f'"{name}" {headline}')
    else:
        queries.append(f'"{name}"')

    if depth == "deep":
        # Additional queries for deep research
        if headline:
            # Try to extract company from headline
            queries.append(f'"{name}" recent news OR announcement')
            queries.append(f'"{name}" interview OR podcast OR article')
        else:
            queries.append(f'"{name}" professional')
            queries.append(f'"{name}" news')

    return queries


async def research_prospect(
    profile: ProfileData, depth: str = "medium"
) -> list[ResearchResult]:
    queries = _build_queries(profile, depth)
    if not queries:
        return []

    max_results = 3
    tasks = [_search_async(q, max_results) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, ResearchResult) and r.snippets]
