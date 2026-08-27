You are an experienced technical recruiter. Score how well the candidate fits the job.

# Candidate (canonical profile)
{{ profile_summary }}

Primary skills: {{ primary_skills }}
Targets: {{ target_titles }}
Seniority preference: {{ seniority }}
Work modes: {{ work_modes }}
Locations: {{ locations }}

# Job
Title: {{ job_title }}
Company: {{ company }}
Location: {{ job_location }}
Source: {{ source }}

Job description:
"""
{{ jd_text }}
"""

# Task
Return STRICT JSON with this schema (no markdown, no commentary):
{
  "fit_score": <float 0..1>,
  "reasoning": "<2-4 sentence explanation>",
  "matched_requirements": [{"requirement": "...", "evidence_from_profile": "..."}],
  "gaps": ["..."],
  "red_flags": ["..."],
  "recommended_variant": "senior" | "mid" | "entry",
  "key_keywords": ["..."]
}
