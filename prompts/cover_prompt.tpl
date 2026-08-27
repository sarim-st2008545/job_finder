You write short, sharp cover messages for engineers. Voice: {{ voice }}

# Candidate
Name: {{ name }}
Headline: {{ headline }}
Top achievements:
{% for a in achievements %}- {{ a }}
{% endfor %}

# Job
Title: {{ job_title }} @ {{ company }}
Description excerpt:
"""
{{ jd_excerpt }}
"""

# Company brief (may be empty)
"""
{{ company_brief }}
"""

# Task
Write {{ n_variants }} distinct cover-message variants in markdown.
Each variant must:
- be <= 180 words
- open with a specific hook tied to THIS company/job (no generic "I am excited")
- name 1-2 concrete achievements relevant to the role
- end with one clear next step
- avoid clichés like "passionate", "team player", "synergy"

Return as:
## Variant 1
<text>

## Variant 2
<text>

(etc.)
