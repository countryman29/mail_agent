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


def test_main_requires_source_path(monkeypatch):
    monkeypatch.setattr(prepare.sys, "argv", ["mail_prepare_draft_from_analysis.py"])

    with pytest.raises(SystemExit, match="Usage:"):
        prepare.main()
