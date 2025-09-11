from __future__ import annotations
import pathlib, argparse, datetime as dt
from typing import Any
from .amadeus_client import AmadeusClient

CITIES = {
    "Bangkok": "BKK",
    "Reykjavik": "REK",
    "Dubai": "DXB",
}

HOTEL_LIST_BY_CITY = "/v1/reference-data/locations/hotels/by-city"
HOTEL_OFFERS = "/v3/shopping/hotel-offers"


def build_candidates(window_start: str, window_days: int, stay_nights: int, max_departure_tries: int = 3) -> list[tuple[str, str]]:
    start = dt.date.fromisoformat(window_start)
    num_possible = window_days - stay_nights + 1
    if num_possible <= 0:
        raise ValueError("window_days must be >= stay_nights")
    k = min(max_departure_tries, num_possible)
    pairs = []
    for i in range(k):
        checkin = start + dt.timedelta(days=i)
        checkout = checkin + dt.timedelta(days=stay_nights)
        pairs.append((checkin.isoformat(), checkout.isoformat()))
    return pairs


def fetch_hotel_ids_by_city(client: AmadeusClient, city_code: str, limit: int = 50, max_hotels: int = 150) -> list[str]:
    """Page through Hotel List by City to collect hotelIds.
    Uses page[limit] & page[offset] pagination.
    """
    hotel_ids: list[str] = []
    offset = 0
    while len(hotel_ids) < max_hotels:
        params = {
            "cityCode": city_code,      # e.g., BKK / REK / DXB (IATA city code)
            "hotelSource": "ALL",       # BEDBANK + DIRECTCHAIN
            "radius": "50",
            "radiusUnit": "KM",
        }
        raw = client.get(HOTEL_LIST_BY_CITY, params)
        data = raw.get("data", []) or []
        for h in data:
            hid = (h.get("hotelId") or h.get("hotel", {}).get("hotelId"))
            if hid:
                hotel_ids.append(hid)
        if not data or len(data) == 0:
            break
        offset += len(data)
    # de-dupe while preserving order
    seen = set()
    uniq = []
    for hid in hotel_ids:
        if hid not in seen:
            seen.add(hid)
            uniq.append(hid)
    return uniq


def chunk(seq: list[str], n: int) -> list[list[str]]:
    return [seq[i:i+n] for i in range(0, len(seq), n)]


def normalize_hotels(resp_objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine multiple Hotel Search v3 responses and produce a sorted hotel list with cheapest offer."""
    out_hotels: dict[str, dict[str, Any]] = {}
    for resp in resp_objects:
        for item in resp.get("data", []) or []:
            hotel = item.get("hotel", {}) or {}
            hid = hotel.get("hotelId")
            if not hid:
                continue
            bucket = out_hotels.setdefault(hid, {
                "hotelId": hid,
                "name": hotel.get("name"),
                "chainCode": hotel.get("chainCode"),
                "iataCode": hotel.get("iataCode"),
                "lat": hotel.get("latitude"),
                "lon": hotel.get("longitude"),
                "offers": [],
                "cheapest": None,
            })
            for off in item.get("offers", []) or []:
                price = off.get("price", {}) or {}
                rec = {
                    "id": off.get("id"),
                    "priceTotal": float(price.get("total", 0) or 0),
                    "currency": price.get("currency"),
                    "boardType": off.get("boardType"),
                    "roomType": (off.get("room", {}) or {}).get("type"),
                    "description": ((off.get("room", {}) or {}).get("description", {}) or {}).get("text"),
                    "cancellable": (off.get("policies", {}) or {}).get("cancellations") is not None,
                }
                bucket["offers"].append(rec)
            if bucket["offers"]:
                bucket["offers"].sort(key=lambda x: x["priceTotal"])
                bucket["cheapest"] = bucket["offers"][0]
    # final list sorted by cheapest price
    hotels = list(out_hotels.values())
    hotels.sort(key=lambda h: h["cheapest"]["priceTotal"] if h.get("cheapest") else 9e9)
    return hotels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--window-days", type=int, default=10)
    ap.add_argument("--stay-nights", type=int, default=7)
    ap.add_argument("--adults", type=int, default=1)
    ap.add_argument("--currency", default="USD")
    ap.add_argument("--max-hotels", type=int, default=120, help="cap number of hotelIds per city")
    ap.add_argument("--ids-per-call", type=int, default=20, help="size of hotelIds batch per /v3 call")
    args = ap.parse_args()

    client = AmadeusClient()
    pairs = build_candidates(args.window_start, args.window_days, args.stay_nights)

    for city_name, city_code in CITIES.items():
        # Step 1: get hotelIds (paginated)
        hotel_ids = fetch_hotel_ids_by_city(client, city_code, max_hotels=args.max_hotels)
        if not hotel_ids:
            print(f"WARNING: No hotelIds found for {city_code}")

        for checkin, checkout in pairs:
            # Step 2: query offers in batches of hotelIds
            raw_chunks: list[dict[str, Any]] = []
            for batch in chunk(hotel_ids, max(1, args.ids_per_call)):
                params = {
                    "hotelIds": ",".join(batch),
                    "adults": str(args.adults),
                    "checkInDate": checkin,
                    "checkOutDate": checkout,
                    "currency": args.currency,
                    "bestRateOnly": "true",
                }
                try:
                    raw = client.get(HOTEL_OFFERS, params)
                except Exception as e:
                    raw = {"error": str(e), "params": params}
                raw_chunks.append(raw)

            # Normalize all chunks aggregated
            norm_hotels = normalize_hotels(raw_chunks)
            norm = {
                "search": {"cityCode": city_code, "checkInDate": checkin, "checkOutDate": checkout, "adults": args.adults, "currency": args.currency, "n_batches": len(raw_chunks)},
                "hotels": norm_hotels,
            }

            # Save both raw (per-batch) and normalized (combined)
            base = pathlib.Path(f"src/data/hotels/{city_code}")
            raw_dir = pathlib.Path(f"src/data/hotels_raw/{city_code}/{checkin}__{checkout}")
            raw_dir.mkdir(parents=True, exist_ok=True)
            for i, payload in enumerate(raw_chunks):
                AmadeusClient.dump_json(raw_dir / f"chunk_{i:02d}.json", payload)
            AmadeusClient.dump_json(base / f"{checkin}__{checkout}.json", norm)
            print(f"Saved {city_code} hotels to src/data/hotels/{city_code}/{checkin}__{checkout}.json  (batches={len(raw_chunks)})")

if __name__ == "__main__":
    main()