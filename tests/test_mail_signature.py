from mail_signature import OUTGOING_SIGNATURE, ensure_outgoing_signature


def test_ensure_outgoing_signature_appends_signature_when_missing():
    assert ensure_outgoing_signature("Hello") == "Hello\n\n" + OUTGOING_SIGNATURE


def test_ensure_outgoing_signature_does_not_duplicate_signature():
    body = "Hello\n\n" + OUTGOING_SIGNATURE

    assert ensure_outgoing_signature(body) == body


def test_ensure_outgoing_signature_replaces_legacy_anton_signature():
    body = """Hello

Best Regards,
Anton Vasilev
Procurement Director
METAHIM LLC"""

    assert ensure_outgoing_signature(body) == "Hello\n\n" + OUTGOING_SIGNATURE
