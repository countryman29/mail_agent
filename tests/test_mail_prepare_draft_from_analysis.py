import json
from pathlib import Path

import pytest

import mail_prepare_draft_from_analysis as prepare
from mail_signature import OUTGOING_SIGNATURE


def test_prepare_draft_from_task_markdown_creates_simple_draft(tmp_path):
    source = tmp_path / "tasks" / "shipment_update_thread.md"
    source.parent.mkdir()
    source.write_text(
        """# Задача по ветке

**Тема ветки:** Shipment Update
**To:** logistics@example.com
**Cc:** ops@example.com

## Recommendation
Сверить номер рейса, дату вылета и статус AWB.
""",
        encoding="utf-8",
    )

    draft_path = prepare.prepare_draft_from_markdown(source, drafts_dir=tmp_path / "drafts")

    assert draft_path == tmp_path / "drafts" / "shipment_update_thread_draft.md"
    assert draft_path.read_text(encoding="utf-8") == """SUBJECT: Re: Shipment Update
TO: logistics@example.com
CC: ops@example.com
BODY:
Здравствуйте.

Черновик подготовлен на основе файла: shipment_update_thread.md

Рекомендация:
Сверить номер рейса, дату вылета и статус AWB.

Best Regards,
Anton Vasilev
Procurement Director
METAHIM LLC.
tel.: +79217766880 (Tel./WhatsApp)
tel.: +74951907375 ext. 103
WeChat: +66918201426
"""


def test_build_reply_draft_uses_message_subject_before_thread_subject():
    text = """# Анализ письма

**Subject:** Original Subject
**Тема:** Invoice Update
**Тема ветки:** Shipment Update

## Recommendation
Проверить инвойс.
"""

    draft = prepare.build_reply_draft(Path("analysis.md"), text)

    assert draft.startswith("SUBJECT: Re: Original Subject\n")
    assert "Проверить инвойс." in draft


def test_build_reply_draft_uses_russian_message_subject_before_thread_subject():
    text = """# Анализ письма

**Тема:** Invoice Update
**Тема ветки:** Shipment Update
"""

    draft = prepare.build_reply_draft(Path("analysis.md"), text)

    assert draft.startswith("SUBJECT: Re: Invoice Update\n")


def test_extract_draft_metadata_reads_from_to_cc_and_subject():
    metadata = prepare.extract_draft_metadata(
        """**From:** sender@example.com
**To:** anton@example.com
**Cc:** copy@example.com
**Subject:** Shipment Update
"""
    )

    assert metadata == {
        "from": "sender@example.com",
        "to": "anton@example.com",
        "cc": "copy@example.com",
        "subject": "Shipment Update",
    }


def test_extract_draft_metadata_supports_russian_aliases():
    metadata = prepare.extract_draft_metadata(
        """**От:** sender@example.com
**Кому:** anton@example.com
**Копия:** copy@example.com
**Тема:** Shipment Update
"""
    )

    assert metadata == {
        "from": "sender@example.com",
        "to": "anton@example.com",
        "cc": "copy@example.com",
        "subject": "Shipment Update",
    }


def test_build_reply_draft_uses_fallbacks_for_missing_fields():
    draft = prepare.build_reply_draft(Path("empty.md"), "")

    assert "SUBJECT: Re: [no subject]" in draft
    assert "\nTO:\nCC:\n" in draft
    assert "Проверить переписку и подготовить ответ." in draft
    assert OUTGOING_SIGNATURE in draft


def test_main_prints_created_draft_path(monkeypatch, tmp_path, capsys):
    source = tmp_path / "analysis.md"
    source.write_text("**Тема:** Test\n", encoding="utf-8")
    monkeypatch.setattr(prepare, "DRAFTS_DIR", tmp_path / "drafts")

    draft_path = prepare.main(str(source))

    assert draft_path == tmp_path / "drafts" / "analysis_draft.md"
    assert f"Draft created: {draft_path}" in capsys.readouterr().out


def test_main_requires_source_path():
    with pytest.raises(SystemExit, match="Source path is required"):
        prepare.main(argv=[])


def test_main_default_dry_run_does_not_write_file(monkeypatch, tmp_path, capsys):
    source = tmp_path / "analysis.md"
    source.write_text("**Тема:** Test\n", encoding="utf-8")
    output_dir = tmp_path / "drafts"
    monkeypatch.setattr(prepare, "DRAFTS_DIR", output_dir)
    monkeypatch.setattr(prepare, "load_safe_config", lambda *args, **kwargs: ({}, {"automation_mode": False}))

    result = prepare.main(argv=[str(source)])

    expected_draft = output_dir / "analysis_draft.md"
    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["no_send"] is True
    assert result["readonly"] is True
    assert result["human_review_required"] is True
    assert result["output_paths"] == [str(expected_draft)]
    assert not expected_draft.exists()
    assert "Dry run: draft not created. Would create:" in capsys.readouterr().out


def test_main_real_run_writes_draft_file(monkeypatch, tmp_path, capsys):
    source = tmp_path / "analysis.md"
    source.write_text("**Тема:** Test\n", encoding="utf-8")
    output_dir = tmp_path / "drafts"
    monkeypatch.setattr(prepare, "load_safe_config", lambda *args, **kwargs: ({}, {"automation_mode": False}))

    result = prepare.main(argv=[str(source), "--real-run", "--output-dir", str(output_dir)])

    expected_draft = output_dir / "analysis_draft.md"
    assert result["status"] == "ok"
    assert result["dry_run"] is False
    assert expected_draft.exists()
    assert expected_draft.read_text(encoding="utf-8").startswith("SUBJECT: Re: Test\n")
    assert f"Draft created: {expected_draft}" in capsys.readouterr().out


def test_main_json_output(monkeypatch, tmp_path, capsys):
    source = tmp_path / "analysis.md"
    source.write_text("**Тема:** Test\n", encoding="utf-8")
    monkeypatch.setattr(prepare, "load_safe_config", lambda *args, **kwargs: ({}, {"automation_mode": False}))

    result = prepare.main(argv=[str(source), "--output-json"])

    captured = capsys.readouterr().out.strip()
    parsed = json.loads(captured)
    assert parsed == result
    assert parsed["status"] == "ok"
    assert parsed["dry_run"] is True


def test_main_fails_for_invalid_source_path(monkeypatch):
    monkeypatch.setattr(prepare, "load_safe_config", lambda *args, **kwargs: ({}, {"automation_mode": False}))

    with pytest.raises(SystemExit, match="Source file not found"):
        prepare.main(argv=["/tmp/definitely-missing-analysis.md"])


def test_main_fails_for_invalid_extension(monkeypatch, tmp_path):
    source = tmp_path / "analysis.json"
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(prepare, "load_safe_config", lambda *args, **kwargs: ({}, {"automation_mode": False}))

    with pytest.raises(SystemExit, match="supported extensions"):
        prepare.main(argv=[str(source)])


def test_script_has_no_imap_or_smtp_imports():
    script_text = Path(prepare.__file__).read_text(encoding="utf-8")

    assert "import imaplib" not in script_text
    assert "import smtplib" not in script_text
    assert "IMAP4_SSL" not in script_text
    assert "SMTP_SSL" not in script_text

