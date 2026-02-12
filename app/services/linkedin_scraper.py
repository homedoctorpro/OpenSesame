from __future__ import annotations

import asyncio
import logging
import re

import httpx

from app.config import settings
from app.models.schemas import ProfileData
from app.services.profile_parser import parse_profile

logger = logging.getLogger(__name__)

_rate_lock = asyncio.Lock()

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def normalize_linkedin_url(url: str) -> str:
    url = url.strip().rstrip("/")
    # Ensure https
    if not url.startswith("http"):
        url = "https://" + url
    # Normalize to www.linkedin.com
    url = re.sub(r"https?://(www\.)?linkedin\.com", "https://www.linkedin.com", url)
    return url


async def _rate_limit():
    async with _rate_lock:
        await asyncio.sleep(settings.linkedin_rate_limit_delay)


async def _scrape_scraperapi(url: str) -> tuple[str | None, str]:
    """Tier 0: ScraperAPI with residential proxies. Returns (html, fail_reason)."""
    if not settings.scraper_api_key:
        return None, "ScraperAPI: No API key configured"
    try:
        api_url = "https://api.scraperapi.com"
        params = {
            "api_key": settings.scraper_api_key,
            "url": url,
            "render": "true",
            "country_code": "us",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(api_url, params=params)
            if resp.status_code != 200:
                reason = f"ScraperAPI: HTTP {resp.status_code}"
                logger.info("%s for %s", reason, url)
                return None, reason
            html = resp.text
            if "authwall" in html[:5000] and "login" in html[:5000]:
                return None, "ScraperAPI: LinkedIn authwall in response"
            if len(html) < 500:
                return None, "ScraperAPI: Response too short"
            return html, ""
    except Exception as e:
        reason = f"ScraperAPI: {e}"
        logger.info("%s for %s", reason, url)
        return None, reason


async def _scrape_tier1(url: str) -> tuple[str | None, str]:
    """Tier 1: httpx with browser-like headers. Returns (html, fail_reason)."""
    try:
        async with httpx.AsyncClient(
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=15.0,
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                reason = f"Tier 1: HTTP {resp.status_code}"
                logger.info("%s for %s", reason, url)
                return None, reason
            html = resp.text
            # Check for authwall
            if "authwall" in resp.url.path or "login" in resp.url.path:
                reason = "Tier 1: LinkedIn authwall redirect (cloud IP blocked)"
                logger.info("%s for %s", reason, url)
                return None, reason
            if len(html) < 500:
                return None, "Tier 1: Response too short (likely blocked)"
            return html, ""
    except Exception as e:
        reason = f"Tier 1: {e}"
        logger.info("%s for %s", reason, url)
        return None, reason


async def _scrape_tier2(url: str) -> tuple[str | None, str]:
    """Tier 2: Playwright headless Chromium. Returns (html, fail_reason)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None, "Tier 2: Playwright not installed"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=BROWSER_HEADERS["User-Agent"],
            )
            page = await context.new_page()
            # Block images/CSS for speed
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ttf}",
                lambda route: route.abort(),
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            # Wait briefly for JS rendering
            await page.wait_for_timeout(2000)
            # Check for authwall
            current_url = page.url
            if "authwall" in current_url or "login" in current_url:
                await browser.close()
                return None, "Tier 2: LinkedIn authwall redirect"
            html = await page.content()
            await browser.close()
            if len(html) < 500:
                return None, "Tier 2: Response too short"
            return html, ""
    except Exception as e:
        reason = f"Tier 2: {e}"
        logger.info("%s for %s", reason, url)
        return None, reason


async def scrape_profile(
    url: str, manual_text: str | None = None
) -> ProfileData:
    """Scrape a LinkedIn profile using 3-tier fallback strategy."""
    url = normalize_linkedin_url(url)

    # If manual text provided, use it directly (Tier 3)
    if manual_text:
        return parse_profile(manual_text, url, tier="manual")

    await _rate_limit()

    fail_reasons = []

    # Tier 0: ScraperAPI (residential proxy)
    html, reason = await _scrape_scraperapi(url)
    if html:
        profile = parse_profile(html, url, tier="scraperapi")
        if profile.name:
            return profile
        fail_reasons.append("ScraperAPI: Got HTML but could not parse name")
    elif reason:
        fail_reasons.append(reason)

    # Tier 1: httpx
    html, reason = await _scrape_tier1(url)
    if html:
        profile = parse_profile(html, url, tier="tier1")
        if profile.name:
            return profile
        fail_reasons.append("Tier 1: Got HTML but could not parse name")
    elif reason:
        fail_reasons.append(reason)

    # Tier 2: Playwright
    html, reason = await _scrape_tier2(url)
    if html:
        profile = parse_profile(html, url, tier="tier2")
        if profile.name:
            return profile
        fail_reasons.append("Tier 2: Got HTML but could not parse name")
    elif reason:
        fail_reasons.append(reason)

    # Tier 3: Return empty profile — frontend will show manual paste fallback
    detail = " → ".join(fail_reasons) if fail_reasons else "All tiers failed"
    return ProfileData(url=url, scrape_tier="failed", raw_text=detail)
