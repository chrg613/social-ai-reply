"""Shared RapidAPI HTTP client with retry logic and rate limiting."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Simple in-memory rate limiter
_request_timestamps: dict[str, list[float]] = {}


class RapidAPIError(Exception):
    """Raised when a RapidAPI call fails."""
    def __init__(self, status_code: int, message: str, api_host: str):
        self.status_code = status_code
        self.api_host = api_host
        super().__init__(f"RapidAPI [{api_host}] {status_code}: {message}")


class RapidAPIClient:
    """Async HTTP client for RapidAPI marketplace APIs.

    Handles authentication, retries, and rate limiting.
    All platform adapters use this shared client.
    """

    BASE_URL = "https://{host}"
    MAX_RETRIES = 2
    RETRY_DELAY = 1.0
    REQUESTS_PER_MINUTE = 30  # safety throttle

    def __init__(self, api_host: str, *, timeout: float = 30.0):
        self.api_host = api_host
        self.timeout = timeout
        settings = get_settings()
        self._api_key = settings.rapidapi_key
        if not self._api_key:
            raise ValueError(
                "RAPIDAPI_KEY is not set. Get a free key at https://rapidapi.com "
                "and add RAPIDAPI_KEY=your-key to your .env file."
            )

    def _get_headers(self) -> dict[str, str]:
        return {
            "x-rapidapi-key": self._api_key,
            "x-rapidapi-host": self.api_host,
        }

    async def _throttle(self) -> None:
        """Simple rate limiter: max N requests per minute per host."""
        now = time.monotonic()
        key = self.api_host
        if key not in _request_timestamps:
            _request_timestamps[key] = []

        # Remove timestamps older than 60 seconds
        _request_timestamps[key] = [t for t in _request_timestamps[key] if now - t < 60]

        if len(_request_timestamps[key]) >= self.REQUESTS_PER_MINUTE:
            wait = 60 - (now - _request_timestamps[key][0])
            if wait > 0:
                logger.info("Rate limit: waiting %.1fs for %s", wait, key)
                await asyncio.sleep(wait)

        _request_timestamps[key].append(now)

    async def get(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Make a GET request to a RapidAPI endpoint.

        Args:
            endpoint: API path (e.g., "/search" or "/user/posts").
            params: Query parameters.

        Returns:
            Parsed JSON response.

        Raises:
            RapidAPIError: On non-200 responses after retries.
        """
        await self._throttle()

        url = f"https://{self.api_host}{endpoint}"
        headers = self._get_headers()

        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, headers=headers, params=params or {})

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 429:  # Rate limited
                    wait = self.RETRY_DELAY * (2 ** attempt)
                    logger.warning("Rate limited by %s, waiting %.1fs (attempt %d)", self.api_host, wait, attempt + 1)
                    await asyncio.sleep(wait)
                    continue

                if response.status_code >= 500:  # Server error, retry
                    wait = self.RETRY_DELAY * (2 ** attempt)
                    logger.warning("Server error %d from %s, retrying in %.1fs", response.status_code, self.api_host, wait)
                    await asyncio.sleep(wait)
                    continue

                # Client error (400, 403, 404) — don't retry
                error_body = response.text[:500]
                raise RapidAPIError(response.status_code, error_body, self.api_host)

            except httpx.HTTPError as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue
                raise RapidAPIError(0, str(e), self.api_host) from e

        raise RapidAPIError(0, f"Max retries exceeded: {last_error}", self.api_host)
