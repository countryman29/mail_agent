import mail_send_reply as send


class HeaderMap(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def make_message(message_id=None, references=None):
    msg = HeaderMap()
    if message_id is not None:
        msg["Message-ID"] = message_id
    if references is not None:
        msg["References"] = references
    return msg


def test_extract_message_ids_returns_single_valid_message_id():
    assert send.extract_message_ids("<one@example.com>") == ["<one@example.com>"]


def test_extract_message_ids_returns_multiple_ids_from_references():
    value = "<first@example.com> <second@example.com> text <third@example.com>"
    assert send.extract_message_ids(value) == [
        "<first@example.com>",
        "<second@example.com>",
        "<third@example.com>",
    ]


def test_extract_message_ids_returns_empty_for_missing_or_malformed_input():
    assert send.extract_message_ids(None) == []
    assert send.extract_message_ids("not a message id") == []
    assert send.extract_message_ids("broken <missing-end@example.com") == []


def test_build_references_header_returns_empty_when_message_id_missing():
    msg = make_message(references="<first@example.com> <second@example.com>")
    assert send.build_references_header(msg) == ("", "")


def test_build_references_header_preserves_last_valid_message_id_as_in_reply_to():
    msg = make_message(
        message_id="noise <older@example.com> <latest@example.com>",
        references="<first@example.com>",
    )
    assert send.build_references_header(msg) == (
        "<latest@example.com>",
        "<first@example.com> <older@example.com> <latest@example.com>",
    )


def test_build_references_header_deduplicates_and_preserves_order():
    msg = make_message(
        message_id="<second@example.com> <third@example.com>",
        references="<first@example.com> <second@example.com> <first@example.com>",
    )
    assert send.build_references_header(msg) == (
        "<third@example.com>",
        "<first@example.com> <second@example.com> <third@example.com>",
    )
