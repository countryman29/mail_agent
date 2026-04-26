import json
from pathlib import Path

import mail_run_pipeline


def patch_pipeline_deps(monkeypatch, tmp_path):
    calls = []
    state_path = tmp_path / "state" / "mail_state.json"
    monkeypatch.setattr(mail_run_pipeline.mail_reset_analysis_state, "STATE_PATH", state_path)
    monkeypatch.setattr(mail_run_pipeline.mail_reset_analysis_state, "main", lambda: calls.append("reset"))
    monkeypatch.setattr(
        mail_run_pipeline.mail_run_analysis,
        "main",
        lambda argv=None: calls.append(("analysis", argv))
        or {
            "status": "ok",
            "counts": {"messages": 2, "threads": 3},
            "output_paths": ["analysis/a.md", "tasks/a.md"],
        },
    )
    return calls, state_path.parent / "last_pipeline_run.json"


def test_main_runs_both_without_reset_by_default(monkeypatch, tmp_path, capsys):
    calls, summary_path = patch_pipeline_deps(monkeypatch, tmp_path)
    monkeypatch.delenv(mail_run_pipeline.RESET_ENV_VAR, raising=False)
    monkeypatch.delenv(mail_run_pipeline.mail_run_analysis.MODE_ENV_VAR, raising=False)

    result = mail_run_pipeline.main()

    assert calls == [("analysis", ["--mode", "both", "--limit", "50", "--readonly", "--dry-run"])]
    assert result == {
        "mode": "both",
        "reset": False,
        "reset_executed": False,
        "messages": 2,
        "threads": 3,
        "state_file": str(mail_run_pipeline.mail_reset_analysis_state.STATE_PATH),
        "status_file": str(summary_path),
    }
    assert not summary_path.exists()
    assert capsys.readouterr().out == (
        "Pipeline complete\n"
        "Mode: both\n"
        "Reset: False\n"
        "Messages analyzed: 2\n"
        "Threads analyzed: 3\n"
        f"State file: {mail_run_pipeline.mail_reset_analysis_state.STATE_PATH}\n"
        f"Status file: {summary_path}\n"
        "Output folders:\n"
        "  - analysis/\n"
        "  - tasks/\n"
    )


def test_main_runs_reset_before_analysis_when_argument_enabled(monkeypatch, tmp_path):
    calls, summary_path = patch_pipeline_deps(monkeypatch, tmp_path)

    result = mail_run_pipeline.main(mode="messages", reset=True, argv=["--real-run"])

    assert calls == ["reset", ("analysis", ["--mode", "messages", "--limit", "50", "--readonly", "--real-run"])]
    assert result == {
        "mode": "messages",
        "reset": True,
        "reset_executed": True,
        "messages": 2,
        "threads": 3,
        "state_file": str(mail_run_pipeline.mail_reset_analysis_state.STATE_PATH),
        "status_file": str(summary_path),
    }
    assert json.loads(summary_path.read_text(encoding="utf-8")) == result


def test_main_uses_env_reset_and_env_mode(monkeypatch, tmp_path, capsys):
    calls, summary_path = patch_pipeline_deps(monkeypatch, tmp_path)
    monkeypatch.setenv(mail_run_pipeline.RESET_ENV_VAR, "1")
    monkeypatch.setenv(mail_run_pipeline.mail_run_analysis.MODE_ENV_VAR, "threads")

    result = mail_run_pipeline.main()

    assert calls == [("analysis", ["--mode", "threads", "--limit", "50", "--readonly", "--dry-run"])]
    assert result == {
        "mode": "threads",
        "reset": True,
        "reset_executed": False,
        "messages": 2,
        "threads": 3,
        "state_file": str(mail_run_pipeline.mail_reset_analysis_state.STATE_PATH),
        "status_file": str(summary_path),
    }
    assert not summary_path.exists()
    assert "Reset: True" in capsys.readouterr().out


def test_main_supports_threads_mode_without_reset(monkeypatch, tmp_path):
    calls, summary_path = patch_pipeline_deps(monkeypatch, tmp_path)
    monkeypatch.setenv(mail_run_pipeline.RESET_ENV_VAR, "0")

    result = mail_run_pipeline.main(mode="threads", argv=["--real-run"])

    assert calls == [("analysis", ["--mode", "threads", "--limit", "50", "--readonly", "--real-run"])]
    assert result == {
        "mode": "threads",
        "reset": False,
        "reset_executed": False,
        "messages": 2,
        "threads": 3,
        "state_file": str(mail_run_pipeline.mail_reset_analysis_state.STATE_PATH),
        "status_file": str(summary_path),
    }
    assert json.loads(summary_path.read_text(encoding="utf-8")) == result


def test_main_reset_requested_in_dry_run_adds_warning_and_skips_reset(monkeypatch, tmp_path, capsys):
    calls, summary_path = patch_pipeline_deps(monkeypatch, tmp_path)

    result = mail_run_pipeline.main(argv=["--reset", "--output-json"])

    parsed = json.loads(capsys.readouterr().out.strip())
    assert calls == [("analysis", ["--mode", "both", "--limit", "50", "--readonly", "--dry-run"])]
    assert result == parsed
    assert parsed["reset"] is True
    assert parsed["reset_executed"] is False
    assert "Reset requested but skipped because dry run is enabled" in parsed["warnings"]
    assert "Dry run enabled: status file was not written" in parsed["warnings"]
    assert not summary_path.exists()


def test_main_propagates_child_argv(monkeypatch, tmp_path):
    calls, _ = patch_pipeline_deps(monkeypatch, tmp_path)

    result = mail_run_pipeline.main(
        argv=[
            "--mode",
            "messages",
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

    assert calls == [
        (
            "analysis",
            [
                "--mode",
                "messages",
                "--limit",
                "7",
                "--folder",
                "INBOX/Test",
                "--output-dir",
                "/tmp/out",
                "--no-state-write",
                "--readwrite",
                "--real-run",
            ],
        )
    ]
    assert result["mode"] == "messages"


def test_main_output_json_contains_required_fields(monkeypatch, tmp_path, capsys):
    calls, summary_path = patch_pipeline_deps(monkeypatch, tmp_path)

    def noisy_analysis_main(argv=None):
        print("NOISY_ANALYSIS_LOG")
        calls.append(("analysis", argv))
        return {
            "status": "ok",
            "counts": {"messages": 2, "threads": 3},
            "output_paths": ["analysis/a.md", "tasks/a.md"],
        }

    monkeypatch.setattr(mail_run_pipeline.mail_run_analysis, "main", noisy_analysis_main)

    result = mail_run_pipeline.main(argv=["--mode", "both", "--output-json", "--real-run"])

    printed = capsys.readouterr().out.strip()
    assert len(printed.splitlines()) == 1
    parsed = json.loads(printed)
    assert result == parsed
    assert parsed["status"] == "ok"
    assert parsed["command"] == "mail_run_pipeline"
    assert parsed["dry_run"] is False
    assert parsed["no_send"] is True
    assert parsed["readonly"] is True
    assert parsed["counts"] == {"messages": 2, "threads": 3}
    assert parsed["messages"] == 2
    assert parsed["threads"] == 3
    assert parsed["mode"] == "both"
    assert parsed["reset"] is False
    assert parsed["reset_executed"] is False
    assert parsed["state_file"] == str(mail_run_pipeline.mail_reset_analysis_state.STATE_PATH)
    assert parsed["status_file"] == str(summary_path)
    assert str(summary_path) in parsed["output_paths"]
    assert calls == [("analysis", ["--mode", "both", "--limit", "50", "--readonly", "--real-run"])]


def test_script_has_no_smtp_or_send_imports():
    script_text = Path(mail_run_pipeline.__file__).read_text(encoding="utf-8")

    assert "import smtplib" not in script_text
    assert "mail_send_reply" not in script_text
    assert "SMTP_SSL" not in script_text
    assert "send_message" not in script_text
    assert "sendmail" not in script_text
