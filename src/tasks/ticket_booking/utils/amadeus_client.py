from __future__ import annotations
import os, time, json, pathlib, typing as t
import requests

from dotenv import load_dotenv
load_dotenv()

DEFAULT_BASE_URL = os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com")
TOKEN_PATH = "/v1/security/oauth2/token"

class AmadeusClient:
    """Minimal Amadeus REST client with token caching.

    Env vars:
      AMADEUS_API_KEY, AMADEUS_API_SECRET, AMADEUS_BASE_URL
    """
    def __init__(self, api_key: str | None = None, api_secret: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv("AMADEUS_API_KEY")
        self.api_secret = api_secret or os.getenv("AMADEUS_API_SECRET")
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Set AMADEUS_API_KEY and AMADEUS_API_SECRET")
        self.base_url = (base_url or os.getenv("AMADEUS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._token: str | None = None
        self._exp_ts: float = 0.0
        self.sess = requests.Session()

    # Token
    def _ensure_token(self) -> None:
        now = time.time()
        if self._token and now < (self._exp_ts - 60):
            return
        r = self.sess.post(
            self.base_url + TOKEN_PATH,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.api_secret,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._exp_ts = now + float(data.get("expires_in", 1500))

    # HTTP
    def get(self, path: str, params: dict[str, t.Any] | None = None) -> dict:
        self._ensure_token()
        url = self.base_url + path
        for attempt in range(3):
            r = self.sess.get(url, params=params, headers={"Authorization": f"Bearer {self._token}"}, timeout=45)
            if r.status_code == 429 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("unreachable")

    # IO helpers
    @staticmethod
    def dump_json(path: str | pathlib.Path, payload: dict | list) -> None:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)