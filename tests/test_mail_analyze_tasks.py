from email.message import EmailMessage
import json
from pathlib import Path

import mail_analyze_tasks as analyze


def test_clean_subject_removes_reply_prefixes_and_normalizes_whitespace():
    assert analyze.clean_subject(" Re: FWD:  Invoice   Update ") == "Invoice Update"
    assert analyze.clean_subject("") == "[no subject]"


def test_slugify_uses_clean_lowercase_safe_filename():
    assert analyze.slugify("Re: Invoice / Update: A?") == "invoice___update__a_"


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
    assert analyze.load_state() == {"processed_message_ids": []}

    corrupt_state = tmp_path / "mail_state.json"
    corrupt_state.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(analyze, "STATE_PATH", corrupt_state)
    assert analyze.load_state() == {"processed_message_ids": []}


def test_detect_open_questions_current_keyword_behavior():
    questions = analyze.detect_open_questions(
        "Please confirm the shipment and provide AWB. Please find the attachment."
    )

    assert questions == [
        "Требуется подтверждение от контрагента",
        "Требуется предоставить данные / документы",
        "Нужно проверить авианакладную / статус AWB",
        "Нужно уточнить статус отгрузки",
        "Нужно проверить приложенные документы",
    ]


def test_detect_urgency_current_keyword_behavior():
    assert analyze.detect_urgency("urgent shipment update") == "Высокая"
    assert analyze.detect_urgency("please confirm AWB") == "Средняя"
    assert analyze.detect_urgency("FYI only") == "Низкая"


def test_build_recommendation_current_priority_order():
    assert analyze.build_recommendation([]) == "Явных открытых вопросов не выявлено. Проверить, требуется ли ответ."
    assert analyze.build_recommendation(["Нужно проверить авианакладную / статус AWB"]) == (
        "Проверить статус AWB и при необходимости направить уточняющее письмо контрагенту."
    )
    assert analyze.build_recommendation(["Требуется подтверждение от контрагента"]) == (
        "Запросить явное подтверждение по открытому вопросу и зафиксировать ответ."
    )
    assert analyze.build_recommendation(["Нужно проверить приложенные документы"]) == (
        "Проверить вложения и подтвердить комплектность документов."
    )
    assert analyze.build_recommendation(["Нужно уточнить статус отгрузки"]) == (
        "Проверить переписку и подготовить уточняющий ответ контрагенту."
    )


def test_render_message_analysis_outputs_uses_canonical_markdown_schema():
    analysis_content, task_content = analyze.render_message_analysis_outputs(
        company_name="Elcon",
        target_folder="INBOX/Elcon",
        message_id="<message@example.com>",
        date_display="2026-04-25 10:00",
        from_="sender@example.com",
        subject="Invoice Update",
        summary="Body summary",
        body_preview="Body preview",
        open_questions=["Нужно проверить авианакладную / статус AWB"],
        recommendation="Проверить статус AWB и при необходимости направить уточняющее письмо контрагенту.",
        urgency="Средняя",
    )

    assert analysis_content.startswith("# Анализ письма")
    assert "**Контрагент:** Elcon" in analysis_content
    assert "**Папка:** INBOX/Elcon" in analysis_content
    assert "**Message ID:** <message@example.com>" in analysis_content
    assert "**Дата:** 2026-04-25 10:00" in analysis_content
    assert "**От:** sender@example.com" in analysis_content
    assert "**Тема:** Invoice Update" in analysis_content
    assert "## Summary\nBody summary" in analysis_content
    assert "## Status\nНовая" in analysis_content
    assert "## Open Questions\n- Нужно проверить авианакладную / статус AWB" in analysis_content
    assert "## Recommendation\nПроверить статус AWB" in analysis_content
    assert "## Urgency\nСредняя" in analysis_content
    assert "## Body Preview\nBody preview" in analysis_content

    assert task_content.startswith("# Задача по письму")
    assert "**Папка:** INBOX/Elcon" in task_content
    assert "**Message ID:** <message@example.com>" in task_content
    assert "**Срочность:** Средняя" in task_content
    assert "**Требуется участие Антона:** Да" in task_content
    assert "## Open Questions\n- Нужно проверить авианакладную / статус AWB" in task_content
    assert "## Status\nНовая" in task_content
    assert "## Recommendation\nПроверить статус AWB" in task_content


def test_render_message_analysis_outputs_marks_no_human_action_when_no_questions():
    analysis_content, task_content = analyze.render_message_analysis_outputs(
        company_name="Elcon",
        target_folder="INBOX/Elcon",
        message_id="42",
        date_display="unknown",
        from_="sender@example.com",
        subject="FYI",
        summary="Текст письма не извлечен.",
        body_preview="",
        open_questions=[],
        recommendation="Явных открытых вопросов не выявлено. Проверить, требуется ли ответ.",
        urgency="Низкая",
    )

    assert "## Status\nБез задачи" in analysis_content
    assert "## Body Preview\nТекст письма не извлечен." in analysis_content
    assert "**Требуется участие Антона:** Нет" in task_content
    assert "## Open Questions\n- Явные открытые вопросы не выявлены" in task_content


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
            1: make_raw_message("S1", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
            2: make_raw_message("S2", "<m2@example.com>", "Body two", "Sat, 25 Apr 2026 11:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    result = analyze.main(argv=["--folder", "INBOX/Test", "--limit", "1", "--real-run"])

    assert result == 1
    assert fake_imap.selected_readonly is True
    assert "INBOX/Test" in (fake_imap.selected_folder or "")
    analysis_files = list((tmp_path / "analysis").rglob("*.md"))
    assert len(analysis_files) == 1


def test_main_no_state_write_does_not_write_state_file(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message("S1", "<m1@example.com>", "Please confirm shipment", "Sat, 25 Apr 2026 10:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    result = analyze.main(argv=["--no-state-write"])

    assert result == 1
    assert not (tmp_path / "state" / "mail_state.json").exists()


def test_main_default_dry_run_does_not_create_analysis_or_task_files(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message("S1", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    result = analyze.main(argv=["--limit", "1"])

    assert result == 1
    assert list((tmp_path / "analysis").rglob("*.md")) == []
    assert list((tmp_path / "tasks").rglob("*.md")) == []
    assert not (tmp_path / "state" / "mail_state.json").exists()


def test_main_real_run_creates_analysis_and_task_files(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message("S1", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    result = analyze.main(argv=["--limit", "1", "--real-run"])

    assert result == 1
    assert len(list((tmp_path / "analysis").rglob("*.md"))) == 1
    assert len(list((tmp_path / "tasks").rglob("*.md"))) == 1
    assert (tmp_path / "state" / "mail_state.json").exists()


def test_main_real_run_no_state_write_does_not_create_state_file(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message("S1", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
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
            1: make_raw_message("S1", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    result = analyze.main(argv=["--output-json", "--limit", "1"])

    parsed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert result["status"] == "ok"
    assert parsed["status"] == "ok"
    assert parsed["command"] == "mail_analyze_tasks"
    assert parsed["dry_run"] is True
    assert parsed["no_send"] is True
    assert parsed["readonly"] is True
    assert parsed["counts"]["messages_analyzed"] == 1
    assert "Dry run enabled: analysis/task files were not written" in parsed["warnings"]
    assert "Dry run enabled: state file was not updated" in parsed["warnings"]
    assert len(parsed["output_paths"]) == 2
    assert list((tmp_path / "analysis").rglob("*.md")) == []
    assert list((tmp_path / "tasks").rglob("*.md")) == []


def test_main_readonly_flag_can_be_disabled(monkeypatch, tmp_path):
    fake_imap = FakeIMAP(
        {
            1: make_raw_message("S1", "<m1@example.com>", "Body one", "Sat, 25 Apr 2026 10:00:00 +0000"),
        }
    )
    configure_runtime(monkeypatch, tmp_path, fake_imap)

    analyze.main(argv=["--readwrite", "--limit", "1"])

    assert fake_imap.selected_readonly is False


def test_script_has_no_smtp_imports_or_send_calls():
    script_text = Path(analyze.__file__).read_text(encoding="utf-8")

    assert "import smtplib" not in script_text
    assert "SMTP_SSL" not in script_text
    assert "send_message" not in script_text
