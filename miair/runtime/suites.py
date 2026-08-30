"""Per-output Receiver Suite registry and lifecycle transactions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Awaitable, Callable

from miair.runtime.models import (
    IngressProtocol,
    IngressSnapshot,
    IngressState,
    OutputTargetSnapshot,
    ReceiverSuiteSnapshot,
)
from miair.runtime.redaction import project_location_host
from miair.targets import OutputTargetConfig, normalize_target_id


SuiteCallback = Callable[["ReceiverSuite"], Awaitable[None]]
_UNSET = object()


class SuiteLifecycleError(RuntimeError):
    """Typed failure returned when a suite transition cannot be completed."""

    def __init__(self, code: str, target_id: str):
        super().__init__(code)
        self.code = code
        self.target_id = target_id


@dataclass(frozen=True)
class IngressRuntime:
    protocol: IngressProtocol
    state: IngressState
    handle: Any = None
    port: int | None = None
    error_code: str | None = None

    def snapshot(self) -> IngressSnapshot:
        return IngressSnapshot(
            protocol=self.protocol,
            state=self.state,
            port=self.port,
            error_code=self.error_code,
        )


class ReceiverSuite:
    """Runtime instances belonging to one configured physical output target."""

    def __init__(
        self,
        target: OutputTargetConfig,
        controller_id: str,
        controller: Any,
        *,
        device_name_prefix: str,
    ):
        self.target = target
        self.controller_id = controller_id
        self.controller = controller
        self.device_name_prefix = device_name_prefix
        self.ingress: dict[IngressProtocol, IngressRuntime] = {}
        self.current_session_id: str | None = None
        self.last_activity_at: datetime | None = None
        # Online is an observation, not a controller-derived guess. It remains
        # unknown until a completed discovery scan supplies a value.
        self.online: bool | None = None
        self.observed_at: datetime | None = None
        self.capabilities: tuple[str, ...] = ()

    def update_observation(
        self,
        *,
        online: bool | None,
        observed_at: datetime | None,
        capabilities: tuple[str, ...] = (),
    ) -> None:
        self.online = online
        self.observed_at = observed_at
        self.capabilities = tuple(capabilities)

    def get_ingress(self, protocol: IngressProtocol) -> IngressRuntime | None:
        return self.ingress.get(protocol)

    def set_ingress(
        self,
        protocol: IngressProtocol,
        state: IngressState,
        *,
        handle: Any = _UNSET,
        port: int | None | object = _UNSET,
        error_code: str | None = None,
    ) -> IngressRuntime:
        previous = self.ingress.get(protocol)
        resolved_handle = previous.handle if previous else None
        resolved_port = previous.port if previous else None
        if handle is not _UNSET:
            resolved_handle = handle
        if port is not _UNSET:
            resolved_port = port
        runtime = IngressRuntime(
            protocol=protocol,
            state=state,
            handle=resolved_handle,
            port=resolved_port,
            error_code=error_code,
        )
        self.ingress[protocol] = runtime
        return runtime

    @property
    def health(self) -> str:
        if not self.target.enabled:
            return "disabled"
        states = {item.state for item in self.ingress.values()}
        if states & {IngressState.DEGRADED, IngressState.UNAVAILABLE}:
            return "degraded"
        if states & {IngressState.READY, IngressState.ACTIVE}:
            return "healthy"
        return "unavailable"

    def snapshot(self) -> ReceiverSuiteSnapshot:
        target = OutputTargetSnapshot(
            id=self.target.id,
            kind=self.target.kind,
            name=self.target.name,
            receiver_alias=self.target.get_receiver_alias(self.device_name_prefix),
            location_host=project_location_host(self.target.location),
            enabled=self.target.enabled,
            online=self.online,
            observed_at=self.observed_at,
            capabilities=self.capabilities,
        )
        ingress = tuple(
            self.ingress[protocol].snapshot()
            for protocol in IngressProtocol
            if protocol in self.ingress
        )
        return ReceiverSuiteSnapshot(
            target=target,
            health=self.health,
            ingress=ingress,
            current_session_id=self.current_session_id,
            last_activity_at=self.last_activity_at,
        )


class ReceiverSuiteRegistry:
    """Stable target keyed registry for independently managed receiver suites."""

    def __init__(self, *, device_name_prefix: str):
        self.device_name_prefix = device_name_prefix
        self._suites: dict[str, ReceiverSuite] = {}
        self._controller_to_target: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def register(
        self,
        target: OutputTargetConfig,
        controller_id: str,
        controller: Any,
    ) -> ReceiverSuite:
        target_id = normalize_target_id(target.id) or target.id
        existing = self._suites.get(target_id)
        if existing is not None and existing.controller_id != controller_id:
            self._controller_to_target.pop(existing.controller_id, None)
        suite = ReceiverSuite(
            target,
            controller_id,
            controller,
            device_name_prefix=self.device_name_prefix,
        )
        self._suites[target_id] = suite
        self._controller_to_target[controller_id] = target_id
        self._locks.setdefault(target_id, asyncio.Lock())
        return suite

    def get(self, target_id: str) -> ReceiverSuite | None:
        key = normalize_target_id(target_id) or target_id
        return self._suites.get(key)

    def get_by_controller_id(self, controller_id: str) -> ReceiverSuite | None:
        target_id = self._controller_to_target.get(controller_id)
        return self._suites.get(target_id) if target_id else None

    def remove(self, target_id: str) -> ReceiverSuite | None:
        key = normalize_target_id(target_id) or target_id
        suite = self._suites.pop(key, None)
        if suite is not None:
            self._controller_to_target.pop(suite.controller_id, None)
            self._locks.pop(key, None)
        return suite

    def clear(self) -> None:
        self._suites.clear()
        self._controller_to_target.clear()
        self._locks.clear()

    def set_ingress(
        self,
        target_id: str,
        protocol: IngressProtocol,
        state: IngressState,
        *,
        handle: Any = _UNSET,
        port: int | None | object = _UNSET,
        error_code: str | None = None,
    ) -> IngressRuntime:
        suite = self.get(target_id)
        if suite is None:
            raise KeyError(target_id)
        return suite.set_ingress(
            protocol,
            state,
            handle=handle,
            port=port,
            error_code=error_code,
        )

    def snapshots(self) -> tuple[ReceiverSuiteSnapshot, ...]:
        return tuple(self._suites[key].snapshot() for key in sorted(self._suites))

    def values(self) -> tuple[ReceiverSuite, ...]:
        return tuple(self._suites[key] for key in sorted(self._suites))

    async def set_enabled(
        self,
        target_id: str,
        enabled: bool,
        *,
        start: SuiteCallback,
        stop: SuiteCallback,
    ) -> ReceiverSuite:
        """Apply one suite transition and compensate any partial failure.

        Callbacks own protocol side effects. The registry restores the original
        config flag and read model even if a callback has already changed them.
        """
        suite = self.get(target_id)
        if suite is None:
            raise KeyError(target_id)
        lock = self._locks.setdefault(suite.target.id, asyncio.Lock())
        async with lock:
            old_enabled = suite.target.enabled
            if old_enabled == bool(enabled):
                return suite
            old_ingress = {
                protocol: replace(runtime)
                for protocol, runtime in suite.ingress.items()
            }
            suite.target.enabled = bool(enabled)
            action = start if enabled else stop
            compensate = stop if enabled else start
            try:
                await action(suite)
            except Exception as exc:
                try:
                    await compensate(suite)
                except Exception:
                    # The original typed transition failure is the API contract;
                    # lifecycle callers log the compensation failure separately.
                    pass
                suite.target.enabled = old_enabled
                suite.ingress = old_ingress
                code = "SUITE_ENABLE_FAILED" if enabled else "SUITE_DISABLE_FAILED"
                raise SuiteLifecycleError(code, suite.target.id) from exc
            return suite
