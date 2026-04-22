import importlib
from email.message import EmailMessage
from pathlib import Path

import pytest

import mail_send_reply as send


class FakeThreadMail:
    def __init__(self, search_ids, raw_message):
        self.search_ids = search_ids
        self.raw_message = raw_message
        self.selected = []
        self.fetched = []

    def select(self, folder, readonly=False):
        self.selected.append((folder, readonly))
        return "OK", [b""]

    def search(self, charset, query):
        self.search_call = (charset, query)
        return "OK", [self.search_ids]

    def fetch(self, message_id, parts):
        self.fetched.append((message_id, parts))
        return "OK", [(b"RFC822", self.raw_message)]


class FakeIMAPContext:
    def __init__(self):
        self.login_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def login(self, username, password):
        self.login_calls.append((username, password))


def reload_send_module(monkeypatch):
    monkeypatch.delenv("MAIL_SEND_FOR_REAL", raising=False)
    return importlib.reload(send)


def make_raw_message(message_id=None):
    msg = EmailMessage()
    msg["Subject"] = "Thread subject"
    if message_id is not None:
        msg["Message-ID"] = message_id
    msg.set_content("hello")
    return msg.as_bytes()


def write_thread_reply_draft(tmp_path: Path, subject: str) -> Path:
    draft = tmp_path / "thread_reply.md"
    draft.write_text(
        f"Subject: {subject}\n"
        "**Тема ветки:** Thread subject\n\n"
        "## Body\n"
        "Reply text.\n",
        encoding="utf-8",
    )
    return draft


def test_read_latest_incoming_message_for_thread_uses_last_matching_message():
    mail = FakeThreadMail(b"1 4 9", make_raw_message("<latest@example.com>"))

    message_id, original_msg = send.read_latest_incoming_message_for_thread(
        mail,
        "INBOX/Elcon",
        "Thread subject",
    )

    assert message_id == "<latest@example.com>"
    assert original_msg.get("Message-ID") == "<latest@example.com>"
    assert mail.selected == [('"INBOX/Elcon"', True)]
    assert mail.fetched == [(b"9", "(RFC822)")]


def test_read_latest_incoming_message_for_thread_fails_without_message_id():
    mail = FakeThreadMail(b"7", make_raw_message())

    with pytest.raises(RuntimeError, match="Message-ID"):
        send.read_latest_incoming_message_for_thread(mail, "INBOX", "Thread subject")


def test_read_latest_incoming_message_for_thread_reports_actionable_not_found_error():
    mail = FakeThreadMail(b"", make_raw_message("<latest@example.com>"))

    with pytest.raises(RuntimeError, match="MAIL_TARGET_FOLDER") as exc_info:
        send.read_latest_incoming_message_for_thread(mail, "INBOX/Elcon", "Thread subject")

    message = str(exc_info.value)
    assert "Thread subject" in message
    assert "INBOX/Elcon" in message
    assert "**Тема ветки:**" in message


def test_main_thread_reply_fails_when_cleaned_to_is_empty(monkeypatch, tmp_path):
    send_mod = reload_send_module(monkeypatch)
    draft_path = write_thread_reply_draft(tmp_path, "Need update")

    monkeypatch.setattr(send_mod, "IMAP_HOST", "imap.example.com")
    monkeypatch.setattr(send_mod, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(send_mod, "EMAIL_USERNAME", "sender@example.com")
    monkeypatch.setattr(send_mod, "EMAIL_PASSWORD", "secret")
    monkeypatch.setattr(send_mod, "DRAFT_FILE", draft_path)
    monkeypatch.setattr(send_mod.imaplib, "IMAP4_SSL", lambda host, port: FakeIMAPContext())
    monkeypatch.setattr(send_mod, "read_latest_incoming_message_for_thread", lambda *args, **kwargs: ("<orig@example.com>", EmailMessage()))
    monkeypatch.setattr(send_mod, "extract_reply_recipients", lambda msg: (["sender@example.com"], ["cc@example.com"]))
    monkeypatch.setattr(send_mod, "build_references_header", lambda msg: ("<orig@example.com>", "<ref@example.com>"))

    with pytest.raises(ValueError, match="To пуст"):
        send_mod.main()


@pytest.mark.parametrize(
    ("draft_subject", "expected_subject"),
    [
        ("Need update", "Re: Need update"),
        ("Re: Need update", "Re: Need update"),
    ],
)
def test_main_thread_reply_normalizes_re_subject(monkeypatch, tmp_path, draft_subject, expected_subject):
    send_mod = reload_send_module(monkeypatch)
    draft_path = write_thread_reply_draft(tmp_path, draft_subject)
    captured = {}

    monkeypatch.setattr(send_mod, "IMAP_HOST", "imap.example.com")
    monkeypatch.setattr(send_mod, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(send_mod, "EMAIL_USERNAME", "sender@example.com")
    monkeypatch.setattr(send_mod, "EMAIL_PASSWORD", "secret")
    monkeypatch.setattr(send_mod, "DRAFT_FILE", draft_path)
    monkeypatch.setattr(send_mod.imaplib, "IMAP4_SSL", lambda host, port: FakeIMAPContext())
    monkeypatch.setattr(send_mod, "read_latest_incoming_message_for_thread", lambda *args, **kwargs: ("<orig@example.com>", EmailMessage()))
    monkeypatch.setattr(send_mod, "extract_reply_recipients", lambda msg: (["user@example.com"], []))
    monkeypatch.setattr(send_mod, "build_references_header", lambda msg: ("<orig@example.com>", "<ref@example.com>"))

    def fake_build_reply_message(subject, body, to_emails, cc_emails, in_reply_to, references):
        captured["subject"] = subject
        msg = EmailMessage()
        msg.set_content(body)
        return msg

    monkeypatch.setattr(send_mod, "build_reply_message", fake_build_reply_message)

    send_mod.main()

    assert captured["subject"] == expected_subject
