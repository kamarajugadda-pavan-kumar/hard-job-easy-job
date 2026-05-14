"""
CLI entry point.

Commands
--------
job-agent init                          initialise the database
job-agent scrape --company "Stripe"     scrape by company name
job-agent scrape --url <url>            scrape a specific URL
job-agent scrape --text <file>          parse a raw job description file
job-agent discover                      scrape all targets in config.yaml
job-agent apply <job_id>               start application (pauses for review)
job-agent approve <job_id>             resume and submit a paused application
job-agent dashboard                     open the TUI
job-agent list [--status matched]       list jobs from the DB
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Optional

import typer
from dotenv import load_dotenv

load_dotenv()
from rich.console import Console
from rich.table import Table

from job_agent.storage.db import init_db, list_jobs
from job_agent.models.job import JobStatus

app     = typer.Typer(help="Hard job, easy job — automated job application agent.")
console = Console()


@app.command()
def init():
    """Initialise the local database."""
    init_db()
    console.print("[green]Database initialised.[/green]")


@app.command()
def scrape(
    company: Annotated[Optional[str], typer.Option("--company", "-c")] = None,
    url:     Annotated[Optional[str], typer.Option("--url",     "-u")] = None,
    text:    Annotated[Optional[str], typer.Option("--text",    "-t")] = None,
):
    """Scrape jobs from a company name, URL, or raw text file."""
    from job_agent.scraper.router import route_input

    if company:
        raw_input = company
    elif url:
        raw_input = url
    elif text:
        path = Path(text)
        raw_input = path.read_text() if path.exists() else text
    else:
        console.print("[red]Provide --company, --url, or --text[/red]")
        raise typer.Exit(1)

    new_jobs = asyncio.run(route_input(raw_input))
    console.print(f"[green]{len(new_jobs)} new job(s) saved.[/green]")


@app.command()
def discover():
    """Scrape all targets configured in config.yaml."""
    # TODO: load config targets, run discovery_graph
    console.print("[yellow]discover command — not yet implemented[/yellow]")


@app.command()
def apply(job_id: str):
    """Start the application process for a job (pauses before submit)."""
    from job_agent.graphs.apply_graph import apply_app
    from job_agent.storage.db import get_job
    from job_agent.tools.profile_loader import load_profile

    job = get_job(job_id)
    if not job:
        console.print(f"[red]Job {job_id} not found.[/red]")
        raise typer.Exit(1)

    profile = load_profile()
    thread  = {"configurable": {"thread_id": job_id}}
    apply_app.invoke(
        {"job": job.model_dump(), "profile": profile.model_dump(), "human_approved": False},
        thread,
    )
    console.print("[yellow]Review the details above, then run:[/yellow]")
    console.print(f"  job-agent approve {job_id}")


@app.command()
def approve(job_id: str):
    """Resume and submit a paused application after human review."""
    from job_agent.graphs.apply_graph import apply_app

    thread = {"configurable": {"thread_id": job_id}}
    apply_app.invoke({"human_approved": True}, thread)
    console.print(f"[green]Application for {job_id} submitted.[/green]")


@app.command()
def list_cmd(
    status: Annotated[Optional[str], typer.Option("--status", "-s")] = None,
):
    """List jobs from the local database."""
    job_status = JobStatus(status) if status else None
    jobs = list_jobs(job_status)

    table = Table(title="Jobs")
    table.add_column("ID",      style="dim")
    table.add_column("Company", style="cyan")
    table.add_column("Title")
    table.add_column("Score",   justify="right")
    table.add_column("Status",  style="magenta")

    for job in jobs:
        table.add_row(
            job.id,
            job.company,
            job.title,
            f"{job.match_score:.0f}%" if job.match_score else "—",
            job.status.value,
        )

    console.print(table)


@app.command()
def dashboard():
    """Open the interactive TUI dashboard."""
    from job_agent.dashboard.app import JobDashboard
    JobDashboard().run()


# Alias so pyproject.toml [project.scripts] points here
cli = app

if __name__ == "__main__":
    app()
