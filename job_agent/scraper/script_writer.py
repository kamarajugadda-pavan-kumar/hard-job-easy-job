"""
Takes a PageAnalysis and asks the LLM to write a Python scraper script
that conforms to the standard interface:

    async def scrape(base_url: str, filters: dict | None = None,
                     max_pages: int = 10) -> list[dict]:
        ...

Two modes:
  api  — generates an httpx-based script that replays the intercepted API call.
  dom  — generates a Playwright DOM-scraping script (existing approach).

The generated script is saved to data/scrapers/{domain_slug}.py.
On retry, the previous script + error traceback are included so the LLM
can fix the specific failure.
"""
from __future__ import annotations

import json as _json
import re
from pathlib import Path
from urllib.parse import urlparse

from job_agent.scraper.page_analyst import PageAnalysis

SCRAPERS_DIR = Path("data/scrapers")


def domain_slug(url: str) -> str:
    host = urlparse(url).netloc.replace(".", "_").replace("-", "_")
    return re.sub(r"_+", "_", host).strip("_")


def script_path(url: str) -> Path:
    return SCRAPERS_DIR / f"{domain_slug(url)}.py"


async def write_script(
    analysis: PageAnalysis,
    screenshot: bytes,
    html_excerpt: str,
    previous_script: str = "",
    previous_error: str = "",
) -> Path:
    """
    Calls the LLM to generate (or fix) a scraper script.
    Saves it to data/scrapers/ and returns the path.
    """
    import base64
    from langchain_core.messages import HumanMessage
    from job_agent.llm import get_llm

    retry_section = (
        RETRY_SECTION.format(
            previous_script=previous_script,
            previous_error=previous_error,
        )
        if previous_script
        else ""
    )

    if analysis.scraper_mode == "api":
        prompt = _build_api_prompt(analysis, retry_section)
        msg = HumanMessage(content=prompt)
    else:
        prompt = DOM_WRITE_PROMPT.format(
            url=analysis.url,
            analysis_json=analysis.model_dump_json(indent=2),
            html_excerpt=html_excerpt,
            retry_section=retry_section,
        )
        image_b64 = base64.b64encode(screenshot).decode()
        msg = HumanMessage(content=[
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
            },
            {"type": "text", "text": prompt},
        ])

    llm = get_llm("script_writer")
    response = await llm.ainvoke([msg])
    code = _extract_code(response.content)

    path = script_path(analysis.url)
    SCRAPERS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(code)
    return path


def _build_api_prompt(analysis: PageAnalysis, retry_section: str) -> str:
    sample_json = _json.dumps(analysis.api_sample_record, indent=2, ensure_ascii=False)
    # Truncate very large records so they fit in context
    if len(sample_json) > 4000:
        sample_json = sample_json[:4000] + "\n  ... (truncated)"
    headers_json = _json.dumps(analysis.api_headers, indent=2)
    return API_WRITE_PROMPT.format(
        url=analysis.url,
        api_endpoint=analysis.api_endpoint,
        api_method=analysis.api_method,
        api_headers_json=headers_json,
        api_post_data=analysis.api_post_data or "(none — GET request)",
        api_list_path=analysis.api_list_path or "(inspect sample to find the list)",
        api_sample_record_json=sample_json,
        api_observed_job_url=analysis.api_observed_job_url or "(not captured — infer URL from sample record fields)",
        retry_section=retry_section,
    )


def _extract_code(content: str | list) -> str:
    if isinstance(content, list):
        text = "\n".join(
            part["text"] if isinstance(part, dict) else part
            for part in content
            if isinstance(part, str) or (isinstance(part, dict) and part.get("type") == "text")
        )
    else:
        text = content
    text = text.strip()
    match = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


# ── API-mode prompt ───────────────────────────────────────────────────────────

API_WRITE_PROMPT = """
You are writing a Python scraper that calls a company's job-listings API directly with httpx.
This is faster and more reliable than DOM scraping.

═══════════════════════════════════════
LISTING PAGE:  {url}
API ENDPOINT:  {api_endpoint}
METHOD:        {api_method}
═══════════════════════════════════════

{retry_section}

━━━ REQUIRED FUNCTION SIGNATURE ━━━
async def scrape(base_url: str, filters: dict | None = None, max_pages: int = 10) -> list[dict]:

Each returned dict MUST have these keys (use None for missing fields):
    title, url, company, location, description, posted_date, job_type

━━━ INTERCEPTED REQUEST ━━━
Headers (session-specific items already removed):
{api_headers_json}

Request body (for POST requests):
{api_post_data}

Dot-path to the job list inside the response JSON:
{api_list_path}

IMPORTANT — navigating the dot-path:
Each segment is a dict key UNLESS that segment resolves to a list of dicts, in which
case take index [0] before moving to the next key.
Example:  path "items.requisitionList"
          → data["items"][0]["requisitionList"]    (items is a list → [0] → next key)
Example:  path "hits.hits"
          → data["hits"]["hits"]                  (hits is a dict → next key)
Example:  path "data.jobs"
          → data["data"]["jobs"]                  (data is a dict → next key)
When in doubt: check whether the value at each step is a list; if so, add [0].

━━━ SAMPLE API RECORD (one raw item from the list) ━━━
{api_sample_record_json}

━━━ OBSERVED JOB DETAIL URL (captured by clicking one card on the listing page) ━━━
{api_observed_job_url}

━━━ YOUR TASKS ━━━

0. ENDPOINT URL — CRITICAL
   - The intercepted API endpoint above IS the URL to call — use it as a hardcoded
     constant in your script. Do NOT try to derive it from base_url using string
     replacement; base_url is the human-facing UI URL, not the API URL.
   - Store it as: ENDPOINT = "{api_endpoint}"

1. URL CONSTRUCTION
   - Compare the observed job detail URL to the fields in the sample record.
   - Find which field(s) build the URL slug/path and which build the query string.
   - Write code to construct the full job detail URL for every record.
   - If the job fields are nested (e.g. inside "_source"), traverse that path first.

2. FIELD EXTRACTION
   - Extract: title, company, location, posted_date, job_type from each record.
   - Fields may be nested — traverse the same path you found for URL construction.
   - Wrap each field extraction in try/except; one missing field must not crash a card.

3. PAGINATION
   - POST body: look for "from", "offset", or "page" keys. Increment by page size each loop.
     Detect end via a total-count field in the response or an empty list.
   - GET request: the offset may be a top-level query param OR embedded inside a complex
     param value (e.g. Oracle HCM's "finder=...limit=N,..."). Handle both cases:
       a) Top-level param (e.g. "?offset=0&..."): use urllib.parse to update it.
       b) Embedded in a param value (e.g. "finder=...limit=12,offset=0,..."):
            Modify the URL string directly with re.sub (import re):
              If "offset=" already appears in the URL:
                url = re.sub(r'offset=\\d+', 'offset=' + str(offset), endpoint)
              Else inject after "limit=N":
                url = re.sub(r'(limit=\\d+)', r'\\1,offset=' + str(offset), endpoint)
   - Detect end: empty job list or offset >= total.
   - Stop when the job list is empty regardless of total.

4. HEADERS & URL ENCODING — CRITICAL
   - Use the provided headers dict as a starting base.
   - Always include: "accept": "application/json", "content-type": "application/json" (for POST).
   - Add a realistic User-Agent string if one is not already present.
   - Do NOT add cookie or authorization headers; those are session-specific.
   - NEVER reconstruct the endpoint URL using httpx params=dict(...) — the URL already
     contains pre-encoded special characters (%3B, %7C, %22, etc.) that httpx will
     double-encode (%253B, %257C, etc.) causing a 400 Bad Request.
   - Always call: await client.get(url_string) where url_string is the full URL string
     with the pagination offset already substituted via re.sub (see point 3 above).

━━━ SCRIPT STRUCTURE ━━━
- Imports: httpx, json, asyncio, urllib.parse, sys
- The scrape() function using httpx.AsyncClient
- async main() that calls scrape(base_url="{url}") and prints json.dumps(result)
- if __name__ == "__main__": asyncio.run(main())

━━━ OUTPUT ━━━
Return ONLY valid Python code. No explanation, no markdown fences.
"""

# ── DOM-mode prompt ───────────────────────────────────────────────────────────

DOM_WRITE_PROMPT = """
You are writing a robust Python web scraper for a heavily JavaScript-driven job listings page.
Assume the page uses a React/Angular/Vue frontend where content renders AFTER the initial HTML load.

═══════════════════════════════════════
TARGET URL:      {url}
PAGE ANALYSIS:   {analysis_json}
HTML EXCERPT:    {html_excerpt}
[Screenshot attached for visual reference]
═══════════════════════════════════════

{retry_section}

━━━ REQUIRED FUNCTION SIGNATURE ━━━
Define this exact function:

    async def scrape(base_url: str, filters: dict | None = None, max_pages: int = 10) -> list[dict]:

Each returned dict MUST have these keys (set to None if not found):
    title, url, company, location, description, posted_date, job_type

━━━ PLAYWRIGHT RULES (follow all of these) ━━━

1. NAVIGATION — always do this after page.goto():
   - await page.wait_for_load_state("networkidle")
   - Then ALSO wait for a known job-content selector:
       await page.wait_for_selector("<job_card_or_list_selector>", timeout=15000)
   Never query the DOM immediately after goto() — React hydration happens after networkidle.

2. SELECTOR STRATEGY — never hardcode a single selector. Use a priority list:
   - Try each candidate with page.query_selector_all() and use the first that returns results.
   - Infer candidates from the HTML excerpt and screenshot (look for repeated li/div/article patterns).
   - If no candidates work, fall back to: page.query_selector_all('[class*="job"], [class*="position"], [class*="listing"], article, li')

3. LAZY LOADING — always scroll before scraping:
   await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
   await page.wait_for_timeout(1500)
   Then scroll back up if needed and re-query.

4. SHADOW DOM / IFRAMES — if query_selector_all returns 0 results on the main frame:
   - Check for iframes: frames = page.frames
   - Try the same selectors on each frame.

5. PAGINATION — pick EXACTLY ONE strategy and do not mix them:

   A) CLICK-BASED (Next/Load-More button):
      - Before clicking, record the current card count: old_count = len(cards)
      - Click the button, then wait for the page to settle with networkidle:
          await next_button.click()
          await page.wait_for_load_state("networkidle")
          await page.wait_for_timeout(800)
      - CRITICAL: Do NOT use wait_for_selector(state="attached") after clicking — on SPA
        pages the old elements stay attached in the DOM during the transition and this
        fires immediately before new content has loaded, causing the script to re-read
        the same page-1 cards on every iteration.
      - After waiting, re-query cards. If len(new_cards) == old_count, the page did not
        advance — break to avoid an infinite loop.
      - Detect end: button is disabled/hidden OR card count did not change.
      - Do NOT also navigate to a URL — clicking already does the navigation.

   B) URL-BASED (page number in query string):
      - Only use this if the URL has an obvious page query param (e.g. ?page=2, ?start=20, ?offset=20).
      - Increment that param each iteration.
      - Do NOT assume path segments are page numbers — they are usually category/filter IDs.
      - Do NOT also click a button — URL navigation already moves the page.

   NEVER combine both strategies in the same loop. Pick one and use it exclusively.

6. BOT PROTECTION & BROWSER — always use Firefox, not Chromium. Many career sites block
   headless Chromium with bot detection. Launch exactly like this:
       browser = await p.firefox.launch(headless=False)
   Then create a context with:
       context = await browser.new_context(
           viewport={{"width": 1280, "height": 900}},
           user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7; rv:125.0) Gecko/20100101 Firefox/125.0",
       )
   MANDATORY rules for page.goto():
   - Always use: await page.goto(url, wait_until="domcontentloaded", timeout=60000)
   - NEVER use wait_until="load" — it blocks on images/fonts/ads long after the DOM is ready.
   Add await page.wait_for_timeout(800) between paginated requests.

7. DOM VALIDATION — before scraping, assert you have results:
   - If len(cards) == 0 after trying all selectors, print a debug snapshot:
       print("[DEBUG] page title:", await page.title(), file=__import__('sys').stderr)
       print("[DEBUG] body excerpt:", (await page.content())[:2000], file=__import__('sys').stderr)
   - Then raise RuntimeError("No job cards found — selectors need updating")

8. FIELD EXTRACTION — be defensive on every field:
   - Always use try/except or conditional checks per field; one missing field must not crash the whole card.
   - Resolve relative URLs: use urllib.parse.urljoin(base_url, href)

━━━ SCRIPT STRUCTURE ━━━
- Imports at top (playwright, json, asyncio, sys, urllib.parse, etc.)
- The scrape() function
- An async main() that calls scrape() and does: print(json.dumps(result, ensure_ascii=False))
- if __name__ == "__main__": asyncio.run(main())

━━━ OUTPUT ━━━
Return ONLY valid Python code. No explanation, no markdown fences, no comments beyond the minimum.
"""

RETRY_SECTION = """
━━━ PREVIOUS ATTEMPT FAILED — FIX THIS ━━━

Script that failed:
{previous_script}

Error / traceback:
{previous_error}

Instructions:
- Fix the specific error above — do not rewrite from scratch unless the approach is fundamentally wrong.
- If selectors returned 0 results, try different selector candidates based on the HTML excerpt.
- If a timeout occurred, increase the timeout or add a wait_for_selector() before the failing line.
- If a field extraction crashed, wrap it in try/except and default to None.
- For API mode: if the request returned 401/403, add a note and try without auth headers.
  If the response structure was wrong, re-examine the sample record and fix the field paths.
"""
