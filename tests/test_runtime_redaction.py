from miair.runtime.redaction import (
    project_location_host,
    redact_event_details,
    redact_network_addresses,
)


def test_location_projection_keeps_only_host():
    assert project_location_host(
        "http://192.168.133.132:1958/device.xml?access_token=secret"
    ) == "192.168.133.132"
    assert project_location_host("not a URL") == ""


def test_event_details_are_allowlisted_and_remove_secrets_and_query_strings():
    details = redact_event_details(
        {
            "media_format": "audio/mpeg",
            "output_adapter": "DLNAOutputAdapter",
            "stream_url": "http://192.168.133.225:8200/media/live.wav?token=secret",
            "client_address": "192.168.133.225",
            "cookie": "userId=123; passToken=secret",
            "password": "secret",
            "nested": {"passToken": "secret"},
        }
    )

    assert details == {
        "media_format": "audio/mpeg",
        "output_adapter": "DLNAOutputAdapter",
        "stream_url": "http://<local-address>:8200/media/live.wav",
        "client_address": "<local-address>",
    }
    assert "secret" not in repr(details)
    assert "passToken" not in repr(details)


def test_redaction_bounds_values_and_rejects_unregistered_fields():
    details = redact_event_details(
        {
            "reason": "x" * 600,
            "volume_percent": 38,
            "arbitrary": "must not be copied",
        }
    )

    assert len(details["reason"]) == 256
    assert details["volume_percent"] == 38
    assert "arbitrary" not in details


def test_network_redaction_removes_ipv4_ipv6_and_scoped_ipv6_literals():
    redacted = redact_network_addresses(
        "peers 192.168.133.225, [2001:db8::5], fe80::a%en0 at 12:30:00"
    )

    assert redacted == (
        "peers <local-address>, <local-address>, <local-address> at 12:30:00"
    )
