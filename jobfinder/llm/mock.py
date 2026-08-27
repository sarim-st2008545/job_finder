"""Deterministic, dependency-free LLM provider for offline runs and tests.

It heuristically detects which kind of prompt it's being asked to answer
(match-scoring vs. cover-letter vs. resume bullet rewrite vs. company brief) and
returns a plausibly-shaped response. Useful for plumbing tests and so the system
runs out of the box without any API key.
"""

from __future__ import annotations

import json
import re

from .base import LLMProvider, LLMResponse


class MockProvider(LLMProvider):
    name = "mock"

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        low = prompt.lower()

        if "strict json" in low and "fit_score" in low:
            payload = {
                "fit_score": 0.62,
                "reasoning": (
                    "Mock provider: keyword overlap looks reasonable; profile shows relevant"
                    " production experience. Replace LLM_PROVIDER in .env to upgrade."
                ),
                "matched_requirements": [
                    {
                        "requirement": "Python production experience",
                        "evidence_from_profile": "Shipped multiple production services in Python.",
                    }
                ],
                "gaps": ["Specific tool listed in JD not in profile (mock)."],
                "red_flags": [],
                "recommended_variant": "mid",
                "key_keywords": _extract_keywords(prompt)[:10],
            }
            return LLMResponse(
                text=json.dumps(payload), provider=self.name, model=self.model
            )

        if "rewrite" in low and "bullets" in low:
            originals = re.findall(r"- (.+)", prompt)[:6] or [
                "Built a thing.",
                "Shipped another thing.",
            ]
            payload = {
                "bullets": [
                    {
                        "original": o,
                        "rewritten": _emphasize(o),
                        "mapped_requirement": "(mock) general fit",
                    }
                    for o in originals
                ]
            }
            return LLMResponse(
                text=json.dumps(payload), provider=self.name, model=self.model
            )

        if "cover" in low or "variant 1" in low:
            text = (
                "## Variant 1\n"
                "Quick note — saw your team is shipping agentic workflows; I built a similar"
                " RAG + agent system at my last role and cut latency 30%. Happy to share the"
                " repo. Up for a 20-minute chat next week?\n\n"
                "## Variant 2\n"
                "Hi — I noticed your job spec leans on production ML rigor. I've shipped 6"
                " models end-to-end and run on-call rotations for them. Would love to hear"
                " what you're optimizing for in the first 90 days.\n\n"
                "## Variant 3\n"
                "Hello — your stack overlaps with what I've been deep in (Python, PyTorch,"
                " vector search). I'd bring a strong bias for measurable wins. Open to a"
                " short intro call this week?\n"
            )
            return LLMResponse(text=text, provider=self.name, model=self.model)

        if "company brief" in low or "tl;dr" in low or "# {{ company_name }}" in low:
            text = (
                "# (mock) Company Brief\n\n"
                "## TL;DR\nMock brief. Plug in a real LLM provider for full content.\n\n"
                "## What they do\nUnknown.\n\n"
                "## Recent signals (last 12 months)\n- unknown\n\n"
                "## Likely tech stack\n- unknown\n\n"
                "## Hiring / org signals\n- unknown\n\n"
                "## Culture signals\n- unknown\n\n"
                "## Competitors\n- unknown\n\n"
                "## Red flags\n- none observed\n\n"
                "## Why I'm a fit (5 points)\n1. ...\n2. ...\n3. ...\n4. ...\n5. ...\n\n"
                "## Open questions to ask in interview\n- unknown\n"
            )
            return LLMResponse(text=text, provider=self.name, model=self.model)

        return LLMResponse(
            text="(mock LLM response — replace LLM_PROVIDER in .env)",
            provider=self.name,
            model=self.model,
        )


def _extract_keywords(text: str) -> list[str]:
    return list(
        {
            w.lower()
            for w in re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{2,}", text)
            if w.isupper() or len(w) >= 5
        }
    )


def _emphasize(s: str) -> str:
    s = s.strip().rstrip(".")
    return f"{s}; aligned to JD requirements."
