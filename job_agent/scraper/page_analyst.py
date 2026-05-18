"""
Opens a URL with Playwright, captures a screenshot + HTML, then uses a
two-pass LLM strategy to find job-card selectors:

  Pass 1 — send a compact DOM skeleton to locate the job-listing container.
  Pass 2 — send the container's full HTML for precise selector extraction.

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
    selectors_found: bool = False
    notes: str = ""


class _ContainerLocation(BaseModel):
    container_selector: str   # CSS selector for the job-listing container, or "" if unknown
    page_type: str            # "listing" | "single_job" | "unknown"


# ── public entry point ────────────────────────────────────────────────────────

async def analyse_page(url: str) -> tuple[PageAnalysis, bytes, str]:
    """
    Opens the URL, captures screenshot + HTML, then runs a two-pass analysis:

      Pass 1: build a compact DOM skeleton and ask the LLM for the container CSS path.
      Pass 2: extract that container's HTML and ask the LLM for precise selectors.

    Returns
    -------
    analysis        : PageAnalysis  (selectors_found=True if successful)
    screenshot      : raw PNG bytes (passed to ScriptWriter for visual context)
    container_html  : the container subtree used for selector extraction
    """
    screenshot, html = await _capture_page(url)

    # Pass 1: skeleton → container selector
    skeleton = _build_skeleton(html)
    print(f"  [analyst] skeleton built ({len(skeleton):,} chars)")
    location = await _llm_find_container(url, screenshot, skeleton)
    print(f"  [analyst] container selector: {location.container_selector!r}")

    # Pass 2: extract container HTML → precise selectors
    container_html = _extract_container(html, location.container_selector)
    print(f"  [analyst] container HTML ({len(container_html):,} chars) → selector pass")
    analysis = await _llm_analyse_container(url, location.page_type, container_html)
    analysis.url = url
    return analysis, screenshot, container_html


# ── internal helpers ──────────────────────────────────────────────────────────

async def _capture_page(url: str) -> tuple[bytes, str]:
    """Use Playwright to load the page and return (screenshot_bytes, full_html)."""
    from playwright.async_api import async_playwright

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
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(3_000)
            screenshot = await page.screenshot(full_page=True, type="png")
            html = await page.content()
            return screenshot, html
        finally:
            await browser.close()


def _build_skeleton(html: str, max_depth: int = 10) -> str:
    """
    Build a compact structural outline of the page DOM.

    Each line:  <indent><tag>[#id][.class1.class2] [| "first 40 chars of direct text"]

    Scripts, styles, SVG paths and similar noise are stripped first.
    """
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
            # cap at 3 classes to keep lines short
            tag_str += "." + ".".join(classes[:3])

        direct_text = "".join(
            str(c).strip()
            for c in node.children
            if isinstance(c, NavigableString)
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
    """
    Return the HTML subtree matched by selector.
    Falls back to the cleaned full body if selector is empty or unmatched.
    """
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


async def _llm_find_container(url: str, screenshot: bytes, skeleton: str) -> _ContainerLocation:
    """Pass 1: send the DOM skeleton (+ screenshot) to locate the job-listing container."""
    import base64

    from langchain_core.messages import HumanMessage

    from job_agent.llm import get_llm

    image_b64 = base64.b64encode(screenshot).decode()
    content: list[dict] = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
        },
        {"type": "text", "text": SKELETON_PROMPT.format(url=url, skeleton=skeleton)},
    ]

    msg = HumanMessage(content=content)
    llm = get_llm("analyst").with_structured_output(_ContainerLocation)
    raw = await llm.ainvoke([msg])
    return _ContainerLocation.model_validate(raw if isinstance(raw, dict) else raw.model_dump())


async def _llm_analyse_container(url: str, page_type: str, container_html: str) -> PageAnalysis:
    """Pass 2: send the container HTML to extract precise CSS selectors."""
    from langchain_core.messages import HumanMessage

    from job_agent.llm import get_llm

    prompt = CONTAINER_PROMPT.format(url=url, page_type=page_type, html=container_html)
    msg = HumanMessage(content=prompt)
    llm = get_llm("analyst").with_structured_output(PageAnalysis)
    raw = await llm.ainvoke([msg])
    return PageAnalysis.model_validate(raw if isinstance(raw, dict) else raw.model_dump())


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