import pytest

from mail_analysis_helpers import fetch_recent_rfc822_messages


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


def test_fetch_recent_rfc822_messages_selects_folder_and_fetches_recent_slice():
    mail = FakeMail(ids=b"1 2 3 4")

    messages = fetch_recent_rfc822_messages(mail, "INBOX/Elcon", limit=2)

    assert mail.selected == ['"INBOX/Elcon"']
    assert mail.fetched == [(b"3", "(RFC822)"), (b"4", "(RFC822)")]
    assert messages == [(b"3", b"raw-3"), (b"4", b"raw-4")]


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
