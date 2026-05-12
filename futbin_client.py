from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any

import aiohttp


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
]


def _normalize_price(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    txt = str(value).replace(",", "")
    if txt.isdigit():
        return int(txt)
    return None


class FutbinClient:
    def __init__(self, timeout_seconds: int, max_retries: int, logger):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.logger = logger
        self.cache: dict[str, tuple[float, Any]] = {}

    def _cache_get(self, key: str) -> Any | None:
        row = self.cache.get(key)
        if not row:
            return None
        expires_at, value = row
        if expires_at < time.time():
            self.cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.cache[key] = (time.time() + ttl_seconds, value)

    def _headers(self, referer: str = "https://www.futbin.com/") -> dict[str, str]:
        return {
            "user-agent": random.choice(USER_AGENTS),
            "accept": "application/json,text/plain,*/*",
            "accept-language": "en-US,en;q=0.9",
            "referer": referer,
        }

    async def _fetch_with_retry(self, session: aiohttp.ClientSession, url: str, headers: dict[str, str]) -> aiohttp.ClientResponse:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = await session.get(url, headers=headers, timeout=self.timeout_seconds)
                if response.status == 429 or response.status >= 500:
                    raise RuntimeError(f"HTTP {response.status}")
                return response
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                delay = 0.45 * attempt
                self.logger.warning("FUTBIN retry", extra={"attempt": attempt, "delay": delay, "reason": str(exc)})
                await asyncio.sleep(delay)
        raise RuntimeError(f"FUTBIN failed: {last_error}")

    async def search_player(self, term: str) -> dict[str, Any]:
        key = f"search:{term.lower()}"
        cached = self._cache_get(key)
        if cached:
            return cached

        url = f"https://www.futbin.com/search?year=26&term={term}"
        async with aiohttp.ClientSession() as session:
            res = await self._fetch_with_retry(session, url, self._headers())
            data = await res.json()

        if not isinstance(data, list) or not data:
            raise RuntimeError("Nie znaleziono zawodnika w FUTBIN")

        best = data[0]
        player = {
            "id": str(best.get("id") or best.get("player_id") or best.get("resource_id")),
            "name": best.get("name", term),
            "rating": int(best.get("rating") or best.get("player_rating") or 0),
            "rarity": best.get("quality") or best.get("version") or "unknown",
        }
        self._cache_set(key, player, 30)
        return player

    @staticmethod
    def _parse_html_price(html: str, platform: str) -> int | None:
        patterns = {
            "ps": r'"LCPrice2"\s*:\s*"?(\d+)"?|"PSPrice"\s*:\s*"?(\d+)"?',
            "xbox": r'"XBLPrice2"\s*:\s*"?(\d+)"?|"XBPrice"\s*:\s*"?(\d+)"?',
            "pc": r'"PCPrice2"\s*:\s*"?(\d+)"?|"PCPrice"\s*:\s*"?(\d+)"?',
        }
        match = re.search(patterns[platform], html, re.IGNORECASE)
        if not match:
            return None
        for group in match.groups():
            if group:
                return _normalize_price(group)
        return None

    @staticmethod
    def _simulate_price(player_id: str, previous: int | None) -> int:
        base = previous or (20000 + int(player_id) % 50000)
        delta = (random.random() - 0.5) * 0.08
        return max(300, int(base * (1 + delta)))

    async def get_prices(self, player_id: str, previous: dict[str, int | None] | None = None) -> dict[str, Any]:
        key = f"price:{player_id}"
        cached = self._cache_get(key)
        if cached:
            return cached

        api_url = f"https://www.futbin.com/26/playerPrices?player={player_id}"
        try:
            async with aiohttp.ClientSession() as session:
                res = await self._fetch_with_retry(
                    session,
                    api_url,
                    self._headers(referer=f"https://www.futbin.com/26/player/{player_id}"),
                )
                raw = await res.json()

            payload = raw.get(player_id, raw)
            prices = {
                "ps": _normalize_price((payload.get("prices") or {}).get("ps", {}).get("LCPrice") or (payload.get("ps") or {}).get("LCPrice")),
                "xbox": _normalize_price((payload.get("prices") or {}).get("xbox", {}).get("LCPrice") or (payload.get("xbox") or {}).get("LCPrice")),
                "pc": _normalize_price((payload.get("prices") or {}).get("pc", {}).get("LCPrice") or (payload.get("pc") or {}).get("LCPrice")),
                "source": "api",
            }
            if not prices["ps"] and not prices["xbox"] and not prices["pc"]:
                raise RuntimeError("Puste ceny z API")
            self._cache_set(key, prices, 10)
            return prices
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("API fallback to HTML scrape", extra={"player_id": player_id, "reason": str(exc)})

        html_url = f"https://www.futbin.com/26/player/{player_id}"
        try:
            async with aiohttp.ClientSession() as session:
                res = await self._fetch_with_retry(session, html_url, self._headers())
                html = await res.text()
            prices = {
                "ps": self._parse_html_price(html, "ps"),
                "xbox": self._parse_html_price(html, "xbox"),
                "pc": self._parse_html_price(html, "pc"),
                "source": "scrape",
            }
            if not prices["ps"] and not prices["xbox"] and not prices["pc"]:
                raise RuntimeError("Puste ceny z HTML")
            self._cache_set(key, prices, 12)
            return prices
        except Exception as exc:  # noqa: BLE001
            self.logger.error("HTML fallback failed, using simulated prices", extra={"player_id": player_id, "reason": str(exc)})

        previous = previous or {}
        simulated = {
            "ps": self._simulate_price(player_id, previous.get("ps")),
            "xbox": self._simulate_price(player_id, previous.get("xbox")),
            "pc": self._simulate_price(player_id, previous.get("pc")),
            "source": "simulated",
        }
        self._cache_set(key, simulated, 8)
        return simulated
