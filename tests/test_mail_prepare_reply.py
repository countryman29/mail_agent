from email.message import EmailMessage
from pathlib import Path

import pytest

import mail_prepare_reply as prepare
import mail_send_reply as send
from mail_signature import OUTGOING_SIGNATURE


class FakePrepareMail:
    def __init__(self, messages):
        self.messages = messages
        self.logged_in = []

    def login(self, username, password):
        self.logged_in.append((username, password))

    def select(self, folder):
        self.selected = folder
        return "OK", [b""]

    def search(self, charset, query):
        return "OK", [b" ".join(str(i).encode() for i in sorted(self.messages))]

    def fetch(self, message_id, parts):
        message_num = int(message_id.decode())
        return "OK", [(b"RFC822", self.messages[message_num])]

    def logout(self):
        self.logged_out = True


def make_raw_message(subject: str, date_value: str, from_value: str = "sender@example.com") -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["Date"] = date_value
    msg["From"] = from_value
    msg.set_content("Hello")
    return msg.as_bytes()


def test_main_generates_canonical_draft_shape(monkeypatch, tmp_path):
    target_subject = "Thread subject"
    fake_mail = FakePrepareMail(
        {
            1: make_raw_message("Other thread", "Mon, 01 Jan 2024 09:00:00 +0000"),
            2: make_raw_message(target_subject, "Mon, 01 Jan 2024 10:00:00 +0000"),
        }
    )

    monkeypatch.setattr(prepare, "IMAP_HOST", "imap.example.com")
    monkeypatch.setattr(prepare, "EMAIL_USERNAME", "sender@example.com")
    monkeypatch.setattr(prepare, "EMAIL_PASSWORD", "secret")
    monkeypatch.setattr(prepare, "TARGET_FOLDER", "INBOX/Elcon")
    monkeypatch.setattr(prepare, "TARGET_THREAD_SUBJECT", target_subject)
    monkeypatch.setattr(prepare, "DRAFTS_DIR", tmp_path)
    monkeypatch.setattr(prepare.imaplib, "IMAP4_SSL", lambda host, port: fake_mail)

    prepare.main()

    draft_files = list(tmp_path.rglob("*_draft.md"))
    assert len(draft_files) == 1
    draft_text = draft_files[0].read_text(encoding="utf-8")

    assert send.extract_subject(draft_text) == "Re: Thread subject"
    assert send.extract_thread_subject_from_draft(draft_text) == "Thread subject"
    assert send.extract_body(draft_text).startswith("Dear Shiven,")
    assert OUTGOING_SIGNATURE in send.extract_body(draft_text)
    assert "## Body" in draft_text
    assert "## Draft reply in English" not in draft_text


def test_build_draft_content_requires_thread_subject_metadata_and_canonical_body():
    latest, draft_text = prepare.build_draft_content(
        [
            {
                "subject": "Thread subject",
                "from": "sender@example.com",
                "date_display": "2024-01-01 10:00",
                "date_folder": "2024-01-01",
                "sort_ts": 1,
            }
        ],
        "INBOX/Elcon",
        "Thread subject",
    )

    assert latest["date_folder"] == "2024-01-01"
    assert "**Тема ветки:** Thread subject" in draft_text
    assert "**Subject:** Re: Thread subject" in draft_text
    assert "\n## Body\n" in draft_text
    assert OUTGOING_SIGNATURE in draft_text


def test_main_fails_clearly_when_thread_is_not_found(monkeypatch, tmp_path):
    fake_mail = FakePrepareMail({1: make_raw_message("Different subject", "Mon, 01 Jan 2024 10:00:00 +0000")})

    monkeypatch.setattr(prepare, "IMAP_HOST", "imap.example.com")
    monkeypatch.setattr(prepare, "EMAIL_USERNAME", "sender@example.com")
    monkeypatch.setattr(prepare, "EMAIL_PASSWORD", "secret")
    monkeypatch.setattr(prepare, "TARGET_FOLDER", "INBOX/Elcon")
    monkeypatch.setattr(prepare, "TARGET_THREAD_SUBJECT", "Missing subject")
    monkeypatch.setattr(prepare, "DRAFTS_DIR", tmp_path)
    monkeypatch.setattr(prepare.imaplib, "IMAP4_SSL", lambda host, port: fake_mail)

    with pytest.raises(RuntimeError, match="Thread not found"):
        prepare.main()


def test_build_draft_content_fails_clearly_when_generated_body_is_empty(monkeypatch):
    monkeypatch.setattr(prepare, "build_ru_draft", lambda: "   ")

    with pytest.raises(ValueError, match="Generated draft body is empty"):
        prepare.build_draft_content(
            [
                {
                    "subject": "Thread subject",
                    "from": "sender@example.com",
                    "date_display": "2024-01-01 10:00",
                    "date_folder": "2024-01-01",
                    "sort_ts": 1,
                }
            ],
            "INBOX/Elcon",
            "Thread subject",
        )
