from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from job_agent.models.job import JobPosting, JobStatus

DB_PATH = Path("data/db/jobs.db")


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id              TEXT PRIMARY KEY,
                url             TEXT UNIQUE,
                company         TEXT NOT NULL,
                title           TEXT NOT NULL,
                location        TEXT,
                description     TEXT,
                required_skills TEXT,
                nice_to_have    TEXT,
                job_type        TEXT,
                salary_range    TEXT,
                posted_date     TEXT,
                match_score     REAL DEFAULT 0,
                match_reasoning TEXT,
                match_gaps      TEXT,
                match_strengths TEXT,
                status          TEXT DEFAULT 'discovered',
                scraped_at      TEXT,
                applied_at      TEXT,
                resume_path     TEXT,
                notes           TEXT DEFAULT '',
                content_hash    TEXT
            );

            CREATE TABLE IF NOT EXISTS applications (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id       TEXT NOT NULL,
                resume_path  TEXT,
                cover_letter TEXT,
                form_data    TEXT,
                status       TEXT DEFAULT 'pending',
                submitted_at TEXT,
                outcome      TEXT DEFAULT '',
                notes        TEXT DEFAULT ''
            );
        """)


def insert_job(job: JobPosting) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO jobs
            (id, url, company, title, location, description, required_skills,
             nice_to_have, job_type, salary_range, posted_date, status,
             scraped_at, notes, content_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            job.id, job.url, job.company, job.title, job.location,
            job.description,
            json.dumps(job.required_skills),
            json.dumps(job.nice_to_have),
            job.job_type, job.salary_range, job.posted_date,
            job.status.value,
            job.scraped_at.isoformat(),
            job.notes, job.content_hash,
        ))


def get_job(job_id: str) -> JobPosting | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(status: JobStatus | None = None) -> list[JobPosting]:
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY scraped_at DESC", (status.value,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY scraped_at DESC").fetchall()
    return [_row_to_job(r) for r in rows]


def update_job_status(job_id: str, status: JobStatus) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status.value, job_id))


def url_exists(url: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM jobs WHERE url = ?", (url,)).fetchone()
    return row is not None


def content_hash_exists(content_hash: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE content_hash = ?", (content_hash,)
        ).fetchone()
    return row is not None


def _row_to_job(row: sqlite3.Row) -> JobPosting:
    d = dict(row)
    d["required_skills"]  = json.loads(d.get("required_skills") or "[]")
    d["nice_to_have"]     = json.loads(d.get("nice_to_have") or "[]")
    d["match_gaps"]       = json.loads(d.get("match_gaps") or "[]")
    d["match_strengths"]  = json.loads(d.get("match_strengths") or "[]")
    d["match_reasoning"]  = d.get("match_reasoning") or ""
    d["notes"]            = d.get("notes") or ""
    return JobPosting(**d)
