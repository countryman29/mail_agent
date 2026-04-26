import pytest

import mail_safe_config as safe_config


def test_load_safe_config_merges_env_file_and_environment(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "IMAP_HOST=imap.from.file",
                "SMTP_HOST=smtp.from.file",
                "EMAIL_USERNAME=file-user@example.com",
                "EMAIL_PASSWORD=file-secret",
            ]
        ),
        encoding="utf-8",
    )

    config, summary = safe_config.load_safe_config(
        env_path=env_file,
        environ={"SMTP_HOST": "smtp.from.env"},
        command_type="imap_read",
        automation_mode=False,
    )

    assert config["IMAP_HOST"] == "imap.from.file"
    assert config["SMTP_HOST"] == "smtp.from.env"
    assert config["EMAIL_USERNAME"] == "file-user@example.com"
    assert config["EMAIL_PASSWORD"] == "file-secret"

    assert summary["automation_mode"] is False
    assert summary["imap_host_set"] is True
    assert summary["smtp_host_set"] is True
    assert summary["email_password"] == safe_config.MASK


def test_load_safe_config_blocks_real_send_in_automation_mode():
    with pytest.raises(ValueError, match="MAIL_SEND_FOR_REAL is blocked in automation mode"):
        safe_config.load_safe_config(
            environ={"MAIL_SEND_FOR_REAL": "true"},
            automation_mode=True,
        )


def test_load_safe_config_validates_required_fields():
    with pytest.raises(ValueError, match="Missing required config for smtp_send"):
        safe_config.load_safe_config(
            command_type="smtp_send",
            env_path="/tmp/nonexistent-mail-agent-env-file",
            environ={"SMTP_HOST": "smtp.example.com"},
            automation_mode=False,
        )


def test_detect_automation_mode_from_flags():
    assert safe_config.detect_automation_mode({"MAIL_AUTOMATION_MODE": "1"}) is True
    assert safe_config.detect_automation_mode({"N8N_MODE": "true"}) is True
    assert safe_config.detect_automation_mode({"CI": "yes"}) is True
    assert safe_config.detect_automation_mode({"MAIL_AUTOMATION_MODE": "0"}) is False
