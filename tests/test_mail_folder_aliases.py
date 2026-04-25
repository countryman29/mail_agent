import mail_folder_aliases as folders


class FakeAliasMail:
    def __init__(self, ok_folder):
        self.ok_folder = ok_folder
        self.selected = []

    def select(self, folder, readonly=None):
        self.selected.append((folder, readonly))
        if folder == f'"{self.ok_folder}"':
            return "OK", [b"1"]
        return "NO", [b"missing"]


class RaisingFirstAliasMail(FakeAliasMail):
    def select(self, folder, readonly=None):
        self.selected.append((folder, readonly))
        if len(self.selected) == 1:
            raise UnicodeEncodeError("ascii", "x", 0, 1, "boom")
        return super().select(folder, readonly=readonly)


def test_folder_alias_candidates_support_ru_en_system_folders():
    assert folders.folder_alias_candidates("INBOX/Elcon") == ["INBOX/Elcon", "Inbox/Elcon", "Входящие/Elcon"]
    assert folders.folder_alias_candidates("Входящие/Elcon") == ["Входящие/Elcon", "INBOX/Elcon", "Inbox/Elcon"]
    assert folders.folder_alias_candidates("Drafts") == ["Drafts", "Черновики"]
    assert folders.folder_alias_candidates("Корзина") == ["Корзина", "Trash", "Deleted Items"]
    assert folders.folder_alias_candidates("Архив") == ["Архив", "Archive"]


def test_select_folder_with_aliases_uses_first_available_alias():
    mail = FakeAliasMail("Входящие/Elcon")

    status, data, selected = folders.select_folder_with_aliases(mail, "INBOX/Elcon", readonly=True)

    assert status == "OK"
    assert data == [b"1"]
    assert selected == "Входящие/Elcon"
    assert mail.selected == [
        ('"INBOX/Elcon"', True),
        ('"Inbox/Elcon"', True),
        ('"Входящие/Elcon"', True),
    ]


def test_select_folder_with_aliases_continues_after_alias_exception():
    mail = RaisingFirstAliasMail("INBOX/Elcon")

    status, data, selected = folders.select_folder_with_aliases(mail, "Входящие/Elcon")

    assert status == "OK"
    assert data == [b"1"]
    assert selected == "INBOX/Elcon"
