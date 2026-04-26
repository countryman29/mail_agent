import json
from email.message import EmailMessage

import mail_analyze_tasks
import mail_analyze_threads


class FakeIMAP:
    def __init__(self, messages):
        self.messages = messages
        self.logged_in = False
        self.logged_out = False

    def login(self, username, password):
        self.logged_in = True

    def select(self, folder, readonly=None):
        self.selected_folder = folder
        self.selected_readonly = readonly
        return "OK", [str(len(self.messages)).encode()]

    def search(self, charset, criteria):
        ids = b" ".join(str(message_id).encode() for message_id in sorted(self.messages))
        return "OK", [ids]

    def fetch(self, message_id, query):
        key = int(message_id.decode())
        return "OK", [(b"RFC822", self.messages[key])]

    def logout(self):
        self.logged_out = True


def make_raw_message(subject: str, message_id: str, body: str, date: str, from_addr="sender@example.com"):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Date"] = date
    msg["From"] = from_addr
    msg.set_content(body)
    return msg.as_bytes()


def configure_analysis_module(monkeypatch, module, tmp_path, fake_imap):
    monkeypatch.setattr(module, "IMAP_HOST", "imap.example.com")
    monkeypatch.setattr(module, "EMAIL_USERNAME", "user@example.com")
    monkeypatch.setattr(module, "EMAIL_PASSWORD", "secret")
    monkeypatch.setattr(module, "TARGET_FOLDER", "INBOX/Elcon")
    monkeypatch.setattr(module, "STATE_PATH", tmp_path / "state" / "mail_state.json")
    monkeypatch.setattr(module, "ANALYSIS_DIR", tmp_path / "analysis")
    monkeypatch.setattr(module, "TASKS_DIR", tmp_path / "tasks")
    if hasattr(module, "load_safe_config"):
        monkeypatch.setattr(
            module,
            "load_safe_config",
            lambda command_type=None: (
                {
                    "IMAP_HOST": "imap.example.com",
                    "IMAP_PORT": "993",
                    "EMAIL_USERNAME": "user@example.com",
                    "EMAIL_PASSWORD": "secret",
                },
                {"automation_mode": False},
            ),
        )
    monkeypatch.setattr(module.imaplib, "IMAP4_SSL", lambda host, port: fake_imap)


def test_mail_analyze_tasks_main_creates_outputs_and_updates_state(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message(
                subject="Invoice Update",
                message_id="<message-1@example.com>",
                body="Please confirm AWB shipment.",
                date="Sat, 25 Apr 2026 10:00:00 +0000",
            )
        }
    )
    configure_analysis_module(monkeypatch, mail_analyze_tasks, tmp_path, fake_imap)

    result = mail_analyze_tasks.main(argv=["--real-run"])

    analysis_files = list((tmp_path / "analysis").rglob("*.md"))
    task_files = list((tmp_path / "tasks").rglob("*.md"))
    state = json.loads((tmp_path / "state" / "mail_state.json").read_text(encoding="utf-8"))

    assert len(analysis_files) == 1
    assert len(task_files) == 1
    assert "# Анализ письма" in analysis_files[0].read_text(encoding="utf-8")
    assert "# Задача по письму" in task_files[0].read_text(encoding="utf-8")
    assert state["processed_message_ids"] == ["1"]
    assert result == 1
    assert fake_imap.logged_in is True
    assert fake_imap.logged_out is True


def test_mail_analyze_threads_main_creates_outputs_and_updates_state(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message(
                subject="Re: Shipment Update",
                message_id="<message-1@example.com>",
                body="Please confirm AWB shipment.",
                date="Sat, 25 Apr 2026 10:00:00 +0000",
            ),
            2: make_raw_message(
                subject="Shipment Update",
                message_id="<message-2@example.com>",
                body="Flight schedule attached.",
                date="Sat, 25 Apr 2026 11:00:00 +0000",
            ),
        }
    )
    configure_analysis_module(monkeypatch, mail_analyze_threads, tmp_path, fake_imap)

    result = mail_analyze_threads.main()

    analysis_files = list((tmp_path / "analysis").rglob("*.md"))
    task_files = list((tmp_path / "tasks").rglob("*.md"))
    state = json.loads((tmp_path / "state" / "mail_state.json").read_text(encoding="utf-8"))

    assert len(analysis_files) == 1
    assert len(task_files) == 1
    assert "# Анализ ветки" in analysis_files[0].read_text(encoding="utf-8")
    assert "# Задача по ветке" in task_files[0].read_text(encoding="utf-8")
    assert state["processed_thread_keys"] == ["shipment_update"]
    assert result == 1
    assert fake_imap.logged_in is True
    assert fake_imap.logged_out is True
