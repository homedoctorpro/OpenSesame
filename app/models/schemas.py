from __future__ import annotations

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=10)
    must_include: str = ""
    char_limit: int = Field(default=300, ge=50, le=1000)
    tone: str = Field(default="professional")
    research_depth: str = Field(default="medium", pattern="^(light|medium|deep)$")
    # Optional manual profile text keyed by URL (for Tier 3 fallback)
    manual_profiles: dict[str, str] = Field(default_factory=dict)


class ProfileData(BaseModel):
    url: str
    name: str = ""
    headline: str = ""
    summary: str = ""
    experience: str = ""
    education: str = ""
    skills: str = ""
    raw_text: str = ""
    scrape_tier: str = ""


class ResearchResult(BaseModel):
    query: str
    snippets: list[str] = Field(default_factory=list)


class OpenerResult(BaseModel):
    url: str
    name: str = ""
    opener: str = ""
    research_snippets: list[str] = Field(default_factory=list)
    scrape_tier: str = ""
    error: str = ""


class GenerateResponse(BaseModel):
    results: list[OpenerResult]
