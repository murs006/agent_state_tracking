from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ...core.task_spec import TaskSpec
from .agent.baseline_agent import run_baseline_trial
from .agent.stateful_agent import run_stateful_trial


# Local data files for this task
_DATA_DIR = Path(__file__).parent / "data"
_FLIGHT_FILE = _DATA_DIR / "flight_bookings.json"
_HOTEL_FILE = _DATA_DIR / "hotel_bookings.json"


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def reset_state() -> None:
    _write_json(_FLIGHT_FILE, {})
    _write_json(_HOTEL_FILE, {})


def detect_success() -> bool:
    """Ticket booking success iff both flight and hotel were booked for 2025-10-03..10.

    Returns success: bool.
    """
    TARGET_START = "2025-10-03"
    TARGET_END = "2025-10-10"

    flights = _read_json(_FLIGHT_FILE) or {}
    hotels = _read_json(_HOTEL_FILE) or {}

    matched_f_conf = ""
    matched_h_conf = ""

    for conf_id, payload in getattr(flights, "items", lambda: [])():
        try:
            dep = str(payload.get("departure", ""))
            ret = str(payload.get("return", ""))
        except Exception:
            continue
        if dep == TARGET_START and ret == TARGET_END:
            matched_f_conf = conf_id
            break

    for conf_id, payload in getattr(hotels, "items", lambda: [])():
        try:
            check_in = str(payload.get("check_in", ""))
            check_out = str(payload.get("check_out", ""))
        except Exception:
            continue
        if check_in == TARGET_START and check_out == TARGET_END:
            matched_h_conf = conf_id
            break

    return bool(matched_f_conf and matched_h_conf)


TASK = TaskSpec(
    name="ticket_booking",
    run_baseline=run_baseline_trial,
    run_stateful=run_stateful_trial,
    reset_state=reset_state,
    detect_success=detect_success,
)
