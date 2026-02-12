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
    if not url.startswith("http"):
        url = "https://" + url
    url = re.sub(r"https?://(www\.)?linkedin\.com", "https://www.linkedin.com", url)
    return url


async def _rate_limit():
    async with _rate_lock:
        await asyncio.sleep(settings.linkedin_rate_limit_delay)


async def _scrape_proxycurl(url: str) -> tuple[ProfileData | None, str]:
    """Tier 0: Proxycurl API — returns structured profile data directly."""
    if not settings.proxycurl_api_key:
        return None, "Proxycurl: No API key configured"
    try:
        api_url = "https://nubela.co/proxycurl/api/v2/linkedin"
        headers = {"Authorization": f"Bearer {settings.proxycurl_api_key}"}
        params = {"linkedin_profile_url": url, "use_cache": "if-present"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(api_url, headers=headers, params=params)
            if resp.status_code == 404:
                return None, "Proxycurl: Profile not found"
            if resp.status_code == 403:
                return None, "Proxycurl: Invalid API key"
            if resp.status_code == 429:
                return None, "Proxycurl: Rate limit / credits exhausted"
            if resp.status_code != 200:
                return None, f"Proxycurl: HTTP {resp.status_code}"

            data = resp.json()

            # Build experience string
            experience_parts = []
            for exp in (data.get("experiences") or [])[:5]:
                title = exp.get("title", "")
                company = exp.get("company", "")
                if title or company:
                    experience_parts.append(f"{title} at {company}".strip(" at "))

            # Build education string
            edu_parts = []
            for edu in (data.get("education") or [])[:3]:
                school = edu.get("school", "")
                degree = edu.get("degree_name", "")
                field = edu.get("field_of_study", "")
                parts = [p for p in [degree, field, school] if p]
                if parts:
                    edu_parts.append(", ".join(parts))

            name = data.get("full_name", "")
            if not name:
                first = data.get("first_name", "")
                last = data.get("last_name", "")
                name = f"{first} {last}".strip()

            profile = ProfileData(
                url=url,
                name=name,
                headline=data.get("headline", "") or data.get("occupation", ""),
                summary=data.get("summary", ""),
                experience="; ".join(experience_parts),
                education="; ".join(edu_parts),
                skills="",
                scrape_tier="proxycurl",
            )
            return profile, ""
    except Exception as e:
        reason = f"Proxycurl: {e}"
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
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ttf}",
                lambda route: route.abort(),
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
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
    """Scrape a LinkedIn profile using tiered fallback strategy."""
    url = normalize_linkedin_url(url)

    if manual_text:
        return parse_profile(manual_text, url, tier="manual")

    await _rate_limit()

    fail_reasons = []

    # Tier 0: Proxycurl (structured API — most reliable)
    profile, reason = await _scrape_proxycurl(url)
    if profile and profile.name:
        return profile
    if reason:
        fail_reasons.append(reason)

    # Tier 1: httpx direct
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

    detail = " → ".join(fail_reasons) if fail_reasons else "All tiers failed"
    return ProfileData(url=url, scrape_tier="failed", raw_text=detail)
