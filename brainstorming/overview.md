# Job Application Agent — Project Overview

## What We're Building

A local, LLM-powered CLI tool that:
1. Ingests your profile (CV, skills, projects)
2. Scrapes job boards and company career pages
3. Scores each posting against your profile
4. Generates a tailored resume for qualifying jobs
5. Uses Playwright to fill and submit applications
6. Pauses for your review before hitting "Submit"
7. Shows everything in a terminal dashboard

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   LangGraph Orchestrator              │
│                                                       │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Scraper  │→ │ Matcher  │→ │  Resume Builder   │  │
│  │  Agent   │  │  Agent   │  │      Agent        │  │
│  └──────────┘  └──────────┘  └─────────┬─────────┘  │
│                                         │             │
│                               ┌─────────▼─────────┐  │
│                               │  Application Agent │  │
│                               │  (Playwright)      │  │
│                               └─────────┬─────────┘  │
│                                         │             │
│                               ┌─────────▼─────────┐  │
│                               │  HUMAN IN THE LOOP │  │
│                               │  (CLI review)      │  │
│                               └───────────────────┘  │
└─────────────────────────────────────────────────────┘
         │                              │
   ┌─────▼──────┐               ┌───────▼──────┐
   │  SQLite DB │               │  Rich TUI     │
   │  (jobs,    │               │  Dashboard    │
   │  apps)     │               └──────────────┘
   └────────────┘
```

---

## Tech Stack

| Purpose | Library | Why |
|---|---|---|
| LLM calls | `langchain-anthropic` | Claude API |
| Agent workflows | `langgraph` | Stateful, resumable graphs |
| Browser automation | `playwright` | Best async browser control |
| Web scraping | `beautifulsoup4` + `httpx` | Fast static scraping |
| PDF parsing | `pdfplumber` | Reliable CV text extraction |
| DOCX generation | `python-docx` | Resume output |
| Data models | `pydantic v2` | Validation + serialization |
| CLI | `typer` | Clean command interface |
| Terminal UI | `rich` + `textual` | Dashboard |
| Database | `sqlite3` (stdlib) | Zero-setup local storage |
| Templates | `jinja2` | Resume templating |

---

## Project Structure

```
hard-job-easy-job/
├── pyproject.toml               # dependencies
├── .env                         # ANTHROPIC_API_KEY
├── config.yaml                  # sites to scrape, thresholds
│
├── data/
│   ├── profile/
│   │   ├── resume.pdf           # your base CV
│   │   ├── skills.yaml          # explicit skills list
│   │   └── projects.md          # project descriptions
│   ├── resumes/                 # generated tailored resumes
│   └── db/
│       └── jobs.db              # SQLite
│
├── job_agent/
│   ├── __init__.py
│   ├── main.py                  # CLI entry point (typer)
│   │
│   ├── models/
│   │   ├── profile.py           # UserProfile pydantic model
│   │   ├── job.py               # JobPosting pydantic model
│   │   └── application.py       # Application pydantic model
│   │
│   ├── storage/
│   │   ├── db.py                # SQLite wrapper
│   │   └── migrations.py        # schema setup
│   │
│   ├── agents/
│   │   ├── scraper.py           # Job discovery agent
│   │   ├── matcher.py           # Scoring agent
│   │   ├── resume_builder.py    # Resume customization agent
│   │   └── applicator.py        # Playwright application agent
│   │
│   ├── graphs/
│   │   ├── discovery_graph.py   # LangGraph: scrape → match → store
│   │   └── apply_graph.py       # LangGraph: build resume → apply → HITL
│   │
│   ├── tools/
│   │   ├── browser_tools.py     # Playwright as LangChain tools
│   │   ├── profile_loader.py    # CV/PDF ingestion
│   │   └── resume_renderer.py   # DOCX/PDF output
│   │
│   └── dashboard/
│       └── app.py               # Textual TUI
```

---

## Module Breakdown

### Module 1: Profile Ingestion

Run once at startup, cache result as `data/profile/profile.json`. Regenerate only when CV is updated.

- Parse PDF/DOCX resume with `pdfplumber`
- Load explicit skills from `skills.yaml`
- LLM extracts structured profile: name, skills, experience, education, projects
- Output: `UserProfile` Pydantic model persisted as JSON

### Module 2: Scraper

See `scraper.md` for full design. Three input modes:
- **Company name** → find careers URL → batch scrape
- **URL** → detect listing vs single posting → scrape accordingly
- **Raw text** → LLM extracts structure directly

Generates reusable Python scraper scripts per site. ATS detection skips regeneration for known platforms (Greenhouse, Lever, Workday).

### Module 3: Matcher / Scorer

LangGraph sequential graph: scrape → score → filter → save.

LLM scores each job 0–100 against your profile. Jobs above the configured threshold are saved to DB with score + reasoning + identified gaps/strengths.

```
Score guide:
  85+   → strong match
  65–84 → decent match, worth applying
  <65   → skip
```

### Module 4: Resume Builder

- DOCX template with `{{placeholders}}` for your base resume
- LLM decides: which skills to emphasize, how to reorder experience bullets, how to rewrite summary
- Output: tailored `.docx` per job, saved to `data/resumes/`
- Avoid tables/columns in template — ATS parsers hate them

### Module 5: Application Agent (Playwright + HITL)

LangGraph graph with `SqliteSaver` checkpointer for state persistence.

Flow: `build_resume → analyze_form → [PAUSE] → human_review → submit`

The `interrupt_before=["submit"]` pattern pauses the graph before submission. The checkpoint is saved to SQLite. User reviews in CLI and resumes with approval.

```bash
job-agent apply <job_id>      # starts, pauses for review
job-agent approve <job_id>    # resumes from checkpoint, submits
```

### Module 6: Dashboard

Textual TUI with:
- Job table (company, title, score, status, date)
- Filter by status: discovered / matched / applied / rejected
- Keyboard shortcuts: `a` apply, `s` skip, `r` refresh, `q` quit

---

## Data Models

### JobPosting

```python
class JobStatus(str, Enum):
    DISCOVERED = "discovered"
    MATCHED    = "matched"
    SKIPPED    = "skipped"
    RESUME_READY = "resume_ready"
    APPLIED    = "applied"
    REJECTED   = "rejected"
    INTERVIEW  = "interview"

class JobPosting(BaseModel):
    id: str                      # sha256(url or company+title)
    url: str
    company: str
    title: str
    location: str
    description: str
    required_skills: list[str]
    nice_to_have: list[str]
    match_score: float
    match_reasoning: str
    status: JobStatus
    scraped_at: datetime
    applied_at: datetime | None
    resume_path: str | None
    notes: str
```

### SQLite Schema

```sql
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    url TEXT UNIQUE,
    company TEXT,
    title TEXT,
    location TEXT,
    description TEXT,
    required_skills TEXT,    -- JSON array
    match_score REAL,
    match_reasoning TEXT,
    status TEXT,
    scraped_at TEXT,
    applied_at TEXT,
    resume_path TEXT,
    notes TEXT
);

CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    cover_letter TEXT,
    form_data TEXT,          -- JSON of filled fields
    submitted_at TEXT,
    outcome TEXT
);
```

---

## `pyproject.toml` Dependencies

```toml
[project]
name = "hard-job-easy-job"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "langchain-anthropic>=0.3",
    "langgraph>=0.2",
    "langchain-core>=0.3",
    "playwright>=1.44",
    "beautifulsoup4>=4.12",
    "httpx>=0.27",
    "pdfplumber>=0.11",
    "python-docx>=1.1",
    "pydantic>=2.7",
    "typer>=0.12",
    "rich>=13",
    "textual>=0.60",
    "jinja2>=3.1",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
]

[project.scripts]
job-agent = "job_agent.main:app"
```

After install: `playwright install chromium` (one-time, downloads the browser binary)

---

## Build Order

```
Week 1 — Foundation
  - pyproject.toml, .env, project skeleton
  - SQLite schema + db.py
  - Pydantic models
  - Profile loader (PDF → structured JSON)
  - Simple score_job() LLM call (no graph yet)

Week 2 — Discovery Pipeline
  - Static scraper for 1 target site
  - Discovery LangGraph (scrape → score → save)
  - typer CLI: discover command
  - Basic Rich table to view results

Week 3 — Resume Builder + Playwright Intro
  - DOCX template + python-docx renderer
  - Playwright: open a job URL, take a screenshot
  - Form analyzer: read all input fields on an apply page
  - Profile-to-form mapper (LLM maps data to field names)

Week 4 — Application Graph + HITL
  - Apply LangGraph with SqliteSaver checkpointer
  - interrupt_before=["submit"] pattern working
  - approve command resumes graph
  - End-to-end: discover → resume → fill → pause → approve → submit

Week 5 — Dashboard + Polish
  - Textual TUI with job table and status filters
  - Keyboard shortcuts from dashboard
  - Error handling, logging, retry logic
```

---

## Key Gotchas

1. **LinkedIn blocks scrapers** — start with simpler sites; use Playwright with a logged-in session (stored cookies) for LinkedIn.

2. **LangGraph HITL requires a checkpointer** — `interrupt_before` only works when `SqliteSaver` (or another checkpointer) is attached. Without it, state is lost between CLI calls.

3. **Playwright async vs sync** — use `async_playwright` with `asyncio.run()`. Don't mix sync Playwright inside an async LangGraph node without wrapping properly.

4. **Rate limiting** — add `await asyncio.sleep(2)` between page requests to avoid IP bans.

5. **LLM output parsing** — use `langchain_core.output_parsers.JsonOutputParser` with a Pydantic model. Don't regex-parse LLM JSON manually.

6. **Resume ATS compatibility** — no tables or columns in the DOCX template. Plain paragraphs with clear section headers only.

---

## Showcase Value

When describing this project in interviews:
- "Multi-agent LangGraph pipeline with stateful checkpointing and human-in-the-loop interrupts"
- "Playwright browser automation for dynamic form detection and submission"
- "LLM-driven semantic job matching and personalized resume generation"
- "Self-writing scraper factory: LLM generates and validates site-specific scrapers"
- "Textual TUI for real-time job tracking"