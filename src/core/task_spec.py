from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass(frozen=True)
class TaskSpec:
    """Contract for a task so the experiment runner can execute it uniformly."""
    name: str
    # Agent trial runners: return {"messages": [...], "state"?: {...}}
    run_baseline: Callable[..., Dict[str, Any]]
    run_stateful: Callable[..., Dict[str, Any]]

    # Task-specific hooks
    reset_state: Callable[[], None]
    detect_success: Callable[[], bool]
