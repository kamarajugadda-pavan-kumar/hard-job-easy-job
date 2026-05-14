"""
Manages data/company_registry.yaml.

- Lookup: company_name → careers URL + ATS type
- Update: auto-appends new entries after a successful scrape
- Fallback: web search when a company is not in the registry
"""
from __future__ import annotations

from pathlib import Path

import yaml

REGISTRY_PATH = Path("data/company_registry.yaml")


class CompanyEntry:
    def __init__(self, careers_url: str, ats: str, last_scraped_at: str | None = None):
        self.careers_url     = careers_url
        self.ats             = ats
        self.last_scraped_at = last_scraped_at


def load_registry() -> dict[str, dict]:
    if not REGISTRY_PATH.exists():
        return {}
    return yaml.safe_load(REGISTRY_PATH.read_text()) or {}


def save_registry(data: dict) -> None:
    REGISTRY_PATH.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def lookup(company_name: str) -> CompanyEntry | None:
    """Return registry entry for a company name, or None if not found."""
    key = company_name.lower().replace(" ", "_")
    data = load_registry()
    entry = data.get(key)
    if entry:
        return CompanyEntry(**entry)
    return None


def upsert(company_name: str, careers_url: str, ats: str = "custom") -> None:
    """Add or update a company entry."""
    key  = company_name.lower().replace(" ", "_")
    data = load_registry()
    data[key] = {"careers_url": careers_url, "ats": ats, "last_scraped_at": None}
    save_registry(data)


def mark_scraped(company_name: str, timestamp: str) -> None:
    key  = company_name.lower().replace(" ", "_")
    data = load_registry()
    if key in data:
        data[key]["last_scraped_at"] = timestamp
        save_registry(data)


async def resolve_company_url(company_name: str) -> str:
    """
    Return a careers page URL for the given company name.
    Checks registry first; falls back to LLM-assisted web search.
    """
    entry = lookup(company_name)
    if entry:
        return entry.careers_url

    # TODO: implement web-search fallback using LLM + search tool
    # searched_url = await _search_careers_url(company_name)
    # upsert(company_name, searched_url)
    # return searched_url
    raise NotImplementedError(
        f"'{company_name}' not in registry. Web search fallback not yet implemented."
    )
