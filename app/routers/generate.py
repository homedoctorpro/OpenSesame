from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.schemas import GenerateRequest, GenerateResponse, OpenerResult
from app.services.ai_generator import generate_opener
from app.services.linkedin_scraper import scrape_profile
from app.services.web_researcher import research_prospect

logger = logging.getLogger(__name__)
router = APIRouter()


async def _process_single(
    url: str,
    request: GenerateRequest,
    semaphore: asyncio.Semaphore,
) -> OpenerResult:
    async with semaphore:
        try:
            # Step 1: Scrape LinkedIn profile
            manual_text = request.manual_profiles.get(url)
            profile = await scrape_profile(url, manual_text=manual_text)

            if profile.scrape_tier == "failed":
                detail = profile.raw_text or "All scraping tiers failed"
                return OpenerResult(
                    url=url,
                    scrape_tier="failed",
                    error=f"Scrape failed: {detail}. Please paste profile text manually.",
                )

            # Step 2: Web research (concurrent with nothing — profile is needed first)
            research = await research_prospect(profile, depth=request.research_depth)

            # Step 3: Generate opener via AI
            opener = await generate_opener(
                profile=profile,
                research=research,
                must_include=request.must_include,
                char_limit=request.char_limit,
                tone=request.tone,
            )

            snippets = []
            for r in research:
                snippets.extend(r.snippets)

            return OpenerResult(
                url=url,
                name=profile.name,
                opener=opener,
                research_snippets=snippets[:5],
                scrape_tier=profile.scrape_tier,
            )

        except Exception as e:
            logger.exception("Error processing %s", url)
            return OpenerResult(url=url, error=str(e))


@router.post("/api/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest):
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    if len(request.urls) > settings.max_urls_per_batch:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {settings.max_urls_per_batch} URLs per batch",
        )

    semaphore = asyncio.Semaphore(3)  # Max 3 concurrent profile processes
    tasks = [_process_single(url, request, semaphore) for url in request.urls]
    results = await asyncio.gather(*tasks)

    return GenerateResponse(results=list(results))
