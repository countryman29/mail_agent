from pathlib import Path
import re
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
DRAFTS_DIR = BASE_DIR / "drafts"

ENV = dotenv_values(ENV_PATH)

IMAP_HOST = ENV.get("IMAP_HOST")
IMAP_PORT = int(ENV.get("IMAP_PORT", "993"))
EMAIL_USERNAME = ENV.get("EMAIL_USERNAME")
EMAIL_PASSWORD = ENV.get("EMAIL_PASSWORD")

TARGET_FOLDER = "INBOX/Elcon"
TARGET_THREAD_SUBJECT = "Shipment Documents - ED/EX/26-27/49 ( LLC Metahim) - SSI Transit 68"
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
        return ""
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


def short_text(text, limit=700):
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def build_ru_summary(items):
    return """Поставщик направил revised/final shipment documents по Transit 68, сообщил, что груз находился под customs clearance, затем прислал final AWB invoice и flight schedule DEL-SVO via SU233 on 21-Apr. При этом ранее с нашей стороны уже был поднят вопрос, что груз по AWB не прибыл, поэтому по ветке остается незакрытым вопрос фактического движения и подтверждения прибытия груза."""


def build_ru_action_needed(items):
    return """Нужно запросить у Elcon четкое подтверждение:
1. что груз фактически вылетел;
2. что AWB активен и отслеживается;
3. где груз находится сейчас;
4. ожидаемую дату фактического прибытия / приема в Москве."""


def build_ru_draft():
    return """Dear Shiven,
Dear Elcon Dispatch Team,

Good day.

Thank you for the documents and flight information.

However, we still need your clear confirmation on the actual current shipment status, because the cargo has not yet been received by us and the AWB status still requires verification.

Please kindly confirm the following:

1. Has the shipment physically departed?
2. Is AWB No. 555-48502753 active and traceable in the airline system?
3. What is the current actual location of the cargo now?
4. What is the expected actual arrival / handling status in Moscow?

Also, please confirm that the final shipping documents previously sent are the latest valid versions.

We will appreciate your urgent clarification.

Best Regards,
Anton Vasilev
Procurement Director
METAHIM LLC
"""


def build_ru_internal_note():
    return """Логика ответа:
- не спорим;
- не повторяем длинную историю;
- фиксируем, что документы получили;
- ключевой вопрос — фактический статус груза и живая отслеживаемость AWB;
- просим четкое подтверждение без лишних обсуждений."""


def build_ru_version():
    return """Добрый день.

Спасибо за документы и информацию по рейсу.

Однако нам все еще нужно четкое подтверждение фактического текущего статуса груза, поскольку груз нами пока не получен, а статус AWB требует дополнительной проверки.

Просим подтвердить:

1. был ли груз фактически отправлен;
2. активна ли авианакладная AWB No. 555-48502753 и отслеживается ли она в системе авиаперевозчика;
3. где груз находится в настоящий момент;
4. какова ожидаемая фактическая дата прибытия / обработки груза в Москве.

Также просим подтвердить, что ранее направленные финальные отгрузочные документы являются актуальными и окончательными версиями.
"""


def main():
    print("DEBUG ENV PATH =", ENV_PATH)
    print("DEBUG IMAP_HOST =", repr(IMAP_HOST))
    print("DEBUG EMAIL_USERNAME =", repr(EMAIL_USERNAME))

    if not IMAP_HOST or not EMAIL_USERNAME or not EMAIL_PASSWORD:
        raise ValueError("Проверь .env: IMAP_HOST / EMAIL_USERNAME / EMAIL_PASSWORD")

    target_clean = clean_subject(TARGET_THREAD_SUBJECT)

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
    items = []

    for num in ids:
        status, msg_data = mail.fetch(num, "(RFC822)")
        if status != "OK":
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_mime(msg.get("Subject"))
        subject_clean = clean_subject(subject)

        if subject_clean != target_clean:
            continue

        from_ = decode_mime(msg.get("From"))
        date_raw = decode_mime(msg.get("Date"))
        body = get_text_from_message(msg)

        try:
            dt = parsedate_to_datetime(date_raw)
            date_display = dt.strftime("%Y-%m-%d %H:%M")
            date_folder = dt.strftime("%Y-%m-%d")
            sort_ts = dt.timestamp()
        except Exception:
            date_display = date_raw
            date_folder = "unknown_date"
            sort_ts = 0

        items.append({
            "id": num.decode(),
            "subject": subject,
            "from": from_,
            "date_display": date_display,
            "date_folder": date_folder,
            "body": body,
            "body_preview": short_text(body),
            "sort_ts": sort_ts,
        })

    mail.logout()

    if not items:
        print("Thread not found.")
        return

    items.sort(key=lambda x: x["sort_ts"])
    latest = items[-1]

    out_dir = DRAFTS_DIR / "Elcon" / latest["date_folder"]
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = slugify(TARGET_THREAD_SUBJECT) + "_draft.md"
    out_file = out_dir / filename

    chronology = "\n".join(
        f"- {x['date_display']} | {x['from']} | {clean_subject(x['subject'])}"
        for x in items
    )

    content = f"""# Черновик ответа по ветке

**Контрагент:** Elcon  
**Папка:** {TARGET_FOLDER}  
**Тема ветки:** {TARGET_THREAD_SUBJECT}  
**Последнее письмо:** {latest['date_display']}  
**Сообщений в ветке:** {len(items)}  

## Краткая выжимка по-русски
{build_ru_summary(items)}

## Что требуется решить
{build_ru_action_needed(items)}

## Хронология
{chronology}

## Проект ответа на русском
{build_ru_version()}

## Draft reply in English
{build_ru_draft()}

## Внутренняя заметка
{build_ru_internal_note()}
"""

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(content)

    print("DRAFT CREATED:", out_file)


if __name__ == "__main__":
    main()
