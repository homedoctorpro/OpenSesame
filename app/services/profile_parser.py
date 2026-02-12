from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from app.models.schemas import ProfileData


def parse_profile(html: str, url: str, tier: str) -> ProfileData:
    """Parse LinkedIn profile HTML into structured data using multiple strategies."""
    if tier == "manual":
        return _parse_plain_text(html, url)

    soup = BeautifulSoup(html, "lxml")

    # Strategy 1: JSON-LD
    profile = _parse_json_ld(soup, url, tier)
    if profile and profile.name:
        return profile

    # Strategy 2: OpenGraph meta tags
    profile = _parse_opengraph(soup, url, tier)
    if profile and profile.name:
        return profile

    # Strategy 3: Raw text fallback
    text = soup.get_text(separator="\n", strip=True)
    return _parse_plain_text(text, url, tier)


def _parse_json_ld(soup: BeautifulSoup, url: str, tier: str) -> ProfileData | None:
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "Person":
                    data = item
                    break
            else:
                continue

        if not isinstance(data, dict) or data.get("@type") != "Person":
            continue

        name = data.get("name", "")
        headline = data.get("jobTitle", "") or data.get("description", "")

        experience_parts = []
        for interaction in data.get("interactionStatistic", []):
            if isinstance(interaction, dict):
                experience_parts.append(str(interaction))

        address = data.get("address", {})
        location = ""
        if isinstance(address, dict):
            location = address.get("addressLocality", "")

        return ProfileData(
            url=url,
            name=name,
            headline=headline,
            summary=data.get("description", ""),
            experience="; ".join(experience_parts) if experience_parts else "",
            education="",
            skills="",
            raw_text="",
            scrape_tier=tier,
        )

    return None


def _parse_opengraph(soup: BeautifulSoup, url: str, tier: str) -> ProfileData | None:
    og_title = soup.find("meta", property="og:title")
    og_desc = soup.find("meta", property="og:description")

    title = og_title.get("content", "") if og_title else ""
    desc = og_desc.get("content", "") if og_desc else ""

    if not title:
        return None

    # LinkedIn og:title is typically "Name - Title - Company | LinkedIn"
    name = title.split(" - ")[0].strip() if " - " in title else title.replace(" | LinkedIn", "").strip()
    headline = ""
    if " - " in title:
        parts = title.split(" - ")
        headline = " - ".join(parts[1:]).replace(" | LinkedIn", "").strip()

    return ProfileData(
        url=url,
        name=name,
        headline=headline,
        summary=desc,
        scrape_tier=tier,
    )


def _parse_plain_text(text: str, url: str, tier: str = "manual") -> ProfileData:
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    name = lines[0] if lines else ""
    headline = lines[1] if len(lines) > 1 else ""

    # Try to find experience/education sections
    full_text = "\n".join(lines)
    experience = ""
    education = ""

    exp_match = re.search(
        r"(?:Experience|Work Experience)\s*\n([\s\S]*?)(?:\n(?:Education|Skills|$))",
        full_text,
        re.IGNORECASE,
    )
    if exp_match:
        experience = exp_match.group(1).strip()[:500]

    edu_match = re.search(
        r"Education\s*\n([\s\S]*?)(?:\n(?:Skills|Interests|$))",
        full_text,
        re.IGNORECASE,
    )
    if edu_match:
        education = edu_match.group(1).strip()[:300]

    return ProfileData(
        url=url,
        name=name,
        headline=headline,
        summary="\n".join(lines[2:6]) if len(lines) > 2 else "",
        experience=experience,
        education=education,
        raw_text=full_text[:2000],
        scrape_tier=tier,
    )
