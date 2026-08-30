import asyncio
from datetime import datetime, timezone

from miair.runtime.models import IngressProtocol, SessionState
from miair.runtime.sessions import MediaSessionCoordinator


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
