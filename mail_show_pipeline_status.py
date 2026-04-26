import json
from pathlib import Path

from mail_cli import add_common_args
from mail_result import build_result, emit_result


BASE_DIR = Path(__file__).resolve().parent
STATUS_PATH = BASE_DIR / "state" / "last_pipeline_run.json"
COMMAND_NAME = "mail_show_pipeline_status"


def load_pipeline_status(path=STATUS_PATH):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"last pipeline run status not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Show local pipeline status")
    add_common_args(parser)
    parser.add_argument("--status-path", default=None, help="Optional override for status JSON path")
    return parser


def _print_human_status(status: dict[str, object]):
    print("Pipeline status")
    print(f"Mode: {status['mode']}")
    print(f"Reset: {status['reset']}")
    print(f"Messages analyzed: {status['messages']}")
    print(f"Threads analyzed: {status['threads']}")
    print(f"State file: {status['state_file']}")


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)

    status_path = Path(args.status_path).expanduser().resolve() if args.status_path else STATUS_PATH
    status = load_pipeline_status(status_path)

    result = build_result(
        status="ok",
        command=COMMAND_NAME,
        dry_run=args.dry_run,
        no_send=args.no_send,
        readonly=args.readonly,
        counts={
            "messages": int(status.get("messages", 0)),
            "threads": int(status.get("threads", 0)),
        },
        output_paths=[str(status_path)],
        warnings=[],
        risk_flags=[],
        human_review_required=False,
        errors=[],
    )
    emit_result(result, output_json=args.output_json)

    if not args.output_json:
        _print_human_status(status)
    return status


if __name__ == "__main__":
    main()
