import json
import os
from pathlib import Path

from mail_cli import add_common_args
from mail_result import build_result, emit_result
import mail_reset_analysis_state
import mail_run_analysis


RESET_ENV_VAR = "MAIL_ANALYSIS_RESET"
COMMAND_NAME = "mail_run_pipeline"


def env_flag(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def save_last_pipeline_run(summary: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Run pipeline analysis with optional reset")
    add_common_args(parser)
    parser.add_argument("--reset", action="store_true", default=None, help="Reset analysis state before run")
    parser.add_argument("--status-path", default=None, help="Override output path for last_pipeline_run.json")
    return parser


def _resolve_mode(args_mode: str | None, explicit_mode: str | None) -> str:
    if explicit_mode is not None:
        return mail_run_analysis.normalize_mode(explicit_mode)
    if args_mode is not None:
        return mail_run_analysis.normalize_mode(args_mode)
    return mail_run_analysis.normalize_mode(os.getenv(mail_run_analysis.MODE_ENV_VAR))


def _build_analysis_child_argv(args, selected_mode: str) -> list[str]:
    child_argv: list[str] = ["--mode", selected_mode, "--limit", str(args.limit)]
    if args.folder:
        child_argv.extend(["--folder", args.folder])
    if args.output_dir:
        child_argv.extend(["--output-dir", args.output_dir])
    if args.no_state_write:
        child_argv.append("--no-state-write")
    child_argv.append("--readonly" if args.readonly else "--readwrite")
    child_argv.append("--dry-run" if args.dry_run else "--real-run")
    return child_argv


def _extract_counts(result: dict[str, object]) -> tuple[int, int]:
    counts = result.get("counts")
    if isinstance(counts, dict):
        if "messages" in counts or "threads" in counts:
            return int(counts.get("messages", 0)), int(counts.get("threads", 0))
        return int(counts.get("messages_analyzed", 0)), int(counts.get("threads_analyzed", 0))
    return int(result.get("messages", 0)), int(result.get("threads", 0))


def main(argv: list[str] | None = None, mode: str | None = None, reset: bool | None = None):
    # Legacy compatibility: main("messages")
    if isinstance(argv, str) and mode is None:
        mode = argv
        argv = None

    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else [])

    selected_mode = _resolve_mode(args.mode, mode)
    env_reset = env_flag(os.getenv(RESET_ENV_VAR))
    should_reset_requested = env_reset if reset is None and args.reset is None else (args.reset if reset is None else reset)
    should_reset_requested = bool(should_reset_requested)
    status_path = (
        Path(args.status_path).expanduser().resolve()
        if args.status_path
        else (mail_reset_analysis_state.STATE_PATH.parent / "last_pipeline_run.json")
    )

    warnings: list[str] = []
    reset_executed = False

    if should_reset_requested and args.dry_run:
        warnings.append("Reset requested but skipped because dry run is enabled")
    elif should_reset_requested:
        mail_reset_analysis_state.main()
        reset_executed = True

    analysis_child_argv = _build_analysis_child_argv(args, selected_mode)
    analysis_result = mail_run_analysis.main(argv=analysis_child_argv)
    messages_count, threads_count = _extract_counts(analysis_result)

    summary = {
        "mode": selected_mode,
        "reset": should_reset_requested,
        "reset_executed": reset_executed,
        "messages": messages_count,
        "threads": threads_count,
        "state_file": str(mail_reset_analysis_state.STATE_PATH),
        "status_file": str(status_path),
    }

    if args.dry_run:
        warnings.append("Dry run enabled: status file was not written")
    else:
        save_last_pipeline_run(summary, status_path)

    output_paths: list[str] = []
    if isinstance(analysis_result, dict):
        output_paths.extend([str(path) for path in analysis_result.get("output_paths", [])])
    if not args.dry_run:
        output_paths.append(str(status_path))

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
    result["mode"] = selected_mode
    result["reset"] = should_reset_requested
    result["reset_executed"] = reset_executed
    result["state_file"] = str(mail_reset_analysis_state.STATE_PATH)
    result["status_file"] = str(status_path)
    emit_result(result, output_json=args.output_json)

    if args.output_json:
        return result

    print("Pipeline complete")
    print(f"Mode: {summary['mode']}")
    print(f"Reset: {summary['reset']}")
    print(f"Messages analyzed: {summary['messages']}")
    print(f"Threads analyzed: {summary['threads']}")
    print(f"State file: {summary['state_file']}")
    print(f"Status file: {summary['status_file']}")
    print("Output folders:")
    print("  - analysis/")
    print("  - tasks/")
    return summary


if __name__ == "__main__":
    import sys

    main(argv=sys.argv[1:])
