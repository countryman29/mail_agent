import json
import sys


def build_result(
    *,
    status: str = "ok",
    command: str,
    dry_run: bool = True,
    no_send: bool = True,
    readonly: bool = True,
    counts: dict[str, int] | None = None,
    output_paths: list[str] | None = None,
    warnings: list[str] | None = None,
    risk_flags: list[str] | None = None,
    human_review_required: bool = True,
    errors: list[str] | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "command": command,
        "dry_run": dry_run,
        "no_send": no_send,
        "readonly": readonly,
        "counts": counts or {},
        "output_paths": output_paths or [],
        "warnings": warnings or [],
        "risk_flags": risk_flags or [],
        "human_review_required": human_review_required,
        "errors": errors or [],
    }


def emit_result(
    result: dict[str, object],
    *,
    output_json: bool = False,
    stream=None,
) -> dict[str, object]:
    if output_json:
        target = stream if stream is not None else sys.stdout
        print(json.dumps(result, ensure_ascii=False), file=target)
    return result
