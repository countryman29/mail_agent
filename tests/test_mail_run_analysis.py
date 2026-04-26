import pytest
import json
from pathlib import Path

import mail_run_analysis


def patch_analysis_mains(monkeypatch):
    calls = []

    def fake_tasks_main(argv=None):
        calls.append(("messages", argv))
        return 2

    def fake_threads_main(argv=None):
        calls.append(("threads", argv))
        return 3

    monkeypatch.setattr(mail_run_analysis.mail_analyze_tasks, "main", fake_tasks_main)
    monkeypatch.setattr(mail_run_analysis.mail_analyze_threads, "main", fake_threads_main)
    return calls


def test_main_runs_both_analyses_by_default(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)
    monkeypatch.delenv(mail_run_analysis.MODE_ENV_VAR, raising=False)

    result = mail_run_analysis.main()

    assert calls == [
        ("messages", ["--limit", "50", "--readonly", "--dry-run"]),
        ("threads", ["--limit", "50", "--readonly", "--dry-run"]),
    ]
    assert result == {"mode": "both", "messages": 2, "threads": 3}


def test_main_runs_message_analysis_only(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)

    result = mail_run_analysis.main(mode="messages")

    assert calls == [("messages", ["--limit", "50", "--readonly", "--dry-run"])]
    assert result == {"mode": "messages", "messages": 2, "threads": 0}


def test_main_runs_thread_analysis_only(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)

    result = mail_run_analysis.main(mode="threads")

    assert calls == [("threads", ["--limit", "50", "--readonly", "--dry-run"])]
    assert result == {"mode": "threads", "messages": 0, "threads": 3}


def test_main_uses_env_mode_when_no_explicit_mode(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)
    monkeypatch.setenv(mail_run_analysis.MODE_ENV_VAR, "thread")

    result = mail_run_analysis.main()

    assert calls == [("threads", ["--limit", "50", "--readonly", "--dry-run"])]
    assert result == {"mode": "threads", "messages": 0, "threads": 3}


def test_main_rejects_unknown_mode(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)

    with pytest.raises(ValueError, match="Unknown analysis mode"):
        mail_run_analysis.main(mode="unknown")

    assert calls == []


def test_main_legacy_main_mode_positional_call(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)

    result = mail_run_analysis.main("messages")

    assert calls == [("messages", ["--limit", "50", "--readonly", "--dry-run"])]
    assert result == {"mode": "messages", "messages": 2, "threads": 0}


def test_main_propagates_cli_flags_to_child_argv(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)

    result = mail_run_analysis.main(
        argv=[
            "--mode",
            "both",
            "--folder",
            "INBOX/Test",
            "--limit",
            "7",
            "--output-dir",
            "/tmp/out",
            "--no-state-write",
            "--readwrite",
            "--real-run",
        ]
    )

    expected_argv = [
        "--limit",
        "7",
        "--folder",
        "INBOX/Test",
        "--output-dir",
        "/tmp/out",
        "--no-state-write",
        "--readwrite",
        "--real-run",
    ]
    assert calls == [("messages", expected_argv), ("threads", expected_argv)]
    assert result == {"mode": "both", "messages": 2, "threads": 3}


def test_main_output_json_emits_valid_aggregate_result(monkeypatch, capsys):
    calls = []

    def fake_tasks_main(argv=None):
        print("NOISY_TASK_LOG")
        calls.append(("messages", argv))
        return {
            "status": "ok",
            "counts": {"messages_analyzed": 4},
            "output_paths": ["analysis/messages_a.md"],
        }

    def fake_threads_main(argv=None):
        print("NOISY_THREAD_LOG")
        calls.append(("threads", argv))
        return {
            "status": "ok",
            "counts": {"threads_analyzed": 5},
            "output_paths": ["analysis/threads_a.md"],
        }

    monkeypatch.setattr(mail_run_analysis.mail_analyze_tasks, "main", fake_tasks_main)
    monkeypatch.setattr(mail_run_analysis.mail_analyze_threads, "main", fake_threads_main)

    result = mail_run_analysis.main(argv=["--output-json", "--mode", "both"])

    printed = capsys.readouterr().out.strip()
    parsed = json.loads(printed)
    assert result == parsed
    assert parsed["status"] == "ok"
    assert parsed["command"] == "mail_run_analysis"
    assert parsed["dry_run"] is True
    assert parsed["no_send"] is True
    assert parsed["readonly"] is True
    assert parsed["counts"] == {"messages": 4, "threads": 5}
    assert parsed["output_paths"] == ["analysis/messages_a.md", "analysis/threads_a.md"]
    assert parsed["mode"] == "both"


def test_script_has_no_smtp_or_send_imports():
    script_text = Path(mail_run_analysis.__file__).read_text(encoding="utf-8")

    assert "import smtplib" not in script_text
    assert "mail_send_reply" not in script_text
    assert "SMTP_SSL" not in script_text
    assert "send_message" not in script_text
    assert "sendmail" not in script_text
