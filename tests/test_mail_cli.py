import pytest

import mail_cli


def test_parse_common_args_uses_safe_defaults():
    args = mail_cli.parse_common_args([])

    assert args.folder is None
    assert args.limit == mail_cli.DEFAULT_LIMIT
    assert args.date_from is None
    assert args.date_to is None
    assert args.thread_id is None
    assert args.message_id is None
    assert args.output_dir is None
    assert args.output_json is False

    assert args.dry_run is True
    assert args.no_send is True
    assert args.readonly is True
    assert args.no_state_write is False
    assert args.mode is None


def test_parse_common_args_accepts_overrides():
    args = mail_cli.parse_common_args(
        [
            "--folder",
            "INBOX/Test",
            "--limit",
            "10",
            "--date-from",
            "2026-01-01",
            "--date-to",
            "2026-01-31",
            "--thread-id",
            "thread-1",
            "--message-id",
            "msg-1",
            "--output-dir",
            "tmp/out",
            "--output-json",
            "--real-run",
            "--allow-send",
            "--readwrite",
            "--no-state-write",
            "--mode",
            "analysis",
        ]
    )

    assert args.folder == "INBOX/Test"
    assert args.limit == 10
    assert args.date_from == "2026-01-01"
    assert args.date_to == "2026-01-31"
    assert args.thread_id == "thread-1"
    assert args.message_id == "msg-1"
    assert args.output_dir == "tmp/out"
    assert args.output_json is True
    assert args.dry_run is False
    assert args.no_send is False
    assert args.readonly is False
    assert args.no_state_write is True
    assert args.mode == "analysis"


@pytest.mark.parametrize("value", ["0", "-1"])
def test_limit_must_be_positive_integer(value):
    with pytest.raises(SystemExit):
        mail_cli.parse_common_args(["--limit", value])
