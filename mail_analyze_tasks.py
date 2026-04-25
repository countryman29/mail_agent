from pathlib import Path
import os
import re
import json
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
from dotenv import dotenv_values
from mail_analysis_helpers import fetch_recent_rfc822_messages, get_text_from_message, load_json_state


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
STATE_PATH = BASE_DIR / "state" / "mail_state.json"
ANALYSIS_DIR = BASE_DIR / "analysis"
TASKS_DIR = BASE_DIR / "tasks"

ENV = dotenv_values(ENV_PATH)

IMAP_HOST = ENV.get("IMAP_HOST")
IMAP_PORT = int(ENV.get("IMAP_PORT", "993"))
EMAIL_USERNAME = ENV.get("EMAIL_USERNAME")
EMAIL_PASSWORD = ENV.get("EMAIL_PASSWORD")

TARGET_FOLDER = "INBOX/Elcon"
LIMIT = 30


def decode_mime(value):
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] if len(name) > 120 else name


def slugify(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", name, flags=re.IGNORECASE)
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:80]


def clean_subject(subject: str) -> str:
    if not subject:
        return "[no subject]"
    s = subject.strip()
    s = re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def short_text(text, limit=1200):
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def load_state():
    return load_json_state(STATE_PATH, {"processed_message_ids": []})


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def detect_open_questions(text: str):
    questions = []

    patterns = [
        (r"\bconfirm\b", "Требуется подтверждение от контрагента"),
        (r"\bprovide\b", "Требуется предоставить данные / документы"),
        (r"\bflight\b", "Нужно проверить детали рейса / отправки"),
        (r"\bawb\b", "Нужно проверить авианакладную / статус AWB"),
        (r"\bshipment\b", "Нужно уточнить статус отгрузки"),
        (r"\bplease find the attachment\b", "Нужно проверить приложенные документы"),
        (r"\bcustom clearance\b", "Нужно контролировать статус таможенного оформления"),
        (r"\bnot arrived\b", "Нужно проверить, почему груз еще не прибыл"),
    ]

    lower_text = text.lower()
    for pattern, label in patterns:
        if re.search(pattern, lower_text):
            questions.append(label)

    seen = []
    for q in questions:
        if q not in seen:
            seen.append(q)
    return seen


def detect_urgency(text: str):
    lower_text = text.lower()
    if any(x in lower_text for x in ["urgent", "today", "immediately", "asap", "not arrived"]):
        return "Высокая"
    if any(x in lower_text for x in ["confirm", "provide", "flight", "awb", "shipment"]):
        return "Средняя"
    return "Низкая"


def build_recommendation(open_questions):
    if not open_questions:
        return "Явных открытых вопросов не выявлено. Проверить, требуется ли ответ."

    if any("AWB" in q or "авианаклад" in q.lower() for q in open_questions):
        return "Проверить статус AWB и при необходимости направить уточняющее письмо контрагенту."

    if any("подтверждение" in q.lower() for q in open_questions):
        return "Запросить явное подтверждение по открытому вопросу и зафиксировать ответ."

    if any("документы" in q.lower() for q in open_questions):
        return "Проверить вложения и подтвердить комплектность документов."

    return "Проверить переписку и подготовить уточняющий ответ контрагенту."


def extract_company_from_folder(folder_name: str):
    if "/" in folder_name:
        return folder_name.split("/")[-1]
    return folder_name


def render_message_analysis_outputs(
    company_name: str,
    target_folder: str,
    message_id: str,
    date_display: str,
    from_: str,
    subject: str,
    summary: str,
    body_preview: str,
    open_questions: list[str],
    recommendation: str,
    urgency: str,
) -> tuple[str, str]:
    q_block = "\n".join([f"- {q}" for q in open_questions]) if open_questions else "- Явные открытые вопросы не выявлены"
    status = "Новая" if open_questions else "Без задачи"
    needs_human = "Да" if open_questions or urgency in ("Высокая", "Средняя") else "Нет"

    analysis_content = f"""# Анализ письма

**Контрагент:** {company_name}  
**Папка:** {target_folder}  
**Message ID:** {message_id}  
**Дата:** {date_display}  
**От:** {from_}  
**Тема:** {subject}  

## Summary
{summary}

## Status
{status}

## Open Questions
{q_block}

## Recommendation
{recommendation}

## Urgency
{urgency}

## Body Preview
{body_preview or "Текст письма не извлечен."}
"""

    task_content = f"""# Задача по письму

**Контрагент:** {company_name}  
**Папка:** {target_folder}  
**Message ID:** {message_id}  
**Дата:** {date_display}  
**Тема:** {subject}  
**Срочность:** {urgency}  
**Требуется участие Антона:** {needs_human}  

## Open Questions
{q_block}

## Status
{status}

## Recommendation
{recommendation}
"""

    return analysis_content, task_content


def main():
    print("DEBUG ENV PATH =", ENV_PATH)
    print("DEBUG IMAP_HOST =", repr(IMAP_HOST))
    print("DEBUG EMAIL_USERNAME =", repr(EMAIL_USERNAME))

    if not IMAP_HOST or not EMAIL_USERNAME or not EMAIL_PASSWORD:
        raise ValueError("Проверь .env: IMAP_HOST / EMAIL_USERNAME / EMAIL_PASSWORD")

    state = load_state()
    processed_ids = set(state.get("processed_message_ids", []))

    company_name = extract_company_from_folder(TARGET_FOLDER)

    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(EMAIL_USERNAME, EMAIL_PASSWORD)

    new_processed = set()
    analyzed_count = 0

    for num, raw_email in fetch_recent_rfc822_messages(mail, TARGET_FOLDER, LIMIT, skip_ids=processed_ids):
        msg_id_local = num.decode()
        msg = email.message_from_bytes(raw_email)

        subject = decode_mime(msg.get("Subject"))
        from_ = decode_mime(msg.get("From"))
        date_raw = decode_mime(msg.get("Date"))
        message_id_header = decode_mime(msg.get("Message-ID"))
        body = get_text_from_message(msg)
        body_preview = short_text(body)

        try:
            dt = parsedate_to_datetime(date_raw)
            date_folder = dt.strftime("%Y-%m-%d")
            date_display = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_folder = "unknown_date"
            date_display = date_raw or "unknown"

        clean_subj = clean_subject(subject)
        thread_slug = slugify(clean_subj) or "no_subject"

        analysis_path = ANALYSIS_DIR / company_name / date_folder
        task_path = TASKS_DIR / company_name / date_folder

        analysis_path.mkdir(parents=True, exist_ok=True)
        task_path.mkdir(parents=True, exist_ok=True)

        analysis_file = analysis_path / f"{thread_slug}_message_{msg_id_local}.md"
        task_file = task_path / f"{thread_slug}_message_{msg_id_local}.md"

        open_questions = detect_open_questions(body)
        urgency = detect_urgency(body)
        recommendation = build_recommendation(open_questions)

        summary = body_preview if body_preview else "Текст письма не извлечен."

        analysis_content, task_content = render_message_analysis_outputs(
            company_name=company_name,
            target_folder=TARGET_FOLDER,
            message_id=message_id_header or msg_id_local,
            date_display=date_display,
            from_=from_,
            subject=clean_subj,
            summary=summary,
            body_preview=body_preview,
            open_questions=open_questions,
            recommendation=recommendation,
            urgency=urgency,
        )

        with open(analysis_file, "w", encoding="utf-8") as f:
            f.write(analysis_content)

        with open(task_file, "w", encoding="utf-8") as f:
            f.write(task_content)

        print("ANALYZED:", analysis_file)
        print("TASK:", task_file)

        new_processed.add(msg_id_local)
        analyzed_count += 1

    mail.logout()

    if new_processed:
        processed_ids.update(new_processed)
        state["processed_message_ids"] = sorted(processed_ids, key=lambda x: int(x) if x.isdigit() else x)
        save_state(state)

    print("\nDone.")
    print("New analyzed messages:", analyzed_count)
    print("State file:", STATE_PATH)


if __name__ == "__main__":
    main()
