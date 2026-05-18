from playwright.async_api import async_playwright
import json
import asyncio
import sys
from urllib.parse import urljoin

async def scrape(base_url: str, filters: dict | None = None, max_pages: int = 10) -> list[dict]:
    results = []
    
    async with async_playwright() as p:
        # Launching a Chromium browser
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        await page.goto(base_url)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_selector("article.article--result", timeout=15000)
        
        for _ in range(max_pages):
            # Lazy loading handling
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)
            
            card_selectors = [
                'article.article--result',
                '[class*="job"]',
                '[class*="position"]',
                '[class*="listing"]',
                'article',
                'li'
            ]
            
            job_cards = []
            
            for selector in card_selectors:
                job_cards = await page.query_selector_all(selector)
                if job_cards:
                    break
            
            if not job_cards:
                print("[DEBUG] page title:", await page.title(), file=sys.stderr)
                print("[DEBUG] body excerpt:", (await page.content())[:2000], file=sys.stderr)
                raise RuntimeError("No job cards found — selectors need updating")
            
            for card in job_cards:
                try:
                    title_el = await card.query_selector('h3.article__header__text__title a')
                    title = await title_el.inner_text() if title_el else None
                    
                    link = await title_el.get_attribute('href') if title_el else None
                    url = urljoin(base_url, link) if link else None
                    
                    company = 'Deloitte'  # Static in the example provided
                    
                    location_el = await card.query_selector('div.article__header__text__subtitle span:last-child')
                    location = await location_el.inner_text() if location_el else None
                    
                    # Assuming description and posted_date are not available
                    description = None
                    posted_date = None
                    job_type = None
                    
                    results.append({
                        "title": title.strip() if title else None,
                        "url": url,
                        "company": company,
                        "location": location.strip() if location else None,
                        "description": description,
                        "posted_date": posted_date,
                        "job_type": job_type
                    })
                except Exception as e:
                    print(f"[DEBUG] Error processing job card: {e}", file=sys.stderr)
            
            next_button = await page.query_selector("a[href='javascript:NextPage()']")
            if next_button:
                await next_button.click()
                await page.wait_for_selector("article.article--result", state="attached", timeout=10000)
                await page.wait_for_timeout(800)
            else:
                break
        
        await browser.close()
    
    return results

async def main():
    url = 'https://usijobs.deloitte.com/en_US/careersusi'
    result = await scrape(url)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())