import mail_send_reply as send


class FakeMail:
    def __init__(self, lines, status="OK"):
        self._lines = lines
        self._status = status

    def list(self):
        return self._status, self._lines


def test_extract_body_prefers_canonical_body():
    draft = """Subject: Test

## Body
Hello from the canonical body.

## Internal
Note
"""
    assert send.extract_body(draft) == "Hello from the canonical body."


def test_extract_body_accepts_legacy_alias_with_warning(capsys):
    draft = """Subject: Test

## Draft reply in English
Legacy body text
"""
    assert send.extract_body(draft) == "Legacy body text"
    captured = capsys.readouterr()
    assert "устаревший раздел" in captured.out
    assert "## Body" in captured.out


def test_extract_body_rejects_empty_canonical_body():
    draft = """Subject: Test

## Body

## Next
Still here
"""
    try:
        send.extract_body(draft)
    except ValueError as exc:
        assert "## Body" in str(exc)
        assert "пустой" in str(exc)
    else:
        raise AssertionError("Expected ValueError for empty canonical body")


def test_clean_email_list_filters_placeholders_invalid_duplicates_and_own_email(monkeypatch):
    monkeypatch.setattr(send, "EMAIL_USERNAME", "me@example.com")
    emails = [
        "",
        "**",
        "invalid",
        "user@example.com",
        "USER@example.com",
        "me@example.com",
        "other@example.com",
        "bad @example.com",
    ]
    assert send.clean_email_list(emails) == ["user@example.com", "other@example.com"]


def test_clean_email_list_accepts_valid_unique_addresses(monkeypatch):
    monkeypatch.setattr(send, "EMAIL_USERNAME", "owner@example.com")
    emails = ["alpha@example.com", "beta@example.com", "alpha@example.com"]
    assert send.clean_email_list(emails) == ["alpha@example.com", "beta@example.com"]


def test_resolve_sent_folder_prefers_special_use_sent_flag():
    mail = FakeMail(
        [
            b'(\\HasNoChildren) "/" "Sent"',
            b'(\\HasNoChildren \\Sent) "/" "Sent Items"',
            b'(\\HasNoChildren) "/" "Archive"',
        ]
    )
    assert send.resolve_sent_folder(mail) == "Sent Items"


def test_resolve_sent_folder_falls_back_to_exact_localized_name():
    mail = FakeMail(
        [
            b'(\\HasNoChildren) "/" "Archive"',
            b'(\\HasNoChildren) "/" "\xd0\x9e\xd1\x82\xd0\xbf\xd1\x80\xd0\xb0\xd0\xb2\xd0\xbb\xd0\xb5\xd0\xbd\xd0\xbd\xd1\x8b\xd0\xb5"',
        ]
    )
    assert send.resolve_sent_folder(mail) == "Отправленные"


def test_resolve_sent_folder_returns_none_when_no_candidates():
    mail = FakeMail([b'(\\HasNoChildren) "/" "Archive"'])
    assert send.resolve_sent_folder(mail) is None
