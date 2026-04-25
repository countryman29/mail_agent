import re


SYSTEM_FOLDER_ALIASES = [
    ("inbox", ["INBOX", "Inbox", "Входящие"]),
    ("sent", ["Sent", "Sent Items", "Отправленные"]),
    ("drafts", ["Drafts", "Черновики"]),
    ("trash", ["Trash", "Deleted Items", "Корзина"]),
    ("archive", ["Archive", "Архив"]),
]


def normalize_folder_segment(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def quote_imap_folder(folder_name: str) -> str:
    escaped = folder_name.replace("\\", "\\\\").replace('"', r"\"")
    return f'"{escaped}"'


def folder_alias_candidates(folder_name: str) -> list[str]:
    parts = folder_name.split("/", 1)
    first = parts[0]
    suffix = f"/{parts[1]}" if len(parts) > 1 else ""
    normalized = normalize_folder_segment(first)

    for _, aliases in SYSTEM_FOLDER_ALIASES:
        if normalized not in {normalize_folder_segment(alias) for alias in aliases}:
            continue

        candidates = [folder_name]
        for alias in aliases:
            candidate = alias + suffix
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    return [folder_name]


def select_folder_with_aliases(mail, folder_name: str, readonly=None):
    last_status = None
    last_data = None
    for candidate in folder_alias_candidates(folder_name):
        quoted = quote_imap_folder(candidate)
        try:
            if readonly is None:
                status, data = mail.select(quoted)
            else:
                status, data = mail.select(quoted, readonly=readonly)
        except Exception as e:
            last_status, last_data = "NO", [str(e).encode("utf-8", errors="replace")]
            continue
        if status == "OK":
            return status, data, candidate
        last_status, last_data = status, data
    return last_status, last_data, folder_name
