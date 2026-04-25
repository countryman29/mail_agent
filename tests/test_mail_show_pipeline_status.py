import json

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

    result = mail_show_pipeline_status.main()

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
