import httpx
import json
import asyncio
import urllib.parse
import sys
import re

ENDPOINT = "https://hdjq.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder=findReqs;siteNumber=CX_1,facetsList=LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,limit=25,locationId=300000000228786,sortBy=POSTING_DATES_DESC"

HEADERS = {
    "ora-irc-cx-userid": "5db1b56e-6d08-43af-b3c6-45370d43473b",
    "sec-ch-ua-platform": "\"macOS\"",
    "referer": "https://hdjq.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?location=India&locationId=300000000228786&locationLevel=country&mode=location",
    "accept-language": "en",
    "sec-ch-ua": "\"Chromium\";v=\"147\", \"Not.A/Brand\";v=\"8\"",
    "sec-ch-ua-mobile": "?0",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "accept": "application/json",
    "content-type": "application/json"
}

async def scrape(base_url: str, filters: dict | None = None, max_pages: int = 10) -> list[dict]:
    async with httpx.AsyncClient() as client:
        jobs = []
        offset = 0
        page_size = 25

        for page in range(max_pages):
            url = re.sub(r'(limit=\d+)', rf'\1,offset={offset}', ENDPOINT)
            response = await client.get(url, headers=HEADERS)
            data = response.json()

            requisition_list = data["items"][0]["requisitionList"]
            if not requisition_list:
                break

            for job in requisition_list:
                try:
                    job_id = job.get("Id")
                    title = job.get("Title")
                    posted_date = job.get("PostedDate")
                    location = job.get("PrimaryLocation")
                    job_type = job.get("JobType")
                    description = job.get("ShortDescriptionStr")
                    company = None  # As per the context, no specific field found for 'company'

                    job_detail_url = f"https://hdjq.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs/preview/{job_id}/?location=India&locationId=300000000228786&locationLevel=country&mode=location"
                    
                    jobs.append({
                        "title": title,
                        "url": job_detail_url,
                        "company": company,
                        "location": location,
                        "description": description,
                        "posted_date": posted_date,
                        "job_type": job_type
                    })
                except Exception:
                    continue

            offset += page_size

        return jobs

async def main():
    result = await scrape(base_url="https://hdjq.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?location=India&locationId=300000000228786&locationLevel=country&mode=location")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    asyncio.run(main())