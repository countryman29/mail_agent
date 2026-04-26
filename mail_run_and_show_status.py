import argparse
import io
from contextlib import redirect_stdout

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
    return argv


def _run_child(main_fn, argv: list[str], suppress_stdout: bool):
    if not suppress_stdout:
        return main_fn(argv=argv)
    with io.StringIO() as buffer, redirect_stdout(buffer):
        return main_fn(argv=argv)


def _extract_counts(pipeline_result: dict[str, object] | object, status_result: dict[str, object] | object) -> dict[str, int]:
    if isinstance(pipeline_result, dict):
        counts = pipeline_result.get("counts")
        if isinstance(counts, dict):
            if "messages" in counts or "threads" in counts:
                return {
                    "messages": int(counts.get("messages", 0)),
                    "threads": int(counts.get("threads", 0)),
                }
            return {
                "messages": int(counts.get("messages_analyzed", 0)),
                "threads": int(counts.get("threads_analyzed", 0)),
            }
        if "messages" in pipeline_result or "threads" in pipeline_result:
            return {
                "messages": int(pipeline_result.get("messages", 0)),
                "threads": int(pipeline_result.get("threads", 0)),
            }

    if isinstance(status_result, dict):
        return {
            "messages": int(status_result.get("messages", 0)),
            "threads": int(status_result.get("threads", 0)),
        }
    return {"messages": 0, "threads": 0}


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else [])

    suppress_child_stdout = bool(args.output_json)
    pipeline_result = _run_child(
        mail_run_pipeline.main,
        _build_pipeline_argv(args),
        suppress_stdout=suppress_child_stdout,
    )

    status_result: dict[str, object]
    skip_status_in_dry_run_json = bool(args.output_json and args.dry_run)
    if skip_status_in_dry_run_json:
        status_result = {
            "status": "skipped",
            "reason": "dry_run_status_not_written",
            "stale": True,
        }
    else:
        status_result = _run_child(
            mail_show_pipeline_status.main,
            _build_status_argv(args),
            suppress_stdout=suppress_child_stdout,
        )

    counts = _extract_counts(pipeline_result, status_result)

    output_paths: list[str] = []
    warnings: list[str] = []
    risk_flags = ["imap_access", "local_output_write", "human_review_required"]
    if isinstance(pipeline_result, dict):
        output_paths.extend([str(path) for path in pipeline_result.get("output_paths", [])])
        warnings.extend([str(w) for w in pipeline_result.get("warnings", [])])
    if skip_status_in_dry_run_json:
        warnings.append("Status read skipped in dry-run JSON mode to avoid stale status file data")
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
