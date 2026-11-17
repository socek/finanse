"""Kopie bazy na Google Drive przez API, bez dodatkowych bibliotek.

Logowanie to OAuth dla aplikacji desktopowych: przeglądarka wraca na adres
http://127.0.0.1:<port>, a kod wymieniamy na token z PKCE. Zakres drive.file
daje dostęp tylko do plików utworzonych przez tę aplikację.

Konfiguracja i token są w pliku gdrive.json obok bazy, z prawami tylko dla
właściciela, bo token pozwala wysyłać pliki na Dysk użytkownika.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

FILE_NAME = "gdrive.json"
FOLDER_NAME = "Finanse – kopie"
COPIES_KEPT = 30
# Jeden zakres: przy kilku Google pokazuje pola wyboru i dostęp do Dysku łatwo pominąć.
SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
ABOUT_URL = "https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_TYPE = "application/vnd.google-apps.folder"
AUTHORIZE_TIMEOUT = 300
_COPY_NAME = re.compile(r"finanse-[0-9]{8}-[0-9]{6}\.db")


class DriveError(Exception):
    """Błąd z opisem dla użytkownika; `status` to kod HTTP, gdy odpowiedział serwer."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# Konfiguracja


def config_path(database):
    return Path(database).parent / FILE_NAME


def load_config(database):
    """Brakujący lub uszkodzony plik oznacza brak konfiguracji."""
    try:
        config = json.loads(config_path(database).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


def save_config(database, **changes):
    """Zmienia podane pola; None usuwa pole. Plik ma prawa 600 od początku."""
    config = {**load_config(database), **changes}
    config = {key: value for key, value in config.items() if value is not None}
    path = config_path(database)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
    os.replace(temporary, path)
    return config


def is_connected(config):
    return bool(config.get("client_id") and config.get("refresh_token"))


def disconnect(database):
    """Zapomina token i folder; dane klienta OAuth zostają do ponownego połączenia."""
    return save_config(database, refresh_token=None, email=None, folder_id=None)


def read_client_file(path):
    """Dane klienta z pliku JSON pobranego z Google Cloud Console."""
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise DriveError(f"Nie da się odczytać pliku {Path(path).name}: {error}") from error
    client = data.get("installed") or data.get("web") if isinstance(data, dict) else None
    if not isinstance(client, dict) or not client.get("client_id"):
        raise DriveError(
            f"Plik {Path(path).name} nie zawiera danych klienta OAuth"
            " (oczekiwano pola „installed” z „client_id”)."
        )
    return client["client_id"], client.get("client_secret", "")


# HTTP


def _http(method, url, data=None, headers=None):
    """Zwraca (status, nagłówki, treść). Błąd sieci zamienia na DriveError."""
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise DriveError(f"Brak połączenia z Google: {reason}") from error


def _json(body):
    try:
        return json.loads(body or b"{}")
    except ValueError:
        return {}


NO_SCOPE_MESSAGE = (
    "Google nie dał aplikacji dostępu do plików na Dysku. W Ustawieniach kliknij Rozłącz,"
    " a potem Połącz z Google… i na ekranie zgody zaznacz dostęp do plików Google Drive."
)


def _api_error(status, body, action):
    data = _json(body)
    if status == 403 and b"insufficient" in body.lower() and b"scope" in body.lower():
        return DriveError(NO_SCOPE_MESSAGE, status)
    detail = data.get("error")
    if isinstance(detail, dict):
        detail = detail.get("message")
    detail = data.get("error_description") or detail or body[:200].decode("utf-8", "replace")
    return DriveError(f"{action} nie powiodło się (HTTP {status}): {detail}", status)


class Drive:
    """Wywołania API Dysku z odświeżanym tokenem. `http` podmieniają testy."""

    def __init__(self, client_id, client_secret, refresh_token, http=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.http = http or _http
        self.access_token = None

    def _refresh(self):
        status, _, body = self.http(
            "POST",
            TOKEN_URL,
            urllib.parse.urlencode(
                {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                }
            ).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        if status == 400 and _json(body).get("error") == "invalid_grant":
            raise DriveError(
                "Dostęp do Google Drive wygasł lub został cofnięty."
                " Połącz konto ponownie w Ustawieniach."
            )
        if status != 200:
            raise _api_error(status, body, "Odświeżenie dostępu do Google")
        self.access_token = _json(body)["access_token"]

    def call(self, method, url, data=None, headers=None, action="Operacja na Dysku"):
        if self.access_token is None:
            self._refresh()
        for attempt in range(2):
            all_headers = {**(headers or {}), "Authorization": f"Bearer {self.access_token}"}
            status, response_headers, body = self.http(method, url, data, all_headers)
            if status == 401 and attempt == 0:
                self._refresh()
                continue
            if status >= 300:
                raise _api_error(status, body, action)
            return response_headers, body
        raise AssertionError("nieosiągalne")

    def list_files(self, query, fields="files(id,name,createdTime)"):
        params = urllib.parse.urlencode(
            {"q": query, "fields": fields, "orderBy": "createdTime", "pageSize": 1000}
        )
        _, body = self.call("GET", f"{FILES_URL}?{params}", action="Odczyt listy plików")
        return _json(body).get("files", [])

    def folder_exists(self, folder_id):
        params = urllib.parse.urlencode({"fields": "id,trashed"})
        try:
            _, body = self.call("GET", f"{FILES_URL}/{folder_id}?{params}")
        except DriveError as error:
            if error.status == 404:  # usunięty z Dysku na stałe
                return False
            raise
        return not _json(body).get("trashed")

    def create_folder(self, name):
        _, body = self.call(
            "POST",
            f"{FILES_URL}?fields=id",
            json.dumps({"name": name, "mimeType": FOLDER_TYPE}).encode(),
            {"Content-Type": "application/json; charset=UTF-8"},
            action="Utworzenie folderu na Dysku",
        )
        return _json(body)["id"]

    def upload(self, path, name, folder_id):
        """Wysyłka wznawialna w jednym kawałku: działa dla plików każdego rozmiaru."""
        size = Path(path).stat().st_size
        headers, _ = self.call(
            "POST",
            f"{UPLOAD_URL}?uploadType=resumable&fields=id",
            json.dumps({"name": name, "parents": [folder_id]}).encode(),
            {
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "application/x-sqlite3",
                "X-Upload-Content-Length": str(size),
            },
            action="Rozpoczęcie wysyłki",
        )
        location = {key.lower(): value for key, value in headers.items()}.get("location")
        if not location:
            raise DriveError("Google nie zwrócił adresu wysyłki pliku.")
        data = Path(path).read_bytes()
        _, body = self.call(
            "PUT",
            location,
            data,
            {"Content-Type": "application/x-sqlite3", "Content-Length": str(len(data))},
            action="Wysyłka kopii",
        )
        return _json(body).get("id")

    def delete(self, file_id):
        self.call("DELETE", f"{FILES_URL}/{file_id}", action="Usunięcie starej kopii")


# Logowanie


def _pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def authorize(client_id, client_secret, open_browser=webbrowser.open, cancel=None,
              timeout=AUTHORIZE_TIMEOUT, http=None):  # fmt: skip
    """Otwiera przeglądarkę ze zgodą Google i czeka na powrót na 127.0.0.1.

    Zwraca {"refresh_token", "email"}; adresu może brakować. `cancel` (threading.Event) przerywa czekanie.
    """
    http = http or _http
    cancel = cancel or threading.Event()
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [None])[0] != state:
                self.send_response(400)
                self.end_headers()
                return
            result.update({key: values[0] for key, values in query.items()})
            ok = "code" in result
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            message = (
                "Połączono z Google Drive. Możesz zamknąć tę kartę i wrócić do aplikacji Finanse."
                if ok
                else "Nie udzielono dostępu. Możesz zamknąć tę kartę."
            )
            self.wfile.write(f"<!doctype html><meta charset=utf-8><p>{message}</p>".encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.2
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    try:
        if not open_browser(url):
            raise DriveError(f"Nie udało się otworzyć przeglądarki. Otwórz adres ręcznie:\n{url}")
        deadline = time.monotonic() + timeout
        while not result:
            if cancel.is_set():
                raise DriveError("Anulowano łączenie z Google Drive.")
            if time.monotonic() > deadline:
                raise DriveError("Nie doczekano się zgody w przeglądarce. Spróbuj ponownie.")
            server.handle_request()
    finally:
        server.server_close()

    if "code" not in result:
        raise DriveError(f"Google odmówił dostępu: {result.get('error', 'brak kodu')}.")
    status, _, body = http(
        "POST",
        TOKEN_URL,
        urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": result["code"],
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
        ).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    if status != 200:
        raise _api_error(status, body, "Uzyskanie dostępu do Google")
    token = _json(body)
    if SCOPE not in token.get("scope", SCOPE).split():
        raise DriveError(
            "Google nie dał aplikacji dostępu do plików na Dysku. Połącz ponownie"
            " i na ekranie zgody zaznacz dostęp do plików Google Drive."
        )
    if not token.get("refresh_token"):
        raise DriveError("Google nie zwrócił tokenu odświeżania. Spróbuj połączyć ponownie.")
    return {"refresh_token": token["refresh_token"], "email": _email(token, http)}


def _email(token, http):
    """Adres konta do pokazania w ustawieniach; bez niego połączenie też działa."""
    drive = Drive("", "", token["refresh_token"], http)
    drive.access_token = token.get("access_token")
    try:
        _, body = drive.call("GET", ABOUT_URL, action="Odczyt konta")
    except (DriveError, KeyError):
        return None
    return _json(body).get("user", {}).get("emailAddress")


# Kopia


def _snapshot(database, directory):
    """Spójna kopia bazy przez API backup SQLite, bez blokowania zapisu w aplikacji."""
    target = Path(directory) / "snapshot.db"
    source = sqlite3.connect(f"{Path(database).resolve().as_uri()}?mode=ro", uri=True)
    try:
        copy = sqlite3.connect(target)
        try:
            source.backup(copy)
        finally:
            copy.close()
    finally:
        source.close()
    return target


def upload_backup(database, http=None, keep=COPIES_KEPT, now=None):
    """Wysyła kopię bazy do folderu aplikacji na Dysku i usuwa najstarsze nad `keep`.

    Działa na własnym połączeniu, więc można ją uruchomić w osobnym wątku.
    Zwraca nazwę wysłanego pliku.
    """
    config = load_config(database)
    if not is_connected(config):
        raise DriveError("Najpierw połącz konto Google w Ustawieniach.")
    drive = Drive(config["client_id"], config.get("client_secret", ""),
                  config["refresh_token"], http)  # fmt: skip

    folder_id = config.get("folder_id")
    if not folder_id or not drive.folder_exists(folder_id):
        folder_id = drive.create_folder(FOLDER_NAME)
        save_config(database, folder_id=folder_id)

    name = f"finanse-{(now or datetime.now()):%Y%m%d-%H%M%S}.db"
    with tempfile.TemporaryDirectory(prefix="finanse-gdrive-") as directory:
        try:
            snapshot = _snapshot(database, directory)
        except sqlite3.Error as error:
            raise DriveError(f"Nie udało się przygotować kopii bazy: {error}") from error
        drive.upload(snapshot, name, folder_id)

    copies = [
        file
        for file in drive.list_files(f"'{folder_id}' in parents and trashed = false")
        if _COPY_NAME.fullmatch(file.get("name", ""))
    ]
    copies.sort(key=lambda file: (file.get("createdTime", ""), file["name"]))
    for old in copies[:-keep] if keep else []:
        drive.delete(old["id"])
    save_config(database, last_upload=f"{datetime.now():%Y-%m-%d %H:%M}")
    return name
