from pathlib import Path
import os
import re
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
from mail_folder_aliases import select_folder_with_aliases

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"


def load_env_file(path: Path):
    env = {}
    if not path.exists():
        return env

    text = path.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


ENV = load_env_file(ENV_PATH)

IMAP_HOST = ENV.get("IMAP_HOST") or os.getenv("IMAP_HOST")
IMAP_PORT = int(ENV.get("IMAP_PORT") or os.getenv("IMAP_PORT") or "993")
EMAIL_USERNAME = ENV.get("EMAIL_USERNAME") or os.getenv("EMAIL_USERNAME")
EMAIL_PASSWORD = ENV.get("EMAIL_PASSWORD") or os.getenv("EMAIL_PASSWORD")

TARGET_FOLDER = "INBOX/Elcon"
SUPPLIER_NAME = "Elcon"
EXPORT_BASE = BASE_DIR / "exports" / SUPPLIER_NAME
LIMIT = 50

SKIP_INLINE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"
}


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
        return "no_subject"
    s = subject.strip()
    s = re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    s = s.strip()
    s = re.sub(r'[\\/*?:"<>|]', "_", s)
    return s[:150] if s else "no_subject"


def safe_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name[:180] if name else "attachment.bin"


def message_date_folder(date_raw: str) -> str:
    try:
        dt = parsedate_to_datetime(date_raw)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return "unknown-date"


def should_skip_part(part, filename: str) -> bool:
    disposition = str(part.get("Content-Disposition", "")).lower()
    content_type = (part.get_content_type() or "").lower()
    content_id = part.get("Content-ID")

    ext = Path(filename).suffix.lower()

    # Пропускаем встроенные картинки письма
    if ext in SKIP_INLINE_EXTENSIONS:
        return True

    if content_id:
        return True

    if content_type.startswith("image/"):
        return True

    if "inline" in disposition and "attachment" not in disposition:
        return True

    return False


def main():
    print("DEBUG ENV PATH =", ENV_PATH)
    print("DEBUG IMAP_HOST =", repr(IMAP_HOST))
    print("DEBUG EMAIL_USERNAME =", repr(EMAIL_USERNAME))

    if not IMAP_HOST or not EMAIL_USERNAME or not EMAIL_PASSWORD:
        raise ValueError("Проверь .env: IMAP_HOST / EMAIL_USERNAME / EMAIL_PASSWORD")

    EXPORT_BASE.mkdir(parents=True, exist_ok=True)

    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(EMAIL_USERNAME, EMAIL_PASSWORD)

    print(f"\n=== SELECT FOLDER: {TARGET_FOLDER} ===")
    status, data, selected_folder = select_folder_with_aliases(mail, TARGET_FOLDER)
    print("SELECT:", status, data)
    if selected_folder != TARGET_FOLDER:
        print("SELECTED FOLDER ALIAS:", selected_folder)
    if status != "OK":
        raise RuntimeError(f"Cannot open folder {TARGET_FOLDER}")

    status, data = mail.search(None, "ALL")
    print("SEARCH:", status)
    if status != "OK":
        raise RuntimeError("Search failed")

    ids = data[0].split()[-LIMIT:]
    print("Messages to check:", len(ids))

    saved_count = 0
    skipped_count = 0

    for num in ids:
        status, msg_data = mail.fetch(num, "(RFC822)")
        if status != "OK":
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_mime(msg.get("Subject"))
        date_raw = decode_mime(msg.get("Date"))
        date_folder = message_date_folder(date_raw)
        subject_folder = clean_subject(subject)

        # Новая структура: supplier / date / thread
        target_dir = EXPORT_BASE / date_folder / subject_folder
        target_dir.mkdir(parents=True, exist_ok=True)

        meta_file = target_dir / f"message_{num.decode()}.txt"
        meta_text = [
            f"Message ID: {num.decode()}",
            f"Date: {date_raw}",
            f"From: {decode_mime(msg.get('From'))}",
            f"To: {decode_mime(msg.get('To'))}",
            f"Subject: {subject}",
            "",
            "Saved attachments:"
        ]

        attachment_found = False

        for part in msg.walk():
            filename = part.get_filename()
            disposition = str(part.get("Content-Disposition", ""))

            if not filename and "attachment" not in disposition.lower():
                continue

            if filename:
                filename = decode_mime(filename)
            else:
                ext = part.get_content_subtype() or "bin"
                filename = f"attachment_{num.decode()}.{ext}"

            filename = safe_filename(filename)

            if should_skip_part(part, filename):
                skipped_count += 1
                print("SKIPPED INLINE:", filename)
                continue

            payload = part.get_payload(decode=True)
            if payload is None:
                continue

            attachment_found = True
            out_path = target_dir / filename
            out_path.write_bytes(payload)

            meta_text.append(f"- {filename}")
            saved_count += 1
            print("SAVED:", out_path)

        if attachment_found:
            meta_file.write_text("\n".join(meta_text), encoding="utf-8")

    mail.logout()

    print("\nDone.")
    print("Total saved attachments:", saved_count)
    print("Total skipped inline files:", skipped_count)
    print("Export folder:", EXPORT_BASE)


if __name__ == "__main__":
    main()
