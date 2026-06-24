"""Per-host HTTP budget: request throttling, exponential backoff, circuit breaking.

Shared by outbound scrapers/clients (Reddit discovery, future platform adapters)
so that every caller in the process respects the same per-host limits. Module
state is process-local, which is correct for the current single-worker
deployment (see railway.toml); revisit if the app moves to multiple workers.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

DEFAULT_MIN_INTERVAL = 0.5
DEFAULT_FAILURE_THRESHOLD = 10
DEFAULT_COOLDOWN_SECONDS = 120.0
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0


class CircuitOpenError(RuntimeError):
    """Raised when a host's circuit is open and requests must not be attempted."""

    def __init__(self, host: str, retry_in: float):
        self.host = host
        self.retry_in = retry_in
        super().__init__(
            f"Circuit open for {host}: too many consecutive failures; retry in {retry_in:.0f}s."
        )


@dataclass
class _HostState:
    last_request_at: float = 0.0
    consecutive_failures: int = 0
    open_until: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


class HttpBudget:
    """Per-host throttle + circuit breaker.

    Usage::

        budget.acquire(host)            # sleeps to honor min interval; raises CircuitOpenError
        ... perform request ...
        budget.record_success(host)     # or budget.record_failure(host)
        time.sleep(budget.backoff_delay(attempt, retry_after=...))  # between retries
    """

    def __init__(
        self,
        *,
        min_interval_by_host: dict[str, float] | None = None,
        default_min_interval: float = DEFAULT_MIN_INTERVAL,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        clock=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self._min_interval_by_host = dict(min_interval_by_host or {})
        self._default_min_interval = default_min_interval
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._sleep = sleep
        self._hosts: dict[str, _HostState] = {}
        self._registry_lock = threading.Lock()

    def set_min_interval(self, host: str, interval: float) -> None:
        self._min_interval_by_host[host] = interval

    def _state(self, host: str) -> _HostState:
        with self._registry_lock:
            state = self._hosts.get(host)
            if state is None:
                state = self._hosts[host] = _HostState()
            return state

    def acquire(self, host: str) -> None:
        """Block until the host's min interval has elapsed; raise if circuit is open."""
        state = self._state(host)
        min_interval = self._min_interval_by_host.get(host, self._default_min_interval)
        with state.lock:
            now = self._clock()
            if state.open_until > now:
                raise CircuitOpenError(host, retry_in=state.open_until - now)
            wait = state.last_request_at + min_interval - now
            # Reserve the slot before sleeping so concurrent callers space out.
            state.last_request_at = max(now, state.last_request_at + min_interval) if wait > 0 else now
        if wait > 0:
            self._sleep(wait)

    def record_success(self, host: str) -> None:
        state = self._state(host)
        with state.lock:
            state.consecutive_failures = 0

    def record_failure(self, host: str) -> None:
        state = self._state(host)
        with state.lock:
            state.consecutive_failures += 1
            if state.consecutive_failures >= self._failure_threshold:
                state.open_until = self._clock() + self._cooldown_seconds
                state.consecutive_failures = 0
                log.warning(
                    "Circuit opened for host %s for %.0fs after repeated failures",
                    host,
                    self._cooldown_seconds,
                )

    def backoff_delay(self, attempt: int, retry_after: str | None = None) -> float:
        """Exponential backoff with full jitter; honors a numeric Retry-After header."""
        if retry_after:
            try:
                return min(float(retry_after), BACKOFF_CAP_SECONDS)
            except ValueError:
                pass
        ceiling = min(BACKOFF_BASE_SECONDS * (2**attempt), BACKOFF_CAP_SECONDS)
        return random.uniform(ceiling / 2, ceiling)

    def is_open(self, host: str) -> bool:
        state = self._state(host)
        with state.lock:
            return state.open_until > self._clock()
