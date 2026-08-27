Rewrite the candidate's resume bullets to maximize relevance to this job, without
inventing facts. Reuse only what's in the profile; if a job requirement isn't
backed by the profile, leave it out.

# Job requirements (most important first)
{{ requirements_block }}

# Existing bullets (verbatim, can be reworded)
{% for b in existing_bullets %}- {{ b }}
{% endfor %}

# Style
{{ voice }}

# Task
Produce exactly {{ n_edits }} rewritten bullets in JSON:
{
  "bullets": [
    {"original": "...", "rewritten": "...", "mapped_requirement": "..."}
  ]
}
Strict JSON. No prose outside JSON.
