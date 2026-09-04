import asyncio
from datetime import datetime, timezone

from miair.runtime.models import IngressProtocol, SessionState
from miair.runtime.sessions import MediaSessionCoordinator
from miair.content.repository import ContentRepository


NOW = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)


def test_same_target_preempts_old_session_and_rejects_stale_callback():
    async def scenario():
        coordinator = MediaSessionCoordinator(clock=lambda: NOW)
        first = await coordinator.begin("uuid:living", IngressProtocol.AIRPLAY)
        second = await coordinator.begin("uuid:living", IngressProtocol.MIPLAY)

        assert first.id != second.id
        assert coordinator.current("uuid:living").id == second.id
        assert await coordinator.transition(first.id, SessionState.PLAYING) is False
        assert await coordinator.transition(second.id, SessionState.PLAYING) is True

    asyncio.run(scenario())


def test_different_targets_have_independent_current_sessions():
    async def scenario():
        coordinator = MediaSessionCoordinator(clock=lambda: NOW)
        living, bedroom = await asyncio.gather(
            coordinator.begin("uuid:living", IngressProtocol.MIPLAY),
            coordinator.begin("uuid:bedroom", IngressProtocol.AIRPLAY),
        )

        assert coordinator.current("uuid:living").id == living.id
        assert coordinator.current("uuid:bedroom").id == bedroom.id
        assert await coordinator.end(living.id) is True
        assert coordinator.current("uuid:living") is None
        assert coordinator.current("uuid:bedroom").id == bedroom.id

    asyncio.run(scenario())


def test_session_coordinator_persists_lifecycle_and_preemption(tmp_path):
    async def scenario():
        repository = ContentRepository(tmp_path / "castfabric.sqlite3", clock=lambda: NOW)
        ids = iter(["session-one", "session-two"])
        coordinator = MediaSessionCoordinator(
            repository=repository,
            clock=lambda: NOW,
            id_factory=lambda: next(ids),
        )

        first = await coordinator.begin("uuid:living", IngressProtocol.MCP)
        await coordinator.transition(first.id, SessionState.PLAYING)
        second = await coordinator.begin("uuid:living", IngressProtocol.AIRPLAY)

        assert repository.get_session(first.id)["state"] == "ended"
        assert repository.get_session(first.id)["end_reason"] == "preempted"
        assert repository.get_session(second.id)["state"] == "starting"
        assert await coordinator.end(second.id, reason="stopped") is True
        assert repository.get_session(second.id)["end_reason"] == "stopped"
        repository.close()

    asyncio.run(scenario())
