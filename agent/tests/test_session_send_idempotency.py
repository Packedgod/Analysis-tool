"""Message-send retries must not duplicate prompts or attempts."""

from __future__ import annotations

import asyncio

import src.session.service as service_module
from src.session.events import EventBus
from src.session.service import SessionService
from src.session.store import SessionStore


class _SearchIndex:
    def index_session(self, *args, **kwargs) -> None:
        pass

    def index_message(self, *args, **kwargs) -> None:
        pass


def test_retried_client_request_returns_original_message_and_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(service_module, "get_shared_index", lambda: _SearchIndex())
    store = SessionStore(tmp_path / "sessions")
    service = SessionService(store=store, event_bus=EventBus(), runs_dir=tmp_path / "runs")
    session = service.create_session("retry")

    async def _no_op_attempt(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(service, "_run_attempt", _no_op_attempt)

    async def _exercise():
        first = await service.send_message(
            session.session_id,
            "run the backtest",
            client_request_id="send-12345678",
        )
        second = await service.send_message(
            session.session_id,
            "run the backtest",
            client_request_id="send-12345678",
        )
        await asyncio.sleep(0)
        return first, second

    first, second = asyncio.run(_exercise())

    assert second == first
    messages = store.get_messages(session.session_id, limit=1000)
    assert len(messages) == 1
    assert messages[0].metadata["client_request_id"] == "send-12345678"
    assert messages[0].linked_attempt_id == first["attempt_id"]
    attempt_dirs = list((tmp_path / "sessions" / session.session_id / "attempts").iterdir())
    assert len(attempt_dirs) == 1


def test_distinct_client_request_ids_create_distinct_attempts(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(service_module, "get_shared_index", lambda: _SearchIndex())
    store = SessionStore(tmp_path / "sessions")
    service = SessionService(store=store, event_bus=EventBus(), runs_dir=tmp_path / "runs")
    session = service.create_session("retry")

    async def _no_op_attempt(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(service, "_run_attempt", _no_op_attempt)

    async def _exercise():
        first = await service.send_message(
            session.session_id,
            "run the backtest",
            client_request_id="send-12345678",
        )
        second = await service.send_message(
            session.session_id,
            "run the backtest",
            client_request_id="send-87654321",
        )
        await asyncio.sleep(0)
        return first, second

    first, second = asyncio.run(_exercise())

    assert first["attempt_id"] != second["attempt_id"]
    assert len(store.get_messages(session.session_id, limit=1000)) == 2
