from pathlib import Path
import html
import os
import re
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime

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
IMAP_PORT_RAW = ENV.get("IMAP_PORT") or os.getenv("IMAP_PORT")
EMAIL_USERNAME = ENV.get("EMAIL_USERNAME") or os.getenv("EMAIL_USERNAME")
EMAIL_PASSWORD = ENV.get("EMAIL_PASSWORD") or os.getenv("EMAIL_PASSWORD")

IMAP_PORT = int(IMAP_PORT_RAW or "993")

TARGET_FOLDER = "INBOX/Elcon"
LIMIT = 50


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
    return s.strip().lower()


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</p\s*>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def get_decoded_payload(part):
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def get_text_from_message(msg):
    if msg.is_multipart():
        plain_parts = []
        html_parts = []
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in disposition.lower():
                continue

            if content_type == "text/plain":
                text = get_decoded_payload(part)
                if text:
                    plain_parts.append(text)
            elif content_type == "text/html":
                text = get_decoded_payload(part)
                if text:
                    html_parts.append(html_to_text(text))
        if plain_parts:
            return "\n".join(plain_parts).strip()
        return "\n".join(html_parts).strip()
    else:
        text = get_decoded_payload(msg)
        if msg.get_content_type() == "text/html":
            return html_to_text(text)
        if text:
            return text.strip()
    return ""


def short_text(text, limit=400):
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def main():
    print("DEBUG ENV PATH =", ENV_PATH)
    print("DEBUG ENV EXISTS =", ENV_PATH.exists())
    print("DEBUG ENV DICT =", ENV)
    print("DEBUG IMAP_HOST =", repr(IMAP_HOST))
    print("DEBUG IMAP_PORT_RAW =", repr(IMAP_PORT_RAW))
    print("DEBUG EMAIL_USERNAME =", repr(EMAIL_USERNAME))

    if not IMAP_HOST or not EMAIL_USERNAME or not EMAIL_PASSWORD:
        raise ValueError("Проверь .env: IMAP_HOST / EMAIL_USERNAME / EMAIL_PASSWORD")

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
    print("Total messages in folder:", len(ids))

    ids = ids[-LIMIT:]
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
        except Exception:
            sort_ts = 0

        thread_key = clean_subject(subject)

        item = {
            "id": num.decode(),
            "date": date_raw,
            "from": from_,
            "subject": subject,
            "body_preview": short_text(body),
            "sort_ts": sort_ts,
        }

        threads.setdefault(thread_key, []).append(item)

    print("\n=== THREADS SUMMARY ===")
    print("Threads found:", len(threads))

    sorted_threads = sorted(
        threads.items(),
        key=lambda kv: max(x["sort_ts"] for x in kv[1]) if kv[1] else 0,
        reverse=True
    )

    for idx, (thread_key, items) in enumerate(sorted_threads, start=1):
        items.sort(key=lambda x: x["sort_ts"])
        print("\n" + "=" * 100)
        print(f"THREAD #{idx}")
        print("Normalized subject:", thread_key)
        print("Messages in thread:", len(items))
        print("Latest subject:", items[-1]["subject"])

        for m in items:
            print("-" * 100)
            print(f"[{m['id']}] {m['date']}")
            print("FROM:", m["from"])
            print("SUBJECT:", m["subject"])
            print("PREVIEW:", m["body_preview"])

    mail.logout()


if __name__ == "__main__":
    main()
