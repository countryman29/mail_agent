import os
import re
import imaplib
import smtplib
import time
from pathlib import Path
from email import message_from_bytes
from email.message import EmailMessage
from email.header import decode_header
from email.utils import getaddresses, formatdate, make_msgid, parseaddr
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
DEFAULT_DRAFT_FILE = Path("drafts") / "test_vasanton.md"


def env_value(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None or value == "":
        value = ENV.get(name, default)
    return str(value).strip()


def env_flag(name: str, default: bool = False) -> bool:
    raw_value = env_value(name, "true" if default else "false").lower()
    return raw_value in {"1", "true", "yes", "on"}


def resolve_runtime_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


DRAFT_FILE = resolve_runtime_path(env_value("MAIL_DRAFT_FILE", str(DEFAULT_DRAFT_FILE)))
TARGET_FOLDER = env_value("MAIL_TARGET_FOLDER", "INBOX") or "INBOX"

# True = только проверка, без реальной отправки
# False = реальная отправка
DRY_RUN = not env_flag("MAIL_SEND_FOR_REAL", default=False)

SENT_LOG_DIR = BASE_DIR / "sent"
LEGACY_BODY_HEADERS = ["Draft reply in English", "Message", "BODY"]
PLACEHOLDER_RECIPIENTS = {"**", "*", "-", "—", "n/a", "na", "none"}
PREFERRED_SENT_NAMES = [
    "sent",
    "sent messages",
    "sent items",
    "отправленные",
    "отправленные сообщения",
]
SENT_KEYWORDS = ["sent", "отправ", "отослан"]
MESSAGE_ID_RE = re.compile(r"<[^<>\s]+>")


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


def extract_section(text: str, header: str) -> str | None:
    pattern = rf"(?ms)^##\s+{re.escape(header)}\s*\n(.*?)(?=^##\s+|\Z)"
    m = re.search(pattern, text)
    if not m:
        return None
    return m.group(1)


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


def is_valid_email_address(value: str) -> bool:
    _, parsed = parseaddr(value)
    if not parsed or parsed != value:
        return False
    if "@" not in parsed or parsed.startswith("@") or parsed.endswith("@"):
        return False
    return " " not in parsed


def clean_email_list(emails: list[str]) -> list[str]:
    cleaned = []
    seen = set()

    for item in emails:
        value = sanitize_header(item).strip()

        if not value:
            continue
        if value.casefold() in PLACEHOLDER_RECIPIENTS:
            continue
        if not is_valid_email_address(value):
            continue

        value_lower = value.lower()
        if EMAIL_USERNAME and value_lower == EMAIL_USERNAME.lower():
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
    canonical_body = extract_section(text, "Body")
    if canonical_body is not None:
        body = canonical_body.strip()
        if not body:
            raise ValueError("Раздел '## Body' найден, но он пустой")
        return body

    for legacy_header in LEGACY_BODY_HEADERS:
        legacy_body = extract_section(text, legacy_header)
        if legacy_body is None:
            continue

        body = legacy_body.strip()
        if not body:
            raise ValueError(
                f"Найден устаревший раздел '## {legacy_header}', но он пустой. Используй непустой раздел '## Body'."
            )

        print(
            f"WARNING: используется устаревший раздел '## {legacy_header}'. "
            "Переименуйте его в '## Body'."
        )
        return body

    accepted_legacy = ", ".join(f"'## {header}'" for header in LEGACY_BODY_HEADERS)
    raise ValueError(
        "Не найден текст письма. Обязательный раздел: '## Body'. "
        f"Временно поддерживаются устаревшие разделы: {accepted_legacy}."
    )


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


def extract_message_ids(value: str | None) -> list[str]:
    if not value:
        return []
    return MESSAGE_ID_RE.findall(sanitize_header(value))


def build_references_header(original_msg) -> tuple[str, str]:
    original_message_ids = extract_message_ids(original_msg.get("Message-ID"))
    if not original_message_ids:
        return "", ""

    in_reply_to = original_message_ids[-1]
    chain = []

    for message_id in extract_message_ids(original_msg.get("References")) + original_message_ids:
        if message_id not in chain:
            chain.append(message_id)

    return in_reply_to, " ".join(chain)


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
        raise RuntimeError(
            f"Не найдено письмо для reply lookup: тема '{thread_subject}', папка '{folder}'. "
            "Проверь MAIL_TARGET_FOLDER и поле '**Тема ветки:**' в draft-файле."
        )

    latest_id = raw_ids[-1]
    status, msg_data = mail.fetch(latest_id, "(RFC822)")
    if status != "OK" or not msg_data or not msg_data[0]:
        raise RuntimeError("Не удалось прочитать последнее письмо ветки")

    raw_bytes = msg_data[0][1]
    original_msg = message_from_bytes(raw_bytes)

    message_ids = extract_message_ids(original_msg.get("Message-ID"))
    if not message_ids:
        raise RuntimeError("В исходном письме отсутствует Message-ID")
    message_id = message_ids[-1]

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


def decode_imap_list_line(raw_line) -> tuple[set[str], str] | None:
    if not raw_line:
        return None

    line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
    match = re.match(r'^\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', line)
    if not match:
        fallback = re.search(r'"((?:[^"\\]|\\.)*)"\s*$', line)
        if not fallback:
            return None
        return set(), fallback.group(1).replace(r"\"", '"').replace(r"\\", "\\")

    flags = {flag.lower() for flag in match.group("flags").split()}
    mailbox_name = match.group("name").strip()

    if mailbox_name.startswith('"') and mailbox_name.endswith('"'):
        mailbox_name = mailbox_name[1:-1].replace(r"\"", '"').replace(r"\\", "\\")

    return flags, mailbox_name


def normalize_mailbox_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


def sent_folder_rank(flags: set[str], mailbox_name: str) -> tuple[int, int, str]:
    normalized_name = normalize_mailbox_name(mailbox_name)

    if "\\sent" in flags:
        preferred_index = PREFERRED_SENT_NAMES.index(normalized_name) if normalized_name in PREFERRED_SENT_NAMES else len(PREFERRED_SENT_NAMES)
        return (0, preferred_index, normalized_name)

    if normalized_name in PREFERRED_SENT_NAMES:
        return (1, PREFERRED_SENT_NAMES.index(normalized_name), normalized_name)

    if any(keyword in normalized_name for keyword in SENT_KEYWORDS):
        return (2, 0, normalized_name)

    return (9, 0, normalized_name)


def resolve_sent_folder(mail) -> str | None:
    status, data = mail.list()
    if status != "OK" or not data:
        print("WARNING: IMAP LIST не вернул доступные папки; Sent не найден")
        return None

    candidates = []
    debug_mailboxes = []

    for raw_line in data:
        parsed = decode_imap_list_line(raw_line)
        if not parsed:
            continue

        flags, mailbox_name = parsed
        debug_mailboxes.append({"name": mailbox_name, "flags": sorted(flags)})
        rank = sent_folder_rank(flags, mailbox_name)
        if rank[0] < 9:
            candidates.append((rank, mailbox_name))

    print("DEBUG MAILBOXES =", debug_mailboxes)

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def append_to_sent(mail, raw_bytes: bytes) -> str | None:
    folder = resolve_sent_folder(mail)
    if not folder:
        print("WARNING: не удалось определить каноническую папку Sent; письмо отправлено без IMAP APPEND")
        return None

    try:
        status, response = mail.append(
            quote_imap_folder(folder),
            "\\Seen",
            imaplib.Time2Internaldate(time.time()),
            raw_bytes,
        )
    except Exception as e:
        print(f"WARNING: письмо отправлено, но IMAP APPEND в папку {folder!r} завершился ошибкой: {e}")
        return None

    if status != "OK":
        print(
            f"WARNING: письмо отправлено, но IMAP APPEND в папку {folder!r} не удался. "
            f"Ответ сервера: {response}"
        )
        return None

    return folder


def make_sent_log_filename(subject: str) -> Path:
    SENT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_subject = re.sub(r'[\\/:*?"<>|]+', "_", sanitize_header(subject))
    safe_subject = re.sub(r"\s+", "_", safe_subject).strip("_")
    if not safe_subject:
        safe_subject = "sent_message"
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
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
    in_reply_to: str,
    references: str,
) -> EmailMessage:
    msg = build_message(subject, body, to_emails, cc_emails)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
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

    raw_to_field = extract_simple_field(draft_text, "To")
    raw_cc_field = extract_simple_field(draft_text, "Cc")
    manual_to = extract_to_emails(draft_text)
    manual_cc = extract_cc_emails(draft_text)

    is_manual_send = bool(raw_to_field or raw_cc_field)

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
            _, original_msg = read_latest_incoming_message_for_thread(
                mail=mail,
                folder=TARGET_FOLDER,
                thread_subject=thread_subject,
            )

        to_emails, cc_emails = extract_reply_recipients(original_msg)
        in_reply_to, references = build_references_header(original_msg)

        subject_lc = subject.lower()
        if not subject_lc.startswith("re:"):
            subject = f"Re: {subject}"

        msg = build_reply_message(
            subject=subject,
            body=body_raw,
            to_emails=to_emails,
            cc_emails=cc_emails,
            in_reply_to=in_reply_to,
            references=references,
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

    saved_folder = None
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as mail:
            mail.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            saved_folder = append_to_sent(mail, raw_bytes)
    except Exception as e:
        print("WARNING: письмо отправлено, но сохранить в отправленные не удалось:", e)

    log_file = save_sent_log(subject, to_emails, cc_emails, body_raw)

    print("EMAIL SENT SUCCESSFULLY")
    if saved_folder:
        print("SAVED TO FOLDER =", saved_folder)
    else:
        print("WARNING: письмо отправлено, но не сохранено в IMAP Sent")
    print("SENT LOG =", log_file)


if __name__ == "__main__":
    main()
