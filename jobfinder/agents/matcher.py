"""Match & Draft Agent.

For a given job:
  1. Compute keyword overlap score from the profile vs. JD.
  2. Ask the LLM for a structured fit score + reasoning + recommended variant.
  3. Combine both into a final match_score.
  4. Generate cover-letter variants and tailored resume bullets.
  5. Persist outputs under data/applications/<job_id>/ and update DB.

The agent never auto-submits. With **`generate_drafts: false`** (default in
`config/settings.yaml`) it only writes **`match_score.json`** per job (rankings
and reasoning). Set **`generate_drafts: true`** to also emit cover/resume
markdown under `data/applications/`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import load_profile
from ..db import (
    get_job,
    set_job_status,
    upsert_application,
)
from ..llm import get_provider
from ..llm.prompts import render
from ..models import Application, MatchResult
from ..utils import (
    keyword_overlap_score,
    write_json,
    write_text,
)
from .base import BaseAgent


class MatcherAgent(BaseAgent):
    name = "matcher"

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.profile = load_profile(self.settings)
        self.provider = get_provider()
        self.cfg = self.settings.matcher or {}

    # ---------------- public ----------------

    def run(self, job_id: str) -> MatchResult | None:
        job = get_job(job_id)
        if not job:
            self.log.warning("No job with id=%s", job_id)
            return None
        if not (job.jd_text or "").strip():
            self.log.warning("Job %s has no jd_text; skipping", job_id)
            return None

        self.emit("match.start", {"job_id": job_id})
        result = self._score(job.jd_text, job.title, job.company, job.location or "", job.source)

        set_job_status(job_id, status="scored", match_score=result.final_score)

        # Only generate drafts if we're above the keyword floor (don't waste tokens)
        min_kw = float(self.cfg.get("min_keyword_score", 0.05))
        if result.keyword_score < min_kw:
            self.emit(
                "match.skipped_drafts",
                {"job_id": job_id, "keyword_score": result.keyword_score, "min": min_kw},
            )
            self._persist_match(job_id, result, with_drafts=False)
            return result

        generate_drafts = bool(self.cfg.get("generate_drafts", True))
        if not generate_drafts:
            self.emit(
                "match.score_only",
                {"job_id": job_id, "score": result.final_score},
            )
            self._persist_match(job_id, result, with_drafts=False)
            return result

        drafts = self._generate_drafts(job, result)
        self._persist_match(job_id, result, drafts=drafts, with_drafts=True)

        require_review = bool(self.cfg.get("require_manual_review", True))
        status = "review_required" if require_review else "drafted"
        set_job_status(job_id, status=status, match_score=result.final_score)

        self.emit(
            "match.end",
            {
                "job_id": job_id,
                "score": result.final_score,
                "variant": result.recommended_variant,
                "status": status,
            },
        )
        return result

    # ---------------- internals ----------------

    def _candidate_keywords(self) -> set[str]:
        skills = self.profile.get("skills", {})
        kws: set[str] = set()
        for k in skills.get("primary", []):
            kws.add(str(k))
        for k in skills.get("secondary", []):
            kws.add(str(k))
        for t in (self.profile.get("targets", {}) or {}).get("titles", []):
            kws.add(str(t))
        return {k for k in kws if k}

    def _score(
        self, jd_text: str, title: str, company: str, location: str, source: str
    ) -> MatchResult:
        kws = self._candidate_keywords()
        kw_score = keyword_overlap_score(kws, jd_text)

        weight_kw = float(self.cfg.get("weight_keyword", 0.4))
        weight_llm = float(self.cfg.get("weight_llm", 0.6))

        prompt = render(
            "match_prompt.tpl",
            profile_summary=_profile_summary(self.profile),
            primary_skills=", ".join(
                (self.profile.get("skills", {}) or {}).get("primary", [])
            ),
            target_titles=", ".join(
                (self.profile.get("targets", {}) or {}).get("titles", [])
            ),
            seniority=", ".join(
                (self.profile.get("targets", {}) or {}).get("seniority", [])
            ),
            work_modes=", ".join(
                (self.profile.get("targets", {}) or {}).get("work_modes", [])
            ),
            locations=", ".join(
                (self.profile.get("targets", {}) or {}).get("locations", [])
            ),
            job_title=title,
            company=company,
            job_location=location,
            source=source,
            jd_text=jd_text[:8000],
        )
        try:
            resp = self.provider.complete(prompt, temperature=0.2, max_tokens=900)
            data = resp.parse_json(default={}) or {}
        except Exception as e:
            self.log.warning("LLM scoring failed: %s", e)
            data = {}

        llm_score = float(data.get("fit_score", 0.0) or 0.0)
        final = round(weight_kw * kw_score + weight_llm * llm_score, 4)

        return MatchResult(
            fit_score=llm_score,
            reasoning=str(data.get("reasoning", "")),
            matched_requirements=list(data.get("matched_requirements", []) or []),
            gaps=list(data.get("gaps", []) or []),
            red_flags=list(data.get("red_flags", []) or []),
            recommended_variant=str(data.get("recommended_variant", "mid")),
            key_keywords=list(data.get("key_keywords", []) or []),
            keyword_score=round(kw_score, 4),
            llm_score=llm_score,
            final_score=final,
        )

    def _generate_drafts(self, job, result: MatchResult) -> dict[str, str]:
        voice = (self.profile.get("voice", {}) or {})
        cover_voice = voice.get("cover_letter", "Direct, warm builder voice.")
        bullet_voice = voice.get("resume_bullet", "Action verb + metric + tech.")

        # COVER
        cover_prompt = render(
            "cover_prompt.tpl",
            voice=cover_voice,
            name=(self.profile.get("basics", {}) or {}).get("name", ""),
            headline=(self.profile.get("basics", {}) or {}).get("headline", ""),
            achievements=self.profile.get("achievements", []) or [],
            job_title=job.title,
            company=job.company,
            jd_excerpt=(job.jd_text or "")[:2500],
            company_brief="",  # filled in if a brief exists; matcher itself doesn't fetch
            n_variants=int(self.cfg.get("cover_variants", 3)),
        )
        cover_resp = self.provider.complete(cover_prompt, temperature=0.7, max_tokens=900)

        # RESUME BULLETS
        variant_key = result.recommended_variant or "mid"
        variants = self.profile.get("variants", {}) or {}
        variant_cfg = variants.get(variant_key) or variants.get("mid") or {}
        picked = set((variant_cfg.get("pick_experience") or []))
        bullets: list[str] = []
        for exp in self.profile.get("experience", []) or []:
            if not picked or exp.get("company") in picked:
                for b in exp.get("bullets", []) or []:
                    bullets.append(b)

        requirements_block = "\n".join(
            f"- {item.get('requirement', '')}"
            for item in (result.matched_requirements or [])
        ) or "(no specific requirements parsed)"

        bullet_prompt = render(
            "resume_bullet_prompt.tpl",
            requirements_block=requirements_block,
            existing_bullets=bullets[:12],
            voice=bullet_voice,
            n_edits=int(self.cfg.get("resume_bullet_edits", 6)),
        )
        bullet_resp = self.provider.complete(bullet_prompt, temperature=0.4, max_tokens=900)
        bullet_json = bullet_resp.parse_json(default={"bullets": []}) or {"bullets": []}

        resume_md = _render_resume_markdown(
            self.profile, variant_key, bullet_json.get("bullets", [])
        )

        return {
            "cover_md": cover_resp.text,
            "resume_md": resume_md,
            "bullets_json": bullet_json,
        }

    def _persist_match(
        self,
        job_id: str,
        result: MatchResult,
        drafts: dict[str, Any] | None = None,
        with_drafts: bool = True,
    ) -> None:
        out_dir: Path = self.settings.paths.applications_dir / job_id
        out_dir.mkdir(parents=True, exist_ok=True)

        match_path = out_dir / "match_score.json"
        write_json(match_path, result.model_dump())

        if not with_drafts or not drafts:
            return

        resume_path = out_dir / "resume_tailored.md"
        cover_path = out_dir / "cover_draft.md"
        bullets_path = out_dir / "bullets.json"

        write_text(resume_path, drafts.get("resume_md", "") or "")
        write_text(cover_path, drafts.get("cover_md", "") or "")
        write_json(bullets_path, drafts.get("bullets_json", {}))

        upsert_application(
            Application(
                job_id=job_id,
                profile_variant=result.recommended_variant or "mid",
                resume_path=str(resume_path),
                cover_path=str(cover_path),
                match_path=str(match_path),
                status="drafted",
            )
        )


def _profile_summary(profile: dict[str, Any]) -> str:
    basics = profile.get("basics", {}) or {}
    parts = [
        basics.get("headline", ""),
        basics.get("location", ""),
        "Skills: "
        + ", ".join((profile.get("skills", {}) or {}).get("primary", []) or []),
    ]
    return " | ".join(p for p in parts if p)


def _render_resume_markdown(
    profile: dict[str, Any], variant_key: str, edited_bullets: list[dict[str, str]]
) -> str:
    basics = profile.get("basics", {}) or {}
    variants = profile.get("variants", {}) or {}
    variant = variants.get(variant_key) or variants.get("mid") or {}
    rewrites = {b.get("original", "").strip(): b.get("rewritten", "") for b in edited_bullets}

    lines: list[str] = []
    lines.append(f"# {basics.get('name', 'Candidate')}")
    if basics.get("headline"):
        lines.append(f"_{basics['headline']}_")
    contact = " · ".join(
        x
        for x in [
            basics.get("email", ""),
            basics.get("phone", ""),
            (basics.get("links", {}) or {}).get("linkedin", ""),
            (basics.get("links", {}) or {}).get("github", ""),
        ]
        if x
    )
    if contact:
        lines.append(contact)
    lines.append("")
    if variant.get("summary"):
        lines.append("## Summary")
        lines.append(variant["summary"])
        lines.append("")

    lines.append("## Experience")
    picked = set(variant.get("pick_experience") or [])
    for exp in profile.get("experience", []) or []:
        if picked and exp.get("company") not in picked:
            continue
        header = f"**{exp.get('role', '')}** — {exp.get('company', '')}  "
        dates = f"_{exp.get('start','')} – {exp.get('end','')}_"
        loc = exp.get("location", "")
        lines.append(f"{header}{dates}{(' · ' + loc) if loc else ''}")
        for b in exp.get("bullets", []) or []:
            edited = rewrites.get(b.strip())
            lines.append(f"- {edited or b}")
        lines.append("")

    skills = profile.get("skills", {}) or {}
    if skills:
        lines.append("## Skills")
        if skills.get("primary"):
            lines.append("**Primary:** " + ", ".join(skills["primary"]))
        if skills.get("secondary"):
            lines.append("**Also:** " + ", ".join(skills["secondary"]))
        lines.append("")

    for ed in profile.get("education", []) or []:
        lines.append("## Education")
        lines.append(
            f"- {ed.get('degree','')} — {ed.get('school','')} ({ed.get('year','')})"
        )
        lines.append("")

    lines.append(f"<!-- variant={variant_key} generated_at={datetime.utcnow().isoformat()} -->")
    return "\n".join(lines)
