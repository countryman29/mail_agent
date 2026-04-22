from pathlib import Path
import os
import re
import json
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
from dotenv import dotenv_values


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


def get_text_from_message(msg):
    if msg.is_multipart():
        plain_parts = []
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in disposition.lower():
                continue

            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    plain_parts.append(payload.decode(charset, errors="replace"))
        return "\n".join(plain_parts).strip()
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace").strip()
    return ""


def short_text(text, limit=1200):
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def load_state():
    if not STATE_PATH.exists():
        return {"processed_message_ids": []}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


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

    print(f"\n=== SELECT FOLDER: {TARGET_FOLDER} ===")
    status, data = mail.select(f'"{TARGET_FOLDER}"')
    print("SELECT:", status, data)
    if status != "OK":
        raise RuntimeError(f"Cannot open folder {TARGET_FOLDER}")

    status, data = mail.search(None, "ALL")
    print("SEARCH:", status)
    if status != "OK":
        raise RuntimeError("Search failed")

    ids = data[0].split()
    ids = ids[-LIMIT:]

    new_processed = set()
    analyzed_count = 0

    for num in ids:
        msg_id_local = num.decode()

        if msg_id_local in processed_ids:
            continue

        status, msg_data = mail.fetch(num, "(RFC822)")
        if status != "OK":
            continue

        raw_email = msg_data[0][1]
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

        if open_questions:
            task_block = "\n".join([f"- {q}" for q in open_questions])
            task_status = "Новая"
        else:
            task_block = "- Явные открытые вопросы не выявлены"
            task_status = "Без задачи"

        analysis_content = f"""# Анализ письма

**Контрагент:** {company_name}  
**Папка:** {TARGET_FOLDER}  
**Дата письма:** {date_display}  
**От:** {from_}  
**Тема:** {clean_subj}  
**Message-ID:** {message_id_header or msg_id_local}  
**Локальный ID:** {msg_id_local}  

## Краткая суть
{summary}

## Перевод / смысл на русском
{summary}

## Открытые вопросы
{task_block}

## Рекомендация
{recommendation}

## Срочность
{urgency}
"""

        task_content = f"""# Задача по письму

**Контрагент:** {company_name}  
**Дата письма:** {date_display}  
**Тема:** {clean_subj}  
**Локальный ID письма:** {msg_id_local}  

## Вопрос
{task_block}

## Что рекомендует агент
{recommendation}

## Срочность
{urgency}

## Статус
{task_status}
"""

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
