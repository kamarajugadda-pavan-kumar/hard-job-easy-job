import asyncio
import json
from playwright.async_api import async_playwright
from urllib.parse import urljoin

async def scrape(base_url: str, filters: dict | None = None, max_pages: int = 10) -> list[dict]:
    results = []
    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=False)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7; rv:125.0) Gecko/20100101 Firefox/125.0",
            )
            page = await context.new_page()
            await page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_selector("article[data-testid='job-card']", timeout=15000)

            for _ in range(max_pages):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

                card_candidates = [
                    "article[data-testid='job-card']",
                    "[class*='job']",
                    "[class*='position']",
                    "[class*='listing']",
                    "article",
                    "li"
                ]

                cards = []
                for selector in card_candidates:
                    cards = await page.query_selector_all(selector)
                    if cards:
                        break

                if not cards:
                    print("[DEBUG] page title:", await page.title(), file=__import__('sys').stderr)
                    print("[DEBUG] body excerpt:", (await page.content())[:2000], file=__import__('sys').stderr)
                    raise RuntimeError("No job cards found — selectors need updating")

                for card in cards:
                    try:
                        title_elem = await card.query_selector(".title-86")
                        link_elem = await card.query_selector(".titleLink-87")
                        location_elem = await card.query_selector(".root-150")
                        desc_elem = await card.query_selector("[data-cy='job-description']")
                        date_elem = await card.query_selector(".postedMessage-88")
                        job_type_elem = await card.query_selector(".label-141")

                        title = await title_elem.inner_text() if title_elem else None
                        link = urljoin(base_url, await link_elem.get_attribute('href')) if link_elem else None
                        location = await location_elem.inner_text() if location_elem else None
                        description = await desc_elem.inner_html() if desc_elem else None
                        posted_date = await date_elem.inner_text() if date_elem else None
                        job_type = await job_type_elem.inner_text() if job_type_elem else None

                        results.append({
                            "title": title,
                            "url": link,
                            "company": "Teradata",  # Static as per the page details
                            "location": location,
                            "description": description,
                            "posted_date": posted_date,
                            "job_type": job_type,
                        })
                    except Exception:
                        continue

                break  # No pagination, exit after the first page

            await context.close()
            await browser.close()

    except Exception as e:
        print(f"Error: {e}", file=__import__('sys').stderr)

    return results

async def main():
    base_url = "https://careers.teradata.com/jobs?location=Hyderabad%2C+India&location=Bengaluru%2C+India&location=Pune%2C+India&location=Bangalore+-+Virtual%2C+India"
    result = await scrape(base_url)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())