import json

import mail_reset_analysis_state


STATUS_PATH = mail_reset_analysis_state.STATE_PATH.parent / "last_pipeline_run.json"


def load_pipeline_status(path=STATUS_PATH):
    if not path.exists():
        raise FileNotFoundError(f"last pipeline run status not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    status = load_pipeline_status(STATUS_PATH)
    print("Pipeline status")
    print(f"Mode: {status['mode']}")
    print(f"Reset: {status['reset']}")
    print(f"Messages analyzed: {status['messages']}")
    print(f"Threads analyzed: {status['threads']}")
    print(f"State file: {status['state_file']}")
    return status


if __name__ == "__main__":
    main()
