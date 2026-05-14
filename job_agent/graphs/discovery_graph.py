"""
LangGraph graph: scrape → score → filter → save

Nodes
-----
scrape       : run the scraper for all configured targets
score        : LLM scores each raw job against the user profile
filter_save  : jobs above threshold → DB (MATCHED), rest → DB (SKIPPED)
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph


class DiscoveryState(TypedDict):
    targets: list[str]          # URLs or company names to scrape
    raw_jobs: list[dict]
    scored_jobs: list[dict]
    saved_count: int
    skipped_count: int


# --- nodes (stubs) ---

def scrape_node(state: DiscoveryState) -> DiscoveryState:
    # TODO: call route_input() for each target, collect JobPostings
    raise NotImplementedError


def score_node(state: DiscoveryState) -> DiscoveryState:
    # TODO: call matcher.score_job() for each raw job
    raise NotImplementedError


def filter_save_node(state: DiscoveryState) -> DiscoveryState:
    # TODO: threshold check, update DB status, count saved/skipped
    raise NotImplementedError


# --- graph wiring ---

def build_discovery_graph():
    g = StateGraph(DiscoveryState)
    g.add_node("scrape",      scrape_node)
    g.add_node("score",       score_node)
    g.add_node("filter_save", filter_save_node)
    g.set_entry_point("scrape")
    g.add_edge("scrape",      "score")
    g.add_edge("score",       "filter_save")
    g.add_edge("filter_save", END)
    return g.compile()


discovery_app = build_discovery_graph()
