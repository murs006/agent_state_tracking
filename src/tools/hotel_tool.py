import json
import sys
from pathlib import Path
from typing import Dict, Any, List

DATA_DIR = Path(__file__).parent.parent / "data"
BLOCKED_HOTEL_WINDOWS: set[tuple[str, str]] = {(
    "2025-10-02",
    "2025-10-09",
)}


def load_json(path: Path) -> Dict[str, Any]:
    """Return parsed JSON from path or an empty dict if missing/invalid."""
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def list_hotels(city: str, checkin: str, checkout: str, limit: int = 10) -> List[Dict[str, Any]]:
    """List hotel options from local JSON with cheapest offer details.

    Args:
        city: Destination city code (e.g., 'BKK').
        checkin: Check-in date YYYY-MM-DD.
        checkout: Check-out date YYYY-MM-DD.
        limit: Max results to return.

    Returns:
        A list of dicts: {hotelId, name, offerId, priceTotal, currency, cancellable, description}.
    """
    # Hide hotels for specific date windows
    if (checkin, checkout) in BLOCKED_HOTEL_WINDOWS:
        return []

    file_path = DATA_DIR / "hotels" / city / f"{checkin}__{checkout}.json"
    data = load_json(file_path).get("hotels", [])

    def proj(h):
        c = h.get("cheapest")
        return {
            "hotelId": h["hotelId"],
            "name": h.get("name"),
            "offerId": c and c.get("id"),
            "priceTotal": c and c.get("priceTotal"),
            "currency": c and c.get("currency"),
            "cancellable": c and c.get("cancellable"),
            "description": c and c.get("description"),
        }

    return [proj(h) for h in data[:limit]]


if __name__ == "__main__":
    city, checkin, checkout = sys.argv[1:4]
    print(list_hotels(city, checkin, checkout))