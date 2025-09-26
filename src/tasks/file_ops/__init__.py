from __future__ import annotations

from typing import Any, Dict, Tuple

from ...core.task_spec import TaskSpec


def _not_implemented(*args, **kwargs) -> Dict[str, Any]:
    raise NotImplementedError("file_ops task is a stub. Implement agents under src/tasks/file_ops/agent/")


def _reset() -> None:
    # No-op placeholder; create data/ if needed later
    return None


def _detect() -> Tuple[bool, str, str]:
    # For now, always false; adapt for file_ops evaluation later
    return False, "", ""


TASK = TaskSpec(
    name="file_ops",
    run_baseline=_not_implemented,
    run_stateful=_not_implemented,
    reset_state=_reset,
    detect_success=_detect,
)
