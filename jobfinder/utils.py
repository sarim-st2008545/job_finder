"""Cross-cutting helpers."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import httpx
from slugify import slugify as _slugify


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")


def stable_id(*parts: str) -> str:
    """Deterministic short ID for a job, derived from its identifying fields."""
    h = hashlib.sha1("\u0001".join(parts).encode("utf-8")).hexdigest()
    return h[:16]


def slug(text: str) -> str:
    return _slugify(text or "")[:80] or "unknown"


def http_client(user_agent: str, timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"},
        timeout=timeout,
        follow_redirects=True,
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(text: str) -> str:
    """Cheap normalization for matching purposes."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(text or "")}


def keyword_overlap_score(
    candidate_keywords: set[str], jd_text: str, weights: dict[str, float] | None = None
) -> float:
    """0..1 score = weighted fraction of candidate keywords found in JD."""
    if not candidate_keywords:
        return 0.0
    jd_tokens = tokenize(jd_text)
    weights = weights or {}
    total = 0.0
    hits = 0.0
    for kw in candidate_keywords:
        w = weights.get(kw.lower(), 1.0)
        total += w
        if kw.lower() in jd_tokens or kw.lower() in jd_text.lower():
            hits += w
    return min(1.0, hits / max(total, 1e-6))
