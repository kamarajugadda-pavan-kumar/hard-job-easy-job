"""
Central LLM factory.

Swap providers or models by editing config.yaml under the `llm:` key.
Any purpose not listed in config falls back to the defaults below.

Usage:
    from job_agent.llm import get_llm
    llm = get_llm("analyst")          # returns a LangChain BaseChatModel
    structured = llm.with_structured_output(MySchema)
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel


_CONFIG_PATH = Path("config.yaml")


def _llm_config(purpose: str) -> dict:
    cfg: dict = {}
    if _CONFIG_PATH.exists():
        raw = yaml.safe_load(_CONFIG_PATH.read_text()) or {}
        cfg = raw.get("llm", {}).get(purpose, {})
    return cfg


@lru_cache(maxsize=None)
def get_llm(purpose: str = "analyst") -> BaseChatModel:
    """Return a cached LangChain chat model for the given purpose."""
    cfg = _llm_config(purpose)

    provider = cfg.pop("provider", None)
    model    = cfg.pop("model", None)

    if not provider:
        raise ValueError(
            f"Missing 'provider' for llm.{purpose} in config.yaml. "
            f"Example:\n  llm:\n    {purpose}:\n      provider: openai\n      model: gpt-4o"
        )
    if not model:
        raise ValueError(
            f"Missing 'model' for llm.{purpose} in config.yaml. "
            f"Example:\n  llm:\n    {purpose}:\n      provider: openai\n      model: gpt-4o"
        )

    return init_chat_model(model, model_provider=provider, **cfg)