import html
import json
import re
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
