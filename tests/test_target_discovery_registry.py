import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from miair.dlna.client import DiscoveredDLNATarget
from miair.runtime.discovery import (
    DiscoveryBusyError,
    DiscoveryState,
    TargetDiscoveryRegistry,
)


NOW = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)


def target(target_id="uuid:living", name="Living"):
    return DiscoveredDLNATarget(
        id=target_id,
        name=name,
        location="http://192.168.133.132/device.xml",
        services={"service": "control"},
    )


def test_scan_atomically_replaces_observations_and_records_completion():
    async def scenario():
        registry = TargetDiscoveryRegistry(lambda: asyncio.sleep(0, result=[target()]), clock=lambda: NOW)

        result = await registry.scan()

        assert registry.state is DiscoveryState.READY
        assert registry.observed_at == NOW
        assert result["uuid:living"].name == "Living"
        assert registry.snapshot()["uuid:living"].location.endswith("device.xml")

    asyncio.run(scenario())


def test_scan_retains_previous_snapshot_while_running_and_rejects_overlap():
    async def scenario():
        release = asyncio.Event()
        calls = 0

        async def discover():
            nonlocal calls
            calls += 1
            if calls == 1:
                return [target()]
            await release.wait()
            return [target("uuid:bedroom", "Bedroom")]

        registry = TargetDiscoveryRegistry(discover, clock=lambda: NOW)
        await registry.scan()
        running = asyncio.create_task(registry.scan())
        await asyncio.sleep(0)

        assert registry.state is DiscoveryState.SCANNING
        assert list(registry.snapshot()) == ["uuid:living"]
        with pytest.raises(DiscoveryBusyError):
            await registry.scan()

        release.set()
        await running
        assert list(registry.snapshot()) == ["uuid:bedroom"]

    asyncio.run(scenario())


def test_scan_error_keeps_last_good_snapshot_and_has_typed_error():
    async def scenario():
        calls = 0

        async def discover():
            nonlocal calls
            calls += 1
            if calls == 1:
                return [target()]
            raise TimeoutError("network address and token must not leak")

        registry = TargetDiscoveryRegistry(
            discover,
            clock=lambda: NOW + timedelta(seconds=calls),
        )
        await registry.scan()

        with pytest.raises(TimeoutError):
            await registry.scan()

        assert registry.state is DiscoveryState.ERROR
        assert registry.error_code == "SCAN_TIMEOUT"
        assert list(registry.snapshot()) == ["uuid:living"]
        assert "network address" not in repr(registry.status())

    asyncio.run(scenario())
