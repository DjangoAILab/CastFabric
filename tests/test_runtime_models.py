from datetime import datetime, timezone

from miair.runtime.models import (
    ActivityEventSnapshot,
    EventOutcome,
    IngressProtocol,
    IngressSnapshot,
    IngressState,
    MediaSessionSnapshot,
    OutputTargetSnapshot,
    ReceiverSuiteSnapshot,
    SessionSourceSnapshot,
    SessionState,
)


NOW = datetime(2026, 8, 30, 7, 0, tzinfo=timezone.utc)


def test_runtime_snapshots_have_explicit_stable_json_shapes():
    target = OutputTargetSnapshot(
        id="uuid:living",
        kind="dlna",
        name="Living speaker",
        receiver_alias="CastFabric · Living speaker",
        location_host="192.168.133.132",
        configured=True,
        enabled=True,
        online=True,
        observed_at=NOW,
        capabilities=("play", "pause", "volume"),
    )
    suite = ReceiverSuiteSnapshot(
        target=target,
        health="healthy",
        ingress=(
            IngressSnapshot(
                protocol=IngressProtocol.DLNA,
                state=IngressState.READY,
                port=8200,
            ),
            IngressSnapshot(
                protocol=IngressProtocol.MIPLAY,
                state=IngressState.ACTIVE,
                port=8899,
            ),
        ),
        current_session_id="session-1",
        last_activity_at=NOW,
    )

    payload = suite.to_dict()

    assert payload == {
        "target": {
            "id": "uuid:living",
            "kind": "dlna",
            "name": "Living speaker",
            "receiver_alias": "CastFabric · Living speaker",
            "location_host": "192.168.133.132",
            "configured": True,
            "enabled": True,
            "online": True,
            "observed_at": "2026-08-30T07:00:00+00:00",
            "capabilities": ["play", "pause", "volume"],
        },
        "health": "healthy",
        "ingress": {
            "dlna": {"state": "ready", "port": 8200, "error_code": None},
            "miplay": {"state": "active", "port": 8899, "error_code": None},
        },
        "current_session_id": "session-1",
        "last_activity_at": "2026-08-30T07:00:00+00:00",
    }


def test_session_and_event_omit_unavailable_source_app_and_latency():
    session = MediaSessionSnapshot(
        id="session-1",
        target_id="uuid:living",
        protocol=IngressProtocol.AIRPLAY,
        state=SessionState.PLAYING,
        source=SessionSourceSnapshot(
            device_name="Wang’s MacBook",
            provenance="protocol_header",
            confidence="device",
        ),
        media_format="PCM 44.1 kHz · 2 ch",
        started_at=NOW,
    )
    event = ActivityEventSnapshot(
        id="event-1",
        occurred_at=NOW,
        target_id="uuid:living",
        session_id=session.id,
        protocol=IngressProtocol.AIRPLAY,
        type="session.started",
        outcome=EventOutcome.SUCCESS,
        summary_key="activity.session_started",
        reason_code=None,
        details={"media_format": "PCM 44.1 kHz · 2 ch"},
    )

    session_payload = session.to_dict()
    event_payload = event.to_dict()

    assert session_payload["source"] == {
        "device_name": "Wang’s MacBook",
        "provenance": "protocol_header",
        "confidence": "device",
    }
    assert "app_name" not in session_payload["source"]
    assert "latency" not in repr(session_payload).lower()
    assert event_payload["outcome"] == "success"
    assert event_payload["details"] == {"media_format": "PCM 44.1 kHz · 2 ch"}


def test_ingress_error_is_typed_without_leaking_exception_text():
    ingress = IngressSnapshot(
        protocol=IngressProtocol.MIPLAY,
        state=IngressState.UNAVAILABLE,
        port=None,
        error_code="PORT_CONFLICT",
    )

    assert ingress.to_dict() == {
        "state": "unavailable",
        "port": None,
        "error_code": "PORT_CONFLICT",
    }
