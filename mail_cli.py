import argparse


DEFAULT_LIMIT = 50


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("limit must be a positive integer")
    return parsed


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--folder", default=None, help="Mailbox folder name")
    parser.add_argument("--limit", type=positive_int, default=DEFAULT_LIMIT, help="Maximum number of items to process")
    parser.add_argument("--date-from", dest="date_from", default=None, help="Start date filter (YYYY-MM-DD)")
    parser.add_argument("--date-to", dest="date_to", default=None, help="End date filter (YYYY-MM-DD)")
    parser.add_argument("--thread-id", dest="thread_id", default=None, help="Thread identifier")
    parser.add_argument("--message-id", dest="message_id", default=None, help="Message identifier")
    parser.add_argument("--output-dir", dest="output_dir", default=None, help="Output directory path")
    parser.add_argument("--output-json", dest="output_json", action="store_true", default=False, help="Emit JSON result")

    # Safe defaults for runtime behavior.
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Run without external side effects")
    parser.add_argument("--real-run", dest="dry_run", action="store_false", help="Allow non-dry-run behavior")

    parser.add_argument("--no-send", dest="no_send", action="store_true", default=True, help="Block sending actions")
    parser.add_argument("--allow-send", dest="no_send", action="store_false", help="Allow sending actions")

    parser.add_argument("--readonly", dest="readonly", action="store_true", default=True, help="Use read-only mailbox operations")
    parser.add_argument("--readwrite", dest="readonly", action="store_false", help="Allow read-write mailbox operations")

    parser.add_argument(
        "--no-state-write",
        dest="no_state_write",
        action="store_true",
        default=False,
        help="Do not write state files",
    )
    parser.add_argument("--state-write", dest="no_state_write", action="store_false", help="Allow state file writes")

    parser.add_argument("--mode", default=None, help="Command mode selector")
    return parser


def build_common_parser(description: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    return add_common_args(parser)


def parse_common_args(argv: list[str] | None = None, description: str | None = None) -> argparse.Namespace:
    parser = build_common_parser(description=description)
    return parser.parse_args(argv)
