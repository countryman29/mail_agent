import json
import os

import mail_reset_analysis_state
import mail_run_analysis


RESET_ENV_VAR = "MAIL_ANALYSIS_RESET"


def env_flag(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def save_last_pipeline_run(summary: dict):
    path = mail_reset_analysis_state.STATE_PATH.parent / "last_pipeline_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main(mode: str | None = None, reset: bool | None = None):
    should_reset = env_flag(os.getenv(RESET_ENV_VAR)) if reset is None else reset
    selected_mode = mail_run_analysis.normalize_mode(mode or os.getenv(mail_run_analysis.MODE_ENV_VAR))

    if should_reset:
        mail_reset_analysis_state.main()

    result = mail_run_analysis.main(selected_mode)
    summary = {
        "mode": result["mode"],
        "reset": should_reset,
        "messages": result["messages"],
        "threads": result["threads"],
        "state_file": str(mail_reset_analysis_state.STATE_PATH),
    }
    save_last_pipeline_run(summary)

    print("Pipeline complete")
    print(f"Mode: {summary['mode']}")
    print(f"Reset: {summary['reset']}")
    print(f"Messages analyzed: {summary['messages']}")
    print(f"Threads analyzed: {summary['threads']}")
    print(f"State file: {summary['state_file']}")
    print("Output folders:")
    print("  - analysis/")
    print("  - tasks/")
    return summary


if __name__ == "__main__":
    main()
