import re


OUTGOING_SIGNATURE = """Best Regards,
Anton Vasilev
Procurement Director
METAHIM LLC.
tel.: +79217766880 (Tel./WhatsApp)
tel.: +74951907375 ext. 103
WeChat: +66918201426"""


def ensure_outgoing_signature(body: str) -> str:
    body = body.rstrip()
    if OUTGOING_SIGNATURE in body:
        return body

    legacy_signature = re.compile(r"(?ms)\n*Best Regards,\s*\nAnton Vasilev\b.*\Z")
    if legacy_signature.search(body):
        return legacy_signature.sub("\n\n" + OUTGOING_SIGNATURE, body).strip()

    if not body:
        return OUTGOING_SIGNATURE
    return body + "\n\n" + OUTGOING_SIGNATURE
