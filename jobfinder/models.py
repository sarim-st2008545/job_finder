"""Pydantic data models shared across agents.

These mirror the SQLite schema 1:1 where applicable so that conversions stay
trivial.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal[
    "new",
    "scored",
    "drafted",
    "review_required",
    "applied",
    "rejected",
    "skipped",
    "archived",
]


class Job(BaseModel):
    id: str
    title: str
    company: str
    url: str
    source: str
    raw_path: str | None = None
    jd_text: str | None = None
    location: str | None = None
    date_posted: datetime | None = None
    date_seen: datetime = Field(default_factory=datetime.utcnow)
    match_score: float | None = None
    status: JobStatus = "new"
    notes: str | None = None


class MatchResult(BaseModel):
    fit_score: float = 0.0
    reasoning: str = ""
    matched_requirements: list[dict[str, str]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    recommended_variant: str = "mid"
    key_keywords: list[str] = Field(default_factory=list)
    keyword_score: float = 0.0
    llm_score: float = 0.0
    final_score: float = 0.0


class Application(BaseModel):
    job_id: str
    profile_variant: str
    resume_path: str
    cover_path: str
    match_path: str
    applied_date: datetime | None = None
    status: JobStatus = "drafted"
    reviewer: str | None = None
    notes: str | None = None


class Company(BaseModel):
    slug: str
    name: str
    domain: str | None = None
    brief_path: str | None = None
    vector_id: str | None = None
    last_scraped: datetime | None = None


class Contact(BaseModel):
    company_slug: str
    name: str
    title: str | None = None
    source_url: str | None = None
    email_candidate: str | None = None
    confidence: float = 0.0
