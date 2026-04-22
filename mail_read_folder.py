import imaplib
import email
from email.header import decode_header
from dotenv import load_dotenv
import os

load_dotenv()

IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

TARGET_FOLDER = "INBOX/Elcon"
LIMIT = 5


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


def get_text_from_message(msg):
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in disposition.lower():
                continue

            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return ""
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
        return ""


def main():
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
    print("Total messages:", len(ids))

    last_ids = ids[-LIMIT:]

    for num in last_ids:
        print("\n" + "=" * 80)
        print("MESSAGE ID:", num.decode())

        status, msg_data = mail.fetch(num, "(RFC822)")
        if status != "OK":
            print("FETCH FAILED")
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_mime(msg.get("Subject"))
        from_ = decode_mime(msg.get("From"))
        to_ = decode_mime(msg.get("To"))
        date_ = decode_mime(msg.get("Date"))
        message_id = decode_mime(msg.get("Message-ID"))

        body = get_text_from_message(msg).strip()
        body_preview = body[:1500] if body else "[no text/plain body found]"

        print("Date:", date_)
        print("From:", from_)
        print("To:", to_)
        print("Subject:", subject)
        print("Message-ID:", message_id)
        print("\n--- BODY PREVIEW ---\n")
        print(body_preview)

    mail.logout()


if __name__ == "__main__":
    main()
