import pytest

import mail_run_analysis


def patch_analysis_mains(monkeypatch):
    calls = []
    monkeypatch.setattr(mail_run_analysis.mail_analyze_tasks, "main", lambda: calls.append("messages"))
    monkeypatch.setattr(mail_run_analysis.mail_analyze_threads, "main", lambda: calls.append("threads"))
    return calls


def test_main_runs_both_analyses_by_default(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)
    monkeypatch.delenv(mail_run_analysis.MODE_ENV_VAR, raising=False)

    mail_run_analysis.main()

    assert calls == ["messages", "threads"]


def test_main_runs_message_analysis_only(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)

    mail_run_analysis.main("messages")

    assert calls == ["messages"]


def test_main_runs_thread_analysis_only(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)

    mail_run_analysis.main("threads")

    assert calls == ["threads"]


def test_main_uses_env_mode_when_no_explicit_mode(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)
    monkeypatch.setenv(mail_run_analysis.MODE_ENV_VAR, "thread")

    mail_run_analysis.main()

    assert calls == ["threads"]


def test_main_rejects_unknown_mode(monkeypatch):
    calls = patch_analysis_mains(monkeypatch)

    with pytest.raises(ValueError, match="Unknown analysis mode"):
        mail_run_analysis.main("unknown")

    assert calls == []
