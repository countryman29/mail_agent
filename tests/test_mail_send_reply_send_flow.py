import importlib
from pathlib import Path

import mail_send_reply as send


class FakeAppendMail:
    def __init__(self, lines=None, append_result=("OK", [b"APPENDUID 1 1"]), append_error=None):
        self._lines = lines or []
        self._append_result = append_result
        self._append_error = append_error
        self.append_calls = []

    def list(self):
        return "OK", self._lines

    def append(self, folder, flags, internal_date, raw_bytes):
        self.append_calls.append((folder, flags, internal_date, raw_bytes))
        if self._append_error is not None:
            raise self._append_error
        return self._append_result


class FakeSMTP:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.login_calls = []
        self.send_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def login(self, username, password):
        self.login_calls.append((username, password))

    def send_message(self, msg, from_addr=None, to_addrs=None):
        self.send_calls.append((msg, from_addr, to_addrs))


class FakeIMAPContext:
    def __init__(self):
        self.login_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def login(self, username, password):
        self.login_calls.append((username, password))


def reload_send_module(monkeypatch, send_for_real=None):
    if send_for_real is None:
        monkeypatch.delenv("MAIL_SEND_FOR_REAL", raising=False)
    else:
        monkeypatch.setenv("MAIL_SEND_FOR_REAL", send_for_real)
    return importlib.reload(send)


def write_manual_draft(tmp_path: Path) -> Path:
    draft = tmp_path / "manual_draft.md"
    draft.write_text(
        "Subject: Minimal test\n"
        "To: user@example.com\n\n"
        "## Body\n"
        "Hello from tests.\n",
        encoding="utf-8",
    )
    return draft


def test_append_to_sent_appends_once_to_selected_folder():
    mail = FakeAppendMail(
        lines=[
            b'(\\HasNoChildren) "/" "Sent"',
            b'(\\HasNoChildren \\Sent) "/" "Sent Items"',
        ]
    )

    saved_folder = send.append_to_sent(mail, b"raw message")

    assert saved_folder == "Sent Items"
    assert len(mail.append_calls) == 1
    assert mail.append_calls[0][0] == '"Sent Items"'


def test_append_to_sent_returns_none_when_append_fails():
    mail = FakeAppendMail(
        lines=[b'(\\HasNoChildren \\Sent) "/" "Sent"'],
        append_result=("NO", [b"permission denied"]),
    )

    saved_folder = send.append_to_sent(mail, b"raw message")

    assert saved_folder is None
    assert len(mail.append_calls) == 1


def test_main_dry_run_does_not_call_smtp_by_default(monkeypatch, tmp_path):
    send_mod = reload_send_module(monkeypatch, send_for_real=None)
    draft_path = write_manual_draft(tmp_path)

    monkeypatch.setattr(send_mod, "IMAP_HOST", "imap.example.com")
    monkeypatch.setattr(send_mod, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(send_mod, "EMAIL_USERNAME", "sender@example.com")
    monkeypatch.setattr(send_mod, "EMAIL_PASSWORD", "secret")
    monkeypatch.setattr(send_mod, "DRAFT_FILE", draft_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("SMTP must not be called during dry run")

    monkeypatch.setattr(send_mod.smtplib, "SMTP_SSL", fail_if_called)

    send_mod.main()


def test_main_calls_smtp_only_when_mail_send_for_real_enabled(monkeypatch, tmp_path):
    send_mod = reload_send_module(monkeypatch, send_for_real="1")
    draft_path = write_manual_draft(tmp_path)
    smtp_instances = []
    imap_instances = []

    monkeypatch.setattr(send_mod, "IMAP_HOST", "imap.example.com")
    monkeypatch.setattr(send_mod, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(send_mod, "EMAIL_USERNAME", "sender@example.com")
    monkeypatch.setattr(send_mod, "EMAIL_PASSWORD", "secret")
    monkeypatch.setattr(send_mod, "DRAFT_FILE", draft_path)
    monkeypatch.setattr(send_mod, "save_sent_log", lambda *args, **kwargs: Path("sent/fake.txt"))
    monkeypatch.setattr(send_mod, "append_to_sent", lambda mail, raw_bytes: "Sent")

    def smtp_factory(host, port):
        instance = FakeSMTP(host, port)
        smtp_instances.append(instance)
        return instance

    def imap_factory(host, port):
        instance = FakeIMAPContext()
        imap_instances.append(instance)
        return instance

    monkeypatch.setattr(send_mod.smtplib, "SMTP_SSL", smtp_factory)
    monkeypatch.setattr(send_mod.imaplib, "IMAP4_SSL", imap_factory)

    send_mod.main()

    assert len(smtp_instances) == 1
    assert smtp_instances[0].login_calls == [("sender@example.com", "secret")]
    assert len(smtp_instances[0].send_calls) == 1
    assert smtp_instances[0].send_calls[0][1] == "sender@example.com"
    assert smtp_instances[0].send_calls[0][2] == ["user@example.com"]
    assert len(imap_instances) == 1
    assert imap_instances[0].login_calls == [("sender@example.com", "secret")]
