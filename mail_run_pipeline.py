import os

import mail_reset_analysis_state
import mail_run_analysis


RESET_ENV_VAR = "MAIL_ANALYSIS_RESET"


def env_flag(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def main(mode: str | None = None, reset: bool | None = None):
    should_reset = env_flag(os.getenv(RESET_ENV_VAR)) if reset is None else reset
    selected_mode = mail_run_analysis.normalize_mode(mode or os.getenv(mail_run_analysis.MODE_ENV_VAR))

    if should_reset:
        mail_reset_analysis_state.main()

    result = mail_run_analysis.main(selected_mode)
    print("Pipeline complete")
    print(f"Mode: {result['mode']}")
    print(f"Reset: {should_reset}")
    print(f"Messages analyzed: {result['messages']}")
    print(f"Threads analyzed: {result['threads']}")
    print(f"State file: {mail_reset_analysis_state.STATE_PATH}")
    print("Output folders:")
    print("  - analysis/")
    print("  - tasks/")
    return result


if __name__ == "__main__":
    main()
