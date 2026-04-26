from email.message import EmailMessage
import json
from pathlib import Path

import mail_analyze_threads as analyze


def test_clean_subject_removes_reply_prefixes_and_normalizes_whitespace():
    assert analyze.clean_subject(" Re: FW:  Shipment   Update ") == "Shipment Update"
    assert analyze.clean_subject("") == "[no subject]"


def test_slugify_uses_clean_lowercase_safe_filename():
    assert analyze.slugify("Re: Shipment / Update: A?") == "shipment___update__a_"


def test_short_text_collapses_whitespace_and_truncates():
    assert analyze.short_text("one\n\n two\tthree", limit=20) == "one two three"
    assert analyze.short_text("abcdef", limit=3) == "abc..."


def test_get_text_from_message_extracts_plain_text_message():
    msg = EmailMessage()
    msg.set_content("Hello plain text\n")

    assert analyze.get_text_from_message(msg) == "Hello plain text"


def test_get_text_from_message_joins_plain_text_parts_and_skips_attachments():
    msg = EmailMessage()
    msg.set_content("First part")
    msg.add_alternative("<p>HTML</p>", subtype="html")
    msg.add_attachment("Attachment text", filename="note.txt")

    assert analyze.get_text_from_message(msg) == "First part"


def test_get_text_from_message_extracts_html_when_plain_text_is_missing():
    msg = EmailMessage()
    msg.set_content("<html><body><p>Hello <b>HTML</b></p><br>Next&nbsp;line</body></html>", subtype="html")

    assert analyze.get_text_from_message(msg) == "Hello HTML Next line"


def test_load_state_returns_default_for_missing_or_corrupt_state(monkeypatch, tmp_path):
    missing_state = tmp_path / "missing.json"
    monkeypatch.setattr(analyze, "STATE_PATH", missing_state)
    assert analyze.load_state() == {"processed_message_ids": [], "processed_thread_keys": []}

    corrupt_state = tmp_path / "mail_state.json"
    corrupt_state.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(analyze, "STATE_PATH", corrupt_state)
    assert analyze.load_state() == {"processed_message_ids": [], "processed_thread_keys": []}


def test_detect_open_questions_deduplicates_keyword_matches():
    questions = analyze.detect_open_questions(
        "Please confirm the shipment and confirm AWB status. Please find the attachment."
    )

    assert questions == [
        "Проверить AWB / статус авианакладной",
        "Проверить текущий статус отгрузки",
        "Проверить комплектность приложенных документов",
        "Требуется подтверждение от контрагента",
        "Проверить packing list",
    ]


def test_detect_urgency_current_keyword_behavior():
    assert analyze.detect_urgency("urgent shipment update") == "Высокая"
    assert analyze.detect_urgency("please confirm AWB") == "Средняя"
    assert analyze.detect_urgency("FYI only") == "Низкая"


def test_build_recommendation_current_priority_order():
    assert analyze.build_recommendation("Груз не прибыл", []) == (
        "Подготовить письмо с требованием уточнить фактический статус груза, местонахождение и подтверждение движения по AWB."
    )
    assert analyze.build_recommendation("Статус", ["Проверить комплектность приложенных документов"]) == (
        "Проверить вложения и подтвердить, что комплект документов полный и корректный."
    )
    assert analyze.build_recommendation("Статус", ["Сверить рейс"]) == "Сверить номер рейса, дату вылета и статус AWB."
    assert analyze.build_recommendation("Статус", ["Требуется подтверждение"]) == (
        "Направить краткий follow-up с запросом явного подтверждения."
    )
    assert analyze.build_recommendation("Статус", []) == "Просмотреть ветку и решить, нужен ли ответ или задача закрыта."


def test_render_thread_analysis_outputs_uses_canonical_markdown_schema():
    items = [
        {
            "id": "12",
            "date_display": "2026-04-25 10:00",
            "from": "sender@example.com",
            "subject": "Re: Shipment Update",
            "body_preview": "Cargo update preview",
        }
    ]

    analysis_content, task_content = analyze.render_thread_analysis_outputs(
        company_name="Elcon",
        target_folder="INBOX/Elcon",
        subject="Shipment Update",
        thread_key="shipment_update",
        items=items,
        status_text="Требуется ручная оценка статуса",
        open_questions=["Проверить AWB / статус авианакладной"],
        recommendation="Сверить номер рейса, дату вылета и статус AWB.",
        urgency="Средняя",
    )

    assert analysis_content.startswith("# Анализ ветки")
    assert "**Контрагент:** Elcon" in analysis_content
    assert "**Папка:** INBOX/Elcon" in analysis_content
    assert "**Тема ветки:** Shipment Update" in analysis_content
    assert "**Thread key:** shipment_update" in analysis_content
    assert "**Сообщений:** 1" in analysis_content
    assert "**Первое письмо:** 2026-04-25 10:00" in analysis_content
    assert "**Последнее письмо:** 2026-04-25 10:00" in analysis_content
    assert "## Summary\nCargo update preview" in analysis_content
    assert "## Status\nТребуется ручная оценка статуса" in analysis_content
    assert "## Open Questions\n- Проверить AWB / статус авианакладной" in analysis_content
    assert "## Recommendation\nСверить номер рейса, дату вылета и статус AWB." in analysis_content
    assert "## Urgency\nСредняя" in analysis_content
    assert "- 2026-04-25 10:00 | sender@example.com | Shipment Update" in analysis_content
    assert "### Message 12" in analysis_content
    assert "**Date:** 2026-04-25 10:00" in analysis_content
    assert "**From:** sender@example.com" in analysis_content
    assert "**Subject:** Shipment Update" in analysis_content

    assert task_content.startswith("# Задача по ветке")
    assert "**Папка:** INBOX/Elcon" in task_content
    assert "**Срочность:** Средняя" in task_content
    assert "**Требуется участие Антона:** Да" in task_content
    assert "## Open Questions\n- Проверить AWB / статус авианакладной" in task_content
    assert "## Status\nТребуется ручная оценка статуса" in task_content
    assert "## Recommendation\nСверить номер рейса, дату вылета и статус AWB." in task_content


class FakeIMAP:
    def __init__(self, messages):
        self.messages = messages
        self.logged_in = False
        self.logged_out = False
        self.selected_folder = None
        self.selected_readonly = None
        self.search_called = False

    def login(self, username, password):
        self.logged_in = True

    def select(self, folder, readonly=None):
        self.selected_folder = folder
        self.selected_readonly = readonly
        return "OK", [str(len(self.messages)).encode()]

    def search(self, charset, criteria):
        self.search_called = True
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


def configure_runtime(monkeypatch, tmp_path, fake_imap):
    monkeypatch.setattr(analyze, "TARGET_FOLDER", "INBOX/Elcon")
    monkeypatch.setattr(analyze, "STATE_PATH", tmp_path / "state" / "mail_state.json")
    monkeypatch.setattr(analyze, "ANALYSIS_DIR", tmp_path / "analysis")
    monkeypatch.setattr(analyze, "TASKS_DIR", tmp_path / "tasks")
    monkeypatch.setattr(
        analyze,
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
    monkeypatch.setattr(analyze.imaplib, "IMAP4_SSL", lambda host, port: fake_imap)


def test_main_cli_folder_and_limit_override(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message("Re: Shipment Update", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
            2: make_raw_message("Shipment Update", "<m2@example.com>", "Body two", "Sat, 25 Apr 2026 11:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    result = analyze.main(argv=["--folder", "INBOX/Test", "--limit", "1"])

    assert result == 1
    assert fake_imap.selected_readonly is True
    assert "INBOX/Test" in (fake_imap.selected_folder or "")


def test_main_readonly_flag_can_be_disabled(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message("Shipment Update", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    analyze.main(argv=["--readwrite", "--limit", "1"])

    assert fake_imap.selected_readonly is False


def test_main_default_dry_run_does_not_create_outputs_or_state(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message("Shipment Update", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    result = analyze.main(argv=["--limit", "1"])

    assert result == 1
    assert list((tmp_path / "analysis").rglob("*.md")) == []
    assert list((tmp_path / "tasks").rglob("*.md")) == []
    assert not (tmp_path / "state" / "mail_state.json").exists()


def test_main_real_run_creates_outputs_and_updates_state(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message("Shipment Update", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    result = analyze.main(argv=["--limit", "1", "--real-run"])

    assert result == 1
    assert len(list((tmp_path / "analysis").rglob("*.md"))) == 1
    assert len(list((tmp_path / "tasks").rglob("*.md"))) == 1
    state = json.loads((tmp_path / "state" / "mail_state.json").read_text(encoding="utf-8"))
    assert state["processed_thread_keys"] == ["shipment_update"]


def test_main_real_run_no_state_write_skips_state(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message("Shipment Update", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    result = analyze.main(argv=["--limit", "1", "--real-run", "--no-state-write"])

    assert result == 1
    assert len(list((tmp_path / "analysis").rglob("*.md"))) == 1
    assert len(list((tmp_path / "tasks").rglob("*.md"))) == 1
    assert not (tmp_path / "state" / "mail_state.json").exists()


def test_main_output_json_emits_valid_result(monkeypatch, tmp_path, capsys):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message("Shipment Update", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    result = analyze.main(argv=["--output-json", "--limit", "1"])

    parsed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert result["status"] == "ok"
    assert parsed["status"] == "ok"
    assert parsed["command"] == "mail_analyze_threads"
    assert parsed["dry_run"] is True
    assert parsed["no_send"] is True
    assert parsed["readonly"] is True
    assert parsed["counts"]["threads_analyzed"] == 1
    assert "Dry run enabled: analysis/task files were not written" in parsed["warnings"]
    assert "Dry run enabled: state file was not updated" in parsed["warnings"]
    assert len(parsed["output_paths"]) == 2
    assert list((tmp_path / "analysis").rglob("*.md")) == []
    assert list((tmp_path / "tasks").rglob("*.md")) == []
    assert not (tmp_path / "state" / "mail_state.json").exists()


def test_script_has_no_smtp_send_imports_or_calls():
    script_text = Path(analyze.__file__).read_text(encoding="utf-8")

    assert "import smtplib" not in script_text
    assert "SMTP_SSL" not in script_text
    assert "send_message" not in script_text
    assert "sendmail" not in script_text
