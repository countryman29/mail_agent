import html
import json
import re
from email.utils import parsedate_to_datetime
from pathlib import Path


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

    text = get_decoded_payload(msg)
    if msg.get_content_type() == "text/html":
        return html_to_text(text)
    if text:
        return text.strip()
    return ""


def load_json_state(path: Path, default: dict):
    fallback = default.copy()
    if not path.exists():
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return fallback
    if not isinstance(state, dict):
        return fallback
    for key, value in fallback.items():
        state.setdefault(key, value)
    return state


def parse_message_date_metadata(date_raw: str):
    try:
        dt = parsedate_to_datetime(date_raw)
        return {
            "date_folder": dt.strftime("%Y-%m-%d"),
            "date_display": dt.strftime("%Y-%m-%d %H:%M"),
            "sort_ts": dt.timestamp(),
        }
    except Exception:
        return {
            "date_folder": "unknown_date",
            "date_display": date_raw or "unknown",
            "sort_ts": 0,
        }


def fetch_recent_rfc822_messages(mail, target_folder: str, limit: int, skip_ids=None):
    print(f"\n=== SELECT FOLDER: {target_folder} ===")
    status, data = mail.select(f'"{target_folder}"')
    print("SELECT:", status, data)
    if status != "OK":
        raise RuntimeError(f"Cannot open folder {target_folder}")

    status, data = mail.search(None, "ALL")
    print("SEARCH:", status)
    if status != "OK":
        raise RuntimeError("Search failed")

    ids = data[0].split()[-limit:]
    skip_ids = set(skip_ids or [])
    messages = []

    for num in ids:
        msg_id_local = num.decode()
        if msg_id_local in skip_ids:
            continue

        status, msg_data = mail.fetch(num, "(RFC822)")
        if status != "OK":
            continue

        messages.append((num, msg_data[0][1]))

    return messages


def write_dated_analysis_outputs(
    analysis_dir: Path,
    tasks_dir: Path,
    company_name: str,
    date_folder: str,
    filename: str,
    analysis_content: str,
    task_content: str,
):
    analysis_path = analysis_dir / company_name / date_folder
    task_path = tasks_dir / company_name / date_folder
    analysis_path.mkdir(parents=True, exist_ok=True)
    task_path.mkdir(parents=True, exist_ok=True)

    analysis_file = analysis_path / filename
    task_file = task_path / filename

    with open(analysis_file, "w", encoding="utf-8") as f:
        f.write(analysis_content)

    with open(task_file, "w", encoding="utf-8") as f:
        f.write(task_content)

    return analysis_file, task_file
