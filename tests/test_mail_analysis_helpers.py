import pytest

from mail_analysis_helpers import (
    fetch_recent_rfc822_messages,
    parse_message_date_metadata,
    write_dated_analysis_outputs,
)


class FakeMail:
    def __init__(self, ids=b"1 2 3", fetch_status="OK", select_status="OK", search_status="OK"):
        self.ids = ids
        self.fetch_status = fetch_status
        self.select_status = select_status
        self.search_status = search_status
        self.selected = []
        self.fetched = []

    def select(self, folder):
        self.selected.append(folder)
        return self.select_status, [b"3"]

    def search(self, charset, criteria):
        return self.search_status, [self.ids]

    def fetch(self, message_id, query):
        self.fetched.append((message_id, query))
        if self.fetch_status != "OK":
            return self.fetch_status, []
        return "OK", [(b"RFC822", b"raw-" + message_id)]


class FakeAliasMail(FakeMail):
    def select(self, folder):
        self.selected.append(folder)
        if folder == '"Входящие/Elcon"':
            return "OK", [b"3"]
        return "NO", [b"missing"]


def test_fetch_recent_rfc822_messages_selects_folder_and_fetches_recent_slice():
    mail = FakeMail(ids=b"1 2 3 4")

    messages = fetch_recent_rfc822_messages(mail, "INBOX/Elcon", limit=2)

    assert mail.selected == ['"INBOX/Elcon"']
    assert mail.fetched == [(b"3", "(RFC822)"), (b"4", "(RFC822)")]
    assert messages == [(b"3", b"raw-3"), (b"4", b"raw-4")]


def test_fetch_recent_rfc822_messages_selects_russian_inbox_alias():
    mail = FakeAliasMail(ids=b"1")

    messages = fetch_recent_rfc822_messages(mail, "INBOX/Elcon", limit=1)

    assert mail.selected == ['"INBOX/Elcon"', '"Inbox/Elcon"', '"Входящие/Elcon"']
    assert messages == [(b"1", b"raw-1")]


def test_fetch_recent_rfc822_messages_skips_ids_before_fetch():
    mail = FakeMail(ids=b"1 2 3")

    messages = fetch_recent_rfc822_messages(mail, "INBOX/Elcon", limit=3, skip_ids={"2"})

    assert mail.fetched == [(b"1", "(RFC822)"), (b"3", "(RFC822)")]
    assert messages == [(b"1", b"raw-1"), (b"3", b"raw-3")]


def test_fetch_recent_rfc822_messages_ignores_failed_fetch():
    mail = FakeMail(ids=b"1", fetch_status="NO")

    assert fetch_recent_rfc822_messages(mail, "INBOX/Elcon", limit=1) == []


def test_fetch_recent_rfc822_messages_raises_when_folder_cannot_open():
    mail = FakeMail(select_status="NO")

    with pytest.raises(RuntimeError, match="Cannot open folder INBOX/Elcon"):
        fetch_recent_rfc822_messages(mail, "INBOX/Elcon", limit=1)


def test_fetch_recent_rfc822_messages_raises_when_search_fails():
    mail = FakeMail(search_status="NO")

    with pytest.raises(RuntimeError, match="Search failed"):
        fetch_recent_rfc822_messages(mail, "INBOX/Elcon", limit=1)


def test_write_dated_analysis_outputs_creates_directories_and_writes_files(tmp_path):
    analysis_file, task_file = write_dated_analysis_outputs(
        analysis_dir=tmp_path / "analysis",
        tasks_dir=tmp_path / "tasks",
        company_name="Elcon",
        date_folder="2026-04-25",
        filename="shipment_update_thread.md",
        analysis_content="# Analysis\nBody",
        task_content="# Task\nBody",
    )

    assert analysis_file == tmp_path / "analysis" / "Elcon" / "2026-04-25" / "shipment_update_thread.md"
    assert task_file == tmp_path / "tasks" / "Elcon" / "2026-04-25" / "shipment_update_thread.md"
    assert analysis_file.read_text(encoding="utf-8") == "# Analysis\nBody"
    assert task_file.read_text(encoding="utf-8") == "# Task\nBody"


def test_parse_message_date_metadata_returns_folder_display_and_sort_timestamp():
    metadata = parse_message_date_metadata("Sat, 25 Apr 2026 10:30:00 +0000")

    assert metadata == {
        "date_folder": "2026-04-25",
        "date_display": "2026-04-25 10:30",
        "sort_ts": 1777113000.0,
    }


def test_parse_message_date_metadata_preserves_existing_invalid_date_fallbacks():
    assert parse_message_date_metadata("not a date") == {
        "date_folder": "unknown_date",
        "date_display": "not a date",
        "sort_ts": 0,
    }
    assert parse_message_date_metadata("") == {
        "date_folder": "unknown_date",
        "date_display": "unknown",
        "sort_ts": 0,
    }
