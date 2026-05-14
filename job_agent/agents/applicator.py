"""
Playwright-based application agent.

Responsibilities:
  1. Open the job application URL
  2. Detect all form fields on the page
  3. Map the user's profile to each field (LLM-assisted)
  4. Pause for human review (LangGraph interrupt_before)
  5. On approval: fill and submit the form
"""
from __future__ import annotations

from job_agent.models.application import Application
from job_agent.models.job import JobPosting
from job_agent.models.profile import UserProfile


async def analyse_form(url: str) -> dict[str, str]:
    """
    Open the application page with Playwright.
    Return a dict of {field_name: field_type} for all detected inputs.
    """
    # TODO: implement with playwright.async_api
    raise NotImplementedError


async def map_profile_to_form(
    form_fields: dict[str, str],
    profile: UserProfile,
    job: JobPosting,
) -> dict[str, str]:
    """
    Use LLM to map profile data to form fields.
    Returns {field_name: value_to_fill}.
    """
    # TODO: call LLM with MAP_PROMPT
    raise NotImplementedError


async def fill_and_submit(
    url: str,
    form_data: dict[str, str],
    resume_path: str,
) -> bool:
    """
    Fill the form using Playwright and click Submit.
    Returns True on success.
    Called only after human approval.
    """
    # TODO: implement with playwright.async_api
    raise NotImplementedError


MAP_PROMPT = """
Map the candidate's profile data to the application form fields.

FORM FIELDS (name → input type):
{form_fields}

CANDIDATE DATA:
{profile_json}

JOB: {title} at {company}

Return JSON: {{ "field_name": "value_to_fill", ... }}
Use empty string for fields you cannot determine.
"""
