import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "state" / "mail_state.json"
EMPTY_ANALYSIS_STATE = {"processed_message_ids": [], "processed_thread_keys": []}


def reset_analysis_state(path: Path = STATE_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(EMPTY_ANALYSIS_STATE, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return EMPTY_ANALYSIS_STATE.copy()


def main():
    state = reset_analysis_state(STATE_PATH)
    print("Reset analysis state:", STATE_PATH)
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
