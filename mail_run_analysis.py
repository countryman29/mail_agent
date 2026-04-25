import os

import mail_analyze_tasks
import mail_analyze_threads


DEFAULT_MODE = "both"
MODE_ENV_VAR = "MAIL_ANALYSIS_MODE"


def normalize_mode(mode: str | None) -> str:
    return (mode or DEFAULT_MODE).strip().lower()


def main(mode: str | None = None):
    mode = normalize_mode(mode or os.getenv(MODE_ENV_VAR))

    if mode in ("messages", "message", "tasks", "task"):
        mail_analyze_tasks.main()
        return

    if mode in ("threads", "thread"):
        mail_analyze_threads.main()
        return

    if mode == "both":
        mail_analyze_tasks.main()
        mail_analyze_threads.main()
        return

    raise ValueError(f"Unknown analysis mode: {mode}. Use 'messages', 'threads', or 'both'.")


if __name__ == "__main__":
    main()
