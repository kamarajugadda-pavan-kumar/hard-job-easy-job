"""
LangGraph graph: build_resume → analyse_form → [HUMAN REVIEW] → submit

The graph is compiled with:
  - SqliteSaver checkpointer  (so state survives between CLI calls)
  - interrupt_before=["submit"]  (pauses for human approval)

Usage
-----
# Start the flow (pauses automatically before submit):
apply_app.invoke(initial_state, {"configurable": {"thread_id": job_id}})

# After the user reviews and approves:
apply_app.invoke({"human_approved": True}, {"configurable": {"thread_id": job_id}})
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph


class ApplyState(TypedDict):
    job: dict
    profile: dict
    resume_path: str
    form_fields: dict           # {field_name: detected_type}
    proposed_values: dict       # {field_name: value_to_fill}
    human_approved: bool
    application_result: str


# --- nodes (stubs) ---

def build_resume_node(state: ApplyState) -> ApplyState:
    # TODO: call resume_builder.build_resume()
    raise NotImplementedError


def analyse_form_node(state: ApplyState) -> ApplyState:
    # TODO: call applicator.analyse_form() + applicator.map_profile_to_form()
    raise NotImplementedError


def submit_node(state: ApplyState) -> ApplyState:
    # TODO: call applicator.fill_and_submit(), update DB status
    raise NotImplementedError


# --- graph wiring ---

def build_apply_graph():
    checkpointer = SqliteSaver.from_conn_string("data/db/jobs.db")

    g = StateGraph(ApplyState)
    g.add_node("build_resume",  build_resume_node)
    g.add_node("analyse_form",  analyse_form_node)
    g.add_node("submit",        submit_node)
    g.set_entry_point("build_resume")
    g.add_edge("build_resume", "analyse_form")
    g.add_edge("analyse_form", "submit")
    g.add_edge("submit",       END)

    return g.compile(
        checkpointer=checkpointer,
        interrupt_before=["submit"],    # pause here for human review
    )


apply_app = build_apply_graph()
