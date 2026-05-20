"""
Opens a URL with Playwright, captures a screenshot + HTML, then either:

  API mode  — intercepts XHR/fetch responses to find the job-listings API
              endpoint, clicks one card to discover the job-detail URL pattern.

  DOM mode  — falls back to a two-pass LLM strategy:
                Pass 1: compact DOM skeleton → locate the job-listing container.
                Pass 2: container HTML → precise selector extraction.

Output is a PageAnalysis dataclass that ScriptWriter uses to generate a scraper.
"""
from __future__ import annotations

import asyncio

from pydantic import BaseModel

_MAX_CONTAINER_CHARS = 15_000  # ~4K tokens — safe under any 30K-TPM quota


class PageAnalysis(BaseModel):
    url: str
    page_type: str                        # "listing" | "single_job" | "unknown"
    requires_javascript: bool = True
    # DOM-mode fields
    job_card_selector: str = ""
    title_selector: str = ""
    link_selector: str = ""
    location_selector: str | None = None
    pagination_type: str = "none"         # "numbered" | "load_more_button" | "infinite_scroll" | "none"
    pagination_selector: str | None = None
    filter_controls: list[str] = []
    total_jobs_visible: int = 0
    selectors_found: bool = False
    notes: str = ""
    # API-mode fields (populated when scraper_mode == "api")
    scraper_mode: str = "dom"             # "api" | "dom"
    api_endpoint: str | None = None
    api_method: str = "GET"
    api_headers: dict = {}
    api_post_data: str | None = None      # raw JSON string of POST body
    api_sample_record: dict | None = None # one raw item from the intercepted list
    api_list_path: str | None = None      # dot-separated path to list, e.g. "hits.hits"
    api_observed_job_url: str | None = None  # URL captured after clicking one card


class _ContainerLocation(BaseModel):
    container_selector: str   # CSS selector for the job-listing container, or "" if unknown
    page_type: str            # "listing" | "single_job" | "unknown"


class _DomPageAnalysis(BaseModel):
    """Structured-output schema for the DOM-mode LLM pass (no API fields)."""
    url: str = ""
    page_type: str = "listing"
    requires_javascript: bool = True
    job_card_selector: str = ""
    title_selector: str = ""
    link_selector: str = ""
    location_selector: str | None = None
    pagination_type: str = "none"
    pagination_selector: str | None = None
    filter_controls: list[str] = []
    total_jobs_visible: int = 0
    selectors_found: bool = False
    notes: str = ""


# ── job-API heuristics ────────────────────────────────────────────────────────

_JOB_KEYS = frozenset({
    # camelCase
    "jobTitle", "jobId", "jobUrl", "jobCode",
    "requisitionId", "req_id", "externalId", "postingId",
    "job_title", "job_id", "requisition_id",
    "posting_title", "opening", "vacancy",
    # Weaker but common (kept; "name"/"id" removed — too generic, match link/metadata objects)
    "title", "role", "role_name",
    # PascalCase variants (Oracle HCM, SAP SuccessFactors, Taleo)
    "Title", "JobTitle", "PostedDate", "JobFamily", "PostingTitle", "JobId",
})

# Lower-cased for case-insensitive matching; strong subset requires only one hit
_JOB_KEYS_LOWER = frozenset(k.lower() for k in _JOB_KEYS)
_JOB_STRONG_KEYS_LOWER = frozenset({
    "jobtitle", "jobid", "joburl", "jobcode", "requisitionid", "req_id",
    "externalid", "postingid", "job_title", "job_id", "requisition_id",
    "posting_title", "posteddate", "postingdate",
})

# Keys that betray a search-params / result-wrapper object, not individual job records.
# If ANY of these appear in items[0], the list is rejected as a wrapper.
_SEARCH_WRAPPER_KEYS_LOWER = frozenset({
    "totaljobscount", "totalresultcount", "totalresults",
    "sortby", "searchtext", "searchid", "candidatenumber",
    "currentpage", "pagesize", "searchquery",
})


def _looks_like_job_list(items: list) -> bool:
    # Need ≥ 2 items so single-item search-result wrappers don't false-positive
    if len(items) < 2 or not isinstance(items[0], dict):
        return False
    sample_keys_lower = {k.lower() for k in items[0].keys()}

    # Reject search-parameter / result-wrapper objects
    if _SEARCH_WRAPPER_KEYS_LOWER & sample_keys_lower:
        return False

    # Case-insensitive key match
    if _JOB_KEYS_LOWER & sample_keys_lower:
        if _JOB_STRONG_KEYS_LOWER & sample_keys_lower:
            return True
        if len(_JOB_KEYS_LOWER & sample_keys_lower) >= 2:
            return True

    # One level deep (e.g. "_source", "node", "data")
    for v in items[0].values():
        if isinstance(v, dict):
            nested_keys_lower = {k.lower() for k in v.keys()}
            if _JOB_KEYS_LOWER & nested_keys_lower:
                return True
    return False


def _find_job_api_data(data) -> tuple[list[dict], str] | None:
    """
    DFS through arbitrary JSON to find the first list that looks like job postings.
    Returns (items, dot_path_to_list) or None.

    Crucially recurses into dict items inside non-matching lists so that wrapper
    structures like Oracle HCM {"items": [{..., "requisitionList": [...jobs...]}]}
    are handled correctly.
    """
    def search(node, path: str) -> tuple[list, str] | None:
        if isinstance(node, list):
            if _looks_like_job_list(node):
                return node, path
            # List didn't match — recurse into its dict items to find nested job lists
            for item in node:
                if isinstance(item, dict):
                    result = search(item, path)  # keep parent key path, not list index
                    if result:
                        return result
        elif isinstance(node, dict):
            for k, v in node.items():
                result = search(v, f"{path}.{k}" if path else k)
                if result:
                    return result
        return None

    return search(data, "")


def _registered_domain(url: str) -> str:
    """'https://sidebar.bugherd.com/...' → 'bugherd.com'"""
    from urllib.parse import urlparse
    host = urlparse(url).netloc.split(":")[0]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _list_len_at_path(data, path: str) -> int:
    try:
        node = data
        for key in path.split("."):
            if key:
                node = node[key]
        return len(node) if isinstance(node, list) else 0
    except Exception:
        return 0


# ── public entry point ────────────────────────────────────────────────────────

async def analyse_page(url: str) -> tuple[PageAnalysis, bytes, str]:
    """
    Opens the URL, then runs API-mode or DOM-mode analysis.

    Returns
    -------
    analysis        : PageAnalysis
    screenshot      : raw PNG bytes
    context_html    : container HTML (DOM mode) or "" (API mode)
    """
    screenshot, html, api_info = await _capture_page(url)

    if api_info:
        analysis = PageAnalysis(
            url=url,
            page_type="listing",
            requires_javascript=True,
            scraper_mode="api",
            api_endpoint=api_info["endpoint"],
            api_method=api_info["method"],
            api_headers=api_info["headers"],
            api_post_data=api_info.get("post_data"),
            api_sample_record=api_info.get("sample_record"),
            api_list_path=api_info.get("list_path", ""),
            api_observed_job_url=api_info.get("observed_job_url"),
            selectors_found=True,
            notes="API mode: job data intercepted from XHR/fetch response.",
        )
        print(f"  [analyst] API mode → {api_info['endpoint']}")
        print(f"  [analyst] list path: {api_info.get('list_path', '')!r}")
        if api_info.get("observed_job_url"):
            print(f"  [analyst] observed job URL: {api_info['observed_job_url']}")
        return analysis, screenshot, ""

    # DOM mode
    skeleton = _build_skeleton(html)
    print(f"  [analyst] DOM mode — skeleton built ({len(skeleton):,} chars)")
    location = await _llm_find_container(url, screenshot, skeleton)
    print(f"  [analyst] container selector: {location.container_selector!r}")
    container_html = _extract_container(html, location.container_selector)
    # Trim here so both the analysis pass and the script-writer prompt stay under quota
    container_html = _smart_trim_html(container_html)
    print(f"  [analyst] container HTML ({len(container_html):,} chars) → selector pass")
    dom = await _llm_analyse_container(url, location.page_type, container_html)
    analysis = PageAnalysis(
        url=url,
        page_type=dom.page_type,
        requires_javascript=dom.requires_javascript,
        job_card_selector=dom.job_card_selector,
        title_selector=dom.title_selector,
        link_selector=dom.link_selector,
        location_selector=dom.location_selector,
        pagination_type=dom.pagination_type,
        pagination_selector=dom.pagination_selector,
        filter_controls=dom.filter_controls,
        total_jobs_visible=dom.total_jobs_visible,
        selectors_found=dom.selectors_found,
        notes=dom.notes,
        scraper_mode="dom",
    )
    return analysis, screenshot, container_html


# ── internal helpers ──────────────────────────────────────────────────────────

async def _capture_page(url: str) -> tuple[bytes, str, dict | None]:
    """
    Load the page with Playwright.
    - Intercepts XHR/fetch responses to find job-listing API calls.
    - If an API is found, clicks one job card to discover the detail-URL pattern.

    Returns (screenshot, html, api_info | None)
    """
    from playwright.async_api import async_playwright

    api_responses: list[dict] = []

    page_domain = _registered_domain(url)

    async def on_response(response) -> None:
        try:
            if response.request.resource_type not in ("xhr", "fetch"):
                return
            # Ignore third-party requests (BugHerd, Hotjar, analytics, etc.)
            if _registered_domain(response.url) != page_domain:
                return
            if "json" not in response.headers.get("content-type", "").lower():
                return
            data = await response.json()
            found = _find_job_api_data(data)
            if found:
                items, list_path = found
                api_responses.append({
                    "endpoint": response.url,
                    "method": response.request.method,
                    "headers": dict(response.request.headers),
                    "post_data": response.request.post_data,
                    "raw_data": data,
                    "list_path": list_path,
                    "sample_record": items[0],
                })
        except Exception:
            pass

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-http2"],
        )
        try:
            page = await browser.new_page(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page.on("response", on_response)
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(3_000)
            screenshot = await page.screenshot(full_page=True, type="png")
            html = await page.content()

            api_info = None
            if api_responses:
                # Pick the candidate that returned the most jobs
                best = max(
                    api_responses,
                    key=lambda r: _list_len_at_path(r["raw_data"], r["list_path"]),
                )
                # Strip session-specific headers before storing
                best["headers"] = {
                    k: v for k, v in best["headers"].items()
                    if k.lower() not in ("host", "cookie", "authorization")
                }
                best["observed_job_url"] = await _try_get_job_url(page, url)
                api_info = best

            return screenshot, html, api_info
        finally:
            await browser.close()


async def _try_get_job_url(page, listing_url: str) -> str | None:
    """
    Click the first visible job card and return the URL we land on.
    Returns None if no clickable card is found or navigation doesn't occur.
    """
    selectors = [
        "[routerLink]",
        "lib-job",
        "[class*='job-card']",
        "[class*='job-item']",
        "[class*='job-listing']",
        "article a",
        "li a",
    ]
    for selector in selectors:
        try:
            card = await page.query_selector(selector)
            if not card:
                continue
            old_url = page.url
            await card.click()
            await page.wait_for_timeout(1_500)
            new_url = page.url
            if new_url != old_url:
                await page.go_back()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2_000)
                return new_url
        except Exception:
            continue
    return None


def _build_skeleton(html: str, max_depth: int = 10) -> str:
    from bs4 import BeautifulSoup, NavigableString, Tag

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "svg", "meta", "link"]):
        tag.decompose()

    body = soup.find("body") or soup
    lines: list[str] = []

    def walk(node: Tag, depth: int) -> None:
        if depth > max_depth:
            return
        tag_str = node.name
        node_id = node.get("id", "")
        classes = node.get("class", [])
        if node_id:
            tag_str += f"#{node_id}"
        if classes:
            tag_str += "." + ".".join(classes[:3])
        direct_text = "".join(
            str(c).strip() for c in node.children if isinstance(c, NavigableString)
        ).strip()
        if direct_text:
            preview = direct_text[:40]
            if len(direct_text) > 40:
                preview += "..."
            lines.append(f"{'  ' * depth}{tag_str} | \"{preview}\"")
        else:
            lines.append(f"{'  ' * depth}{tag_str}")
        for child in node.children:
            if isinstance(child, Tag):
                walk(child, depth + 1)

    walk(body, 0)
    return "\n".join(lines)


def _extract_container(html: str, selector: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    if selector:
        container = soup.select_one(selector)
        if container is not None:
            return str(container)
        print(f"  [analyst] selector {selector!r} did not match — falling back to full body")
    for tag in soup.find_all(["script", "style", "noscript", "svg", "meta", "link"]):
        tag.decompose()
    return str(soup.find("body") or soup)


def _smart_trim_html(html: str, max_chars: int = _MAX_CONTAINER_CHARS) -> str:
    """
    If html is within budget, return as-is.
    Otherwise try to extract the first 5 direct children (job cards) from the
    container so the LLM sees enough structure without the full blob.
    Falls back to a plain character truncation.
    """
    if len(html) <= max_chars:
        return html

    from bs4 import BeautifulSoup, Tag
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find() or soup          # outermost element
    children = [c for c in root.children if isinstance(c, Tag)]
    if children:
        sample = "".join(str(c) for c in children[:5])
        if len(sample) <= max_chars:
            note = f"\n<!-- HTML trimmed: showing first {len(children[:5])} of {len(children)} children ({len(html):,} chars total) -->"
            return sample + note

    # Plain truncation fallback
    note = f"\n<!-- HTML truncated at {max_chars:,} chars (original: {len(html):,} chars) -->"
    return html[:max_chars] + note


async def _llm_with_retry(coro_fn, max_retries: int = 3, base_delay: float = 15.0):
    """
    Call an async coroutine function, retrying on transient rate-limit errors.
    Does NOT retry 'request too large' errors — those need input reduction, not time.
    """
    for attempt in range(max_retries):
        try:
            return await coro_fn()
        except Exception as e:
            msg = str(e).lower()
            is_rate_limit = "rate_limit" in msg or "429" in msg
            is_too_large  = "too large" in msg or "maximum context" in msg or "context_length" in msg
            if is_too_large:
                raise   # can't fix by waiting
            if is_rate_limit and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"  [analyst] rate limit hit — waiting {delay:.0f}s before retry {attempt + 2}/{max_retries}...")
                await asyncio.sleep(delay)
            else:
                raise


async def _llm_find_container(url: str, screenshot: bytes, skeleton: str) -> _ContainerLocation:
    import base64
    from langchain_core.messages import HumanMessage
    from job_agent.llm import get_llm

    image_b64 = base64.b64encode(screenshot).decode()
    content: list[dict] = [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        {"type": "text", "text": SKELETON_PROMPT.format(url=url, skeleton=skeleton)},
    ]
    msg = HumanMessage(content=content)
    llm = get_llm("analyst").with_structured_output(_ContainerLocation)

    async def _call():
        raw = await llm.ainvoke([msg])
        return _ContainerLocation.model_validate(raw if isinstance(raw, dict) else raw.model_dump())

    return await _llm_with_retry(_call)


async def _llm_analyse_container(url: str, page_type: str, container_html: str) -> _DomPageAnalysis:
    from langchain_core.messages import HumanMessage
    from job_agent.llm import get_llm

    # container_html is already trimmed by analyse_page before this call
    prompt = CONTAINER_PROMPT.format(url=url, page_type=page_type, html=container_html)
    msg = HumanMessage(content=prompt)
    llm = get_llm("analyst").with_structured_output(_DomPageAnalysis)

    async def _call():
        raw = await llm.ainvoke([msg])
        return _DomPageAnalysis.model_validate(raw if isinstance(raw, dict) else raw.model_dump())

    return await _llm_with_retry(_call)


# ── prompts ───────────────────────────────────────────────────────────────────

SKELETON_PROMPT = """
You are analyzing a job listings page to locate the main job-listing container.

URL: {url}

A screenshot of the rendered page is attached. Below is a compact DOM skeleton
(tag name, id, classes, and a 40-character text preview per element):

{skeleton}

Your task: identify the single DOM element that wraps the repeating job cards
(e.g. a <ul>, <div>, or <section> whose children are individual job entries).

Return JSON matching this schema exactly:
{{
  "container_selector": "<CSS selector — e.g. 'ul.job-list' or 'div#job-results' — or empty string if unknown>",
  "page_type": "listing" | "single_job" | "unknown"
}}

RULES:
- Prefer the most specific selector that uniquely identifies the container (id > class > tag).
- If the page is a single-job detail page, set container_selector to "" and page_type to "single_job".
- If you cannot identify a container, return container_selector as "" and page_type as "unknown".
- Return only valid JSON. No explanation.
"""

CONTAINER_PROMPT = """
You are extracting CSS selectors from the HTML of a job-listing container on a company careers page.

URL: {url}
Page type hint: {page_type}

CONTAINER HTML (scripts/styles removed):
{html}

Your task: identify CSS selectors for each part of a job card within this container.

Return JSON matching this schema exactly:
{{
  "url": "{url}",
  "page_type": "listing" | "single_job" | "unknown",
  "requires_javascript": true | false,
  "job_card_selector": "<CSS selector for each job card element, or empty string>",
  "title_selector": "<CSS selector for the job title inside a card, or empty string>",
  "link_selector": "<CSS selector for the job URL anchor inside a card, or empty string>",
  "location_selector": "<CSS selector for location inside a card, or null>",
  "pagination_type": "numbered" | "load_more_button" | "infinite_scroll" | "none",
  "pagination_selector": "<CSS selector for the next-page control, or null>",
  "filter_controls": ["location", "team", ...],
  "total_jobs_visible": <integer — count of job cards visible in this HTML>,
  "selectors_found": true | false,
  "notes": "<observations or why selectors could not be determined>"
}}

CRITICAL RULES:
- Set "selectors_found": true ONLY if you can see actual job listing elements (titles, links).
- Do NOT guess or invent selectors. If job cards are not visible, leave selectors as empty strings.
- Return only valid JSON. No explanation.
"""
