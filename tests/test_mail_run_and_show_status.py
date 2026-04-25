import mail_run_and_show_status


def test_main_runs_pipeline_then_shows_status(monkeypatch):
    calls = []
    status = {"mode": "both", "messages": 2, "threads": 3}

    monkeypatch.setattr(mail_run_and_show_status.mail_run_pipeline, "main", lambda: calls.append("pipeline"))
    monkeypatch.setattr(
        mail_run_and_show_status.mail_show_pipeline_status,
        "main",
        lambda: calls.append("status") or status,
    )

    result = mail_run_and_show_status.main()

    assert calls == ["pipeline", "status"]
    assert result == status
