import json

import mail_reset_analysis_state


def test_reset_analysis_state_creates_parent_directory_and_exact_json(tmp_path):
    state_path = tmp_path / "state" / "mail_state.json"

    state = mail_reset_analysis_state.reset_analysis_state(state_path)

    assert state == mail_reset_analysis_state.EMPTY_ANALYSIS_STATE
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "processed_message_ids": [],
        "processed_thread_keys": [],
    }
    assert state_path.read_text(encoding="utf-8") == (
        '{\n  "processed_message_ids": [],\n  "processed_thread_keys": []\n}\n'
    )


def test_reset_analysis_state_overwrites_existing_state(tmp_path):
    state_path = tmp_path / "state" / "mail_state.json"
    state_path.parent.mkdir()
    state_path.write_text('{"processed_message_ids": ["1"], "other": true}', encoding="utf-8")

    mail_reset_analysis_state.reset_analysis_state(state_path)

    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "processed_message_ids": [],
        "processed_thread_keys": [],
    }


def test_main_prints_reset_path_and_final_json(monkeypatch, tmp_path, capsys):
    state_path = tmp_path / "state" / "mail_state.json"
    monkeypatch.setattr(mail_reset_analysis_state, "STATE_PATH", state_path)

    mail_reset_analysis_state.main()

    captured = capsys.readouterr()
    assert f"Reset analysis state: {state_path}" in captured.out
    assert '"processed_message_ids": []' in captured.out
    assert '"processed_thread_keys": []' in captured.out
