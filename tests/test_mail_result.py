import json

import mail_result


def test_build_result_contains_expected_fields():
    result = mail_result.build_result(command="mail_run_analysis")

    assert result == {
        "status": "ok",
        "command": "mail_run_analysis",
        "dry_run": True,
        "no_send": True,
        "readonly": True,
        "counts": {},
        "output_paths": [],
        "warnings": [],
        "risk_flags": [],
        "human_review_required": True,
        "errors": [],
    }


def test_emit_result_returns_dict_without_printing_when_json_disabled(capsys):
    result = mail_result.build_result(command="mail_show_pipeline_status")

    returned = mail_result.emit_result(result, output_json=False)

    assert returned is result
    assert capsys.readouterr().out == ""


def test_emit_result_prints_json_when_enabled(capsys):
    result = mail_result.build_result(
        command="mail_prepare_draft_from_analysis",
        output_paths=["drafts/example_draft.md"],
    )

    returned = mail_result.emit_result(result, output_json=True)

    assert returned is result
    printed = capsys.readouterr().out.strip()
    assert json.loads(printed) == result
