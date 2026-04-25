from email.message import EmailMessage

import mail_read_folder
import mail_threads


def make_html_message():
    msg = EmailMessage()
    msg.set_content("<html><body><p>Hello <b>HTML</b></p><br>Next&nbsp;line</body></html>", subtype="html")
    return msg


def make_plain_and_html_message():
    msg = EmailMessage()
    msg.set_content("Plain body")
    msg.add_alternative("<html><body>HTML body</body></html>", subtype="html")
    return msg


def test_mail_read_folder_extracts_html_when_plain_text_is_missing():
    assert mail_read_folder.get_text_from_message(make_html_message()) == "Hello HTML Next line"


def test_mail_threads_extracts_html_when_plain_text_is_missing():
    assert mail_threads.get_text_from_message(make_html_message()) == "Hello HTML Next line"


def test_low_level_readers_prefer_plain_text_over_html_alternative():
    msg = make_plain_and_html_message()

    assert mail_read_folder.get_text_from_message(msg) == "Plain body"
    assert mail_threads.get_text_from_message(msg) == "Plain body"
