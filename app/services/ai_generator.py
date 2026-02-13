from __future__ import annotations

from openai import AsyncOpenAI

from app.config import settings
from app.models.schemas import ProfileData, ResearchResult

SYSTEM_PROMPT = """\
You are an expert BDR (Business Development Representative) copywriter who crafts \
personalized cold outreach opening lines. Your openers are:

- Hyper-specific to the prospect — referencing real details from their profile or recent activity
- Warm and human, never robotic or templated
- Concise and punchy — every word earns its place
- Designed to earn a reply, not just get opened

RULES:
- Pick the SINGLE most interesting or surprising detail you can find — a recent company \
milestone, a personal post, an unusual career move, a specific project. Generic observations kill reply rates.
- NEVER reference shared tools, platforms, or tech stacks as the main hook (e.g. "fellow \
Recharge user" or "I see you also use Shipstation") — dig deeper for something unique.
- NEVER start with "I noticed..." or "I came across..." — these are overused and ignored
- NEVER use buzzwords like "synergy", "leverage", "game-changer", "cutting-edge"
- NEVER be sycophantic or over-the-top flattering
- NEVER mention that you researched them
- DO reference specific details: a recent role change, a project, a post they wrote, a company milestone
- DO match the requested tone
- Prioritize recent company news, personal posts, or unique career moves over generic profile facts
- Output ONLY the opener text — no quotes, no labels, no explanation

BAD example (generic): "Running ops at a growing DTC brand while juggling Recharge and \
Shipstation — that's no small feat."
GOOD example (specific): "MyOva just landed that Innovate UK grant for the PCOS home-testing \
kit — scaling clinical validation and DTC ops at the same time must be a wild ride."
"""


def _build_user_prompt(
    profile: ProfileData,
    research: list[ResearchResult],
    must_include: str,
    char_limit: int,
    tone: str,
) -> str:
    parts = [f"PROSPECT PROFILE:\n- Name: {profile.name}"]
    if profile.headline:
        parts.append(f"- Headline: {profile.headline}")
    if profile.summary:
        parts.append(f"- Summary: {profile.summary}")
    if profile.experience:
        parts.append(f"- Experience: {profile.experience}")
    if profile.education:
        parts.append(f"- Education: {profile.education}")
    if profile.skills:
        parts.append(f"- Skills: {profile.skills}")

    if research:
        has_snippets = any(r.snippets for r in research)
        if has_snippets:
            parts.append("\nWEB RESEARCH FINDINGS:")
            idx = 1
            for r in research:
                if r.snippets:
                    parts.append(f"\n[Source: {r.query}]")
                    for s in r.snippets[:3]:
                        parts.append(f"{idx}. {s}")
                        idx += 1

    parts.append(f"\nTONE: {tone}")
    parts.append(f"MAX CHARACTERS: {char_limit}")
    if must_include:
        parts.append(f"MUST INCLUDE: {must_include}")

    parts.append(
        "\nWrite a single personalized cold outreach opener for this prospect. "
        "Prioritize recent company news, personal posts, or unique career moves "
        "over generic profile facts."
    )
    return "\n".join(parts)


def _enforce_char_limit(text: str, limit: int) -> str:
    text = text.strip().strip('"').strip("'").strip()
    if len(text) <= limit:
        return text
    # Trim at last sentence boundary within limit
    truncated = text[:limit]
    for sep in [". ", "! ", "? "]:
        idx = truncated.rfind(sep)
        if idx > limit // 3:
            return truncated[: idx + 1]
    # Fall back to last space
    idx = truncated.rfind(" ")
    if idx > limit // 3:
        return truncated[:idx] + "..."
    return truncated + "..."


async def generate_opener(
    profile: ProfileData,
    research: list[ResearchResult],
    must_include: str = "",
    char_limit: int = 300,
    tone: str = "professional",
) -> str:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    user_prompt = _build_user_prompt(profile, research, must_include, char_limit, tone)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
        max_tokens=400,
    )

    raw = response.choices[0].message.content or ""
    return _enforce_char_limit(raw, char_limit)
