from __future__ import annotations
import uuid, json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

FLIGHT_FILE = DATA_DIR / "flight_bookings.json"
HOTEL_FILE  = DATA_DIR / "hotel_bookings.json"

# Blocked date windows to simulate temporary unavailability
BLOCKED_FLIGHT_WINDOWS: set[tuple[str, str]] = {(
    "2025-10-01",
    "2025-10-08",
)}
BLOCKED_HOTEL_WINDOWS: set[tuple[str, str]] = {(
    "2025-10-02",
    "2025-10-09",
)}


def _load_json(path: Path) -> Dict[str, Any]:
    """Return parsed JSON from path or an empty dict if the file is missing."""
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    """Atomically rewrite path with *data* using pretty indentation."""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_iso_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _is_date_order_valid(start: str, end: str) -> bool:
    try:
        return datetime.strptime(start, "%Y-%m-%d") < datetime.strptime(end, "%Y-%m-%d")
    except Exception:
        return False


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _find_flight_offer(
    flight_id: str, _departure: str, _return_date: str, _dest: str
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Locate a flight offer by its globally unique id across all local flight files.

    Returns meta: {"city": <dest>, "search": <search_obj>, "offer": <offer_obj>} on success.
    The date and dest parameters are ignored for lookup since IDs are unique.
    """
    flights_root = DATA_DIR / "flights"
    if not flights_root.exists():
        return False, "Flights data directory missing.", None

    # Walk all destinations and date-pair files to find the id once.
    for city_dir in flights_root.iterdir():
        if not city_dir.is_dir():
            continue
        for candidate in city_dir.glob("*.json"):
            data = _load_json(candidate)
            offers = data.get("offers") or []
            for o in offers:
                if str(o.get("id")) == str(flight_id):
                    return True, None, {
                        "city": city_dir.name,
                        "search": data.get("search") or {},
                        "offer": o,
                    }
    return False, "Flight not found.", None


def _find_hotel(
    hotel_id: str, offer_id: str, check_in: str, check_out: str, city: str
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Locate a hotel and a specific room offer by IDs within the specified city and date pair.

    Searches only under data/hotels/{city}/{check_in__check_out}.json and returns
    meta: {"city": <city>, "search": <search_obj>, "hotel": <hotel_obj>, "offer": <offer_obj>} on success.
    """
    hotels_root = DATA_DIR / "hotels"
    if not hotels_root.exists():
        return False, "Hotels data directory missing.", None

    if not (isinstance(city, str) and city.strip()):
        return False, "City (IATA/city code) is required.", None

    date_file = f"{check_in}__{check_out}.json"
    folder = hotels_root / city
    if not folder.is_dir():
        return False, f"Unknown city '{city}'.", None

    candidate = folder / date_file
    if not candidate.exists():
        return False, (
            f"No hotel with id '{hotel_id}' for {city} on {check_in} to {check_out}."
        ), None

    data = _load_json(candidate)
    hotels = data.get("hotels") or []
    hotel_obj = None
    for h in hotels:
        if str(h.get("hotelId")) == str(hotel_id):
            hotel_obj = h
            break
    if hotel_obj is None:
        return False, (
            f"No hotel with id '{hotel_id}' for {city} on {check_in} to {check_out}."
        ), None

    # Ensure the specified offer exists for this hotel and dates
    offers = hotel_obj.get("offers") or []
    offer_obj = None
    for o in offers:
        if str(o.get("id")) == str(offer_id):
            offer_obj = o
            break
    if offer_obj is None:
        return False, (
            f"No offer with id '{offer_id}' for hotel '{hotel_id}' on {city} {check_in} to {check_out}."
        ), None

    meta = {
        "city": city,
        "search": data.get("search") or {},
        "hotel": hotel_obj,
        "offer": offer_obj,
    }
    return True, None, meta



def _load_flight_bookings() -> Dict[str, Dict[str, Any]]:
    return _load_json(FLIGHT_FILE)


def _load_hotel_bookings() -> Dict[str, Dict[str, Any]]:
    return _load_json(HOTEL_FILE)


def book_flight(flight_id: str, departure: str, return_date: str, dest: str) -> Dict[str, str]:
    """
    Confirm a round-trip flight for a specific destination and date pair.

    Args:
        flight_id (str): Identifier exactly as returned by your flight list/search tool.
        departure (str): Outbound date in ISO ``YYYY-MM-DD`` format.
        return_date (str): Inbound date in ISO ``YYYY-MM-DD`` format.
        dest (str): Destination IATA/city code (e.g., "BKK", "DXB", "REK").

    Returns:
        dict: On success, a confirmation record {confirmation_id, flight_id, departure, return, destination}.
        If validation fails, returns {error: <message>}.
    """
    # Validate only the id; dates/dest are ignored as ids are unique
    if not _valid_id(flight_id):
        return {"error": "Flight id is required."}

    ok, err, meta = _find_flight_offer(flight_id, departure, return_date, dest)
    if not ok:
        return {"error": err or "Flight not found."}

    # Fill details from the located offer's search metadata
    s = meta.get("search") or {}
    dep_from_meta = s.get("departureDate")
    ret_from_meta = s.get("returnDate")
    if (dep_from_meta, ret_from_meta) in BLOCKED_FLIGHT_WINDOWS:
        return {"error": "Flights are unavailable for these dates. Please choose a different date window."}
    conf = f"FL-{uuid.uuid4().hex[:6]}"
    record = {
        "confirmation_id": conf,
        "flight_id": flight_id,
        "departure": dep_from_meta,
        "return": ret_from_meta,
        "destination": s.get("destination") or meta.get("city"),
    }
    # Load fresh, update, then persist
    flights = _load_flight_bookings()
    flights[conf] = record
    _save_json(FLIGHT_FILE, flights)
    return record


def book_hotel(hotel_id: str, offer_id: str, check_in: str, check_out: str, city: str) -> Dict[str, str]:
    """
    Confirm a hotel stay for a given date range in a specific city.

    Args:
    hotel_id (str): Property identifier exactly as returned by list_hotels.
    offer_id (str): Room/offer identifier exactly as returned by list_hotels (offerId).
        check_in (str): First night in ISO ``YYYY-MM-DD`` format (inclusive).
        check_out (str): Check-out date in ISO ``YYYY-MM-DD`` format (exclusive).
        city (str): Destination city/IATA code (e.g., "BKK").

    Returns:
        dict: On success, a confirmation record {confirmation_id, hotel_id, offer_id, check_in, check_out, city}.
        If validation fails, returns {error: <message>}.
    """
    # Basic input validation to prevent hallucinated/ill-formed requests
    if not _valid_id(hotel_id):
        return {"error": "Hotel id is required."}
    if not _valid_id(offer_id):
        return {"error": "Offer id is required."}
    if not _is_iso_date(check_in) or not _is_iso_date(check_out):
        return {"error": "Dates must be in ISO format YYYY-MM-DD."}
    if not _is_date_order_valid(check_in, check_out):
        return {"error": "Check-in must be earlier than check-out."}
    if not _valid_id(city):
        return {"error": "City (IATA/city code) is required."}

    # Verify the hotel exists
    ok, err, meta = _find_hotel(hotel_id, offer_id, check_in, check_out, city)
    if not ok:
        return {"error": err or "Hotel not found."}
    
    # Prevent booking for blocked windows
    if (check_in, check_out) in BLOCKED_HOTEL_WINDOWS:
        return {"error": "Hotels are unavailable for these dates. Please choose a different date window."}
    
    conf = f"HT-{uuid.uuid4().hex[:6]}"
    record = {
        "confirmation_id": conf,
        "hotel_id": hotel_id,
        "offer_id": offer_id,
        "check_in": check_in,
        "check_out": check_out,
        "city": city
    }
    hotels = _load_hotel_bookings()
    hotels[conf] = record
    _save_json(HOTEL_FILE, hotels)
    return record