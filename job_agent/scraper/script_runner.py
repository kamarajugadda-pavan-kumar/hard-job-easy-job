"""
Executes a generated scraper script in a subprocess and returns parsed jobs.

ScraperFactory orchestrates the full loop:
  1. analyse_page  (LLM-assisted DOM/API analysis)
  2. write_script  (LLM writes a Playwright/httpx scraper)
  3. run_script    (subprocess execution)
  4. retry loop    (LLM fixes errors)
  5. human assist  (if pagination fails after 2 LLM attempts, ask the user to
                    click Next Page once while the browser is open, capture what
                    changed, and give that context to the LLM for one final pass)
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel

from job_agent.models.job import JobPosting
from job_agent.scraper.page_analyst import PageAnalysis, _registered_domain, analyse_page
from job_agent.scraper.script_writer import script_path, write_script

# ── error signals that suggest pagination is the root cause ──────────────────
_PAGINATION_SIGNALS = (
    "timeout", "pagination", "next page", "load more",
    "no job cards", "staleelementreference", "click", "button",
)


class RunResult(BaseModel):
    success: bool
    jobs: list[dict] = []
    error: str = ""
    stdout: str = ""
    stderr: str = ""


def run_script(path: Path, url: str, timeout: int = 300) -> RunResult:
    """Execute a scraper script in a subprocess. Expects JSON array on stdout."""
    result = subprocess.run(
        ["python", str(path), "--url", url, "--output-json"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        return RunResult(success=False, error=result.stderr, stderr=result.stderr)
    try:
        jobs = json.loads(result.stdout)
        return RunResult(success=True, jobs=jobs, stdout=result.stdout)
    except json.JSONDecodeError as e:
        return RunResult(success=False, error=f"JSON decode failed: {e}", stdout=result.stdout)


async def run_ats_scraper(ats_slug: str, url: str) -> list[JobPosting]:
    """Run a pre-built ATS scraper; fall back to ScraperFactory if missing."""
    ats_path = Path(f"data/scrapers/{ats_slug}.py")
    if not ats_path.exists():
        factory = ScraperFactory(url)
        return await factory.run()
    result = run_script(ats_path, url, timeout=1800)  # 30 min — large sites (PwC ~4500 jobs)
    if result.success:
        return _dicts_to_postings(result.jobs)
    raise RuntimeError(f"Pre-built ATS scraper failed: {result.error}")


class ScraperFactory:
    """
    Orchestrates: analyse_page → write_script → run_script, with retry loop.

    On attempt 3, if the error looks pagination-related, pauses and asks the
    user to demonstrate one pagination click in the open browser window.
    Captures what changed (URL params, XHR endpoint) and gives that context
    to the LLM so it can fix the pagination logic concretely.
    """

    def __init__(self, url: str, max_attempts: int = 5):
        self.url          = url
        self.max_attempts = max_attempts

    async def run(self) -> list[JobPosting]:
        # ── cache hit ──────────────────────────────────────────────────────
        existing_path = script_path(self.url)
        if existing_path.exists():
            print(f"  [cache] Using existing script: {existing_path}")
            result = run_script(existing_path, self.url)
            if result.success and result.jobs:
                print(f"  Found {len(result.jobs)} jobs.")
                return _dicts_to_postings(result.jobs)
            print(f"  [cache] Existing script failed: {result.error.splitlines()[0]}")
            print("  Regenerating from scratch...")
            previous_script = existing_path.read_text()
            previous_error  = result.error
        else:
            previous_script = ""
            previous_error  = ""

        # ── page analysis (opens browser once) ────────────────────────────
        analysis, screenshot, html = await analyse_page(self.url)
        self._dump_analysis(analysis)

        human_observation = ""  # filled if human help is triggered

        for attempt in range(1, self.max_attempts + 1):
            # ── human-assist gate (attempt 3, pagination failures only) ───
            if (
                attempt == 3
                and previous_error
                and not human_observation
                and _looks_like_pagination_failure(previous_error)
            ):
                human_observation = await _capture_pagination_with_human(self.url)
                if human_observation:
                    print(f"  [human assist] captured: {human_observation[:120]}")

            # Build the error context (append human observation when available)
            error_ctx = previous_error
            if human_observation:
                error_ctx = (
                    previous_error
                    + "\n\n━━━ HUMAN-DEMONSTRATED PAGINATION ━━━\n"
                    + "The user manually clicked the pagination control in the browser.\n"
                    + "Here is what was observed:\n"
                    + human_observation
                    + "\n\nUse this information to fix the pagination logic in the script."
                )

            print(f"[{attempt}/{self.max_attempts}] Writing scraper script...")
            path = await write_script(
                analysis, screenshot, html,
                previous_script=previous_script,
                previous_error=error_ctx,
            )

            print(f"[{attempt}/{self.max_attempts}] Running scraper...")
            result = run_script(path, self.url)

            if result.success:
                postings = _dicts_to_postings(result.jobs)
                if postings:
                    print(f"  Found {len(postings)} jobs.")
                    return postings

                # Script "ran" but produced no usable data — treat as failure
                raw_count = len(result.jobs)
                if raw_count == 0:
                    msg = (
                        "Script ran successfully but returned 0 records. "
                        "The selectors may not match rendered content."
                    )
                else:
                    msg = (
                        f"Script returned {raw_count} records but all had null title/url. "
                        f"The selectors are too broad (matching non-job elements like nav/footer). "
                        f"Use more specific selectors — look for job-specific attributes like "
                        f"data-automation-id, data-job-id, or classes containing 'job', 'position', 'result'."
                    )
                result = RunResult(success=False, error=msg)

            print(f"  Failed: {result.error.splitlines()[0]}")
            previous_script = path.read_text()
            previous_error  = result.error
            self._dump_attempt(attempt, previous_script, previous_error)

        raise RuntimeError(
            f"ScraperFactory: all {self.max_attempts} attempts failed for {self.url}.\n"
            f"Debug logs saved to data/scrapers/debug/"
        )

    def _dump_analysis(self, analysis: PageAnalysis) -> None:
        path = script_path(self.url).with_suffix(".analysis.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(analysis.model_dump_json(indent=2))
        print(f"  [analyst] analysis saved → {path}")

    def _dump_attempt(self, attempt: int, script: str, error: str) -> None:
        from datetime import datetime
        debug_dir = Path("data/scrapers/debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        slug = self.url.replace("https://", "").replace("/", "_")[:40]
        ts   = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        (debug_dir / f"{slug}_attempt{attempt}_{ts}.json").write_text(
            json.dumps({"url": self.url, "attempt": attempt, "script": script, "error": error}, indent=2)
        )


# ── human-assist helpers ──────────────────────────────────────────────────────

def _looks_like_pagination_failure(error: str) -> bool:
    lower = error.lower()
    return any(s in lower for s in _PAGINATION_SIGNALS)


async def _capture_pagination_with_human(url: str) -> str:
    """
    Open a visible browser at `url`, ask the user to click the pagination
    control once, then capture and return a plain-English description of what
    changed (URL parameters, XHR endpoint/body).

    Returns an observation string for the LLM, or "" on failure.
    """
    from playwright.async_api import async_playwright

    print()
    print("=" * 62)
    print("  HUMAN HELP NEEDED  —  Pagination")
    print("=" * 62)
    print(f"  Opening browser at: {url}")
    print()

    page_domain = _registered_domain(url)
    new_xhrs: list[dict] = []

    async def on_response(response) -> None:
        try:
            if response.request.resource_type not in ("xhr", "fetch"):
                return
            if _registered_domain(response.url) != page_domain:
                return
            if "json" not in response.headers.get("content-type", "").lower():
                return
            new_xhrs.append({
                "url":       response.url,
                "method":    response.request.method,
                "post_data": response.request.post_data,
            })
        except Exception:
            pass

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False, args=["--disable-http2"])
            page = await browser.new_page(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(3_000)
            before_url = page.url

            page.on("response", on_response)

            print("  The browser is now open and showing the careers page.")
            print()
            print("  ACTION: Please click the 'Next Page', '›', or 'Load More'")
            print("          button in the browser window.")
            print()
            input("  Press Enter here after you have clicked it... ")

            await page.wait_for_timeout(2_500)
            after_url = page.url
            await browser.close()

    except Exception as e:
        print(f"  [human assist] browser error: {e}")
        return ""

    # ── build observation string ──────────────────────────────────────────
    observations: list[str] = []

    if after_url != before_url:
        observations.append(f"URL changed after click:")
        observations.append(f"  Before: {before_url}")
        observations.append(f"  After:  {after_url}")

        # Highlight which query param changed (e.g. page=1 → page=2)
        before_qs = parse_qs(urlparse(before_url).query)
        after_qs  = parse_qs(urlparse(after_url).query)
        for k, vals in after_qs.items():
            before_val = before_qs.get(k, ["(absent)"])[0]
            if before_val != vals[0]:
                observations.append(
                    f"  Query param '{k}' changed: {before_val!r} → {vals[0]!r}"
                )

        # Path change (e.g. /page/1 → /page/2)
        before_path = urlparse(before_url).path
        after_path  = urlparse(after_url).path
        if before_path != after_path:
            observations.append(f"  Path changed: {before_path!r} → {after_path!r}")
    else:
        observations.append("URL did not change (likely AJAX / load-more pattern).")

    # Filter to first meaningful XHR (ignore tiny ones)
    meaningful = [x for x in new_xhrs if x["url"] != before_url]
    if meaningful:
        xhr = meaningful[0]
        observations.append(f"New XHR fired after click:")
        observations.append(f"  {xhr['method']} {xhr['url']}")
        if xhr.get("post_data"):
            observations.append(f"  Request body: {xhr['post_data'][:400]}")

    if not observations:
        return "No URL or XHR change detected after the user clicked."

    result = "\n".join(observations)
    print()
    print("  [captured]")
    for line in observations:
        print(f"  {line}")
    print()
    return result


# ── helpers ───────────────────────────────────────────────────────────────────

def _company_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.replace("www.", "")
        name = host.split(".")[-2]
        return name.upper() if len(name) <= 4 else name.capitalize()
    except Exception:
        return ""


def _dicts_to_postings(raw: list[dict]) -> list[JobPosting]:
    from datetime import datetime, timezone
    seen_urls: set[str] = set()
    postings = []
    for d in raw:
        d = {k: v for k, v in d.items() if v is not None}
        if not d.get("title"):
            continue
        url = d.get("url", "")
        if url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
        if not d.get("company") and url:
            d["company"] = _company_from_url(url)
        if isinstance(d.get("posted_date"), (int, float)):
            ts = d["posted_date"]
            if ts > 1e10:
                ts /= 1000
            d["posted_date"] = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        try:
            postings.append(JobPosting(**d))
        except Exception as e:
            print(f"  [warn] skipped job dict: {e} | keys={list(d.keys())} | sample={str(d)[:200]}")
    return postings
