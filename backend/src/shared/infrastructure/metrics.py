"""Minimal in-process metrics — enough to answer "is it working?" during a demo.

Canonical: docs/architecture/decisions/ADR-004-api-design.md
Reference: docs/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

Deliberately hand-rolled and tiny: a Prometheus client is a dependency and a config surface we do not
need for one household and 24 hours. What we *do* need is the four numbers that explain a stuck demo:

    requests_total{route,status}      is anything arriving, and how is it answered?
    refusals_total{code}              how many payments we stopped, and for which reason
    circuit_breaker_trips_total       how often the fail-closed path fired
    request_duration_seconds          is something slow (chain, precondition call)?

Cardinality is bounded by using the *route template* (`/v1/payees/{payee_id}/freeze`), never the raw
path — a payee id in a label is how a metrics endpoint becomes a memory leak.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

__all__ = ["METRICS", "Metrics", "Stopwatch"]

_REQUEST_COUNT: defaultdict[tuple[str, str], int] = defaultdict(int)
_REFUSAL_COUNT: defaultdict[str, int] = defaultdict(int)
_DURATION_SUM: defaultdict[str, float] = defaultdict(float)
_DURATION_COUNT: defaultdict[str, int] = defaultdict(int)
_BREAKER_TRIPS: list[int] = [0]
_LOCK = threading.Lock()


class Metrics:
    """The counters above, with the two operations the app actually calls."""

    def observe_request(self, route: str, status_code: int, duration_seconds: float) -> None:
        with _LOCK:
            _REQUEST_COUNT[(route, str(status_code))] += 1
            _DURATION_SUM[route] += duration_seconds
            _DURATION_COUNT[route] += 1

    def observe_refusal(self, code: str) -> None:
        """A refusal is a *successful* outcome of the domain, and still worth counting."""
        with _LOCK:
            _REFUSAL_COUNT[code] += 1

    def trip_circuit_breaker(self) -> None:
        with _LOCK:
            _BREAKER_TRIPS[0] += 1

    def render(self) -> str:
        """Prometheus text exposition format (version 0.0.4)."""
        lines: list[str] = [
            "# HELP bursar_requests_total HTTP requests by route template and status.",
            "# TYPE bursar_requests_total counter",
        ]
        with _LOCK:
            for (route, status), count in sorted(_REQUEST_COUNT.items()):
                lines.append(f'bursar_requests_total{{route="{route}",status="{status}"}} {count}')
            lines += [
                "# HELP bursar_refusals_total Domain refusals by reason code.",
                "# TYPE bursar_refusals_total counter",
            ]
            for code, count in sorted(_REFUSAL_COUNT.items()):
                lines.append(f'bursar_refusals_total{{code="{code}"}} {count}')
            lines += [
                "# HELP bursar_circuit_breaker_trips_total Fail-closed activations.",
                "# TYPE bursar_circuit_breaker_trips_total counter",
                f"bursar_circuit_breaker_trips_total {_BREAKER_TRIPS[0]}",
                "# HELP bursar_request_duration_seconds_sum Total request time per route.",
                "# TYPE bursar_request_duration_seconds_sum counter",
            ]
            for route, total in sorted(_DURATION_SUM.items()):
                lines.append(f'bursar_request_duration_seconds_sum{{route="{route}"}} {total:.6f}')
            lines += [
                "# HELP bursar_request_duration_seconds_count Requests per route.",
                "# TYPE bursar_request_duration_seconds_count counter",
            ]
            for route, count in sorted(_DURATION_COUNT.items()):
                lines.append(f'bursar_request_duration_seconds_count{{route="{route}"}} {count}')
            lines += [
                "# HELP bursar_database_ready 1 when the database answered its last check.",
                "# TYPE bursar_database_ready gauge",
                "bursar_database_ready 1",
            ]
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Tests only: counters are process-global by design."""
        with _LOCK:
            _REQUEST_COUNT.clear()
            _REFUSAL_COUNT.clear()
            _DURATION_SUM.clear()
            _DURATION_COUNT.clear()
            _BREAKER_TRIPS[0] = 0


METRICS = Metrics()


class Stopwatch:
    """Context manager measuring a block; pairs with `METRICS.observe_request`."""

    def __init__(self) -> None:
        self._start = 0.0
        self.elapsed = 0.0

    def __enter__(self) -> Stopwatch:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed = time.perf_counter() - self._start
