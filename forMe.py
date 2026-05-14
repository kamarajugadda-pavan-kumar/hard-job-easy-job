from job_agent.scraper.page_analyst import _capture_page
import asyncio
import subprocess

async def runThis():
    _, html = await _capture_page("https://careers.ey.com/ey/search/?createNewAlert=false&q=&optionsFacetsDD_customfield1=Consulting&optionsFacetsDD_country=IN&optionsFacetsDD_city=")
    subprocess.run("pbcopy", input=html.encode(), check=True)
    print(f"HTML ({len(html)} chars) copied to clipboard.")

asyncio.run(runThis())