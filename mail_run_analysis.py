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
        return {"mode": "messages", "messages": mail_analyze_tasks.main(), "threads": 0}

    if mode in ("threads", "thread"):
        return {"mode": "threads", "messages": 0, "threads": mail_analyze_threads.main()}

    if mode == "both":
        messages = mail_analyze_tasks.main()
        threads = mail_analyze_threads.main()
        return {"mode": "both", "messages": messages, "threads": threads}

    raise ValueError(f"Unknown analysis mode: {mode}. Use 'messages', 'threads', or 'both'.")


if __name__ == "__main__":
    main()
