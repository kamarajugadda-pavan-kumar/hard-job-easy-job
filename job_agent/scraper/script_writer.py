"""
Takes a PageAnalysis and asks the LLM to write a Python scraper script
that conforms to the standard interface:

    async def scrape(base_url: str, filters: dict | None = None,
                     max_pages: int = 10) -> list[dict]:
        ...

The generated script is saved to data/scrapers/{domain_slug}.py.
On retry, the previous script + error traceback are included so the LLM
can fix the specific failure.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from job_agent.scraper.page_analyst import PageAnalysis

SCRAPERS_DIR = Path("data/scrapers")

SCRIPT_INTERFACE = '''
async def scrape(
    base_url: str,
    filters: dict | None = None,
    max_pages: int = 10,
) -> list[dict]:
    """
    Returns a list of dicts, each with these keys (use None for missing fields):
        title, url, company, location, description, posted_date, job_type
    Writes the result as JSON to stdout before returning.
    """
'''


def domain_slug(url: str) -> str:
    """'https://stripe.com/jobs' → 'stripe_com'"""
    host = urlparse(url).netloc.replace(".", "_").replace("-", "_")
    return re.sub(r"_+", "_", host).strip("_")


def script_path(url: str, version: int = 1) -> Path:
    slug = domain_slug(url)
    suffix = "" if version == 1 else f"_v{version}"
    return SCRAPERS_DIR / f"{slug}{suffix}.py"


async def write_script(
    analysis: PageAnalysis,
    screenshot: bytes,
    html_excerpt: str,
    previous_script: str = "",
    previous_error: str = "",
    version: int = 1,
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

    prompt = WRITE_PROMPT.format(
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

    path = script_path(analysis.url, version)
    SCRAPERS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(code)
    return path


def _extract_code(content: str | list) -> str:
    """Strip markdown fences if the LLM wrapped the code despite instructions."""
    if isinstance(content, list):
        # LangChain multimodal response — join text parts
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


WRITE_PROMPT = """
You are writing a Python web scraper for a job listings page.

TARGET URL: {url}
PAGE ANALYSIS:
{analysis_json}

HTML EXCERPT:
{html_excerpt}

[Screenshot attached for visual reference]

{retry_section}

Write a complete, runnable Python script that:
1. Defines `async def scrape(base_url, filters=None, max_pages=10) -> list[dict]`
2. Each dict has keys: title, url, company, location, description, posted_date, job_type
3. Uses `playwright.async_api` if `requires_javascript` is true, else `httpx` + `beautifulsoup4`
4. Handles pagination up to max_pages
5. Prints the result as JSON to stdout: `print(json.dumps(result))`
6. Includes `if __name__ == "__main__": asyncio.run(main())` so it can be run directly

Return ONLY the Python code. No explanation, no markdown fences.
"""

RETRY_SECTION = """
PREVIOUS ATTEMPT FAILED. Here is the script that failed:

{previous_script}

Error / traceback:
{previous_error}

Fix the specific error above. Do not rewrite from scratch unless the approach is fundamentally wrong.
"""
