import json
from pathlib import Path

import pytest

import mail_show_pipeline_status


def test_main_prints_last_pipeline_status(monkeypatch, tmp_path, capsys):
    status_path = tmp_path / "state" / "last_pipeline_run.json"
    status_path.parent.mkdir()
    status = {
        "mode": "both",
        "reset": False,
        "messages": 2,
        "threads": 3,
        "state_file": "/tmp/mail_state.json",
    }
    status_path.write_text(json.dumps(status), encoding="utf-8")
    monkeypatch.setattr(mail_show_pipeline_status, "STATUS_PATH", status_path)

    result = mail_show_pipeline_status.main(argv=[])

    assert result == status
    assert capsys.readouterr().out == (
        "Pipeline status\n"
        "Mode: both\n"
        "Reset: False\n"
        "Messages analyzed: 2\n"
        "Threads analyzed: 3\n"
        "State file: /tmp/mail_state.json\n"
    )


def test_load_pipeline_status_raises_clear_error_when_missing(tmp_path):
    status_path = tmp_path / "state" / "last_pipeline_run.json"

    with pytest.raises(FileNotFoundError, match="last pipeline run status not found"):
        mail_show_pipeline_status.load_pipeline_status(status_path)


def test_main_supports_output_json(monkeypatch, tmp_path, capsys):
    status_path = tmp_path / "state" / "last_pipeline_run.json"
    status_path.parent.mkdir()
    status = {
        "mode": "both",
        "reset": False,
        "messages": 7,
        "threads": 4,
        "state_file": "/tmp/mail_state.json",
    }
    status_path.write_text(json.dumps(status), encoding="utf-8")

    result = mail_show_pipeline_status.main(
        argv=["--status-path", str(status_path), "--output-json"]
    )

    assert result == status
    parsed = json.loads(capsys.readouterr().out.strip())
    assert parsed["status"] == "ok"
    assert parsed["command"] == "mail_show_pipeline_status"
    assert parsed["dry_run"] is True
    assert parsed["no_send"] is True
    assert parsed["readonly"] is True
    assert parsed["counts"] == {"messages": 7, "threads": 4}
    assert parsed["output_paths"] == [str(status_path.resolve())]
    assert parsed["human_review_required"] is False


def test_main_does_not_write_status_file(monkeypatch, tmp_path):
    status_path = tmp_path / "state" / "last_pipeline_run.json"
    status_path.parent.mkdir()
    original = {
        "mode": "both",
        "reset": False,
        "messages": 2,
        "threads": 3,
        "state_file": "/tmp/mail_state.json",
    }
    status_path.write_text(json.dumps(original), encoding="utf-8")
    before = status_path.read_text(encoding="utf-8")

    result = mail_show_pipeline_status.main(argv=["--status-path", str(status_path)])

    after = status_path.read_text(encoding="utf-8")
    assert result == original
    assert after == before


def test_script_has_no_imap_or_smtp_imports():
    script_text = Path(mail_show_pipeline_status.__file__).read_text(encoding="utf-8")

    assert "import imaplib" not in script_text
    assert "import smtplib" not in script_text
    assert "IMAP4_SSL" not in script_text
    assert "SMTP_SSL" not in script_text
