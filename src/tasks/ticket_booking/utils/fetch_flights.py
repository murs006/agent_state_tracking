from __future__ import annotations
import os, pathlib, argparse, datetime as dt
from typing import Any
from .amadeus_client import AmadeusClient

CITIES = {
    "Bangkok": "BKK",
    "Reykjavik": "REK",
    "Dubai": "DXB",
}

FLIGHT_PATH = "/v2/shopping/flight-offers"


def build_candidates(window_start: str, window_days: int, stay_nights: int, max_departure_tries: int = 3) -> list[tuple[str, str]]:
    """Return list of (departureDate, returnDate) pairs.
    Formula: candidates = min(3, window_days - stay_nights + 1)."""
    start = dt.date.fromisoformat(window_start)
    num_possible = window_days - stay_nights + 1
    if num_possible <= 0:
        raise ValueError("window_days must be >= stay_nights")
    k = min(max_departure_tries, num_possible)
    pairs = []
    for i in range(k):
        dep = start + dt.timedelta(days=i)
        ret = dep + dt.timedelta(days=stay_nights)
        pairs.append((dep.isoformat(), ret.isoformat()))
    return pairs


def normalize_flights(resp: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for off in resp.get("data", [])[:50]:
        price = float(off.get("price", {}).get("grandTotal", off.get("price", {}).get("total", 0)))
        itin = []
        for it in off.get("itineraries", []):
            segs = []
            for s in it.get("segments", []):
                segs.append({
                    "carrierCode": s.get("carrierCode"),
                    "number": s.get("number"),
                    "from": s.get("departure", {}).get("iataCode"),
                    "to": s.get("arrival", {}).get("iataCode"),
                    "dep": s.get("departure", {}).get("at"),
                    "arr": s.get("arrival", {}).get("at"),
                    "duration": s.get("duration"),
                })
            itin.append({"segments": segs, "duration": it.get("duration")})
        out.append({
            "id": off.get("id"),
            "price": price,
            "validatingAirlineCodes": off.get("validatingAirlineCodes"),
            "itineraries": itin,
        })
    out.sort(key=lambda x: x["price"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", default=os.getenv("ORIGIN", "JFK"))
    ap.add_argument("--window-start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--window-days", type=int, default=10)
    ap.add_argument("--stay-nights", type=int, default=7)
    ap.add_argument("--adults", type=int, default=1)
    ap.add_argument("--currency", default="USD")
    args = ap.parse_args()

    client = AmadeusClient()
    pairs = build_candidates(args.window_start, args.window_days, args.stay_nights)

    for city_name, dest_code in CITIES.items():
        for dep, ret in pairs:
            params = {
                "originLocationCode": args.origin,
                "destinationLocationCode": dest_code,
                "departureDate": dep,
                "returnDate": ret,
                "adults": args.adults,
                "currencyCode": args.currency,
                "max": 50,
            }
            raw = client.get(FLIGHT_PATH, params)
            norm = {
                "search": {"origin": args.origin, "destination": dest_code, "departureDate": dep, "returnDate": ret, "adults": args.adults, "currency": args.currency},
                "offers": normalize_flights(raw),
            }
            raw_path = pathlib.Path(f"src/data/flights_raw/{dest_code}/{dep}__{ret}.json")
            norm_path = pathlib.Path(f"src/data/flights/{dest_code}/{dep}__{ret}.json")
            AmadeusClient.dump_json(raw_path, raw)
            AmadeusClient.dump_json(norm_path, norm)
            print(f"Saved flights → {norm_path}")

if __name__ == "__main__":
    main()