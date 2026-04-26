import json
from pathlib import Path

import mail_run_and_show_status


def test_main_runs_pipeline_then_shows_status_with_default_dry_run(monkeypatch):
    calls = []
    status = {"mode": "both", "messages": 2, "threads": 3, "state_file": "/tmp/state/mail_state.json"}
    pipeline_result = {
        "status": "ok",
        "counts": {"messages": 2, "threads": 3},
        "output_paths": [],
        "warnings": ["Dry run enabled: status file was not written"],
    }

    monkeypatch.setattr(
        mail_run_and_show_status.mail_run_pipeline,
        "main",
        lambda argv=None: calls.append(("pipeline", argv)) or pipeline_result,
    )
    monkeypatch.setattr(
        mail_run_and_show_status.mail_show_pipeline_status,
        "main",
        lambda argv=None: calls.append(("status", argv)) or status,
    )

    result = mail_run_and_show_status.main(argv=[])

    assert calls == [
        ("pipeline", ["--limit", "50", "--readonly", "--dry-run"]),
        ("status", ["--readonly", "--dry-run"]),
    ]
    assert result == status


def test_main_real_run_propagates_real_run_flags(monkeypatch):
    calls = []
    status = {"mode": "messages", "messages": 1, "threads": 0, "state_file": "/tmp/state/mail_state.json"}
    pipeline_result = {"status": "ok", "counts": {"messages": 1, "threads": 0}, "output_paths": [], "warnings": []}

    monkeypatch.setattr(
        mail_run_and_show_status.mail_run_pipeline,
        "main",
        lambda argv=None: calls.append(("pipeline", argv)) or pipeline_result,
    )
    monkeypatch.setattr(
        mail_run_and_show_status.mail_show_pipeline_status,
        "main",
        lambda argv=None: calls.append(("status", argv)) or status,
    )

    result = mail_run_and_show_status.main(argv=["--mode", "messages", "--real-run"])

    assert calls == [
        ("pipeline", ["--limit", "50", "--mode", "messages", "--readonly", "--real-run"]),
        ("status", ["--readonly", "--real-run"]),
    ]
    assert result == status


def test_main_propagates_reset_in_dry_run(monkeypatch):
    calls = []
    status = {"mode": "both", "messages": 2, "threads": 3, "state_file": "/tmp/state/mail_state.json"}
    pipeline_result = {
        "status": "ok",
        "counts": {"messages": 2, "threads": 3},
        "output_paths": [],
        "warnings": ["Reset requested but skipped because dry run is enabled"],
    }

    monkeypatch.setattr(
        mail_run_and_show_status.mail_run_pipeline,
        "main",
        lambda argv=None: calls.append(("pipeline", argv)) or pipeline_result,
    )
    monkeypatch.setattr(
        mail_run_and_show_status.mail_show_pipeline_status,
        "main",
        lambda argv=None: calls.append(("status", argv)) or status,
    )

    result = mail_run_and_show_status.main(argv=["--reset"])

    assert calls == [
        ("pipeline", ["--limit", "50", "--readonly", "--dry-run", "--reset"]),
        ("status", ["--readonly", "--dry-run"]),
    ]
    assert result == status


def test_main_propagates_child_argv(monkeypatch):
    calls = []
    status = {"mode": "threads", "messages": 0, "threads": 5, "state_file": "/tmp/state/mail_state.json"}
    pipeline_result = {"status": "ok", "counts": {"messages": 0, "threads": 5}, "output_paths": [], "warnings": []}

    monkeypatch.setattr(
        mail_run_and_show_status.mail_run_pipeline,
        "main",
        lambda argv=None: calls.append(("pipeline", argv)) or pipeline_result,
    )
    monkeypatch.setattr(
        mail_run_and_show_status.mail_show_pipeline_status,
        "main",
        lambda argv=None: calls.append(("status", argv)) or status,
    )

    mail_run_and_show_status.main(
        argv=[
            "--mode",
            "threads",
            "--folder",
            "INBOX/Test",
            "--limit",
            "7",
            "--output-dir",
            "/tmp/out",
            "--no-state-write",
            "--readwrite",
            "--real-run",
            "--status-path",
            "/tmp/custom/last_pipeline_run.json",
        ]
    )

    assert calls == [
        (
            "pipeline",
            [
                "--limit",
                "7",
                "--mode",
                "threads",
                "--folder",
                "INBOX/Test",
                "--output-dir",
                "/tmp/out",
                "--no-state-write",
                "--readwrite",
                "--real-run",
                "--status-path",
                "/tmp/custom/last_pipeline_run.json",
            ],
        ),
        ("status", ["--status-path", "/tmp/custom/last_pipeline_run.json", "--readwrite", "--real-run"]),
    ]


def test_main_output_json_emits_aggregate_result(monkeypatch, capsys):
    calls = []
    status = {"mode": "both", "messages": 2, "threads": 3, "state_file": "/tmp/state/mail_state.json"}
    pipeline_result = {
        "status": "ok",
        "counts": {"messages": 2, "threads": 3},
        "output_paths": ["/tmp/analysis/a.md"],
        "warnings": ["Dry run enabled: status file was not written"],
        "status_file": "/tmp/state/last_pipeline_run.json",
    }

    monkeypatch.setattr(
        mail_run_and_show_status.mail_run_pipeline,
        "main",
        lambda argv=None: calls.append(("pipeline", argv)) or pipeline_result,
    )
    monkeypatch.setattr(
        mail_run_and_show_status.mail_show_pipeline_status,
        "main",
        lambda argv=None: calls.append(("status", argv)) or status,
    )

    result = mail_run_and_show_status.main(argv=["--output-json"])

    printed = capsys.readouterr().out.strip()
    assert len(printed.splitlines()) == 1
    parsed = json.loads(printed)
    assert result == parsed
    assert parsed["status"] == "ok"
    assert parsed["command"] == "mail_run_and_show_status"
    assert parsed["dry_run"] is True
    assert parsed["no_send"] is True
    assert parsed["readonly"] is True
    assert parsed["counts"] == {"messages": 2, "threads": 3}
    assert parsed["warnings"] == [
        "Dry run enabled: status file was not written",
        "Status read skipped in dry-run JSON mode to avoid stale status file data",
    ]
    assert parsed["pipeline_result"] == pipeline_result
    assert parsed["status_result"] == {
        "status": "skipped",
        "reason": "dry_run_status_not_written",
        "stale": True,
    }
    assert parsed["status_file"] == "/tmp/state/last_pipeline_run.json"
    assert calls == [
        ("pipeline", ["--limit", "50", "--readonly", "--dry-run", "--output-json"]),
    ]


def test_main_output_json_suppresses_noisy_child_stdout(monkeypatch, capsys):
    calls = []
    pipeline_result = {
        "status": "ok",
        "counts": {"messages": 1, "threads": 1},
        "output_paths": [],
        "warnings": ["Dry run enabled: status file was not written"],
        "status_file": "/tmp/state/last_pipeline_run.json",
    }

    def noisy_pipeline(argv=None):
        print("NOISY_PIPELINE_LOG")
        calls.append(("pipeline", argv))
        return pipeline_result

    def noisy_status(argv=None):
        print("NOISY_STATUS_LOG")
        calls.append(("status", argv))
        return {"mode": "both", "messages": 1, "threads": 1, "state_file": "/tmp/state/mail_state.json"}

    monkeypatch.setattr(mail_run_and_show_status.mail_run_pipeline, "main", noisy_pipeline)
    monkeypatch.setattr(mail_run_and_show_status.mail_show_pipeline_status, "main", noisy_status)

    result = mail_run_and_show_status.main(argv=["--output-json", "--real-run"])

    printed = capsys.readouterr().out.strip()
    assert len(printed.splitlines()) == 1
    parsed = json.loads(printed)
    assert result == parsed
    assert parsed["status"] == "ok"
    assert parsed["pipeline_result"] == pipeline_result
    assert parsed["status_result"]["mode"] == "both"
    assert calls == [
        ("pipeline", ["--limit", "50", "--readonly", "--real-run", "--output-json"]),
        ("status", ["--readonly", "--real-run"]),
    ]


def test_main_output_json_counts_fallback_to_pipeline_direct_fields(monkeypatch, capsys):
    pipeline_result = {
        "status": "ok",
        "messages": 9,
        "threads": 4,
        "output_paths": [],
        "warnings": [],
        "status_file": "/tmp/state/last_pipeline_run.json",
    }
    status = {"mode": "both", "messages": 100, "threads": 200, "state_file": "/tmp/state/mail_state.json"}

    monkeypatch.setattr(mail_run_and_show_status.mail_run_pipeline, "main", lambda argv=None: pipeline_result)
    monkeypatch.setattr(mail_run_and_show_status.mail_show_pipeline_status, "main", lambda argv=None: status)

    result = mail_run_and_show_status.main(argv=["--output-json", "--real-run"])

    parsed = json.loads(capsys.readouterr().out.strip())
    assert result == parsed
    assert parsed["counts"] == {"messages": 9, "threads": 4}


def test_script_has_no_smtp_or_send_imports():
    script_text = Path(mail_run_and_show_status.__file__).read_text(encoding="utf-8")

    assert "import smtplib" not in script_text
    assert "mail_send_reply" not in script_text
    assert "SMTP_SSL" not in script_text
    assert "send_message" not in script_text
    assert "sendmail" not in script_text
