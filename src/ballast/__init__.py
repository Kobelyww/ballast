"""Ballast: a budget-aware agent runtime with auditable, replayable runs.

Zero runtime dependencies on purpose — see docs/ARCHITECTURE.md for why.
"""

from __future__ import annotations

__version__ = "0.2.0"

from .context.engine import ContextEngine, ContextPolicy
from .kernel.agent import Agent, AgentConfig, RunResult
from .kernel.budget import BudgetExceeded, RunBudget, UsageLedger
from .kernel.events import RunContext
from .kernel.hitl import Interrupt
from .kernel.toolkit import Tool, Toolkit
from .llm.base import ChatRequest, ChatResponse, Pricing, ToolCall, Usage

__all__ = [
    "__version__",
    "Agent",
    "AgentConfig",
    "RunResult",
    "BudgetExceeded",
    "ChatRequest",
    "ChatResponse",
    "ContextEngine",
    "ContextPolicy",
    "Interrupt",
    "Pricing",
    "RunBudget",
    "RunContext",
    "Tool",
    "Toolkit",
    "ToolCall",
    "Usage",
    "UsageLedger",
]
