"""Tests for ``worker.events.publish`` log-level policy.

The seed script and other non-worker callers used to log a full
traceback per event when Redis wasn't reachable (compose-internal
hostname doesn't resolve from the host). These tests lock in the fix
— connection errors are DEBUG outside a worker, ERROR inside one —
and make sure unrelated exceptions still page loudly regardless.

Worker logging is configured via ``structlog.PrintLoggerFactory``
(writes directly to stdout, bypasses stdlib ``logging``), so pytest's
``caplog`` can't see the records. We assert against the log *methods*
being invoked on ``events.log`` instead — the level a caller chose is
the contract we care about, not the bytes that land on stdout.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import redis.exceptions

from worker import events


class _FakeConnectionError(redis.exceptions.ConnectionError):
    """Concrete subclass so tests can confirm the connection branch fires."""


class _ExplodingClient:
    """Raises the configured exception on every ``publish`` call."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def publish(self, channel, body):  # noqa: ARG002
        raise self._exc


@pytest.fixture
def force_redis(monkeypatch: pytest.MonkeyPatch):
    """Force ``Redis.from_url(...).publish(...)`` to raise ``exc``."""

    def _install(exc: Exception) -> None:
        monkeypatch.setattr(
            "worker.events.redis_sync.Redis.from_url",
            lambda *a, **kw: _ExplodingClient(exc),
        )

    return _install


@pytest.fixture
def mock_log(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ``events.log`` with a spy so we can assert which level fired."""
    m = MagicMock()
    monkeypatch.setattr("worker.events.log", m)
    return m


@pytest.fixture(autouse=True)
def _clear_worker_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every test starts without the worker-process flag; tests that
    # need it set it explicitly.
    monkeypatch.delenv("ATLAS_WORKER_PROCESS", raising=False)


def test_connection_error_outside_worker_logs_debug(
    force_redis, mock_log,
) -> None:
    force_redis(_FakeConnectionError("nxdomain: redis"))

    out = events.publish(uuid4(), {"type": "demo"})

    assert out == 0  # fire-and-forget
    # Exactly one log call on the debug path, no exception-level call.
    assert mock_log.debug.call_count == 1
    assert mock_log.exception.call_count == 0
    assert mock_log.error.call_count == 0
    # Event name matches the new, connection-specific key.
    (event_name,), _kw = mock_log.debug.call_args
    assert event_name == "events.publish_connection_failed"


def test_connection_error_inside_worker_logs_error(
    force_redis, mock_log, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_WORKER_PROCESS", "1")
    force_redis(_FakeConnectionError("refused"))

    out = events.publish(uuid4(), {"type": "demo"})

    assert out == 0
    # log.exception attaches traceback + emits at ERROR.
    assert mock_log.exception.call_count == 1
    assert mock_log.debug.call_count == 0
    (event_name,), _kw = mock_log.exception.call_args
    assert event_name == "events.publish_connection_failed"


def test_non_connection_exception_always_logs_error(
    force_redis, mock_log,
) -> None:
    # Even outside a worker, unexpected failures (JSON encode, auth
    # rejection, unknown error classes) stay at ERROR — they're not
    # the benign "host can't reach compose-internal hostname" case
    # this fix targets.
    force_redis(RuntimeError("something unexpected"))

    out = events.publish(uuid4(), {"type": "demo"})

    assert out == 0
    assert mock_log.exception.call_count == 1
    assert mock_log.debug.call_count == 0
    (event_name,), _kw = mock_log.exception.call_args
    assert event_name == "events.publish_failed"
