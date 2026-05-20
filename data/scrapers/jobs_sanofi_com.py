import asyncio
import json
import sys
import urllib.parse
from playwright.async_api import async_playwright

async def scrape(base_url: str, filters: dict | None = None, max_pages: int = 10) -> list[dict]:
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7; rv:125.0) Gecko/20100101 Firefox/125.0",
        )
        page = await context.new_page()
        
        current_page = 1
        all_jobs = []
        
        while current_page <= max_pages:
            paginated_url = urllib.parse.urljoin(base_url, f"?p={current_page}")
            await page.goto(paginated_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_selector("ul > li", timeout=15000)
            
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)

            card_selectors = [
                "ul > li", 
                '[class*="job"]', 
                '[class*="position"]', 
                '[class*="listing"]', 
                "article", 
                "li"
            ]

            cards = []
            for selector in card_selectors:
                cards = await page.query_selector_all(selector)
                if cards:
                    break

            if len(cards) == 0:
                print("[DEBUG] page title:", await page.title(), file=sys.stderr)
                print("[DEBUG] body excerpt:", (await page.content())[:2000], file=sys.stderr)
                raise RuntimeError("No job cards found — selectors need updating")

            for card in cards:
                job = {}
                try:
                    title_element = await card.query_selector("h2")
                    job['title'] = await title_element.inner_text() if title_element else None
                    
                    link_element = await card.query_selector("a[data-job-id]")
                    job_url_path = await link_element.get_attribute("href") if link_element else None
                    job['url'] = urllib.parse.urljoin(base_url, job_url_path) if job_url_path else None

                    location_element = await card.query_selector(".job-location")
                    job['location'] = (await location_element.inner_text()).replace("Location: ", "") if location_element else None
                    
                    job['company'] = None
                    job['description'] = None
                    job['posted_date'] = None
                    job['job_type'] = None
                except Exception as e:
                    continue
                
                all_jobs.append(job)

            pagination_element = await page.query_selector("#pagination-bottom .next")
            if not pagination_element:
                break

            current_page += 1
            await page.wait_for_timeout(800)

        await browser.close()
        return all_jobs

async def main():
    result = await scrape("https://jobs.sanofi.com/en/search-jobs/India/2649/2/1269750/22/79/50/2")
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())