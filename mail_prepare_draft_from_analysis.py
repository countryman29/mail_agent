import re
from pathlib import Path

from mail_cli import add_common_args
from mail_result import build_result, emit_result
from mail_safe_config import load_safe_config
from mail_signature import ensure_outgoing_signature


BASE_DIR = Path(__file__).resolve().parent
DRAFTS_DIR = BASE_DIR / "drafts"
ALLOWED_SOURCE_EXTENSIONS = {".md", ".txt"}
COMMAND_NAME = "mail_prepare_draft_from_analysis"


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


def validate_source_path(source_path: Path | str) -> Path:
    resolved_source = Path(source_path).expanduser().resolve()
    if not resolved_source.exists():
        raise ValueError(f"Source file not found: {resolved_source}")
    if not resolved_source.is_file():
        raise ValueError(f"Source path is not a file: {resolved_source}")
    if resolved_source.suffix.lower() not in ALLOWED_SOURCE_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_SOURCE_EXTENSIONS))
        raise ValueError(f"Source file must use one of supported extensions ({allowed}): {resolved_source}")
    return resolved_source


def resolve_output_dir(output_dir: Path | str | None) -> Path:
    candidate = DRAFTS_DIR if output_dir in (None, "") else Path(output_dir)
    resolved = candidate.expanduser().resolve()
    if resolved.exists() and not resolved.is_dir():
        raise ValueError(f"Output path is not a directory: {resolved}")
    return resolved


def resolve_draft_path(source_path: Path, output_dir: Path) -> Path:
    draft_name = f"{source_path.stem}_draft.md"
    draft_path = (output_dir / draft_name).resolve()
    try:
        draft_path.relative_to(output_dir)
    except ValueError as exc:
        raise ValueError(f"Draft path escapes output directory: {draft_path}") from exc
    return draft_path


def prepare_draft_from_markdown(
    source_path: Path | str,
    drafts_dir: Path | str = DRAFTS_DIR,
    *,
    dry_run: bool = False,
) -> Path:
    source_path = validate_source_path(source_path)
    drafts_dir = resolve_output_dir(drafts_dir)
    text = source_path.read_text(encoding="utf-8")
    draft_path = resolve_draft_path(source_path, drafts_dir)
    draft_text = build_reply_draft(source_path, text)

    if not dry_run:
        drafts_dir.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(draft_text, encoding="utf-8")
    return draft_path


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Prepare reply draft from local markdown analysis")
    add_common_args(parser)
    parser.add_argument("source_path", nargs="?", help="Path to source analysis/task markdown file")
    parser.add_argument("--source-path", dest="source_path_option", default=None, help="Path to source markdown file")
    return parser


def resolve_cli_source_path(args) -> str:
    if args.source_path_option:
        return args.source_path_option
    if args.source_path:
        return args.source_path
    raise ValueError("Source path is required (positional or --source-path)")


def execute(source_path: str, output_dir: str | None, *, dry_run: bool, no_send: bool, readonly: bool) -> dict[str, object]:
    load_safe_config(command_type="draft_only")

    resolved_source = validate_source_path(source_path)
    resolved_output_dir = resolve_output_dir(output_dir)
    draft_path = prepare_draft_from_markdown(
        resolved_source,
        drafts_dir=resolved_output_dir,
        dry_run=dry_run,
    )

    warnings: list[str] = []
    if dry_run:
        warnings.append("Dry run enabled: draft file was not written")
        if not resolved_output_dir.exists():
            warnings.append(f"Output directory does not exist and would be created: {resolved_output_dir}")

    return build_result(
        status="ok",
        command=COMMAND_NAME,
        dry_run=dry_run,
        no_send=no_send,
        readonly=readonly,
        counts={"drafts_created": 0 if dry_run else 1},
        output_paths=[str(draft_path)],
        warnings=warnings,
        risk_flags=["draft_requires_human_review"],
        human_review_required=True,
        errors=[],
    )


def main(source_path: str | None = None, argv: list[str] | None = None):
    # Legacy compatibility: explicit source_path argument keeps current write behavior.
    if source_path is not None and argv is None:
        draft_path = prepare_draft_from_markdown(source_path, DRAFTS_DIR, dry_run=False)
        print("Draft created:", draft_path)
        return draft_path

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        selected_source_path = resolve_cli_source_path(args)
        result = execute(
            selected_source_path,
            args.output_dir,
            dry_run=args.dry_run,
            no_send=args.no_send,
            readonly=args.readonly,
        )
    except ValueError as exc:
        error_result = build_result(
            status="error",
            command=COMMAND_NAME,
            dry_run=getattr(args, "dry_run", True),
            no_send=getattr(args, "no_send", True),
            readonly=getattr(args, "readonly", True),
            output_paths=[],
            warnings=[],
            risk_flags=["draft_requires_human_review"],
            human_review_required=True,
            errors=[str(exc)],
        )
        emit_result(error_result, output_json=getattr(args, "output_json", False))
        raise SystemExit(str(exc))

    emit_result(result, output_json=args.output_json)
    if not args.output_json:
        if args.dry_run:
            print("Dry run: draft not created. Would create:", result["output_paths"][0])
        else:
            print("Draft created:", result["output_paths"][0])
    return result


if __name__ == "__main__":
    main()
