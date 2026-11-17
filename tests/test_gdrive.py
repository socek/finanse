import json
import os
import sqlite3
import threading
import urllib.parse
import urllib.request
from datetime import datetime

import pytest
from PySide6.QtCore import QCoreApplication

from finanse import gdrive
from finanse.db import connect
from finanse.gui import common
from finanse.gui.main_window import MainWindow
from finanse.gui.settings_tab import SettingsTab
from finanse.storage import database_path
from finanse.wallets import create_wallet


class FakeDrive:
    """Udaje token Google i API Dysku w pamięci; pliki to słownik id → metadane."""

    def __init__(self):
        self.files = {}
        self.uploads = {}
        self.calls = []
        self.next_id = 0
        self.refresh_status = 200
        self.expire_once = False
        self.granted = gdrive.SCOPE

    def _id(self):
        self.next_id += 1
        return f"id{self.next_id}"

    def __call__(self, method, url, data=None, headers=None):
        headers = headers or {}
        self.calls.append((method, url))
        parsed = urllib.parse.urlparse(url)
        if url == gdrive.TOKEN_URL:
            form = urllib.parse.parse_qs(data.decode())
            if self.refresh_status != 200:
                return self.refresh_status, {}, b'{"error": "invalid_grant"}'
            body = {"access_token": f"token-{len(self.calls)}", "scope": self.granted}
            if form["grant_type"] == ["authorization_code"]:
                body.update(refresh_token="refresh")
                self.code_form = form
            return 200, {}, json.dumps(body).encode()
        if self.expire_once:
            self.expire_once = False
            return 401, {}, b"{}"
        assert headers["Authorization"].startswith("Bearer token-")
        if self.granted != gdrive.SCOPE:
            return 403, {}, b'{"error": {"message": "Request had insufficient authentication scopes."}}'
        if url == gdrive.ABOUT_URL:
            return 200, {}, b'{"user": {"emailAddress": "ja@example.com"}}'
        if parsed.path.startswith("/upload/") and method == "POST":
            upload = self._id()
            self.uploads[upload] = json.loads(data)
            return 200, {"Location": f"https://upload.example/{upload}"}, b""
        if parsed.netloc == "upload.example":
            meta = self.uploads.pop(parsed.path.strip("/"))
            file_id = self._id()
            self.files[file_id] = {**meta, "id": file_id, "data": data,
                                   "createdTime": f"2026-11-16T10:00:{self.next_id:02d}Z"}  # fmt: skip
            return 200, {}, json.dumps({"id": file_id}).encode()
        if method == "POST":
            file_id = self._id()
            self.files[file_id] = {**json.loads(data), "id": file_id}
            return 200, {}, json.dumps({"id": file_id}).encode()
        if method == "GET" and parsed.path == "/drive/v3/files":
            query = urllib.parse.parse_qs(parsed.query)["q"][0]
            parent = query.split("'")[1]
            found = [
                {key: file[key] for key in ("id", "name", "createdTime")}
                for file in self.files.values()
                if parent in file.get("parents", [])
            ]
            return 200, {}, json.dumps({"files": found}).encode()
        file_id = parsed.path.rsplit("/", 1)[1]
        if file_id not in self.files:
            return 404, {}, b'{"error": {"message": "File not found"}}'
        if method == "DELETE":
            del self.files[file_id]
            return 204, {}, b""
        return 200, {}, json.dumps({"id": file_id, "trashed": False}).encode()

    def copies(self):
        return sorted(
            file["name"] for file in self.files.values() if file.get("mimeType") is None
        )


@pytest.fixture
def database(tmp_path):
    from finanse.db import init_db

    path = tmp_path / "finanse.db"
    init_db(str(path))
    db = connect(str(path))
    create_wallet(db, "Konto")
    db.close()
    return path


def connected(database):
    gdrive.save_config(database, client_id="cid", client_secret="sec", refresh_token="refresh")


def test_config_file_is_private_and_none_removes_fields(database):
    gdrive.save_config(database, client_id="cid", refresh_token="r", email="a@b")
    path = gdrive.config_path(database)
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert gdrive.is_connected(gdrive.load_config(database))
    gdrive.disconnect(database)
    assert gdrive.load_config(database) == {"client_id": "cid"}
    path.write_text("zepsute")
    assert gdrive.load_config(database) == {}


def test_read_client_file(tmp_path):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
    assert gdrive.read_client_file(path) == ("cid", "sec")
    path.write_text("{}")
    with pytest.raises(gdrive.DriveError, match="installed"):
        gdrive.read_client_file(path)


def test_upload_backup_creates_folder_uploads_database_and_prunes(database):
    connected(database)
    drive = FakeDrive()
    for second in range(4):
        gdrive.upload_backup(database, http=drive, keep=2,
                             now=datetime(2026, 11, 16, 10, 0, second))  # fmt: skip

    folders = [file for file in drive.files.values() if file.get("mimeType") == gdrive.FOLDER_TYPE]
    assert [folder["name"] for folder in folders] == [gdrive.FOLDER_NAME]
    assert drive.copies() == ["finanse-20261116-100002.db", "finanse-20261116-100003.db"]
    config = gdrive.load_config(database)
    assert config["folder_id"] == folders[0]["id"]
    assert config["last_upload"]

    # Wysłany plik to pełna baza SQLite z danymi.
    data = next(f["data"] for f in drive.files.values() if f.get("mimeType") is None)
    copy = database.parent / "pobrana.db"
    copy.write_bytes(data)
    check = sqlite3.connect(copy)
    assert check.execute("SELECT name FROM wallets").fetchall() == [("Konto",)]
    check.close()


def test_upload_backup_recreates_deleted_folder_and_refreshes_expired_token(database):
    connected(database)
    gdrive.save_config(database, folder_id="usuniety")
    drive = FakeDrive()
    drive.expire_once = True
    gdrive.upload_backup(database, http=drive)
    assert gdrive.load_config(database)["folder_id"] != "usuniety"
    assert len(drive.copies()) == 1
    refreshes = [call for call in drive.calls if call[1] == gdrive.TOKEN_URL]
    assert len(refreshes) == 2


def test_upload_backup_reports_revoked_access_and_missing_connection(database):
    with pytest.raises(gdrive.DriveError, match="połącz konto"):
        gdrive.upload_backup(database, http=FakeDrive())
    connected(database)
    drive = FakeDrive()
    drive.refresh_status = 400
    with pytest.raises(gdrive.DriveError, match="Połącz konto ponownie"):
        gdrive.upload_backup(database, http=drive)


def _follow_redirect(url, **params):
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    redirect = query["redirect_uri"][0]
    params.setdefault("state", query["state"][0])

    def visit():
        urllib.request.urlopen(f"{redirect}/?{urllib.parse.urlencode(params)}").read()

    threading.Thread(target=visit, daemon=True).start()
    return query


def test_authorize_exchanges_code_with_pkce():
    drive = FakeDrive()
    seen = {}

    def browser(url):
        seen.update(_follow_redirect(url, code="kod"))
        return True

    token = gdrive.authorize("cid", "sec", open_browser=browser, http=drive, timeout=10)
    assert token == {"refresh_token": "refresh", "email": "ja@example.com"}
    assert seen["code_challenge_method"] == ["S256"]
    assert seen["scope"] == [gdrive.SCOPE]
    assert drive.code_form["code"] == ["kod"]
    assert drive.code_form["code_verifier"]


def test_authorize_rejects_consent_without_drive_access():
    drive = FakeDrive()
    drive.granted = ""

    def browser(url):
        _follow_redirect(url, code="kod")
        return True

    with pytest.raises(gdrive.DriveError, match="zaznacz dostęp do plików"):
        gdrive.authorize("cid", "sec", open_browser=browser, http=drive, timeout=10)


def test_upload_explains_missing_drive_scope(database):
    connected(database)
    drive = FakeDrive()
    drive.granted = "openid email"
    with pytest.raises(gdrive.DriveError, match="kliknij Rozłącz"):
        gdrive.upload_backup(database, http=drive)


def test_authorize_reports_refusal_cancel_and_timeout():
    def refuse(url):
        _follow_redirect(url, error="access_denied")
        return True

    with pytest.raises(gdrive.DriveError, match="access_denied"):
        gdrive.authorize("cid", "", open_browser=refuse, http=FakeDrive(), timeout=10)

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(gdrive.DriveError, match="Anulowano"):
        gdrive.authorize("cid", "", open_browser=lambda _: True, cancel=cancel)
    with pytest.raises(gdrive.DriveError, match="Nie doczekano"):
        gdrive.authorize("cid", "", open_browser=lambda _: True, timeout=0.3)


# Okno


@pytest.fixture
def messages(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    monkeypatch.setattr(common, "show_info", lambda _p, text: collected.append(text))
    monkeypatch.setattr(common, "confirm", lambda *_a, **_k: True)
    return collected


def _finish(background):
    background.wait(10)
    QCoreApplication.processEvents()


def test_settings_connects_uploads_and_disconnects(database, messages, monkeypatch):
    drive = FakeDrive()
    monkeypatch.setattr(gdrive, "_http", drive)
    db = connect(str(database))
    tab = SettingsTab(db)
    assert tab.drive_status.text() == "Nie połączono."
    assert not tab.drive_upload_button.isEnabled()

    tab.connect_drive(open_browser=lambda url: True)
    assert messages == ["Podaj Client ID klienta OAuth albo wczytaj jego plik JSON."
                        " Instrukcja jest w README, w części „Kopia na Google Drive”."]  # fmt: skip
    messages.clear()

    client = database.parent / "client.json"
    client.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
    tab.load_drive_client_file(client)
    assert tab.drive_client_id.text() == "cid"

    def browser(url):
        _follow_redirect(url, code="kod")
        return True

    tab.connect_drive(open_browser=browser)
    assert tab.drive_connect_button.text() == "Anuluj łączenie"
    _finish(tab.drive_connect)
    assert messages == []
    assert "ja@example.com" in tab.drive_status.text()
    assert tab.drive_client_id.isReadOnly()

    tab.drive_auto.setChecked(True)
    assert gdrive.load_config(database)["auto"] is True

    window = MainWindow(db)
    window.settings.upload_to_drive(interactive=False)
    _finish(window.settings.drive_upload)
    assert len(drive.copies()) == 1
    assert "Wysłano kopię" in window.statusBar().currentMessage()
    assert messages == []

    tab.upload_to_drive()
    _finish(tab.drive_upload)
    assert messages[0].startswith("Wysłano kopię „finanse-")

    tab.disconnect_drive()
    config = gdrive.load_config(database)
    assert not gdrive.is_connected(config) and "auto" not in config
    assert config["client_id"] == "cid"
    db.close()


def test_main_window_uploads_on_startup_only_when_enabled(database, messages, monkeypatch):
    drive = FakeDrive()
    monkeypatch.setattr(gdrive, "_http", drive)
    db = connect(str(database))
    connected(database)
    window = MainWindow(db)
    window.upload_on_startup()
    assert not window.settings.drive_upload.running()
    assert drive.calls == []

    gdrive.save_config(database_path(db), auto=True)
    window.upload_on_startup()
    _finish(window.settings.drive_upload)
    assert len(drive.copies()) == 1
    assert messages == []

    drive.refresh_status = 400
    gdrive.save_config(database_path(db), refresh_token="inny")
    window.upload_on_startup()
    _finish(window.settings.drive_upload)
    assert "Połącz konto ponownie" in window.statusBar().currentMessage()
    assert messages == []  # przy starcie bez okienek
    db.close()
