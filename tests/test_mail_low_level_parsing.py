from email.message import EmailMessage

import mail_read_folder
import mail_threads


def make_html_message():
    msg = EmailMessage()
    msg.set_content("<html><body><p>Hello <b>HTML</b></p><br>Next&nbsp;line</body></html>", subtype="html")
    return msg


def test_mail_read_folder_extracts_html_when_plain_text_is_missing():
    assert mail_read_folder.get_text_from_message(make_html_message()) == "Hello HTML Next line"


def test_mail_threads_extracts_html_when_plain_text_is_missing():
    assert mail_threads.get_text_from_message(make_html_message()) == "Hello HTML Next line"
