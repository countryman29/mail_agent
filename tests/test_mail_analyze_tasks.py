from email.message import EmailMessage

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
