import asyncio
import json
from playwright.async_api import async_playwright


async def scrape(base_url: str, max_pages: int = 10) -> list[dict]:
    jobs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False  # Change to True after debugging
        )

        context = await browser.new_context()

        page = await context.new_page()

        print("Opening EY careers page...")

        await page.goto(
            base_url,
            wait_until="networkidle",
            timeout=60000
        )

        # Give JS time to hydrate/render
        await page.wait_for_timeout(5000)

        # Scroll to trigger lazy loading if needed
        await page.mouse.wheel(0, 5000)

        await page.wait_for_timeout(3000)

        page_number = 1

        while page_number <= max_pages:

            print(f"\nScraping page {page_number}...")

            # DEBUGGING:
            # Print all visible text if selectors fail
            # print(await page.locator("body").inner_text())

            # Multiple possible selectors because EY changes DOM often
            selectors = [
                'li[id^="job"]',
                'li.jobs-list-item',
                '.job',
                '.job-listing',
                'tr.data-row'
            ]

            job_cards = []

            for selector in selectors:
                cards = await page.query_selector_all(selector)

                if cards:
                    print(f"Using selector: {selector}")
                    job_cards = cards
                    break

            if not job_cards:
                print("No job cards found.")
                break

            print(f"Found {len(job_cards)} jobs")

            for card in job_cards:

                # Try multiple title selectors
                title_selectors = [
                    '.jobTitle a.jobTitle-link',
                    'a.jobTitle-link',
                    'a[href*="/job/"]',
                    'a'
                ]

                title = ""
                url = ""

                for ts in title_selectors:
                    title_el = await card.query_selector(ts)

                    if title_el:
                        try:
                            title = (await title_el.inner_text()).strip()
                            url = await title_el.get_attribute("href")

                            if url and url.startswith("/"):
                                url = f"https://careers.ey.com{url}"

                            if title:
                                break

                        except Exception:
                            pass

                # Location
                location = ""

                location_selectors = [
                    '.jobLocation',
                    '.location',
                    '[data-th="Location"]'
                ]

                for ls in location_selectors:
                    loc_el = await card.query_selector(ls)

                    if loc_el:
                        try:
                            location = (await loc_el.inner_text()).strip()

                            if location:
                                break

                        except Exception:
                            pass

                # Skip empty cards
                if not title:
                    continue

                jobs.append({
                    "title": title,
                    "url": url,
                    "company": "EY",
                    "location": location,
                    "description": "",
                    "posted_date": "",
                    "job_type": "Consulting"
                })

                print(f"Collected: {title}")

            # Pagination
            next_selectors = [
                '.pagination a[aria-label="Next Page"]',
                'a[aria-label="Next"]',
                'a.next',
                'button[aria-label="Next Page"]'
            ]

            next_btn = None

            for ns in next_selectors:
                btn = await page.query_selector(ns)

                if btn:
                    next_btn = btn
                    break

            if not next_btn:
                print("No next page button found.")
                break

            try:
                print("Going to next page...")

                await next_btn.click()

                await page.wait_for_load_state("networkidle")

                await page.wait_for_timeout(4000)

                # Scroll again after pagination
                await page.mouse.wheel(0, 5000)

                await page.wait_for_timeout(2000)

                page_number += 1

            except Exception as e:
                print(f"Pagination failed: {e}")
                break

        await browser.close()

    return jobs


async def main():

    base_url = (
        "https://careers.ey.com/ey/search/"
        "?createNewAlert=false"
        "&q="
        "&optionsFacetsDD_customfield1=Consulting"
        "&optionsFacetsDD_country=IN"
        "&optionsFacetsDD_city="
    )

    result = await scrape(base_url)

    print("\n==================== FINAL RESULTS ====================\n")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())