import asyncio
import json
import urllib.parse
from playwright.async_api import async_playwright

async def scrape(base_url: str, filters: dict | None = None, max_pages: int = 10) -> list[dict]:
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
        )
        page = await context.new_page()

        await page.goto(base_url)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_selector('tr.data-row', timeout=15000)

        current_page = 0

        while current_page < max_pages:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)

            job_card_candidates = [
                'tr.data-row', '(class*="job"), (class*="position"), article, li'
            ]
            job_cards = []

            for selector in job_card_candidates:
                job_cards = await page.query_selector_all(selector)
                if job_cards:
                    break

            if len(job_cards) == 0:
                print("[DEBUG] page title:", await page.title(), file=__import__('sys').stderr)
                print("[DEBUG] body excerpt:", (await page.content())[:2000], file=__import__('sys').stderr)
                raise RuntimeError("No job cards found — selectors need updating")

            for card in job_cards:
                try:
                    title_elem = await card.query_selector('a.jobTitle-link')
                    title = await title_elem.inner_text() if title_elem else None

                    url_elem = await card.query_selector('a.jobTitle-link')
                    url = urllib.parse.urljoin(base_url, await url_elem.get_attribute('href')) if url_elem else None

                    location_elem = await card.query_selector('span.jobLocation')
                    location = await location_elem.inner_text() if location_elem else None

                    # Set values that are not provided on the page to None
                    company = description = posted_date = job_type = None

                    results.append({
                        'title': title,
                        'url': url,
                        'company': company,
                        'location': location,
                        'description': description,
                        'posted_date': posted_date,
                        'job_type': job_type
                    })
                except Exception as e:
                    print("[DEBUG] Error extracting job:", e, file=__import__('sys').stderr)

            next_button = await page.query_selector('.pagination a[aria-label="Next"]')
            if not next_button:
                break
            await next_button.click()
            await page.wait_for_selector("tr.data-row", state="attached", timeout=10000)
            await page.wait_for_timeout(800)  # Bot protection
            current_page += 1

        await browser.close()

    return results

async def main():
    url = "https://careers.ey.com/ey/search/?createNewAlert=false&q=&optionsFacetsDD_customfield1=Consulting&optionsFacetsDD_country=IN&optionsFacetsDD_city="
    results = await scrape(url)
    print(json.dumps(results, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())