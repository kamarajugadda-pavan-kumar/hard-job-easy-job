"""
Reusable Playwright helpers shared across scraper and applicator modules.
"""
from __future__ import annotations

from playwright.async_api import Browser, Page, async_playwright


async def get_page_content(url: str, wait_for: str = "networkidle") -> tuple[bytes, str]:
    """
    Load a URL with Playwright and return (screenshot_bytes, full_html).

    Parameters
    ----------
    url       : page to load
    wait_for  : Playwright wait strategy — "networkidle" | "domcontentloaded" | "load"
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await browser.new_page()
        await page.goto(url)
        await page.wait_for_load_state(wait_for)
        screenshot = await page.screenshot(full_page=True)
        html       = await page.content()
        await browser.close()
    return screenshot, html


async def get_page_text(url: str) -> str:
    """Load a URL and return the visible text content (no HTML tags)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await browser.new_page()
        await page.goto(url)
        await page.wait_for_load_state("networkidle")
        text = await page.evaluate("() => document.body.innerText")
        await browser.close()
    return text


async def get_form_fields(url: str) -> dict[str, str]:
    """
    Load a URL and return all form input fields as {name_or_id: input_type}.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await browser.new_page()
        await page.goto(url)
        await page.wait_for_load_state("networkidle")
        fields: dict[str, str] = await page.evaluate("""
            () => {
                const inputs = document.querySelectorAll('input, textarea, select');
                const result = {};
                inputs.forEach(el => {
                    const key = el.name || el.id || el.placeholder || 'unknown';
                    result[key] = el.tagName.toLowerCase() === 'select'
                        ? 'select' : (el.type || 'text');
                });
                return result;
            }
        """)
        await browser.close()
    return fields
