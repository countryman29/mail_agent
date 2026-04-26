import os
import argparse

import mail_analyze_tasks
import mail_analyze_threads
from mail_cli import add_common_args
from mail_result import build_result, emit_result


DEFAULT_MODE = "both"
MODE_ENV_VAR = "MAIL_ANALYSIS_MODE"
COMMAND_NAME = "mail_run_analysis"


def normalize_mode(mode: str | None) -> str:
    return (mode or DEFAULT_MODE).strip().lower()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run aggregate mail analysis")
    add_common_args(parser)
    return parser


def _resolved_mode(args_mode: str | None, explicit_mode: str | None) -> str:
    if explicit_mode is not None:
        return normalize_mode(explicit_mode)
    if args_mode is not None:
        return normalize_mode(args_mode)
    return normalize_mode(os.getenv(MODE_ENV_VAR))


def _build_child_argv(args) -> list[str]:
    child_argv: list[str] = ["--limit", str(args.limit)]
    if args.folder:
        child_argv.extend(["--folder", args.folder])
    if args.output_dir:
        child_argv.extend(["--output-dir", args.output_dir])
    if args.no_state_write:
        child_argv.append("--no-state-write")
    child_argv.append("--readonly" if args.readonly else "--readwrite")
    child_argv.append("--dry-run" if args.dry_run else "--real-run")
    return child_argv


def _extract_count(result: dict[str, object] | int, key: str) -> int:
    if isinstance(result, dict):
        return int(result.get("counts", {}).get(key, 0))
    return int(result)


def _extract_output_paths(result: dict[str, object] | int) -> list[str]:
    if isinstance(result, dict):
        return [str(path) for path in result.get("output_paths", [])]
    return []


def main(argv: list[str] | None = None, mode: str | None = None):
    # Legacy compatibility: allow main("messages") style calls.
    if isinstance(argv, str) and mode is None:
        mode = argv
        argv = None

    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else [])

    resolved_mode = _resolved_mode(args.mode, mode)
    child_argv = _build_child_argv(args)

    messages_result: dict[str, object] | int = 0
    threads_result: dict[str, object] | int = 0
    warnings: list[str] = []
    output_paths: list[str] = []

    if resolved_mode in ("messages", "message", "tasks", "task"):
        messages_result = mail_analyze_tasks.main(argv=child_argv)
        output_paths.extend(_extract_output_paths(messages_result))
        mode_out = "messages"
    elif resolved_mode in ("threads", "thread"):
        threads_result = mail_analyze_threads.main(argv=child_argv)
        output_paths.extend(_extract_output_paths(threads_result))
        mode_out = "threads"
    elif resolved_mode == "both":
        messages_result = mail_analyze_tasks.main(argv=child_argv)
        threads_result = mail_analyze_threads.main(argv=child_argv)
        output_paths.extend(_extract_output_paths(messages_result))
        output_paths.extend(_extract_output_paths(threads_result))
        mode_out = "both"
    else:
        raise ValueError(f"Unknown analysis mode: {resolved_mode}. Use 'messages', 'threads', or 'both'.")

    messages_count = _extract_count(messages_result, "messages_analyzed")
    threads_count = _extract_count(threads_result, "threads_analyzed")

    result = build_result(
        status="ok",
        command=COMMAND_NAME,
        dry_run=args.dry_run,
        no_send=args.no_send,
        readonly=args.readonly,
        counts={"messages": messages_count, "threads": threads_count},
        output_paths=output_paths,
        warnings=warnings,
        risk_flags=["imap_access", "local_output_write", "human_review_required"],
        human_review_required=True,
        errors=[],
    )
    result["mode"] = mode_out
    emit_result(result, output_json=args.output_json)

    if args.output_json:
        return result
    return {"mode": mode_out, "messages": messages_count, "threads": threads_count}


if __name__ == "__main__":
    import sys

    main(argv=sys.argv[1:])
