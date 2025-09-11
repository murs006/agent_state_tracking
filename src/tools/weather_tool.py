import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any


DATA_PATH = Path(__file__).parent.parent / "data" / "weather.json"

def _load_data() -> Dict[str, Dict[str, Dict[str, Any]]]:
    with DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)
    
_WEATHER_DATA = _load_data()


def get_weather(
    city: str,
    start: str,
    end: str | None = None
) -> List[Dict[str, Any]]:
    
    """Retrieves daily weather forecasts for a specified date range.

    Args:
        city (str): The case-insensitive name of the city.
        start (str): The start date for the forecast in 'YYYY-MM-DD' format.
        end (str, optional): The end date in 'YYYY-MM-DD' format. If omitted,
            the forecast for the start date is returned. Defaults to None.

    Returns:
        list[dict[str, any]]: A list of dictionaries, where each contains
            the weather forecast for a single day.
    """

    city_key = city.title()
    if city_key not in _WEATHER_DATA:
        raise ValueError(f"Unknown city: {city}")

    end = end or start
    cur: datetime = datetime.fromisoformat(start)
    end_dt: datetime = datetime.fromisoformat(end)

    if end_dt < cur:
        raise ValueError("`end` date must be on or after `start` date.")

    out: List[Dict[str, Any]] = []
    while cur <= end_dt:
        date_str = cur.date().isoformat()
        try:
            rec = _WEATHER_DATA[city_key][date_str]
        except KeyError as e:
            raise KeyError(f"No weather data for {city_key} on {date_str}") from e
        out.append({"date": date_str, **rec})
        cur += timedelta(days=1)

    return out