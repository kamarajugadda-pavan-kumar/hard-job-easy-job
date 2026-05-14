"""
Scores a JobPosting against the user's profile.

Returns a score 0–100 with reasoning, identified gaps, and strengths.
Jobs above the configured threshold are marked MATCHED; others SKIPPED.
"""
from __future__ import annotations

from job_agent.models.job import JobPosting, JobStatus
from job_agent.models.profile import UserProfile


async def score_job(job: JobPosting, profile: UserProfile) -> JobPosting:
    """
    Call the LLM to score the job against the profile.
    Updates job.match_score, match_reasoning, match_gaps, match_strengths, status.
    Returns the updated JobPosting (not yet saved — caller persists).
    """
    # TODO: call LLM with SCORE_PROMPT, parse JSON, update job fields
    raise NotImplementedError


SCORE_PROMPT = """
You are evaluating job fit for a candidate. Score 0-100 and explain.

CANDIDATE PROFILE
-----------------
Skills: {skills}
Years of experience: {years_exp}
Key projects: {projects}
Experience summary: {experience}

JOB POSTING
-----------
Title: {title}
Company: {company}
Required skills: {required_skills}
Nice to have: {nice_to_have}
Description: {description}

Score guide:
  85+   strong match — apply immediately
  65–84 decent match — worth applying with a tailored resume
  <65   weak match — skip

Return JSON only:
{{
  "score": <0-100>,
  "reasoning": "<2-3 sentences>",
  "strengths": ["<matching skill/exp>", ...],
  "gaps": ["<missing requirement>", ...]
}}
"""
