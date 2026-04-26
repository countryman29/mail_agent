from pathlib import Path
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
LIMIT = 100
COMMAND_NAME = "mail_analyze_threads"


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
    return s.strip()


def slugify(name: str) -> str:
    name = clean_subject(name).lower()
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:120]


def short_text(text, limit=500):
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def load_state():
    return load_json_state(STATE_PATH, {"processed_message_ids": [], "processed_thread_keys": []})


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Analyze mailbox threads into markdown outputs")
    add_common_args(parser)
    return parser


def fetch_recent_rfc822_messages_with_readonly(mail, target_folder: str, limit: int, readonly=True):
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
    messages = []

    for num in ids:
        status, msg_data = mail.fetch(num, "(RFC822)")
        if status != "OK":
            continue
        messages.append((num, msg_data[0][1]))

    return messages


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


def detect_open_questions(full_text: str):
    text = full_text.lower()
    questions = []

    checks = [
        ("awb", "Проверить AWB / статус авианакладной"),
        ("flight", "Проверить рейс и маршрут"),
        ("shipment", "Проверить текущий статус отгрузки"),
        ("custom clearance", "Проверить статус таможенного оформления"),
        ("please find the attachment", "Проверить комплектность приложенных документов"),
        ("confirm", "Требуется подтверждение от контрагента"),
        ("not arrived", "Груз не прибыл, нужно выяснить статус"),
        ("photos", "Проверить фото товара / упаковки"),
        ("invoice", "Проверить инвойс"),
        ("pl", "Проверить packing list"),
    ]

    for needle, label in checks:
        if needle in text:
            questions.append(label)

    result = []
    for q in questions:
        if q not in result:
            result.append(q)
    return result


def detect_thread_status(full_text: str):
    text = full_text.lower()

    if "not arrived" in text:
        return "Есть вопрос по фактическому прибытию груза"
    if "custom clearance" in text:
        return "Груз находится в процессе оформления / движения"
    if "flight schedule" in text or "today night is the flight" in text:
        return "Есть подтверждение рейса / отправки"
    if "please approve" in text:
        return "Ожидается согласование документов"
    if "please find the attachment" in text:
        return "Получены документы / вложения"
    return "Требуется ручная оценка статуса"


def detect_urgency(full_text: str):
    text = full_text.lower()
    if any(x in text for x in ["urgent", "asap", "immediately", "not arrived", "today"]):
        return "Высокая"
    if any(x in text for x in ["confirm", "awb", "flight", "shipment"]):
        return "Средняя"
    return "Низкая"


def build_recommendation(status_text: str, open_questions: list[str]):
    if "не прибыл" in status_text.lower():
        return "Подготовить письмо с требованием уточнить фактический статус груза, местонахождение и подтверждение движения по AWB."
    if any("документ" in q.lower() for q in open_questions):
        return "Проверить вложения и подтвердить, что комплект документов полный и корректный."
    if any("рейс" in q.lower() for q in open_questions):
        return "Сверить номер рейса, дату вылета и статус AWB."
    if any("подтверждение" in q.lower() for q in open_questions):
        return "Направить краткий follow-up с запросом явного подтверждения."
    return "Просмотреть ветку и решить, нужен ли ответ или задача закрыта."


def company_from_folder(folder: str):
    if "/" in folder:
        return folder.split("/")[-1]
    return folder


def render_thread_analysis_outputs(
    company_name: str,
    target_folder: str,
    subject: str,
    thread_key: str,
    items: list[dict],
    status_text: str,
    open_questions: list[str],
    recommendation: str,
    urgency: str,
) -> tuple[str, str]:
    first = items[0]
    latest = items[-1]
    summary = latest["body_preview"] or "Текст письма не извлечен."
    chronology = "\n".join(
        [
            f"- {x['date_display']} | {x['from']} | {clean_subject(x['subject'])}"
            for x in items
        ]
    )

    previews = "\n\n".join(
        [
            f"### Message {x['id']}\n**Date:** {x['date_display']}\n**From:** {x['from']}\n**Subject:** {clean_subject(x['subject'])}\n\n{x['body_preview']}"
            for x in items
        ]
    )

    q_block = "\n".join([f"- {q}" for q in open_questions]) if open_questions else "- Явные открытые вопросы не выявлены"
    needs_task = "Да" if open_questions or urgency in ("Высокая", "Средняя") else "Нет"

    analysis_content = f"""# Анализ ветки

**Контрагент:** {company_name}  
**Папка:** {target_folder}  
**Тема ветки:** {subject}  
**Thread key:** {thread_key}  
**Сообщений:** {len(items)}  
**Первое письмо:** {first['date_display']}  
**Последнее письмо:** {latest['date_display']}  

## Summary
{summary}

## Status
{status_text}

## Open Questions
{q_block}

## Recommendation
{recommendation}

## Urgency
{urgency}

## Chronology
{chronology}

## Messages
{previews}
"""

    task_content = f"""# Задача по ветке

**Контрагент:** {company_name}  
**Папка:** {target_folder}  
**Тема ветки:** {subject}  
**Последнее письмо:** {latest['date_display']}  
**Срочность:** {urgency}  
**Требуется участие Антона:** {needs_task}  

## Open Questions
{q_block}

## Status
{status_text}

## Recommendation
{recommendation}
"""

    return analysis_content, task_content


def analyze_threads(
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
    processed_thread_keys = set(state.get("processed_thread_keys", []))

    company_name = company_from_folder(target_folder)
    analysis_base_dir = ANALYSIS_DIR if output_dir in (None, "") else Path(output_dir).expanduser().resolve() / "analysis"
    tasks_base_dir = TASKS_DIR if output_dir in (None, "") else Path(output_dir).expanduser().resolve() / "tasks"

    mail = imaplib.IMAP4_SSL(imap_host, imap_port)
    mail.login(email_username, email_password)

    threads = {}

    for num, raw_email in fetch_recent_rfc822_messages_with_readonly(
        mail, target_folder, limit, readonly=readonly
    ):
        msg = email.message_from_bytes(raw_email)

        subject = decode_mime(msg.get("Subject"))
        from_ = decode_mime(msg.get("From"))
        date_raw = decode_mime(msg.get("Date"))
        body = get_text_from_message(msg)

        date_metadata = parse_message_date_metadata(date_raw)

        thread_subject = clean_subject(subject)
        thread_key = slugify(thread_subject)

        item = {
            "id": num.decode(),
            "date_raw": date_raw,
            "date_display": date_metadata["date_display"],
            "date_folder": date_metadata["date_folder"],
            "from": from_,
            "subject": subject,
            "body": body,
            "body_preview": short_text(body),
            "sort_ts": date_metadata["sort_ts"],
        }

        threads.setdefault(thread_key, {"subject": thread_subject, "items": []})
        threads[thread_key]["items"].append(item)

    created = 0
    new_thread_keys = set()
    output_paths: list[str] = []

    for thread_key, payload in threads.items():
        if thread_key in processed_thread_keys:
            continue

        items = sorted(payload["items"], key=lambda x: x["sort_ts"])
        subject = payload["subject"]

        latest = items[-1]
        latest_date_folder = latest["date_folder"]

        full_text = "\n\n".join(
            [
                f"[{x['date_display']}] FROM: {x['from']}\nSUBJECT: {x['subject']}\n{x['body']}"
                for x in items
            ]
        )

        open_questions = detect_open_questions(full_text)
        status_text = detect_thread_status(full_text)
        urgency = detect_urgency(full_text)
        recommendation = build_recommendation(status_text, open_questions)

        analysis_content, task_content = render_thread_analysis_outputs(
            company_name=company_name,
            target_folder=target_folder,
            subject=subject,
            thread_key=thread_key,
            items=items,
            status_text=status_text,
            open_questions=open_questions,
            recommendation=recommendation,
            urgency=urgency,
        )

        filename = f"{thread_key}_thread.md"
        analysis_file, task_file = build_dated_output_paths(
            analysis_dir=analysis_base_dir,
            tasks_dir=tasks_base_dir,
            company_name=company_name,
            date_folder=latest_date_folder,
            filename=filename,
        )
        if not dry_run:
            analysis_file, task_file = write_dated_analysis_outputs(
                analysis_dir=analysis_base_dir,
                tasks_dir=tasks_base_dir,
                company_name=company_name,
                date_folder=latest_date_folder,
                filename=filename,
                analysis_content=analysis_content,
                task_content=task_content,
            )

        print("THREAD ANALYZED:", analysis_file)
        print("THREAD TASK:", task_file)
        output_paths.extend([str(analysis_file), str(task_file)])

        new_thread_keys.add(thread_key)
        created += 1

    mail.logout()

    warnings: list[str] = []
    if dry_run:
        warnings.append("Dry run enabled: analysis/task files were not written")
    if new_thread_keys:
        if dry_run:
            warnings.append("Dry run enabled: state file was not updated")
        elif no_state_write:
            warnings.append("State update skipped because --no-state-write is enabled")
        else:
            state["processed_thread_keys"] = sorted(set(state.get("processed_thread_keys", [])) | new_thread_keys)
            save_state(state)

    print("\nDone.")
    print("Threads analyzed:", created)
    print("State file:", STATE_PATH)
    return build_result(
        status="ok",
        command=COMMAND_NAME,
        dry_run=dry_run,
        no_send=no_send,
        readonly=readonly,
        counts={"threads_analyzed": created},
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
    result = analyze_threads(
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
    return int(result["counts"]["threads_analyzed"])


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
