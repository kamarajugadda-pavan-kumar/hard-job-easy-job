"""
Pre-built scraper for any Workday-hosted career site.

Workday exposes a stable public JSON API at:
  POST /wday/cxs/{company}/{site}/jobs

Works for *.wd1.myworkdayjobs.com, *.wd3.myworkdayjobs.com, etc.
URL is passed via --url flag by the runner.
"""
import asyncio
import json
import re
import sys
from urllib.parse import urlparse
import math

import httpx

_REQ_ID_RE = re.compile(r"^[A-Z]+-\d+")  # matches "SR-39875", "JR-12345", etc.
_LOCALE_SEGMENTS = {"en-us", "en-gb", "en", "fr", "de", "es", "it", "pt", "ja", "zh"}


def _parse_workday_url(url: str) -> tuple[str, str, str]:
    """
    Returns (base_url, company, site).

    https://fractal.wd1.myworkdayjobs.com/Careers
      → ("https://fractal.wd1.myworkdayjobs.com", "fractal", "Careers")

    https://company.wd3.myworkdayjobs.com/en-US/ExternalCareers
      → ("https://company.wd3.myworkdayjobs.com", "company", "ExternalCareers")
    """
    parsed = urlparse(url)
    host = parsed.netloc
    company = host.split(".")[0]
    parts = [p for p in parsed.path.strip("/").split("/") if p.lower() not in _LOCALE_SEGMENTS]
    site = parts[0] if parts else "careers"
    return f"{parsed.scheme}://{host}", company, site


async def _discover_url_prefix(
    client: httpx.AsyncClient, base: str, site: str, sample_ext_path: str
) -> str:
    """
    Make one HEAD request to discover the locale+site prefix Workday uses
    for job detail URLs on this specific instance.

    e.g. "/en-US/Careers" or "/en-GB/ExternalCareers"

    Falls back to "/en-US/{site}" if the redirect can't be read.
    """
    try:
        resp = await client.head(
            f"{base}{sample_ext_path}", follow_redirects=True, timeout=10
        )
        final = str(resp.url)
        # Strip query string for clean parsing
        final = final.split("?")[0]
        if "/job/" in final and final.startswith(base):
            after_base = final[len(base):]               # e.g. "/en-US/Careers/job/..."
            prefix = after_base[: after_base.index("/job/")]  # e.g. "/en-US/Careers"
            if prefix:
                return prefix
    except Exception:
        pass
    return f"/en-US/{site}"


async def scrape(base_url: str, filters: dict | None = None, max_pages: int = 10) -> list[dict]:
    base, company, site = _parse_workday_url(base_url)
    api_url = f"{base}/wday/cxs/{company}/{site}/jobs"

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "referer": base_url,
        "origin": base,
    }

    jobs = []
    limit = 20
    offset = 0
    total: int | None = None  # read once from the first page; Workday returns 0 on all others
    url_prefix: str | None = None  # discovered once from the first job's redirect

    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
        while True:
            body = {
                "limit": limit,
                "offset": offset,
                "searchText": "",
                "appliedFacets": {},
            }
            response = await client.post(api_url, json=body)
            response.raise_for_status()
            data = response.json()

            postings = data.get("jobPostings", [])

            # total is only reliable on the first page — Workday returns 0 for all others
            if total is None:
                total = data.get("total") or 0
                print(f"  [workday] total jobs reported by API: {total}", file=sys.stderr)

            if not postings:
                break

            for p in postings:
                ext_path = p.get("externalPath", "")

                if ext_path:
                    # Discover prefix once from the first job's redirect
                    if url_prefix is None:
                        url_prefix = await _discover_url_prefix(client, base, site, ext_path)
                    job_url = f"{base}{url_prefix}{ext_path}"
                else:
                    job_url = None

                bullet_fields = p.get("bulletFields") or []
                job_type = next((f for f in bullet_fields if not _REQ_ID_RE.match(f)), None)

                jobs.append({
                    "title": p.get("title"),
                    "url": job_url,
                    "company": company.capitalize(),
                    "location": p.get("locationsText"),
                    "description": None,
                    "posted_date": p.get("postedOn"),
                    "job_type": job_type,
                })

            offset += limit
            if total and offset >= total:
                break
            await asyncio.sleep(0.2)  # polite delay between pages

    return jobs


async def main() -> None:
    url = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--url" and i + 1 < len(args):
            url = args[i + 1]
            break
    if not url:
        print("Usage: workday.py --url <workday-careers-url>", file=sys.stderr)
        sys.exit(1)

    result = await scrape(url)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
