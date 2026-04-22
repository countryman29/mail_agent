import os
import ssl
import imaplib
import smtplib
from dotenv import load_dotenv
import certifi

load_dotenv()

IMAP_HOST = os.getenv("MAIL_IMAP_HOST")
IMAP_PORT = int(os.getenv("MAIL_IMAP_PORT", "993"))
IMAP_USER = os.getenv("MAIL_IMAP_USER")
IMAP_PASSWORD = os.getenv("MAIL_IMAP_PASSWORD")

SMTP_HOST = os.getenv("MAIL_SMTP_HOST")
SMTP_PORT = int(os.getenv("MAIL_SMTP_PORT", "465"))
SMTP_USER = os.getenv("MAIL_SMTP_USER")
SMTP_PASSWORD = os.getenv("MAIL_SMTP_PASSWORD")

print("=== IMAP TEST ===")
try:
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    imap.login(IMAP_USER, IMAP_PASSWORD)
    print("IMAP login success")
    imap.logout()
except Exception as e:
    print(f"IMAP failed: {e}")

print("=== SMTP TEST ===")
try:
    context = ssl.create_default_context(cafile=certifi.where())

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as smtp:
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        print("SMTP login success")

except Exception as e:
    print(f"SMTP failed: {e}")
