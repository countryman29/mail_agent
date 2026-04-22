from pathlib import Path
import re
import imaplib
import smtplib
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
DRAFT_FILE = BASE_DIR / "drafts" / "Elcon" / "2026-04-21" / "shipment_documents_-_ed_ex_26-27_49_(_llc_metahim)_-_ssi_transit_68_draft.md"
TARGET_FOLDER = "INBOX/Elcon"

# Всегда реальная отправка
DRY_RUN = False

SENT_LOG_DIR = BASE_DIR / "sent"
SENT_LOG_DIR.mkdir(parents=True, exist_ok=True)


def decode_mime(value: str) -> str:
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


def normalize_subject(subject: str) -> str:
    subject = decode_mime(subject or "").replace("\r", " ").replace("\n", " ").strip()
    subject = re.sub(r"\s+", " ", subject)
    return subject


def ensure_reply_subject(subject: str) -> str:
    subject = normalize_subject(subject)
    if not subject:
        return "Re: [no subject]"
    if re.match(r"(?i)^re\s*:", subject):
        return subject
    return f"Re: {subject}"


def extract_english_draft(text: str) -> str:
    pattern = r"## Draft reply in English\s*(.*?)\s*## "
    m = re.search(pattern, text, flags=re.DOTALL)
    if m:
        return m.group(1).strip()

    pattern_last = r"## Draft reply in English\s*(.*)$"
    m = re.search(pattern_last, text, flags=re.DOTALL)
    if m:
        return m.group(1).strip()

    raise ValueError("Не найден блок '## Draft reply in English'")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]+', "_", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:180] if len(name) > 180 else name


def get_thread_last_message(mail, folder: str):
    print(f"\n=== SELECT FOLDER: {folder} ===")
    status, data = mail.select(f'"{folder}"')
    print("SELECT:", status, data)
    if status != "OK":
        raise RuntimeError(f"Cannot open folder {folder}")

    status, data = mail.search(None, "ALL")
    print("SEARCH:", status)
    if status != "OK":
        raise RuntimeError("Search failed")

    ids = data[0].split()
    if not ids:
        raise RuntimeError("Folder is empty")

    last_id = ids[-1]
    status, msg_data = mail.fetch(last_id, "(RFC822)")
    if status != "OK":
        raise RuntimeError("Cannot fetch last message")

    raw_email = msg_data[0][1]
    msg = message_from_bytes(raw_email)
    return last_id.decode(), msg, raw_email


def extract_reply_recipients(msg, own_email: str):
    own_email = (own_email or "").strip().lower()

    raw_to = msg.get_all("To", [])
    raw_cc = msg.get_all("Cc", [])

    to_list = getaddresses(raw_to)
    cc_list = getaddresses(raw_cc)

    cleaned_to = []
    cleaned_cc = []
    seen = set()

    def add_unique(items, target):
        for display_name, email_addr in items:
            email_clean = (email_addr or "").strip()
            if not email_clean:
                continue

            email_key = email_clean.lower()
            if email_key == own_email:
                continue

            if email_key in seen:
                continue

            seen.add(email_key)
            if display_name:
                target.append(f"{display_name} <{email_clean}>")
            else:
                target.append(email_clean)

    add_unique(to_list, cleaned_to)
    add_unique(cc_list, cleaned_cc)

    # Если To оказался пустым, но есть Cc — первый адрес из Cc переносим в To
    if not cleaned_to and cleaned_cc:
        cleaned_to.append(cleaned_cc.pop(0))

    return cleaned_to, cleaned_cc


def append_to_sent_folder(imap_host, imap_port, username, password, raw_bytes: bytes):
    with imaplib.IMAP4_SSL(imap_host, imap_port) as imap:
        imap.login(username, password)

        # Сначала пробуем стандартную папку Sent
        status, _ = imap.append("Sent", "\\Seen", imaplib.Time2Internaldate(), raw_bytes)
        if status == "OK":
            print("APPENDED TO IMAP FOLDER: Sent")
            return

        # Если не получилось, попробуем локализованную sent-папку
        status_list, folders = imap.list()
        if status_list == "OK":
            for folder_line in folders:
                line = folder_line.decode(errors="replace")
                if "\\Sent" in line:
                    m = re.search(r'"([^"]+)"\s+"([^"]+)"\s*$', line)
                    if m:
                        folder_name = m.group(2)
                    else:
                        parts = line.rsplit(" ", 1)
                        folder_name = parts[-1].strip('"') if parts else "Sent"

                    status_append, _ = imap.append(folder_name, "\\Seen", imaplib.Time2Internaldate(), raw_bytes)
                    if status_append == "OK":
                        print(f"APPENDED TO IMAP FOLDER: {folder_name}")
                        return

        raise RuntimeError("Не удалось сохранить письмо в папку Sent по IMAP")


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
    body = extract_english_draft(draft_text)

    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as mail:
        mail.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        thread_message_id, original_msg, _ = get_thread_last_message(mail, TARGET_FOLDER)

    subject = ensure_reply_subject(original_msg.get("Subject", ""))
    to_emails, cc_emails = extract_reply_recipients(original_msg, EMAIL_USERNAME)

    if not to_emails and not cc_emails:
        raise RuntimeError("Не удалось определить адресатов для ответа")

    original_message_id = normalize_subject(original_msg.get("Message-ID", ""))
    references = normalize_subject(original_msg.get("References", ""))
    in_reply_to = original_message_id

    if references:
        references_value = f"{references} {original_message_id}".strip()
    else:
        references_value = original_message_id

    reply = EmailMessage()
    reply["From"] = EMAIL_USERNAME
    reply["To"] = ", ".join(to_emails)
    if cc_emails:
        reply["Cc"] = ", ".join(cc_emails)
    reply["Subject"] = subject
    reply["Date"] = formatdate(localtime=True)
    reply["Message-ID"] = make_msgid()
    if in_reply_to:
        reply["In-Reply-To"] = in_reply_to
    if references_value:
        reply["References"] = references_value
    reply.set_content(body)

    all_recipients = to_emails + cc_emails

    print("FINAL TO =", to_emails)
    print("FINAL CC =", cc_emails)
    print("THREAD MESSAGE ID =", thread_message_id)
    print("ORIGINAL MESSAGE-ID =", original_message_id)

    if DRY_RUN:
        print("DRY RUN: письмо не отправлено")
        return

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.send_message(reply, from_addr=EMAIL_USERNAME, to_addrs=all_recipients)

    raw_sent_bytes = reply.as_bytes()
    append_to_sent_folder(
        imap_host=IMAP_HOST,
        imap_port=IMAP_PORT,
        username=EMAIL_USERNAME,
        password=EMAIL_PASSWORD,
        raw_bytes=raw_sent_bytes,
    )

    sent_file = SENT_LOG_DIR / f"{sanitize_filename(DRAFT_FILE.stem)}_sent.txt"
    sent_file.write_text(
        "\n".join([
            f"SUBJECT: {subject}",
            f"TO: {', '.join(to_emails)}",
            f"CC: {', '.join(cc_emails)}",
            f"THREAD_MESSAGE_ID: {thread_message_id}",
            f"ORIGINAL_MESSAGE_ID: {original_message_id}",
            "",
            body,
        ]),
        encoding="utf-8"
    )

    print("EMAIL SENT SUCCESSFULLY")
    print("SENT LOG:", sent_file)


if __name__ == "__main__":
    main()
