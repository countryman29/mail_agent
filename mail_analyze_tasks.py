from pathlib import Path
import os
import re
import json
import imaplib
import email
from email.header import decode_header
from dotenv import dotenv_values
from mail_cli import add_common_args
from mail_result import build_result, emit_result
from mail_safe_config import load_safe_config
from mail_analysis_helpers import (
    get_text_from_message,
    load_json_state,
    parse_message_date_metadata,
    write_dated_analysis_outputs,
)
from mail_folder_aliases import select_folder_with_aliases


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
STATE_PATH = BASE_DIR / "state" / "mail_state.json"
ANALYSIS_DIR = BASE_DIR / "analysis"
TASKS_DIR = BASE_DIR / "tasks"

ENV = dotenv_values(ENV_PATH)

IMAP_HOST = ENV.get("IMAP_HOST")
IMAP_PORT = int(ENV.get("IMAP_PORT", "993"))
EMAIL_USERNAME = ENV.get("EMAIL_USERNAME")
EMAIL_PASSWORD = ENV.get("EMAIL_PASSWORD")

TARGET_FOLDER = "INBOX/Elcon"
LIMIT = 30
COMMAND_NAME = "mail_analyze_tasks"


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


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] if len(name) > 120 else name


def slugify(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", name, flags=re.IGNORECASE)
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:80]


def clean_subject(subject: str) -> str:
    if not subject:
        return "[no subject]"
    s = subject.strip()
    s = re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def short_text(text, limit=1200):
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def load_state():
    return load_json_state(STATE_PATH, {"processed_message_ids": []})


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def build_dated_output_paths(
    analysis_dir: Path,
    tasks_dir: Path,
    company_name: str,
    date_folder: str,
    filename: str,
) -> tuple[Path, Path]:
    analysis_file = analysis_dir / company_name / date_folder / filename
    task_file = tasks_dir / company_name / date_folder / filename
    return analysis_file, task_file


def fetch_recent_rfc822_messages_with_readonly(mail, target_folder: str, limit: int, skip_ids=None, readonly=True):
    print(f"\n=== SELECT FOLDER: {target_folder} ===")
    status, data, selected_folder = select_folder_with_aliases(mail, target_folder, readonly=readonly)
    print("SELECT:", status, data)
    if status != "OK":
        raise RuntimeError(f"Cannot open folder {target_folder}")
    if selected_folder != target_folder:
        print("SELECTED FOLDER ALIAS:", selected_folder)

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


def detect_open_questions(text: str):
    questions = []

    patterns = [
        (r"\bconfirm\b", "Требуется подтверждение от контрагента"),
        (r"\bprovide\b", "Требуется предоставить данные / документы"),
        (r"\bflight\b", "Нужно проверить детали рейса / отправки"),
        (r"\bawb\b", "Нужно проверить авианакладную / статус AWB"),
        (r"\bshipment\b", "Нужно уточнить статус отгрузки"),
        (r"\bplease find the attachment\b", "Нужно проверить приложенные документы"),
        (r"\bcustom clearance\b", "Нужно контролировать статус таможенного оформления"),
        (r"\bnot arrived\b", "Нужно проверить, почему груз еще не прибыл"),
    ]

    lower_text = text.lower()
    for pattern, label in patterns:
        if re.search(pattern, lower_text):
            questions.append(label)

    seen = []
    for q in questions:
        if q not in seen:
            seen.append(q)
    return seen


def detect_urgency(text: str):
    lower_text = text.lower()
    if any(x in lower_text for x in ["urgent", "today", "immediately", "asap", "not arrived"]):
        return "Высокая"
    if any(x in lower_text for x in ["confirm", "provide", "flight", "awb", "shipment"]):
        return "Средняя"
    return "Низкая"


def build_recommendation(open_questions):
    if not open_questions:
        return "Явных открытых вопросов не выявлено. Проверить, требуется ли ответ."

    if any("AWB" in q or "авианаклад" in q.lower() for q in open_questions):
        return "Проверить статус AWB и при необходимости направить уточняющее письмо контрагенту."

    if any("подтверждение" in q.lower() for q in open_questions):
        return "Запросить явное подтверждение по открытому вопросу и зафиксировать ответ."

    if any("документы" in q.lower() for q in open_questions):
        return "Проверить вложения и подтвердить комплектность документов."

    return "Проверить переписку и подготовить уточняющий ответ контрагенту."


def extract_company_from_folder(folder_name: str):
    if "/" in folder_name:
        return folder_name.split("/")[-1]
    return folder_name


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Analyze mailbox messages into markdown tasks")
    add_common_args(parser)
    return parser


def render_message_analysis_outputs(
    company_name: str,
    target_folder: str,
    message_id: str,
    date_display: str,
    from_: str,
    subject: str,
    summary: str,
    body_preview: str,
    open_questions: list[str],
    recommendation: str,
    urgency: str,
) -> tuple[str, str]:
    q_block = "\n".join([f"- {q}" for q in open_questions]) if open_questions else "- Явные открытые вопросы не выявлены"
    status = "Новая" if open_questions else "Без задачи"
    needs_human = "Да" if open_questions or urgency in ("Высокая", "Средняя") else "Нет"

    analysis_content = f"""# Анализ письма

**Контрагент:** {company_name}  
**Папка:** {target_folder}  
**Message ID:** {message_id}  
**Дата:** {date_display}  
**От:** {from_}  
**Тема:** {subject}  

## Summary
{summary}

## Status
{status}

## Open Questions
{q_block}

## Recommendation
{recommendation}

## Urgency
{urgency}

## Body Preview
{body_preview or "Текст письма не извлечен."}
"""

    task_content = f"""# Задача по письму

**Контрагент:** {company_name}  
**Папка:** {target_folder}  
**Message ID:** {message_id}  
**Дата:** {date_display}  
**Тема:** {subject}  
**Срочность:** {urgency}  
**Требуется участие Антона:** {needs_human}  

## Open Questions
{q_block}

## Status
{status}

## Recommendation
{recommendation}
"""

    return analysis_content, task_content


def analyze_messages(
    *,
    target_folder: str,
    limit: int,
    output_dir: str | None,
    no_state_write: bool,
    readonly: bool,
    dry_run: bool,
    no_send: bool,
):
    config, _ = load_safe_config(command_type="imap_read")
    imap_host = config.get("IMAP_HOST", IMAP_HOST)
    email_username = config.get("EMAIL_USERNAME", EMAIL_USERNAME)
    email_password = config.get("EMAIL_PASSWORD", EMAIL_PASSWORD)
    imap_port = int(config.get("IMAP_PORT", IMAP_PORT))

    print("DEBUG ENV PATH =", ENV_PATH)
    print("DEBUG IMAP_HOST =", repr(imap_host))
    print("DEBUG EMAIL_USERNAME =", repr(email_username))

    if not imap_host or not email_username or not email_password:
        raise ValueError("Проверь .env: IMAP_HOST / EMAIL_USERNAME / EMAIL_PASSWORD")

    state = load_state()
    processed_ids = set(state.get("processed_message_ids", []))

    company_name = extract_company_from_folder(target_folder)
    analysis_base_dir = ANALYSIS_DIR if output_dir in (None, "") else Path(output_dir).expanduser().resolve() / "analysis"
    tasks_base_dir = TASKS_DIR if output_dir in (None, "") else Path(output_dir).expanduser().resolve() / "tasks"

    mail = imaplib.IMAP4_SSL(imap_host, imap_port)
    mail.login(email_username, email_password)

    new_processed = set()
    analyzed_count = 0
    output_paths: list[str] = []

    for num, raw_email in fetch_recent_rfc822_messages_with_readonly(
        mail,
        target_folder,
        limit,
        skip_ids=processed_ids,
        readonly=readonly,
    ):
        msg_id_local = num.decode()
        msg = email.message_from_bytes(raw_email)

        subject = decode_mime(msg.get("Subject"))
        from_ = decode_mime(msg.get("From"))
        date_raw = decode_mime(msg.get("Date"))
        message_id_header = decode_mime(msg.get("Message-ID"))
        body = get_text_from_message(msg)
        body_preview = short_text(body)

        date_metadata = parse_message_date_metadata(date_raw)
        date_folder = date_metadata["date_folder"]
        date_display = date_metadata["date_display"]

        clean_subj = clean_subject(subject)
        thread_slug = slugify(clean_subj) or "no_subject"

        open_questions = detect_open_questions(body)
        urgency = detect_urgency(body)
        recommendation = build_recommendation(open_questions)

        summary = body_preview if body_preview else "Текст письма не извлечен."

        analysis_content, task_content = render_message_analysis_outputs(
            company_name=company_name,
            target_folder=target_folder,
            message_id=message_id_header or msg_id_local,
            date_display=date_display,
            from_=from_,
            subject=clean_subj,
            summary=summary,
            body_preview=body_preview,
            open_questions=open_questions,
            recommendation=recommendation,
            urgency=urgency,
        )

        filename = f"{thread_slug}_message_{msg_id_local}.md"
        analysis_file, task_file = build_dated_output_paths(
            analysis_dir=analysis_base_dir,
            tasks_dir=tasks_base_dir,
            company_name=company_name,
            date_folder=date_folder,
            filename=filename,
        )
        if not dry_run:
            analysis_file, task_file = write_dated_analysis_outputs(
                analysis_dir=analysis_base_dir,
                tasks_dir=tasks_base_dir,
                company_name=company_name,
                date_folder=date_folder,
                filename=filename,
                analysis_content=analysis_content,
                task_content=task_content,
            )

        print("ANALYZED:", analysis_file)
        print("TASK:", task_file)
        output_paths.extend([str(analysis_file), str(task_file)])

        new_processed.add(msg_id_local)
        analyzed_count += 1

    mail.logout()

    warnings: list[str] = []
    if dry_run:
        warnings.append("Dry run enabled: analysis/task files were not written")
    if new_processed:
        if dry_run:
            warnings.append("Dry run enabled: state file was not updated")
        elif no_state_write:
            warnings.append("State update skipped because --no-state-write is enabled")
        else:
            processed_ids.update(new_processed)
            state["processed_message_ids"] = sorted(processed_ids, key=lambda x: int(x) if x.isdigit() else x)
            save_state(state)

    print("\nDone.")
    print("New analyzed messages:", analyzed_count)
    print("State file:", STATE_PATH)
    return build_result(
        status="ok",
        command=COMMAND_NAME,
        dry_run=dry_run,
        no_send=no_send,
        readonly=readonly,
        counts={"messages_analyzed": analyzed_count},
        output_paths=output_paths,
        warnings=warnings,
        risk_flags=["imap_access", "local_output_write", "human_review_required"],
        human_review_required=True,
        errors=[],
    )


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else [])

    selected_folder = args.folder or TARGET_FOLDER
    result = analyze_messages(
        target_folder=selected_folder,
        limit=args.limit,
        output_dir=args.output_dir,
        no_state_write=args.no_state_write,
        readonly=args.readonly,
        dry_run=args.dry_run,
        no_send=args.no_send,
    )
    emit_result(result, output_json=args.output_json)
    if args.output_json:
        return result
    return int(result["counts"]["messages_analyzed"])


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
