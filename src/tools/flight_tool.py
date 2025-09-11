import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple

DATA_DIR = Path(__file__).parent.parent / "data"
BLOCKED_FLIGHT_WINDOWS: set[tuple[str, str]] = {(
    "2025-10-01",
    "2025-10-08",
)}


def load_json(path: Path) -> Dict[str, Any]:
    """Return parsed JSON from path or an empty dict if missing/invalid."""
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _summarize_offer(offer: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, Dict[str, Any] | None, str | None, str | None]:
    """Return per-leg summaries plus a back-compat overall summary.

    Outbound and return each include: dep_time, arr_time, stops.
    Overall summary provides dep_time (first outbound dep), arr_time (last return or outbound arr).
    """
    its: List[Dict[str, Any]] = offer.get("itineraries") or []

    def leg_summary(it: Dict[str, Any]) -> Dict[str, Any] | None:
        segs = (it or {}).get("segments") or []
        if not segs:
            return None
        return {
            "dep_time": segs[0].get("dep"),
            "arr_time": segs[-1].get("arr"),
            "stops": max(0, len(segs) - 1),
        }

    outbound = leg_summary(its[0]) if len(its) >= 1 else None
    ret_leg = leg_summary(its[1]) if len(its) >= 2 else None

    total_dep = outbound and outbound.get("dep_time")
    total_arr = (ret_leg and ret_leg.get("arr_time")) or (outbound and outbound.get("arr_time"))

    return outbound, ret_leg, total_dep, total_arr


def list_flights(dest: str, dep: str, ret: str, limit: int = 8) -> List[Dict[str, Any]]:
    """List flight offers from local JSON and summarize each leg.

    Args:
        dest: Destination IATA code (e.g., 'BKK').
        dep: Outbound date YYYY-MM-DD.
        ret: Return date YYYY-MM-DD.
        limit: Max results to return.

    Returns:
        A list of dicts: {id, price, dep_time, arr_time, outbound:{dep_time, arr_time, stops}, return:{dep_time, arr_time, stops}}.
    """
    # Hide flights for specific date windows
    if (dep, ret) in BLOCKED_FLIGHT_WINDOWS:
        return []

    file_path = DATA_DIR / "flights" / dest / f"{dep}__{ret}.json"
    data = load_json(file_path).get("offers", [])

    def proj(o):
            outbound, ret_leg, total_dep, total_arr = _summarize_offer(o)
            return {
                "id": o["id"],
                "price": o["price"],
                "dep_time": total_dep,
                "arr_time": total_arr,
                "outbound": outbound,
                "return": ret_leg,
            }

    return [proj(o) for o in data[:limit]]

if __name__ == "__main__":
    dest, dep, ret = sys.argv[1:4]
    print(list_flights(dest, dep, ret))