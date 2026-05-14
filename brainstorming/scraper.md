# Scraper Module — Brainstorm

## Responsibility

The scraper module's job is narrow and well-defined: **given some form of job source input, return a list of structured `JobPosting` objects and persist them to the DB**.

It does not score, match, or apply. It only discovers and stores.

---

## Three Input Modes

```
User Input
    │
    ▼
┌──────────────────────────────────────────────┐
│              CLI Input Router                 │
│  detects: company_name | url | raw_text       │
└──────────┬───────────────┬───────────────┬───┘
           │               │               │
     ┌─────▼─────┐   ┌─────▼─────┐   ┌────▼──────┐
     │  Company  │   │    URL    │   │  Raw Text │
     │   Mode    │   │   Mode    │   │   Mode    │
     └─────┬─────┘   └─────┬─────┘   └────┬──────┘
           │               │               │
           └───────────────┴───────────────┘
                           │
                    ┌──────▼──────┐
                    │  Normalizer │  → JobPosting model
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Dedup +    │
                    │  DB Write   │
                    └─────────────┘
```

---

## Mode 1: Company Name

User runs: `job-agent scrape --company "Stripe"`

### How to find the careers URL

**Option A — LLM + web search**: Ask the LLM "what is the careers page URL for Stripe?" via a search tool. Simple but can hallucinate.

**Option B — Registry + search fallback** (recommended): Maintain a YAML of known companies. For unknown ones, fall back to web search.

```yaml
# data/company_registry.yaml
stripe:
  careers_url: "https://stripe.com/jobs"
  ats: greenhouse
openai:
  careers_url: "https://openai.com/careers"
  ats: custom
notion:
  careers_url: "https://www.notion.so/careers"
  ats: lever
```

Start Option B. The registry accumulates value over time. Every new company you scrape gets added automatically.

Once the URL is resolved, **company mode falls entirely into URL mode**. No separate downstream logic needed.

---

## Mode 2: URL Mode

This is the core of the module.

### Step 1: URL Classification

```
URL received
    │
    ▼
┌─────────────────────┐
│   URL Classifier    │
│                     │
│  (A) Job listing    │  → stripe.com/jobs
│      page           │    linkedin.com/jobs/search?...
│      (many jobs)    │    greenhouse.io/company/stripe
│                     │
│  (B) Single job     │  → stripe.com/jobs/12345
│      posting        │    linkedin.com/jobs/view/87654
└──────────┬──────────┘
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
Scraper       Single-Job
Factory       Extractor
```

Classification heuristic: does the URL path end in a numeric ID or slug that looks like a specific posting? Does the page render a list of cards or a single `<article>`? An LLM call on the page title + URL is fast and reliable here.

---

## Mode 3: Raw Text

User runs: `job-agent scrape --text "$(pbpaste)"` or `job-agent scrape --file jd.txt`

No scraping needed. Just an LLM extraction call:

```
EXTRACT_PROMPT = """
Extract a structured job posting from this raw text.
Return JSON with: title, company, location, job_type,
required_skills (list), nice_to_have_skills (list),
description, salary_range.
Use null for any field not mentioned.

Text:
{raw_text}
"""
```

Result flows into the Normalizer like any other mode.

---

## The Scraper Factory (URL Listing Mode)

The centerpiece of the module. When given a job listing page URL, the factory **writes a Python scraper script** for it using an LLM.

```
URL (listing page)
    │
    ▼
┌──────────────────────────────────────────────────────┐
│                  Scraper Factory                      │
│                                                       │
│  Step 1: ATS DETECTOR                                 │
│  Is this a known ATS platform?                        │
│  → Yes: reuse existing scraper from data/scrapers/    │
│  → No: continue to Step 2                             │
│                                                       │
│  Step 2: PAGE ANALYST                                 │
│  Playwright opens URL headlessly                      │
│  → Captures: screenshot + trimmed HTML + visible text │
│  → LLM analyzes: pagination, filters, card selectors  │
│  → Returns: PageAnalysis (structured)                 │
│                                                       │
│  Step 3: SCRIPT WRITER                                │
│  LLM receives PageAnalysis + HTML excerpt             │
│  → Writes a Python scraper conforming to interface    │
│  → Saved to: data/scrapers/{domain_slug}.py           │
│                                                       │
│  Step 4: VALIDATOR / TEST RUN                         │
│  Execute the script in a subprocess with timeout      │
│  → Success: return parsed jobs list                   │
│  → Failure: go to Step 5                              │
│                                                       │
│  Step 5: RETRY LOOP (max 3 attempts)                  │
│  Feed error + traceback + failed script to LLM        │
│  → LLM rewrites the script                            │
│  → Save as v2, v3 (keep old versions)                 │
│  → All retries exhausted: notify user, dump debug info│
└──────────────────────────────────────────────────────┘
```

---

## ATS Detection

Many companies outsource their careers page to a third-party ATS. One scraper covers all companies on that platform.

```
URL received
    │
    ▼
┌─────────────────────────────┐
│       ATS Detector          │
│                             │
│  boards.greenhouse.io/      │  → data/scrapers/greenhouse.py
│  jobs.lever.co/             │  → data/scrapers/lever.py
│  myworkday.com/             │  → data/scrapers/workday.py
│  *.ashbyhq.com/             │  → data/scrapers/ashby.py
│  jobs.smartrecruiters.com/  │  → data/scrapers/smartrecruiters.py
│  Unknown domain             │  → ScraperFactory generates new one
└─────────────────────────────┘
```

Greenhouse + Lever alone cover ~40% of tech companies. Build these two first, let the factory handle the rest.

Detection is just URL string matching — no LLM needed here.

---

## The Generated Script's Standard Interface

Every script the LLM writes (and every hand-written ATS scraper) must expose the same interface:

```python
# data/scrapers/stripe_careers.py
# Auto-generated | URL: https://stripe.com/jobs | Generated: 2026-05-13

async def scrape(
    base_url: str,
    filters: dict | None = None,
    max_pages: int = 10
) -> list[dict]:
    """
    Returns:
    [
        {
            "title": str,
            "url": str,
            "company": str,
            "location": str,
            "description": str | None,
            "posted_date": str | None,
            "job_type": str | None,
        },
        ...
    ]
    """
    ...
```

The LLM is instructed: "Write an `async def scrape()` function with exactly this signature. Use playwright if the page requires JavaScript, otherwise use httpx + beautifulsoup4. The function must write JSON to stdout and exit."

**Why this matters**: the orchestrator calls `scrape(url)` without knowing which scraper it's using. All scrapers are interchangeable plugins.

---

## Script Storage

Generated scrapers persist and accumulate value:

```
data/scrapers/
    stripe_careers.py          ← active scraper for stripe.com/jobs
    stripe_careers_v2.py       ← kept for rollback/debugging
    linkedin_jobs.py
    greenhouse.py              ← covers ALL Greenhouse companies
    lever.py                   ← covers ALL Lever companies
    workday.py
    ashby.py

data/scrapers/debug/
    example_com_2026-05-13.json  ← dump when all retries fail
```

On future runs: check if `data/scrapers/{domain_slug}.py` exists. If yes, skip the factory entirely and use it directly.

---

## Script Execution Safety

LLM-generated code needs careful execution.

| Method | Safety | Simplicity | Verdict |
|---|---|---|---|
| `exec()` inline | Low | High | No — can touch env, filesystem |
| `subprocess` separate process | Medium | Medium | Yes — use this |
| Docker container | High | Low | Overkill for a local personal tool |

**Pattern**:
```python
result = subprocess.run(
    ["python", script_path, "--url", url, "--output-json"],
    capture_output=True,
    timeout=60,
    cwd=project_root
)
jobs = json.loads(result.stdout)
```

The generated script writes JSON to stdout. The factory reads stdout. If the process hangs, `timeout=60` kills it and we retry.

---

## Deduplication Strategy

```
Job candidate arrives
    │
    ▼
┌────────────────────────────────────────┐
│             Dedup Layer                │
│                                        │
│  1. URL exact match in DB?             │  → skip entirely
│     (strongest signal)                 │
│                                        │
│  2. content_hash match?                │  → skip (repost of same JD)
│     SHA256(company + title + desc[:500])│
│                                        │
│  3. company + title match, no URL?     │  → update existing record
│     (e.g. text mode then URL mode)     │
│                                        │
│  4. Truly new?                         │  → insert
└────────────────────────────────────────┘
```

Add a `content_hash TEXT` column to the jobs table for fast dedup without reading full descriptions.

---

## Retry and Failure UX

```
$ job-agent scrape --url https://example.com/careers

[1/3] Analyzing page structure...        ✓
[1/3] Writing scraper script...          ✓ saved to data/scrapers/example_com.py
[1/3] Running scraper...                 ✗ TimeoutError on line 34

[2/3] Rewriting with error context...    ✓ saved to data/scrapers/example_com_v2.py
[2/3] Running scraper...                 ✗ CSS selector '.job-card' not found

[3/3] Rewriting with error context...    ✓ saved to data/scrapers/example_com_v3.py
[3/3] Running scraper...                 ✓ Found 23 jobs. 18 new, 5 duplicates skipped.
```

If all retries fail:
```
[FAILED] Could not generate a working scraper after 3 attempts.

Debug info saved to: data/scrapers/debug/example_com_2026-05-13.json
Options:
  Retry now:      job-agent scrape --url https://example.com/careers --retry
  Edit manually:  data/scrapers/example_com_v3.py  (then re-run with --use-existing)
```

The debug dump includes: URL, all 3 script versions, all error tracebacks. Enough context to fix manually in under 10 minutes.

---

## LangGraph Subgraph for the Factory

The factory is stateful (multiple steps, retry loop) — a natural fit for a LangGraph subgraph.

```python
class ScraperFactoryState(TypedDict):
    url: str
    page_html: str
    page_screenshot: bytes
    page_analysis: dict
    current_script: str
    script_path: str
    last_error: str
    attempt: int
    max_attempts: int
    jobs: list[dict]
    success: bool

def should_retry(state: ScraperFactoryState) -> str:
    if state["success"]:
        return "done"
    if state["attempt"] >= state["max_attempts"]:
        return "failed"
    return "retry"

graph = StateGraph(ScraperFactoryState)
graph.add_node("analyze_page", analyze_page_node)
graph.add_node("write_script", write_script_node)
graph.add_node("run_script", run_script_node)
graph.add_node("done", done_node)
graph.add_node("failed", failed_node)

graph.set_entry_point("analyze_page")
graph.add_edge("analyze_page", "write_script")
graph.add_edge("write_script", "run_script")
graph.add_conditional_edges("run_script", should_retry, {
    "retry": "write_script",    # loop back, skip re-analysis
    "done": "done",
    "failed": "failed",
})
```

Note: on retry we skip `analyze_page` and go straight to `write_script` with the error context. The page structure hasn't changed — we only need to fix the script.

---

## Page Analyst Prompt

This is what gets sent to the LLM along with the screenshot and HTML excerpt:

```
You are analyzing a company job listings page to help write a scraper.

URL: {url}
Page title: {title}
Visible text (first 3000 chars): {visible_text}
HTML excerpt (first 5000 chars): {html_excerpt}
[screenshot attached]

Identify and return JSON with:
{
  "page_type": "listing" | "single_job" | "unknown",
  "requires_javascript": true | false,
  "job_card_selector": "CSS selector for each job card",
  "title_selector": "CSS selector for job title within card",
  "link_selector": "CSS selector for job URL within card",
  "location_selector": "CSS selector for location or null",
  "pagination_type": "numbered" | "load_more_button" | "infinite_scroll" | "none",
  "pagination_selector": "CSS selector for next page button or null",
  "filter_controls": ["list of filter types present: location, role, team, etc."],
  "total_jobs_visible": estimated number,
  "notes": "any quirks or special handling needed"
}
```

---

## Module File Structure

```
job_agent/scraper/
    __init__.py
    router.py           ← detects input mode (company / url / text)
    ats_detector.py     ← URL → known ATS platform name or None
    page_analyst.py     ← Playwright capture + LLM analysis
    script_writer.py    ← LLM writes the scraper Python file
    script_runner.py    ← subprocess execution + retry orchestration
    single_job.py       ← extracts one posting from a detail-page URL
    text_parser.py      ← LLM extracts structure from raw pasted text
    deduplicator.py     ← checks DB before insert, returns new-only list
    registry.py         ← loads/saves data/company_registry.yaml
```

---

## Open Questions

1. **Company name discovery**: YAML registry + web search fallback is the right call. Every new scrape auto-appends to the registry.

2. **Screenshot vs HTML**: Send both to the LLM. Screenshots let Claude understand visual layout. HTML provides the selectors. Together they're much more reliable than either alone.

3. **Max pages per scrape**: Configurable in `config.yaml`, default 5. Company sites can have 200+ postings — you don't want to scrape them all every run.

4. **Login-required pages**: Out of scope for v1. LinkedIn and similar require cookies/session. Handle in v2 with a "login first" Playwright flow that stores the session.

5. **ATS pre-built scrapers priority**: Greenhouse → Lever → Ashby → Workday. In that order. They cover the majority of Series A–C tech companies.

6. **Re-scrape frequency**: Track `last_scraped_at` per company in the registry. Only re-scrape if older than N hours (configurable). Prevents hammering the same site on every run.
