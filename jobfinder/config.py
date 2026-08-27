"""Centralized config loader.

Reads `config/settings.yaml` + `.env` and exposes a single `Settings` object.
All path settings are resolved to absolute paths relative to the project root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (PROJECT_ROOT / path)


@dataclass
class Paths:
    data_dir: Path
    raw_jobs_dir: Path
    applications_dir: Path
    companies_dir: Path
    vector_store_dir: Path
    reports_dir: Path
    logs_dir: Path
    db_path: Path
    profile_path: Path
    prompts_dir: Path

    def ensure(self) -> None:
        for p in [
            self.data_dir,
            self.raw_jobs_dir,
            self.applications_dir,
            self.companies_dir,
            self.vector_store_dir,
            self.reports_dir,
            self.logs_dir,
        ]:
            p.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    paths: Paths
    raw: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)

    # convenience getters
    @property
    def scanner(self) -> dict[str, Any]:
        return self.raw.get("scanner", {})

    @property
    def matcher(self) -> dict[str, Any]:
        return self.raw.get("matcher", {})

    @property
    def company_research(self) -> dict[str, Any]:
        return self.raw.get("company_research", {})

    @property
    def filters(self) -> dict[str, Any]:
        return self.raw.get("filters", {})

    @property
    def llm_provider(self) -> str:
        return self.env.get("LLM_PROVIDER", "mock").lower()

    @property
    def llm_model(self) -> str:
        return self.env.get("LLM_MODEL", "gpt-4o-mini")

    @property
    def embedding_model(self) -> str:
        return self.env.get(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )

    @property
    def user_agent(self) -> str:
        return self.env.get("USER_AGENT", "jobfinder/0.1 (+local)")


@lru_cache(maxsize=1)
def get_settings(settings_path: Path | None = None) -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    path = settings_path or DEFAULT_SETTINGS_PATH
    raw: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    pblock = raw.get("paths", {})
    paths = Paths(
        data_dir=_resolve(pblock.get("data_dir", "data")),
        raw_jobs_dir=_resolve(pblock.get("raw_jobs_dir", "data/raw_jobs")),
        applications_dir=_resolve(pblock.get("applications_dir", "data/applications")),
        companies_dir=_resolve(pblock.get("companies_dir", "data/companies")),
        vector_store_dir=_resolve(pblock.get("vector_store_dir", "data/vector_store")),
        reports_dir=_resolve(pblock.get("reports_dir", "data/reports")),
        logs_dir=_resolve(pblock.get("logs_dir", "logs")),
        db_path=_resolve(pblock.get("db_path", "data/app.db")),
        profile_path=_resolve(pblock.get("profile_path", "profile/profile.yaml")),
        prompts_dir=_resolve(pblock.get("prompts_dir", "prompts")),
    )
    paths.ensure()

    env_snapshot = {k: v for k, v in os.environ.items()}
    return Settings(paths=paths, raw=raw, env=env_snapshot)


def load_profile(settings: Settings | None = None) -> dict[str, Any]:
    """Load the user's canonical profile. Falls back to the example if missing."""
    s = settings or get_settings()
    primary = s.paths.profile_path
    fallback = primary.with_name("profile.example.yaml")
    target = primary if primary.exists() else fallback
    if not target.exists():
        return {}
    with target.open("r", encoding="utf-8") as f:
        if target.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(f) or {}
        import json

        return json.load(f)
