import httpx
import json
import asyncio
import re

ENDPOINT = "https://fa-etvl-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder=findReqs;siteNumber=CX_1,facetsList=LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,limit=12,lastSelectedFacet=AttributeChar14,selectedFlexFieldsFacets=%22AttributeChar14%7CY%22,selectedLocationsFacet=300000000435151,sortBy=POSTING_DATES_DESC"

HEADERS = {
    "sec-ch-ua-platform": "\"macOS\"",
    "referer": "https://fa-etvl-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?lastSelectedFacet=AttributeChar14&selectedFlexFieldsFacets=%22AttributeChar14%7CY%22&selectedLocationsFacet=300000000435151",
    "accept-language": "en",
    "sec-ch-ua": "\"Chromium\";v=\"147\", \"Not.A/Brand\";v=\"8\"",
    "sec-ch-ua-mobile": "?0",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "accept": "application/json",
    "content-type": "application/json",
    "ora-irc-language": "en"
}

async def scrape(base_url: str, filters: dict | None = None, max_pages: int = 10) -> list[dict]:
    async with httpx.AsyncClient() as client:
        jobs = []
        offset = 0
        while len(jobs) < max_pages * 12:
            current_url = re.sub(r'(limit=\d+)', r'\1,offset=' + str(offset), ENDPOINT)
            response = await client.get(current_url, headers=HEADERS)
            data = response.json()
            try:
                job_list = data["items"][0]["requisitionList"]
            except (KeyError, IndexError):
                break

            if not job_list:
                break

            for job in job_list:
                job_dict = {}
                try:
                    job_dict['title'] = job.get("Title", None)
                except KeyError:
                    job_dict['title'] = None
                try:
                    job_dict['url'] = f"https://fa-etvl-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/{job['Id']}"
                except KeyError:
                    job_dict['url'] = None
                try:
                    job_dict['company'] = job.get("Organization", None)
                except KeyError:
                    job_dict['company'] = None
                try:
                    location = job.get("workLocation", [{}])
                    if location:
                        location = location[0]
                        job_dict['location'] = ", ".join(filter(None, [location.get("TownOrCity"), location.get("Region2"), location.get("Country")]))
                    else:
                        job_dict['location'] = None
                except KeyError:
                    job_dict['location'] = None
                try:
                    job_dict['description'] = job.get("ShortDescriptionStr", "")
                except KeyError:
                    job_dict['description'] = None
                try:
                    job_dict['posted_date'] = job.get("PostedDate", None)
                except KeyError:
                    job_dict['posted_date'] = None
                try:
                    job_dict['job_type'] = job.get("JobType", None)
                except KeyError:
                    job_dict['job_type'] = None

                jobs.append(job_dict)

            offset += 12

            if len(job_list) < 12:
                break

    return jobs

async def main():
    result = await scrape(base_url="https://fa-etvl-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?lastSelectedFacet=AttributeChar14&selectedFlexFieldsFacets=%22AttributeChar14%7CY%22&selectedLocationsFacet=300000000435151")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    asyncio.run(main())