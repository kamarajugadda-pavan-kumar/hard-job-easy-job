"""
Opens a URL with Playwright, captures a screenshot + HTML excerpt,
then asks the LLM to analyse the page structure.

Output is a PageAnalysis dataclass that the ScriptWriter uses to
generate a targeted scraper.
"""
from __future__ import annotations

from pydantic import BaseModel


class PageAnalysis(BaseModel):
    url: str
    page_type: str                        # "listing" | "single_job" | "unknown"
    requires_javascript: bool = True
    job_card_selector: str = ""
    title_selector: str = ""
    link_selector: str = ""
    location_selector: str | None = None
    pagination_type: str = "none"         # "numbered" | "load_more_button" | "infinite_scroll" | "none"
    pagination_selector: str | None = None
    filter_controls: list[str] = []
    total_jobs_visible: int = 0
    selectors_found: bool = False         # LLM sets False when job cards aren't visible in the chunk
    notes: str = ""


# ── public entry point ────────────────────────────────────────────────────────

async def analyse_page(
    url: str,
    chunk_size: int = 6_000,
    overlap: int = 600,
    max_chunks: int = 8,
) -> tuple[PageAnalysis, bytes, str]:
    """
    Opens the URL, captures screenshot + HTML, then slides a window over the
    body text until the LLM finds job-card selectors or max_chunks is reached.

    Returns
    -------
    analysis     : PageAnalysis  (selectors_found=True if successful)
    screenshot   : raw PNG bytes (passed to ScriptWriter for visual context)
    html_excerpt : the body chunk where selectors were found (or last chunk tried)
    """
    screenshot, html = await _capture_page(url)
    chunks = _body_chunks(html, chunk_size, overlap)

    analysis = PageAnalysis(url=url, page_type="unknown")
    winning_chunk = chunks[0] if chunks else html[:chunk_size]
    # print(chunks)
    # return None
    for i, chunk in enumerate(chunks[:max_chunks]):
        print(f"  [analyst] chunk {i+1}/{min(len(chunks), max_chunks)} ({len(chunk)} chars)")
        # Pass screenshot only on the first call — gives structural context without repeating cost
        candidate = await _llm_analyse(url, screenshot if i == 0 else None, chunk)
        if candidate.selectors_found:
            candidate.url = url
            return candidate, screenshot, chunk
        winning_chunk = chunk

    # No chunk had selectors — return the last attempt (best effort)
    analysis.url = url
    analysis.notes = f"No job cards found after {min(len(chunks), max_chunks)} chunks."
    return analysis, screenshot, winning_chunk


# ── internal helpers ──────────────────────────────────────────────────────────

async def _capture_page(url: str) -> tuple[bytes, str]:
    """Use Playwright to load the page and return (screenshot_bytes, full_html)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            # Extra wait for JS-heavy pages that render after networkidle
            await page.wait_for_timeout(1_500)
            screenshot = await page.screenshot(full_page=True, type="png")
            html = await page.content()
            return screenshot, html
        finally:
            await browser.close()


def _body_chunks(html: str, chunk_size: int, overlap: int) -> list[str]:
    """
    Strip noise tags, locate the job-listing container via DOM structure analysis,
    then chunk only that subtree. Falls back to anchor-heuristic chunking of the
    full body if no container is found.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "svg", "meta", "link"]):
        tag.decompose()

    body = soup.find("body") or soup
    container = _find_job_container(body)

    if container is not None:
        classes = " ".join(container.get("class", []))
        text = str(container)
        print(f"  [analyst] container found: <{container.name} class='{classes}'> ({len(text):,} chars)")
        start = 0
    else:
        print("  [analyst] no container found — falling back to anchor heuristic")
        text = str(body)
        start = _find_listing_offset(text, chunk_size)
        print(f"  [analyst] anchor offset: {start:,} / {len(text):,} chars")

    if len(text) - start <= chunk_size:
        return [text[start:]]

    chunks: list[str] = []
    pos = start
    while pos < len(text):
        chunks.append(text[pos : pos + chunk_size])
        pos += chunk_size - overlap
    return chunks


def _find_job_container(body_soup, min_repeated: int = 5):
    """
    Walk every container element in the body and score it by how many direct
    children share the same (tag, class-signature). The element whose children
    are most structurally uniform is most likely the job listing container.

    Elements inside <nav>, <header>, <footer> are excluded.
    Returns None if no element scores above min_repeated.
    """
    from collections import Counter
    from bs4 import Tag

    EXCLUDED_ANCESTORS = {"nav", "header", "footer"}
    CONTAINER_TAGS    = {"ul", "ol", "div", "section", "main", "tbody"}

    best_element = None
    best_score   = 0.0

    for element in body_soup.find_all(True):
        if element.name not in CONTAINER_TAGS:
            continue

        # Skip anything inside navigation / chrome areas
        if any(p.name in EXCLUDED_ANCESTORS for p in element.parents):
            continue

        children = [c for c in element.children if isinstance(c, Tag)]
        if len(children) < min_repeated:
            continue

        # Signature: (tag_name, sorted class tuple) per direct child
        sigs = [
            (c.name, tuple(sorted(c.get("class", []))))
            for c in children
        ]
        top_count = Counter(sigs).most_common(1)[0][1]

        # Depth bonus breaks ties in favour of more specific (deeper) containers
        depth = sum(1 for _ in element.parents)
        score = top_count + depth * 0.01

        if score > best_score:
            best_score   = score
            best_element = element

    return best_element if best_score >= min_repeated else None


def _find_listing_offset(text: str, chunk_size: int) -> int:
    """
    Regex fallback: find the first job-related class/id attribute and return
    a start offset one chunk before it so the LLM gets container context.
    """
    import re

    patterns = [
        r'(?:class|id)=["\'][^"\']*\b(job[\-_]?(?:card|item|listing|result|row|tile))\b',
        r'(?:class|id)=["\'][^"\']*\b(search[\-_]?result)\b',
        r'(?:class|id)=["\'][^"\']*\b(position|vacancy|opening|career[\-_]?listing)\b',
        r'(?:class|id)=["\'][^"\']*\b(jobs?|listings?|results?)\b',
    ]

    earliest = len(text)
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m and m.start() < earliest:
            earliest = m.start()

    if earliest == len(text):
        return 0
    return max(0, earliest - chunk_size)


async def _llm_analyse(url: str, screenshot: bytes | None, html_chunk: str) -> PageAnalysis:
    """Send one HTML chunk (+ optional screenshot) to the LLM."""
    import base64

    from langchain_core.messages import HumanMessage

    from job_agent.llm import get_llm

    prompt = ANALYST_PROMPT.format(url=url, html=html_chunk)

    content: list[dict] = []
    if screenshot is not None:
        image_b64 = base64.b64encode(screenshot).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
        })
    content.append({"type": "text", "text": prompt})

    msg = HumanMessage(content=content)
    llm = get_llm("analyst").with_structured_output(PageAnalysis)
    raw = await llm.ainvoke([msg])
    return PageAnalysis.model_validate(raw if isinstance(raw, dict) else raw.model_dump())


# ── prompts ───────────────────────────────────────────────────────────────────

ANALYST_PROMPT = """
You are analysing a chunk of HTML from a company job listings page to identify CSS selectors for a scraper.

URL: {url}

HTML CHUNK (may be a partial window of the full page body — script/style tags removed):
{html}

[A screenshot of the full page may be attached for structural context.]

Your task: find CSS selectors for job listings IN THIS CHUNK ONLY.

Return JSON matching this schema exactly:
{{
  "url": "{url}",
  "page_type": "listing" | "single_job" | "unknown",
  "requires_javascript": true | false,
  "job_card_selector": "<CSS selector for each job card, or empty string>",
  "title_selector": "<CSS selector for job title inside a card, or empty string>",
  "link_selector": "<CSS selector for the job URL inside a card, or empty string>",
  "location_selector": "<CSS selector for location inside a card, or null>",
  "pagination_type": "numbered" | "load_more_button" | "infinite_scroll" | "none",
  "pagination_selector": "<CSS selector for next-page control, or null>",
  "filter_controls": ["location", "team", ...],
  "total_jobs_visible": <integer — count of job cards visible in this chunk, 0 if none>,
  "selectors_found": true | false,
  "notes": "<observations or why selectors could not be determined>"
}}

CRITICAL RULES:
- Set "selectors_found": true ONLY if you can see actual job listing elements (titles, links) in the HTML chunk above.
- Set "selectors_found": false if this chunk contains navigation, headers, filters, footers, or other non-listing content.
- Do NOT guess or invent selectors. If job cards are not visible in this chunk, leave job_card_selector/title_selector/link_selector as empty strings and set selectors_found to false.
- The caller will slide to the next chunk and try again if selectors_found is false.
- Return only valid JSON. No explanation.
"""