"""Abstract base class for all pipeline agents."""

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from langchain_openai import ChatOpenAI


class BaseAgent(ABC):
    """Abstract base providing LLM access, logging, and a standard run() interface."""

    name: str = "base_agent"
    description: str = "Abstract base agent"

    def __init__(self, llm: Optional[ChatOpenAI] = None, verbose: bool = False):
        self.llm = llm
        self.verbose = verbose
        self.logger = logging.getLogger(f"ats.{self.name}")
        if verbose:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

    @abstractmethod
    def run(self, state: dict) -> dict:
        """Execute agent logic, mutate state, and return updated state."""
        ...

    def _log(self, message: str, level: str = "info") -> None:
        """Log a message at the given level."""
        getattr(self.logger, level)(f"[{self.name}] {message}")

    def _add_error(self, state: dict, error: str) -> dict:
        """Append an error message to state['errors'] and return state."""
        errors = state.get("errors", [])
        errors.append(f"[{self.name}] {error}")
        state["errors"] = errors
        self.logger.error(f"[{self.name}] {error}")
        return state

    def _safe_llm_invoke(self, messages: list, fallback_fn=None) -> Any:
        """Invoke LLM with a fallback callable if the LLM raises an exception."""
        try:
            if self.llm is None:
                raise ValueError("No LLM configured for this agent.")
            return self.llm.invoke(messages)
        except Exception as e:
            self.logger.warning(f"[{self.name}] LLM call failed: {e}. Using fallback.")
            if fallback_fn is not None:
                return fallback_fn()
            raise
