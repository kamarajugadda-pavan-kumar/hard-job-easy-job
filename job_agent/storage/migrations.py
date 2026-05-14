"""Run this once on first launch via `job-agent init` or automatically from main."""
from job_agent.storage.db import init_db


def run() -> None:
    init_db()
    print("Database initialised.")
