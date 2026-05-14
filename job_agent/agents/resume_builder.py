"""
Generates a tailored resume for a specific job posting.

Flow:
  1. LLM decides which skills to emphasise and how to reorder bullets
  2. Fill the DOCX template with tailored content
  3. Save to data/resumes/{company}_{title}.docx
  4. Update job.resume_path and status → RESUME_READY in DB
"""
from __future__ import annotations

from job_agent.models.job import JobPosting
from job_agent.models.profile import UserProfile


async def build_resume(job: JobPosting, profile: UserProfile) -> str:
    """
    Build a tailored resume for the job.
    Returns the path to the generated .docx file.
    """
    # TODO: call LLM for tailoring decisions, fill DOCX template, save
    raise NotImplementedError


TAILOR_PROMPT = """
Given this job posting and my profile, customise my resume content.

JOB: {title} at {company}
Required skills: {required_skills}
Description (first 1000 chars): {description}

MY PROFILE:
Skills: {skills}
Experience bullets: {experience_bullets}
Projects: {projects}
Current summary: {summary}

Return JSON:
{{
  "summary": "<rewritten 2-3 sentence summary tailored to this role>",
  "top_skills": ["<ordered list of 8-10 most relevant skills>"],
  "experience_bullets": ["<reordered/reworded bullets, most relevant first>"],
  "projects_to_include": ["<project names to highlight, most relevant first>"]
}}
"""
