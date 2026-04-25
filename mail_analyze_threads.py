from pathlib import Path
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
LIMIT = 100


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


def clean_subject(subject: str) -> str:
    if not subject:
        return "[no subject]"
    s = subject.strip()
    s = re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def slugify(name: str) -> str:
    name = clean_subject(name).lower()
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:120]


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


def short_text(text, limit=500):
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def load_state():
    if not STATE_PATH.exists():
        return {"processed_message_ids": [], "processed_thread_keys": []}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def detect_open_questions(full_text: str):
    text = full_text.lower()
    questions = []

    checks = [
        ("awb", "Проверить AWB / статус авианакладной"),
        ("flight", "Проверить рейс и маршрут"),
        ("shipment", "Проверить текущий статус отгрузки"),
        ("custom clearance", "Проверить статус таможенного оформления"),
        ("please find the attachment", "Проверить комплектность приложенных документов"),
        ("confirm", "Требуется подтверждение от контрагента"),
        ("not arrived", "Груз не прибыл, нужно выяснить статус"),
        ("photos", "Проверить фото товара / упаковки"),
        ("invoice", "Проверить инвойс"),
        ("pl", "Проверить packing list"),
    ]

    for needle, label in checks:
        if needle in text:
            questions.append(label)

    result = []
    for q in questions:
        if q not in result:
            result.append(q)
    return result


def detect_thread_status(full_text: str):
    text = full_text.lower()

    if "not arrived" in text:
        return "Есть вопрос по фактическому прибытию груза"
    if "custom clearance" in text:
        return "Груз находится в процессе оформления / движения"
    if "flight schedule" in text or "today night is the flight" in text:
        return "Есть подтверждение рейса / отправки"
    if "please approve" in text:
        return "Ожидается согласование документов"
    if "please find the attachment" in text:
        return "Получены документы / вложения"
    return "Требуется ручная оценка статуса"


def detect_urgency(full_text: str):
    text = full_text.lower()
    if any(x in text for x in ["urgent", "asap", "immediately", "not arrived", "today"]):
        return "Высокая"
    if any(x in text for x in ["confirm", "awb", "flight", "shipment"]):
        return "Средняя"
    return "Низкая"


def build_recommendation(status_text: str, open_questions: list[str]):
    if "не прибыл" in status_text.lower():
        return "Подготовить письмо с требованием уточнить фактический статус груза, местонахождение и подтверждение движения по AWB."
    if any("документ" in q.lower() for q in open_questions):
        return "Проверить вложения и подтвердить, что комплект документов полный и корректный."
    if any("рейс" in q.lower() for q in open_questions):
        return "Сверить номер рейса, дату вылета и статус AWB."
    if any("подтверждение" in q.lower() for q in open_questions):
        return "Направить краткий follow-up с запросом явного подтверждения."
    return "Просмотреть ветку и решить, нужен ли ответ или задача закрыта."


def company_from_folder(folder: str):
    if "/" in folder:
        return folder.split("/")[-1]
    return folder


def render_thread_analysis_outputs(
    company_name: str,
    target_folder: str,
    subject: str,
    items: list[dict],
    status_text: str,
    open_questions: list[str],
    recommendation: str,
    urgency: str,
) -> tuple[str, str]:
    latest = items[-1]
    chronology = "\n".join(
        [
            f"- {x['date_display']} | {x['from']} | {clean_subject(x['subject'])}"
            for x in items
        ]
    )

    previews = "\n\n".join(
        [
            f"### Письмо {x['id']}\n**Дата:** {x['date_display']}\n**От:** {x['from']}\n**Кратко:** {x['body_preview']}"
            for x in items
        ]
    )

    q_block = "\n".join([f"- {q}" for q in open_questions]) if open_questions else "- Явные открытые вопросы не выявлены"
    needs_task = "Да" if open_questions or urgency in ("Высокая", "Средняя") else "Нет"

    analysis_content = f"""# Анализ ветки переписки

**Контрагент:** {company_name}  
**Папка:** {target_folder}  
**Тема ветки:** {subject}  
**Сообщений в ветке:** {len(items)}  
**Последнее письмо:** {latest['date_display']}  

## Хронология
{chronology}

## Текущий статус
{status_text}

## Открытые вопросы
{q_block}

## Рекомендация
{recommendation}

## Срочность
{urgency}

## Письма в ветке
{previews}
"""

    task_content = f"""# Задача по ветке переписки

**Контрагент:** {company_name}  
**Тема ветки:** {subject}  
**Последнее письмо:** {latest['date_display']}  

## Текущий вопрос
{q_block}

## Статус
{status_text}

## Что рекомендует агент
{recommendation}

## Срочность
{urgency}

## Требуется участие Антона
{needs_task}
"""

    return analysis_content, task_content


def main():
    print("DEBUG ENV PATH =", ENV_PATH)
    print("DEBUG IMAP_HOST =", repr(IMAP_HOST))
    print("DEBUG EMAIL_USERNAME =", repr(EMAIL_USERNAME))

    if not IMAP_HOST or not EMAIL_USERNAME or not EMAIL_PASSWORD:
        raise ValueError("Проверь .env: IMAP_HOST / EMAIL_USERNAME / EMAIL_PASSWORD")

    state = load_state()
    processed_thread_keys = set(state.get("processed_thread_keys", []))

    company_name = company_from_folder(TARGET_FOLDER)

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

    ids = data[0].split()[-LIMIT:]
    threads = {}

    for num in ids:
        status, msg_data = mail.fetch(num, "(RFC822)")
        if status != "OK":
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_mime(msg.get("Subject"))
        from_ = decode_mime(msg.get("From"))
        date_raw = decode_mime(msg.get("Date"))
        body = get_text_from_message(msg)

        try:
            dt = parsedate_to_datetime(date_raw)
            sort_ts = dt.timestamp()
            date_folder = dt.strftime("%Y-%m-%d")
            date_display = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            sort_ts = 0
            date_folder = "unknown_date"
            date_display = date_raw or "unknown"

        thread_subject = clean_subject(subject)
        thread_key = slugify(thread_subject)

        item = {
            "id": num.decode(),
            "date_raw": date_raw,
            "date_display": date_display,
            "date_folder": date_folder,
            "from": from_,
            "subject": subject,
            "body": body,
            "body_preview": short_text(body),
            "sort_ts": sort_ts,
        }

        threads.setdefault(thread_key, {"subject": thread_subject, "items": []})
        threads[thread_key]["items"].append(item)

    created = 0
    new_thread_keys = set()

    for thread_key, payload in threads.items():
        if thread_key in processed_thread_keys:
            continue

        items = sorted(payload["items"], key=lambda x: x["sort_ts"])
        subject = payload["subject"]

        latest = items[-1]
        latest_date_folder = latest["date_folder"]

        full_text = "\n\n".join(
            [
                f"[{x['date_display']}] FROM: {x['from']}\nSUBJECT: {x['subject']}\n{x['body']}"
                for x in items
            ]
        )

        open_questions = detect_open_questions(full_text)
        status_text = detect_thread_status(full_text)
        urgency = detect_urgency(full_text)
        recommendation = build_recommendation(status_text, open_questions)

        analysis_path = ANALYSIS_DIR / company_name / latest_date_folder
        task_path = TASKS_DIR / company_name / latest_date_folder
        analysis_path.mkdir(parents=True, exist_ok=True)
        task_path.mkdir(parents=True, exist_ok=True)

        analysis_file = analysis_path / f"{thread_key}_thread.md"
        task_file = task_path / f"{thread_key}_thread.md"

        analysis_content, task_content = render_thread_analysis_outputs(
            company_name=company_name,
            target_folder=TARGET_FOLDER,
            subject=subject,
            items=items,
            status_text=status_text,
            open_questions=open_questions,
            recommendation=recommendation,
            urgency=urgency,
        )

        with open(analysis_file, "w", encoding="utf-8") as f:
            f.write(analysis_content)

        with open(task_file, "w", encoding="utf-8") as f:
            f.write(task_content)

        print("THREAD ANALYZED:", analysis_file)
        print("THREAD TASK:", task_file)

        new_thread_keys.add(thread_key)
        created += 1

    mail.logout()

    state["processed_thread_keys"] = sorted(set(state.get("processed_thread_keys", [])) | new_thread_keys)
    save_state(state)

    print("\nDone.")
    print("Threads analyzed:", created)
    print("State file:", STATE_PATH)


if __name__ == "__main__":
    main()
