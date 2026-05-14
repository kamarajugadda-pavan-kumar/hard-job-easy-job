"""
Textual TUI dashboard for viewing and managing job applications.

Launch with: job-agent dashboard
Or directly: python -m job_agent.dashboard.app
"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Label

from job_agent.models.job import JobStatus
from job_agent.storage.db import list_jobs


class JobDashboard(App):
    CSS = """
    #title { padding: 1 2; color: $accent; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        Binding("a", "apply_selected",   "Apply"),
        Binding("s", "skip_selected",    "Skip"),
        Binding("r", "refresh",          "Refresh"),
        Binding("f", "filter_toggle",    "Filter"),
        Binding("q", "quit",             "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("  Job Application Tracker", id="title")
        yield DataTable(id="jobs_table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self._populate_table()

    def _populate_table(self) -> None:
        table = self.query_one("#jobs_table", DataTable)
        table.clear(columns=True)
        table.add_columns("ID", "Company", "Title", "Score", "Status", "Scraped")
        for job in list_jobs():
            table.add_row(
                job.id,
                job.company,
                job.title,
                f"{job.match_score:.0f}%" if job.match_score else "—",
                job.status.value,
                job.scraped_at.strftime("%Y-%m-%d") if job.scraped_at else "—",
            )

    def action_refresh(self) -> None:
        self._populate_table()

    def action_apply_selected(self) -> None:
        # TODO: get selected row job_id, trigger apply_graph
        pass

    def action_skip_selected(self) -> None:
        # TODO: get selected row job_id, update status → SKIPPED
        pass

    def action_filter_toggle(self) -> None:
        # TODO: cycle through status filters
        pass


if __name__ == "__main__":
    JobDashboard().run()
