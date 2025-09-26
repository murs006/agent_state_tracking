from typing import Any

SPAN_MAP = {
    ("2025-10-01", "2025-10-08"): "_01_08",
    ("2025-10-02", "2025-10-09"): "_02_09",
    ("2025-10-03", "2025-10-10"): "_03_10",
}

ACCEPTED_START = "2025-10-03"
ACCEPTED_END   = "2025-10-10"

def _span_suffix(start: str | None, end: str | None) -> str | None:
    return SPAN_MAP.get(((start or ""), (end or "")))

def _is_correct_span_for_tool(tool_name: str, data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if tool_name == "book_hotel":
        start = data.get("check_in")
        end = data.get("check_out")
    elif tool_name == "book_flight":
        start = data.get("departure")
        end = data.get("return") or data.get("return_date")
    else:
        return False
    return (start == ACCEPTED_START) and (end == ACCEPTED_END)