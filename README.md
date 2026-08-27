# Local-first Agentic Job-Search System

A developer-first Python prototype that scans job boards, scores postings against
your canonical profile, drafts tailored resumes and cover messages, builds
one-page company briefs, and tracks everything in local SQLite + Markdown.

Nothing leaves your machine unless you point an agent at a cloud LLM provider.
All data lives in `data/` and `profile/` (both gitignored).

---

## Status

| Agent              | Phase  | Status           |
|--------------------|--------|------------------|
| Job-Scanner        | 1      | working          |
| Match & Draft      | 1      | working          |
| Company-R&D        | 1      | working          |
| Contact-Finder     | 2      | skeleton (works) |
| Outreach & Tracking| 3      | planned          |

---

## Report-first workflow (recommended)

This stack **does not apply** to jobs or send your data anywhere (except optional
LLM API calls you configure). The main command refreshes local data and writes
**one Markdown report** you open yourself:

```bash
python run.py update
```

Outputs:

- `data/reports/latest.md` — always overwritten with the newest summary  
- `data/reports/opportunities_YYYYMMDD_HHMMSSUTC.md` — timestamped snapshot  

Optional flags: `--no-scan`, `--no-match`, `--match-status new`, `--strong 0.55`.

To **only** rebuild the report from SQLite (no network):

```bash
python run.py report
```

Match scoring stores `data/applications/<job_id>/match_score.json`. By default
`config/settings.yaml` sets **`matcher.generate_drafts: false`** so you get
rankings and notes without cover/resume files. Set it to `true` when you want
local draft markdown for specific roles.

---

## Quickstart

```bash
# 1. Install deps (Python 3.10+ recommended)
python -m venv .venv
.venv\Scripts\activate                   # on Windows
pip install -r requirements.txt

# 2. Initialize profile + .env from examples
python run.py init

# 3. Edit profile/profile.yaml with your real CV
#    Edit .env to pick LLM_PROVIDER (default = mock, works offline)

# 4. Refresh board + score + write data/reports/latest.md
python run.py update

# 5. Open the report in your editor or Markdown viewer
#    (path is printed at the end of the command)

# 6. See raw queue in the terminal
python run.py status
python run.py list

# 7. Inspect one job + scoring artifact
python run.py show <job_id>

# 8. Add a job by URL or pasted JD
python run.py add-job "https://example.com/some/job"
python run.py add-job --text-file ./jd.txt --title "Senior ML" --company "Acme AI"

# 9. Build a one-page company brief (optional, on your shortlist)
python run.py brief "Acme AI"

# 10. Generate likely email candidates for known contacts (optional)
python run.py contacts "Acme AI" -n "Jane Doe (Head of AI)" -n "John Roe (CTO)"

# 11. Run continuously (every 4 hours): scan → score new → refresh report
python run.py schedule --every 4
```

---

## Folder layout

```
job_finder/
├── run.py                       CLI entrypoint
├── requirements.txt
├── README.md
├── .env.example                 secrets template (LLM keys, etc.)
├── .gitignore
├── config/
│   └── settings.yaml            scanner sources, scoring weights, filters
├── prompts/
│   ├── match_prompt.tpl
│   ├── cover_prompt.tpl
│   ├── resume_bullet_prompt.tpl
│   └── company_brief_prompt.tpl
├── profile/
│   ├── profile.example.yaml     fill this out -> save as profile.yaml
│   └── profile.yaml             your canonical profile (gitignored)
├── jobfinder/                   package
│   ├── cli.py                   typer commands
│   ├── config.py                settings + env + paths
│   ├── db.py                    SQLite schema + upserts
│   ├── models.py                pydantic data models
│   ├── logging_setup.py         rich + JSONL audit log
│   ├── reporting.py             opportunities Markdown report
│   ├── utils.py                 scoring/io helpers
│   ├── scheduler.py             APScheduler loop
│   ├── llm/                     provider abstraction
│   │   ├── base.py
│   │   ├── factory.py
│   │   ├── prompts.py           Jinja loader
│   │   ├── mock.py              offline default
│   │   ├── openai_provider.py
│   │   ├── anthropic_provider.py
│   │   └── ollama_provider.py
│   ├── vectorstore/
│   │   └── chroma_store.py      local Chroma + sentence-transformers
│   ├── sources/                 job-board plugins
│   │   ├── base.py
│   │   ├── remoteok.py          public JSON, no auth (on by default)
│   │   ├── rss.py               any RSS/Atom feed
│   │   ├── manual.py            paste URL or JD text
│   │   └── linkedin_playwright.py    PUBLIC search results only
│   └── agents/
│       ├── base.py
│       ├── job_scanner.py
│       ├── matcher.py
│       ├── company_research.py
│       └── contact_finder.py
├── data/                        all output (gitignored)
│   ├── app.db                   SQLite
│   ├── raw_jobs/                raw HTML/text per job
│   ├── reports/
│   │   ├── latest.md            newest opportunities report (overwrite)
│   │   └── opportunities_*.md time-stamped snapshots
│   ├── applications/<job_id>/
│   │   ├── match_score.json
│   │   ├── resume_tailored.md
│   │   ├── cover_draft.md
│   │   └── bullets.json
│   ├── companies/<slug>/
│   │   ├── brief.md
│   │   ├── sources.md
│   │   └── contacts.csv
│   └── vector_store/            Chroma persistence
└── logs/
    └── jobfinder.log.jsonl
```

---

## LLM providers

`LLM_PROVIDER` in `.env` controls which provider the agents call.

| Value      | Cost                                 | Setup                                                                  |
|------------|--------------------------------------|------------------------------------------------------------------------|
| `mock`     | free, offline                        | no setup; always returns deterministic placeholder output             |
| `openai`   | API usage                            | `OPENAI_API_KEY`, `LLM_MODEL=gpt-4o-mini` (cheap) or `gpt-4o`         |
| `anthropic`| API usage                            | `ANTHROPIC_API_KEY`, `LLM_MODEL=claude-3-5-haiku-latest`              |
| `ollama`   | free, local CPU/GPU                  | install Ollama, run `ollama pull llama3.1:8b`, set `LLM_MODEL`        |

All providers fall back to `mock` automatically if init fails (missing key, etc.)
so the pipeline never breaks because of an LLM outage.

---

## Adding a new job source

1. Create `jobfinder/sources/myboard.py`
2. Subclass `JobSource`, decorate with `@register("myboard")`
3. Implement `.fetch(limit)` returning an iterable of `RawJob`
4. Enable it in `config/settings.yaml`:

```yaml
scanner:
  sources:
    - name: myboard
      enabled: true
      my_option: 123
```

---

## Privacy and ToS notes

- LinkedIn and Indeed both restrict automated scraping. The provided
  `linkedin_playwright` source hits **public** search pages only and is meant
  for personal low-volume use. Prefer subscribing to LinkedIn / Indeed email
  alerts and ingesting them via the `manual` source or an IMAP-backed source
  you add.
- The system never auto-submits applications. Every generated draft is held
  in `review_required` until you mark it as applied.
- All secrets live in `.env` (gitignored). The DB and raw HTML never leave
  `data/` unless you copy them out.

---

## Roadmap

- IMAP/Gmail ingestion for job-alert emails
- Streamlit dashboard reading `app.db`
- Resume rendering to PDF (markdown -> pandoc/weasyprint)
- Outreach Agent (Gmail draft creation w/ manual approval gate)
- Eval harness so the matcher can be tuned against your historical applications
