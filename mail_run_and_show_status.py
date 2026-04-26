import argparse

from mail_cli import add_common_args
from mail_result import build_result, emit_result
import mail_run_pipeline
import mail_show_pipeline_status


COMMAND_NAME = "mail_run_and_show_status"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run pipeline then show status")
    add_common_args(parser)
    parser.add_argument("--reset", action="store_true", default=False, help="Request state reset in pipeline run")
    parser.add_argument("--status-path", default=None, help="Override status file path")
    return parser


def _build_pipeline_argv(args) -> list[str]:
    argv: list[str] = ["--limit", str(args.limit)]
    if args.mode:
        argv.extend(["--mode", args.mode])
    if args.folder:
        argv.extend(["--folder", args.folder])
    if args.output_dir:
        argv.extend(["--output-dir", args.output_dir])
    if args.no_state_write:
        argv.append("--no-state-write")
    argv.append("--readonly" if args.readonly else "--readwrite")
    argv.append("--dry-run" if args.dry_run else "--real-run")
    if args.reset:
        argv.append("--reset")
    if args.status_path:
        argv.extend(["--status-path", args.status_path])
    if args.output_json:
        argv.append("--output-json")
    return argv


def _build_status_argv(args) -> list[str]:
    argv: list[str] = []
    if args.status_path:
        argv.extend(["--status-path", args.status_path])
    argv.append("--readonly" if args.readonly else "--readwrite")
    argv.append("--dry-run" if args.dry_run else "--real-run")
    if args.output_json:
        argv.append("--output-json")
    return argv


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else [])

    pipeline_result = mail_run_pipeline.main(argv=_build_pipeline_argv(args))
    status_result = mail_show_pipeline_status.main(argv=_build_status_argv(args))

    pipeline_counts = pipeline_result.get("counts", {}) if isinstance(pipeline_result, dict) else {}
    status_messages = int(status_result.get("messages", 0)) if isinstance(status_result, dict) else 0
    status_threads = int(status_result.get("threads", 0)) if isinstance(status_result, dict) else 0
    counts = {
        "messages": int(pipeline_counts.get("messages", status_messages)),
        "threads": int(pipeline_counts.get("threads", status_threads)),
    }

    output_paths: list[str] = []
    warnings: list[str] = []
    risk_flags = ["imap_access", "local_output_write", "human_review_required"]
    if isinstance(pipeline_result, dict):
        output_paths.extend([str(path) for path in pipeline_result.get("output_paths", [])])
        warnings.extend([str(w) for w in pipeline_result.get("warnings", [])])
    status_path_value = None
    if isinstance(status_result, dict):
        status_path_value = status_result.get("state_file")
    if isinstance(pipeline_result, dict) and pipeline_result.get("status_file"):
        status_path_value = pipeline_result.get("status_file")

    result = build_result(
        status="ok",
        command=COMMAND_NAME,
        dry_run=args.dry_run,
        no_send=args.no_send,
        readonly=args.readonly,
        counts=counts,
        output_paths=output_paths,
        warnings=warnings,
        risk_flags=risk_flags,
        human_review_required=True,
        errors=[],
    )
    result["pipeline_result"] = pipeline_result
    result["status_result"] = status_result
    if status_path_value is not None:
        result["status_file"] = str(status_path_value)
    emit_result(result, output_json=args.output_json)

    if args.output_json:
        return result
    return status_result


if __name__ == "__main__":
    import sys

    main(argv=sys.argv[1:])
