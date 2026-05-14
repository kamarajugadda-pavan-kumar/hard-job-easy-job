"""
Detects whether a URL belongs to a known ATS platform.

If recognised, the corresponding pre-built scraper script in
data/scrapers/ is reused instead of generating a new one.
"""
from __future__ import annotations

# Maps URL substrings → ATS slug (must match filename in data/scrapers/)
ATS_PATTERNS: list[tuple[str, str]] = [
    ("boards.greenhouse.io",     "greenhouse"),
    ("greenhouse.io",            "greenhouse"),
    ("jobs.lever.co",            "lever"),
    ("lever.co",                 "lever"),
    ("myworkday.com",            "workday"),
    ("wd1.myworkdayjobs.com",    "workday"),
    ("wd3.myworkdayjobs.com",    "workday"),
    ("ashbyhq.com",              "ashby"),
    ("jobs.smartrecruiters.com", "smartrecruiters"),
    ("icims.com",                "icims"),
    ("taleo.net",                "taleo"),
    ("jobvite.com",              "jobvite"),
]


def detect(url: str) -> str | None:
    """
    Return the ATS slug if the URL matches a known platform, else None.

    >>> detect("https://boards.greenhouse.io/stripe")
    'greenhouse'
    >>> detect("https://stripe.com/jobs")
    None
    """
    lowered = url.lower()
    for pattern, slug in ATS_PATTERNS:
        if pattern in lowered:
            return slug
    return None
