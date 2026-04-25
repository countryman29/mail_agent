import re
import sys
from pathlib import Path
from mail_signature import ensure_outgoing_signature


BASE_DIR = Path(__file__).resolve().parent
DRAFTS_DIR = BASE_DIR / "drafts"


def extract_markdown_field(text: str, field_name: str) -> str:
    pattern = rf"^\*\*{re.escape(field_name)}:\*\*\s*(.+?)\s*$"
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def extract_section(text: str, section_name: str) -> str:
    pattern = rf"^## {re.escape(section_name)}\s*\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def first_markdown_field(text: str, field_names: list[str]) -> str:
    for field_name in field_names:
        value = extract_markdown_field(text, field_name)
        if value:
            return value
    return ""


def extract_draft_metadata(text: str) -> dict:
    return {
        "from": first_markdown_field(text, ["From", "От"]),
        "to": first_markdown_field(text, ["To", "Кому"]),
        "cc": first_markdown_field(text, ["Cc", "CC", "Копия"]),
        "subject": first_markdown_field(text, ["Subject", "Тема"])
        or extract_markdown_field(text, "Тема ветки")
        or "[no subject]",
    }


def format_header(name: str, value: str) -> str:
    return f"{name}: {value}" if value else f"{name}:"


def build_reply_draft(source_path: Path, text: str) -> str:
    metadata = extract_draft_metadata(text)
    recommendation = extract_section(text, "Recommendation") or "Проверить переписку и подготовить ответ."
    body = ensure_outgoing_signature(
        f"""Здравствуйте.

Черновик подготовлен на основе файла: {source_path.name}

Рекомендация:
{recommendation}"""
    )

    return f"""{format_header("SUBJECT", f"Re: {metadata['subject']}")}
{format_header("TO", metadata["to"])}
{format_header("CC", metadata["cc"])}
BODY:
{body}
"""


def prepare_draft_from_markdown(source_path: Path | str, drafts_dir: Path | str = DRAFTS_DIR) -> Path:
    source_path = Path(source_path)
    drafts_dir = Path(drafts_dir)
    text = source_path.read_text(encoding="utf-8")

    drafts_dir.mkdir(parents=True, exist_ok=True)
    draft_path = drafts_dir / f"{source_path.stem}_draft.md"
    draft_path.write_text(build_reply_draft(source_path, text), encoding="utf-8")
    return draft_path


def main(source_path: str | None = None):
    if source_path is None:
        if len(sys.argv) != 2:
            raise SystemExit("Usage: python mail_prepare_draft_from_analysis.py <analysis_or_task_md>")
        source_path = sys.argv[1]

    draft_path = prepare_draft_from_markdown(source_path, DRAFTS_DIR)
    print("Draft created:", draft_path)
    return draft_path


if __name__ == "__main__":
    main()
