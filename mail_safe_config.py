import os
from pathlib import Path

from dotenv import dotenv_values


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = BASE_DIR / ".env"
MASK = "***"


REQUIRED_FIELDS_BY_COMMAND_TYPE = {
    "imap_read": ["IMAP_HOST", "EMAIL_USERNAME", "EMAIL_PASSWORD"],
    "smtp_send": ["SMTP_HOST", "EMAIL_USERNAME", "EMAIL_PASSWORD"],
    "pipeline_status": [],
    "draft_only": [],
}


def _is_truthy(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def detect_automation_mode(environ: dict[str, str] | None = None) -> bool:
    env = dict(environ) if environ is not None else dict(os.environ)
    return any(
        _is_truthy(env.get(name))
        for name in ("MAIL_AUTOMATION_MODE", "AUTOMATION_MODE", "N8N_MODE", "CI")
    )


def load_raw_config(
    env_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    resolved_env_path = Path(env_path) if env_path is not None else DEFAULT_ENV_PATH
    file_config = dotenv_values(resolved_env_path) if resolved_env_path.exists() else {}
    merged = {k: str(v) for k, v in file_config.items() if v is not None}

    env = dict(environ) if environ is not None else dict(os.environ)
    for key, value in env.items():
        if value is not None and value != "":
            merged[key] = str(value)
    return merged


def env_flag(config: dict[str, str], name: str, default: bool = False) -> bool:
    if name not in config or config[name] == "":
        return default
    return _is_truthy(config[name])


def validate_required_fields(config: dict[str, str], command_type: str | None = None) -> None:
    if not command_type:
        return
    required = REQUIRED_FIELDS_BY_COMMAND_TYPE.get(command_type, [])
    missing = [field for field in required if not str(config.get(field, "")).strip()]
    if missing:
        raise ValueError(f"Missing required config for {command_type}: {', '.join(missing)}")


def validate_send_safety(config: dict[str, str], automation_mode: bool) -> None:
    if automation_mode and env_flag(config, "MAIL_SEND_FOR_REAL", default=False):
        raise ValueError("MAIL_SEND_FOR_REAL is blocked in automation mode")


def sanitized_config_summary(config: dict[str, str], automation_mode: bool | None = None) -> dict[str, object]:
    mode = detect_automation_mode(config) if automation_mode is None else automation_mode
    summary = {
        "automation_mode": mode,
        "imap_host_set": bool(str(config.get("IMAP_HOST", "")).strip()),
        "smtp_host_set": bool(str(config.get("SMTP_HOST", "")).strip()),
        "email_username_set": bool(str(config.get("EMAIL_USERNAME", "")).strip()),
        "email_password_set": bool(str(config.get("EMAIL_PASSWORD", "")).strip()),
        "mail_send_for_real": env_flag(config, "MAIL_SEND_FOR_REAL", default=False),
    }
    if summary["email_password_set"]:
        summary["email_password"] = MASK
    return summary


def load_safe_config(
    command_type: str | None = None,
    env_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
    automation_mode: bool | None = None,
) -> tuple[dict[str, str], dict[str, object]]:
    config = load_raw_config(env_path=env_path, environ=environ)
    mode = detect_automation_mode(environ=config) if automation_mode is None else automation_mode
    validate_send_safety(config=config, automation_mode=mode)
    validate_required_fields(config=config, command_type=command_type)
    summary = sanitized_config_summary(config=config, automation_mode=mode)
    return config, summary
