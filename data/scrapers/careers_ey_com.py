import asyncio
from playwright.async_api import async_playwright
from urllib.parse import urljoin
import json

async def scrape(base_url: str, filters: dict | None = None, max_pages: int = 10) -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36")
        )
        await page.goto(base_url)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_selector('tr.data-row', timeout=15000)

        jobs = []
        for _ in range(max_pages):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)
            
            cards = await page.query_selector_all('tr.data-row')
            if len(cards) == 0:
                frames = page.frames
                for frame in frames:
                    cards = await frame.query_selector_all('tr.data-row')
                    if cards:
                        break
                if len(cards) == 0:
                    print("[DEBUG] page title:", await page.title(), file=__import__('sys').stderr)
                    print("[DEBUG] body excerpt:", (await page.content())[:2000], file=__import__('sys').stderr)
                    raise RuntimeError("No job cards found — selectors need updating")

            for card in cards:
                try:
                    title_el = await card.query_selector("a.jobTitle-link")
                    title = await title_el.inner_text() if title_el else None
                    url = urljoin(base_url, await title_el.get_attribute("href")) if title_el else None
                    location_el = await card.query_selector("span.jobLocation")
                    location = await location_el.inner_text() if location_el else None
                    jobs.append({
                        "title": title,
                        "url": url,
                        "company": None,
                        "location": location,
                        "description": None,
                        "posted_date": None,
                        "job_type": None
                    })
                except Exception as e:
                    print(f"[ERROR] Failed to process a job card: {e}", file=__import__('sys').stderr)

            next_button = await page.query_selector('a.next')
            if not next_button or not await next_button.is_enabled():
                break
            await next_button.click()
            await page.wait_for_selector('tr.data-row', state="attached", timeout=10000)
            await page.wait_for_timeout(800)

        await browser.close()
        return jobs

async def main():
    base_url = "https://careers.ey.com/ey/search/?createNewAlert=false&q=&optionsFacetsDD_customfield1=Consulting&optionsFacetsDD_country=IN&optionsFacetsDD_city="
    result = await scrape(base_url)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())