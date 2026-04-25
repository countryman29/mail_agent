import mail_run_pipeline


def patch_pipeline_deps(monkeypatch):
    calls = []
    monkeypatch.setattr(mail_run_pipeline.mail_reset_analysis_state, "main", lambda: calls.append("reset"))
    monkeypatch.setattr(mail_run_pipeline.mail_run_analysis, "main", lambda mode=None: calls.append(("analysis", mode)))
    return calls


def test_main_runs_both_without_reset_by_default(monkeypatch, capsys):
    calls = patch_pipeline_deps(monkeypatch)
    monkeypatch.delenv(mail_run_pipeline.RESET_ENV_VAR, raising=False)
    monkeypatch.delenv(mail_run_pipeline.mail_run_analysis.MODE_ENV_VAR, raising=False)

    mail_run_pipeline.main()

    assert calls == [("analysis", "both")]
    assert "Pipeline complete: mode=both, reset=False" in capsys.readouterr().out


def test_main_runs_reset_before_analysis_when_argument_enabled(monkeypatch):
    calls = patch_pipeline_deps(monkeypatch)

    mail_run_pipeline.main(mode="messages", reset=True)

    assert calls == ["reset", ("analysis", "messages")]


def test_main_uses_env_reset_and_env_mode(monkeypatch):
    calls = patch_pipeline_deps(monkeypatch)
    monkeypatch.setenv(mail_run_pipeline.RESET_ENV_VAR, "1")
    monkeypatch.setenv(mail_run_pipeline.mail_run_analysis.MODE_ENV_VAR, "threads")

    mail_run_pipeline.main()

    assert calls == ["reset", ("analysis", "threads")]


def test_main_supports_threads_mode_without_reset(monkeypatch):
    calls = patch_pipeline_deps(monkeypatch)
    monkeypatch.setenv(mail_run_pipeline.RESET_ENV_VAR, "0")

    mail_run_pipeline.main(mode="threads")

    assert calls == [("analysis", "threads")]
