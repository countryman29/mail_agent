import mail_run_pipeline


def patch_pipeline_deps(monkeypatch):
    calls = []
    monkeypatch.setattr(mail_run_pipeline.mail_reset_analysis_state, "main", lambda: calls.append("reset"))
    monkeypatch.setattr(
        mail_run_pipeline.mail_run_analysis,
        "main",
        lambda mode=None: calls.append(("analysis", mode)) or {"mode": mode, "messages": 2, "threads": 3},
    )
    return calls


def test_main_runs_both_without_reset_by_default(monkeypatch, capsys):
    calls = patch_pipeline_deps(monkeypatch)
    monkeypatch.delenv(mail_run_pipeline.RESET_ENV_VAR, raising=False)
    monkeypatch.delenv(mail_run_pipeline.mail_run_analysis.MODE_ENV_VAR, raising=False)

    result = mail_run_pipeline.main()

    assert calls == [("analysis", "both")]
    assert result == {"mode": "both", "messages": 2, "threads": 3}
    assert capsys.readouterr().out == (
        "Pipeline complete\n"
        "Mode: both\n"
        "Reset: False\n"
        "Messages analyzed: 2\n"
        "Threads analyzed: 3\n"
        f"State file: {mail_run_pipeline.mail_reset_analysis_state.STATE_PATH}\n"
        "Output folders:\n"
        "  - analysis/\n"
        "  - tasks/\n"
    )


def test_main_runs_reset_before_analysis_when_argument_enabled(monkeypatch):
    calls = patch_pipeline_deps(monkeypatch)

    result = mail_run_pipeline.main(mode="messages", reset=True)

    assert calls == ["reset", ("analysis", "messages")]
    assert result == {"mode": "messages", "messages": 2, "threads": 3}


def test_main_uses_env_reset_and_env_mode(monkeypatch):
    calls = patch_pipeline_deps(monkeypatch)
    monkeypatch.setenv(mail_run_pipeline.RESET_ENV_VAR, "1")
    monkeypatch.setenv(mail_run_pipeline.mail_run_analysis.MODE_ENV_VAR, "threads")

    result = mail_run_pipeline.main()

    assert calls == ["reset", ("analysis", "threads")]
    assert result == {"mode": "threads", "messages": 2, "threads": 3}


def test_main_supports_threads_mode_without_reset(monkeypatch):
    calls = patch_pipeline_deps(monkeypatch)
    monkeypatch.setenv(mail_run_pipeline.RESET_ENV_VAR, "0")

    result = mail_run_pipeline.main(mode="threads")

    assert calls == [("analysis", "threads")]
    assert result == {"mode": "threads", "messages": 2, "threads": 3}
