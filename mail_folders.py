import imaplib
import os
from dotenv import load_dotenv

load_dotenv()

IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_PORT_RAW = os.getenv("IMAP_PORT", "993")
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

print("DEBUG IMAP_HOST =", repr(IMAP_HOST))
print("DEBUG IMAP_PORT_RAW =", repr(IMAP_PORT_RAW))
print("DEBUG EMAIL_USERNAME =", repr(EMAIL_USERNAME))

if not IMAP_HOST:
    raise ValueError("IMAP_HOST is empty or not loaded from .env")

if not IMAP_PORT_RAW:
    raise ValueError("IMAP_PORT is empty or not loaded from .env")

IMAP_PORT = int(IMAP_PORT_RAW.strip())


def decode_imap_line(line):
    if isinstance(line, bytes):
        return line.decode("utf-8", errors="replace")
    return str(line)


def main():
    print("\n=== CONNECTING TO IMAP ===")
    mail = imaplib.IMAP4_SSL(IMAP_HOST.strip(), IMAP_PORT)
    mail.login(EMAIL_USERNAME.strip(), EMAIL_PASSWORD.strip())

    print("IMAP login successful")

    print("\n=== ALL FOLDERS ===")
    status, folders = mail.list()
    print("LIST status:", status)

    if folders:
        for item in folders:
            print(decode_imap_line(item))

    print("\n=== INBOX CHECK ===")
    status, data = mail.select("INBOX", readonly=True)
    print("SELECT INBOX:", status, data)

    if status == "OK":
        status, data = mail.search(None, "ALL")
        print("SEARCH ALL:", status)

        if status == "OK" and data and data[0]:
            ids = data[0].split()
            print("Total messages in INBOX:", len(ids))
            print("Last 10 IDs:", [x.decode() for x in ids[-10:]])
        else:
            print("INBOX is empty")

    mail.logout()


if __name__ == "__main__":
    main()
