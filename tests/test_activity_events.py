from datetime import datetime, timedelta, timezone

from miair.runtime.events import ActivityEventJournal
from miair.runtime.models import EventOutcome, IngressProtocol


NOW = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)


def test_event_journal_is_bounded_filterable_and_redacted():
    ticks = iter(NOW + timedelta(seconds=i) for i in range(4))
    journal = ActivityEventJournal(max_events=3, clock=lambda: next(ticks))
    for index in range(4):
        journal.append(
            target_id="uuid:living" if index < 3 else "uuid:bedroom",
            protocol=IngressProtocol.MIPLAY,
            type="session.control",
            outcome=EventOutcome.SUCCESS if index != 2 else EventOutcome.FAILED,
            summary_key="activity.control",
            details={
                "stream_url": "http://192.168.1.2/live?token=secret",
                "cookie": "passToken=secret",
            },
        )

    assert len(journal.query()) == 3
    assert len(journal.query(target_id="uuid:living")) == 2
    assert len(journal.query(outcome=EventOutcome.FAILED)) == 1
    assert "secret" not in repr([event.to_dict() for event in journal.query()])


def test_event_file_failure_degrades_journal_without_losing_memory_event(tmp_path):
    impossible = tmp_path / "missing" / "activity.jsonl"
    journal = ActivityEventJournal(path=impossible, clock=lambda: NOW)

    event = journal.append(
        target_id="uuid:living",
        protocol=IngressProtocol.DLNA,
        type="session.started",
        outcome=EventOutcome.SUCCESS,
        summary_key="activity.session_started",
    )

    assert journal.degraded is True
    assert journal.query()[0].id == event.id
