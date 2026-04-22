from pathlib import Path
import re
import imaplib
import smtplib
from datetime import datetime, timezone
from email import message_from_bytes
from email.message import EmailMessage
from email.header import decode_header
from email.utils import getaddresses, formatdate, make_msgid
from dotenv import dotenv_values


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
ENV = dotenv_values(ENV_PATH)

# ===== ENV =====
IMAP_HOST = ENV.get("IMAP_HOST")
IMAP_PORT = int(ENV.get("IMAP_PORT", "993"))
SMTP_HOST = ENV.get("SMTP_HOST")
SMTP_PORT = int(ENV.get("SMTP_PORT", "465"))
EMAIL_USERNAME = ENV.get("EMAIL_USERNAME")
EMAIL_PASSWORD = ENV.get("EMAIL_PASSWORD")

# ===== НАСТРОЙКИ =====
DRAFT_FILE = BASE_DIR / "drafts" / "test_vasanton.md"
TARGET_FOLDER = "INBOX"

# True = только проверка, без реальной отправки
# False = реальная отправка
DRY_RUN = False

SENT_LOG_DIR = BASE_DIR / "sent"
SENT_LOG_DIR.mkdir(parents=True, exist_ok=True)


def decode_mime_words(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded).strip()


def sanitize_header(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[\r\n]+", " ", str(value)).strip()


def quote_imap_folder(folder_name: str) -> str:
    escaped = folder_name.replace("\\", "\\\\").replace('"', r"\"")
    return f'"{escaped}"'


def extract_section(text: str, header: str) -> str:
    pattern = rf"(?ms)^##\s+{re.escape(header)}\s*\n(.*?)(?=^##\s+|\Z)"
    m = re.search(pattern, text)
    if not m:
        raise ValueError(f"Не найден раздел '## {header}' в draft-файле")
    return m.group(1).strip()


def extract_subject(text: str) -> str:
    m = re.search(r"(?mi)^\*\*Subject:\*\*\s*(.+?)\s*$", text)
    if m:
        return sanitize_header(m.group(1))

    m = re.search(r"(?mi)^Subject:\s*(.+?)\s*$", text)
    if m:
        return sanitize_header(m.group(1))

    raise ValueError("Не найдена строка 'Subject:' или '**Subject:**' в draft-файле")


def extract_simple_field(text: str, field_name: str) -> str:
    patterns = [
        rf"(?mi)^\*\*{re.escape(field_name)}:\*\*\s*(.*?)\s*$",
        rf"(?mi)^{re.escape(field_name)}:\s*(.*?)\s*$",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return m.group(1).strip()
    return ""


def parse_emails_from_line(value: str) -> list[str]:
    if not value:
        return []
    parsed = getaddresses([value])
    result = []
    for _, email_addr in parsed:
        email_addr = sanitize_header(email_addr)
        if email_addr:
            result.append(email_addr)
    return result


def clean_email_list(emails: list[str]) -> list[str]:
    cleaned = []
    seen = set()

    for item in emails:
        value = sanitize_header(item).strip()

        if not value:
            continue
        if value in {"**", "*", "-", "—"}:
            continue
        if "@" not in value:
            continue

        value_lower = value.lower()
        if value_lower == EMAIL_USERNAME.lower():
            continue

        if value_lower not in seen:
            cleaned.append(value)
            seen.add(value_lower)

    return cleaned


def extract_to_emails(text: str) -> list[str]:
    raw = extract_simple_field(text, "To")
    return clean_email_list(parse_emails_from_line(raw))


def extract_cc_emails(text: str) -> list[str]:
    raw = extract_simple_field(text, "Cc")
    return clean_email_list(parse_emails_from_line(raw))


def extract_body(text: str) -> str:
    for header in ["Body", "BODY", "Message", "Draft reply in English"]:
        try:
            return extract_section(text, header)
        except ValueError:
            pass
    raise ValueError("Не найден раздел '## Body' в draft-файле")


def extract_thread_subject_from_draft(text: str) -> str:
    patterns = [
        r'(?mi)^\*\*Тема ветки:\*\*\s*(.+?)\s*$',
        r'(?mi)^Тема ветки:\s*(.+?)\s*$',
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return sanitize_header(m.group(1))
    raise ValueError("Не найдена строка '**Тема ветки:** ...' в draft-файле")


def read_latest_incoming_message_for_thread(mail, folder: str, thread_subject: str):
    status, _ = mail.select(quote_imap_folder(folder), readonly=True)
    if status != "OK":
        raise RuntimeError(f"Не удалось открыть папку {folder}")

    subject_escaped = thread_subject.replace('"', "")
    status, data = mail.search(None, f'(HEADER Subject "{subject_escaped}")')
    if status != "OK":
        raise RuntimeError("Не удалось выполнить IMAP SEARCH по теме")

    raw_ids = data[0].split() if data and data[0] else []
    if not raw_ids:
        raise RuntimeError(f"Во входящих не найдено письмо по теме: {thread_subject}")

    latest_id = raw_ids[-1]
    status, msg_data = mail.fetch(latest_id, "(RFC822)")
    if status != "OK" or not msg_data or not msg_data[0]:
        raise RuntimeError("Не удалось прочитать последнее письмо ветки")

    raw_bytes = msg_data[0][1]
    original_msg = message_from_bytes(raw_bytes)

    message_id = sanitize_header(original_msg.get("Message-ID"))
    if not message_id:
        raise RuntimeError("В исходном письме отсутствует Message-ID")

    print("THREAD MESSAGE ID =", latest_id.decode(errors="replace"))
    print("ORIGINAL MESSAGE-ID =", message_id)

    return message_id, original_msg


def extract_reply_recipients(original_msg):
    from_header = sanitize_header(original_msg.get("From"))
    to_header = sanitize_header(original_msg.get("To"))
    cc_header = sanitize_header(original_msg.get("Cc"))

    from_addrs = [email for _, email in getaddresses([from_header]) if email]
    to_addrs = [email for _, email in getaddresses([to_header]) if email]
    cc_addrs = [email for _, email in getaddresses([cc_header]) if email]

    final_to = clean_email_list(from_addrs)
    final_cc = clean_email_list(to_addrs + cc_addrs)

    return final_to, final_cc


def resolve_all_sent_folders(mail) -> list[str]:
    status, data = mail.list()
    if status != "OK" or not data:
        print("DEBUG MAILBOXES = []")
        return []

    mailbox_names = []

    for raw_line in data:
        if not raw_line:
            continue

        line = raw_line.decode("utf-8", errors="replace")
        name = None

        parts = line.split(' "/" ')
        if len(parts) >= 2:
            name = parts[-1].strip().strip('"')
        else:
            parts = line.split(' "." ')
            if len(parts) >= 2:
                name = parts[-1].strip().strip('"')
            else:
                m = re.search(r'"([^"]+)"\s*$', line)
                if m:
                    name = m.group(1).strip()

        if name:
            mailbox_names.append(name)

    print("DEBUG MAILBOXES =", mailbox_names)

    preferred_exact = [
        "Sent",
        "INBOX.Sent",
        "INBOX/Sent",
        "Отправленные",
        "INBOX.Отправленные",
        "INBOX/Отправленные",
        "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-",
    ]

    found = []

    for candidate in preferred_exact:
        for name in mailbox_names:
            if name == candidate and name not in found:
                found.append(name)

    keyword_candidates = [
        "sent",
        "отправ",
        "отослан",
        "outbox",
    ]

    for name in mailbox_names:
        lname = name.lower()
        if any(keyword in lname for keyword in keyword_candidates):
            if name not in found:
                found.append(name)

    for name in mailbox_names:
        if name.startswith("&") and name not in found:
            if name == "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-":
                found.append(name)

    return found


def append_to_sent(mail, raw_bytes: bytes) -> list[str]:
    folders = resolve_all_sent_folders(mail)

    if not folders:
        print("DEBUG APPEND: не найдено ни одной папки для сохранения отправленных")
        return []

    internal_date = imaplib.Time2Internaldate(datetime.now(timezone.utc))
    saved_folders = []

    for folder in folders:
        try:
            status, response = mail.append(
                quote_imap_folder(folder),
                "\\Seen",
                internal_date,
                raw_bytes,
            )
            print(f"DEBUG APPEND {folder} = {status}")

            if status == "OK":
                saved_folders.append(folder)
            else:
                print(f"DEBUG APPEND ERROR {folder} = {response}")

        except Exception as e:
            print(f"DEBUG APPEND EXCEPTION {folder} = {e}")

    return saved_folders


def make_sent_log_filename(subject: str) -> Path:
    safe_subject = re.sub(r'[\\/:*?"<>|]+', "_", sanitize_header(subject))
    safe_subject = re.sub(r"\s+", "_", safe_subject).strip("_")
    if not safe_subject:
        safe_subject = "sent_message"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return SENT_LOG_DIR / f"{timestamp}_{safe_subject}.txt"


def save_sent_log(subject: str, to_emails: list[str], cc_emails: list[str], body: str):
    log_file = make_sent_log_filename(subject)
    log_file.write_text(
        "SUBJECT: " + subject + "\n"
        + "TO: " + ", ".join(to_emails) + "\n"
        + "CC: " + ", ".join(cc_emails) + "\n\n"
        + body,
        encoding="utf-8",
    )
    return log_file


def build_message(subject: str, body: str, to_emails: list[str], cc_emails: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = EMAIL_USERNAME
    msg["To"] = ", ".join(to_emails)
    if cc_emails:
        msg["Cc"] = ", ".join(cc_emails)
    msg["Subject"] = sanitize_header(subject)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)
    return msg


def build_reply_message(
    subject: str,
    body: str,
    to_emails: list[str],
    cc_emails: list[str],
    original_message_id: str,
) -> EmailMessage:
    msg = build_message(subject, body, to_emails, cc_emails)
    msg["In-Reply-To"] = sanitize_header(original_message_id)
    msg["References"] = sanitize_header(original_message_id)
    return msg


def main():
    print("DEBUG ENV PATH =", ENV_PATH)
    print("DEBUG IMAP_HOST =", repr(IMAP_HOST))
    print("DEBUG SMTP_HOST =", repr(SMTP_HOST))
    print("DEBUG EMAIL_USERNAME =", repr(EMAIL_USERNAME))
    print("DEBUG DRAFT_FILE =", DRAFT_FILE)
    print("DEBUG DRY_RUN =", DRY_RUN)

    if not IMAP_HOST or not SMTP_HOST or not EMAIL_USERNAME or not EMAIL_PASSWORD:
        raise ValueError("Проверь .env: IMAP_HOST / SMTP_HOST / EMAIL_USERNAME / EMAIL_PASSWORD")

    if not DRAFT_FILE.exists():
        raise FileNotFoundError(f"Draft file not found: {DRAFT_FILE}")

    draft_text = DRAFT_FILE.read_text(encoding="utf-8")

    subject = extract_subject(draft_text)
    body_raw = extract_body(draft_text)

    manual_to = extract_to_emails(draft_text)
    manual_cc = extract_cc_emails(draft_text)

    is_manual_send = len(manual_to) > 0

    if is_manual_send:
        print("MODE = MANUAL SEND")
        to_emails = manual_to
        cc_emails = manual_cc
        msg = build_message(subject=subject, body=body_raw, to_emails=to_emails, cc_emails=cc_emails)
    else:
        print("MODE = THREAD REPLY")
        thread_subject = extract_thread_subject_from_draft(draft_text)

        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as mail:
            mail.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            original_message_id, original_msg = read_latest_incoming_message_for_thread(
                mail=mail,
                folder=TARGET_FOLDER,
                thread_subject=thread_subject,
            )

        to_emails, cc_emails = extract_reply_recipients(original_msg)

        subject_lc = subject.lower()
        if not subject_lc.startswith("re:"):
            subject = f"Re: {subject}"

        msg = build_reply_message(
            subject=subject,
            body=body_raw,
            to_emails=to_emails,
            cc_emails=cc_emails,
            original_message_id=original_message_id,
        )

    to_emails = clean_email_list(to_emails)
    cc_emails = clean_email_list(cc_emails)
    all_recipients = to_emails + cc_emails

    if not to_emails:
        raise ValueError("Список получателей To пуст после очистки")
    if not all_recipients:
        raise ValueError("Нет валидных получателей для отправки")

    print("FINAL TO =", to_emails)
    print("FINAL CC =", cc_emails)
    print("SUBJECT =", subject)

    raw_bytes = msg.as_bytes()

    if DRY_RUN:
        print("DRY RUN: письмо не отправлено")
        print("DRY RUN: письмо не сохранено в отправленные")
        return

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.send_message(
            msg,
            from_addr=EMAIL_USERNAME,
            to_addrs=all_recipients,
        )

    saved_folders = []
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as mail:
            mail.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            saved_folders = append_to_sent(mail, raw_bytes)
    except Exception as e:
        print("WARNING: письмо отправлено, но сохранить в отправленные не удалось:", e)

    log_file = save_sent_log(subject, to_emails, cc_emails, body_raw)

    print("EMAIL SENT SUCCESSFULLY")
    if saved_folders:
        print("SAVED TO FOLDERS =", ", ".join(saved_folders))
    else:
        print("WARNING: письмо отправлено, но не сохранено ни в одну папку отправленных")
    print("SENT LOG =", log_file)


if __name__ == "__main__":
    main()
