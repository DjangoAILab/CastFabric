from datetime import datetime, timedelta, timezone

from miair.runtime.events import ActivityEventJournal
from miair.runtime.models import EventOutcome, IngressProtocol
from miair.content.repository import ContentRepository


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


def test_event_cursor_returns_older_items_in_stable_order():
    ticks = iter(NOW + timedelta(seconds=i) for i in range(4))
    ids = iter(["event-1", "event-2", "event-3", "event-4"])
    journal = ActivityEventJournal(
        clock=lambda: next(ticks),
        id_factory=lambda: next(ids),
    )
    for _ in range(4):
        journal.append(
            target_id="uuid:living",
            type="session.control",
            outcome=EventOutcome.SUCCESS,
            summary_key="activity.control",
        )

    first_page = journal.query(limit=2)
    second_page = journal.query(limit=2, cursor=first_page[-1].id)

    assert [event.id for event in first_page] == ["event-4", "event-3"]
    assert [event.id for event in second_page] == ["event-2", "event-1"]
    assert journal.get("event-2").id == "event-2"


def test_new_events_persist_to_sqlite_and_never_append_legacy_jsonl(tmp_path):
    repository = ContentRepository(tmp_path / "castfabric.sqlite3", clock=lambda: NOW)
    legacy = tmp_path / "activity.jsonl"
    legacy.write_text('{"legacy":true}\n', encoding="utf-8")
    journal = ActivityEventJournal(
        repository=repository,
        path=legacy,
        clock=lambda: NOW,
        id_factory=lambda: "event-sqlite",
    )

    journal.append(
        target_id="uuid:living",
        protocol=IngressProtocol.MCP,
        type="session.started",
        outcome=EventOutcome.SUCCESS,
        summary_key="activity.session_started",
        details={"url": "https://example.test/audio?token=secret"},
    )

    assert legacy.read_text(encoding="utf-8") == '{"legacy":true}\n'
    persisted = repository.query_events(limit=10)
    assert persisted[0]["id"] == "event-sqlite"
    assert "secret" not in repr(persisted)
    repository.close()
