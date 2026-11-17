import threading

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import gdrive
from ..settings import load_settings, save_setting
from ..storage import database_path
from . import common, shortcuts, title_bar
from .drive_backup import Background
from .themes import SYSTEM, apply_theme, theme_choices

ACTION, SHORTCUT, RESET = range(3)


class SettingsTab(QWidget):
    """`on_changed` odświeża widoki, które pokazują kolory motywu i podpisy skrótów."""

    def __init__(self, db, on_changed=None, parent=None):
        super().__init__(parent)
        self.database = database_path(db)
        self.on_changed = on_changed
        self.theme = QComboBox()
        for key, name in theme_choices():
            self.theme.addItem(name, key)
        saved = load_settings(self.database).get("theme", SYSTEM)
        self.theme.setCurrentIndex(max(self.theme.findData(saved), 0))
        self.theme.currentIndexChanged.connect(self._theme_selected)
        self.title_bar = QCheckBox("Pokazuj pasek tytułowy w oknach aplikacji")
        self.title_bar.setToolTip(
            "Dla menedżerów okien, które same nie rysują pasków, np. Hyprland."
            " Przeciągnięcie paska przesuwa okno."
        )
        self.title_bar.setChecked(title_bar.is_enabled())
        self.title_bar.toggled.connect(self._title_bar_toggled)
        form = QFormLayout()
        form.addRow("Motyw", self.theme)
        form.addRow("Okna", self.title_bar)

        self.editors = {}
        self.table = QTableWidget(len(shortcuts.ACTIONS), 3)
        self.table.setHorizontalHeaderLabels(["Działanie", "Skrót", ""])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(ACTION, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(SHORTCUT, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(RESET, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(SHORTCUT, 220)
        for row, action in enumerate(shortcuts.ACTIONS):
            self.table.setItem(row, ACTION, QTableWidgetItem(action.label))
            editor = QKeySequenceEdit()
            editor.setMaximumSequenceLength(1)
            editor.setClearButtonEnabled(True)
            editor.editingFinished.connect(lambda key=action.key: self._edited(key))
            self.editors[action.key] = editor
            self.table.setCellWidget(row, SHORTCUT, editor)
            reset = QPushButton("Domyślny")
            reset.setAutoDefault(False)
            reset.clicked.connect(lambda _=False, key=action.key: self._reset(key))
            self.table.setCellWidget(row, RESET, reset)
            self.table.setRowHeight(row, 30)
        self._show_sequences()

        self.reset_all_button = QPushButton("Przywróć wszystkie domyślne")
        self.reset_all_button.clicked.connect(self.reset_all)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(self.reset_all_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._build_drive())
        layout.addWidget(QLabel("Skróty klawiszowe"))
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)

    def _show_sequences(self):
        for key, editor in self.editors.items():
            editor.blockSignals(True)
            editor.setKeySequence(QKeySequence(shortcuts.sequence_text(key)))
            editor.blockSignals(False)

    def _theme_selected(self):
        key = self.theme.currentData()
        apply_theme(key)
        self._notify()
        self._save("theme", key, "motywu")

    def _title_bar_toggled(self, checked):
        title_bar.set_enabled(checked)
        self._save(title_bar.SETTING, checked, "paska tytułowego")

    def _notify(self):
        if self.on_changed:
            self.on_changed()

    def _save(self, name, value, description):
        try:
            save_setting(self.database, name, value)
        except OSError as error:
            common.show_errors(self, [f"Nie udało się zapisać {description}: {error}"])

    def _shortcuts_changed(self):
        self._show_sequences()
        self._notify()
        self._save("shortcuts", shortcuts.saved_values(), "skrótów")

    def _edited(self, key):
        text = shortcuts.text_of(self.editors[key].keySequence())
        if text == shortcuts.sequence_text(key):
            return
        error = shortcuts.validation_error(key, text)
        if error:
            self._show_sequences()
            common.show_errors(self, [error])
            return
        shortcuts.set_sequence(key, text)
        self._shortcuts_changed()

    def _reset(self, key):
        default = shortcuts.default_text(key)
        error = shortcuts.validation_error(key, default)
        if error:
            common.show_errors(self, [error])
            return
        shortcuts.set_sequence(key, default)
        self._shortcuts_changed()

    def reset_all(self):
        shortcuts.reset_all()
        self._shortcuts_changed()

    def refresh(self):
        """Ustawienia nie zależą od danych, ale okno odświeża stronę przy każdym otwarciu."""
        self._show_drive()

    # Google Drive

    def _build_drive(self):
        self.drive_connect = Background(self)
        self.drive_connect.finished.connect(self._drive_connected)
        self.drive_connect.failed.connect(self._drive_connect_failed)
        self.drive_cancel = threading.Event()
        self.drive_upload = Background(self)
        self.drive_upload.finished.connect(self._drive_uploaded)
        self.drive_upload.failed.connect(self._drive_upload_failed)
        self.drive_upload_interactive = False

        self.drive_client_id = QLineEdit()
        self.drive_client_id.setPlaceholderText("…apps.googleusercontent.com")
        self.drive_client_secret = QLineEdit()
        self.drive_client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        for field in (self.drive_client_id, self.drive_client_secret):
            field.editingFinished.connect(self._save_drive_client)
        self.drive_client_file_button = QPushButton("Wczytaj z pliku…")
        self.drive_client_file_button.setToolTip(
            "Plik JSON klienta OAuth typu „Aplikacja komputerowa” pobrany z Google Cloud Console."
        )
        self.drive_client_file_button.clicked.connect(self.load_drive_client_file)
        client = QHBoxLayout()
        client.addWidget(self.drive_client_id, 1)
        client.addWidget(self.drive_client_file_button)

        self.drive_status = common.plain_label()
        self.drive_status.setWordWrap(True)
        self.drive_connect_button = QPushButton()
        self.drive_connect_button.clicked.connect(self._drive_connect_clicked)
        self.drive_upload_button = QPushButton("Wyślij kopię teraz")
        self.drive_upload_button.clicked.connect(lambda: self.upload_to_drive())
        self.drive_auto = QCheckBox("Wysyłaj kopię przy każdym uruchomieniu")
        self.drive_auto.toggled.connect(self._drive_auto_toggled)
        buttons = QHBoxLayout()
        buttons.addWidget(self.drive_connect_button)
        buttons.addWidget(self.drive_upload_button)
        buttons.addStretch()

        form = QFormLayout()
        form.addRow("Client ID", client)
        form.addRow("Client secret", self.drive_client_secret)
        form.addRow("Stan", self.drive_status)
        form.addRow("", buttons)
        form.addRow("", self.drive_auto)
        box = QGroupBox("Kopia na Google Drive")
        box.setLayout(form)
        self._show_drive()
        return box

    def _drive_config(self):
        return gdrive.load_config(self.database)

    def _show_drive(self):
        config = self._drive_config()
        connected = gdrive.is_connected(config)
        connecting = self.drive_connect.running()
        for field, key in (
            (self.drive_client_id, "client_id"),
            (self.drive_client_secret, "client_secret"),
        ):
            if not field.hasFocus():
                field.setText(config.get(key, ""))
            # Token należy do klienta, więc zmiana klienta wymaga rozłączenia.
            field.setReadOnly(connected or connecting)
        self.drive_client_file_button.setEnabled(not connected and not connecting)
        if connecting:
            status = "Czekam na zgodę w przeglądarce…"
            self.drive_connect_button.setText("Anuluj łączenie")
        elif connected:
            status = f"Połączono z kontem {config.get('email') or 'Google'}."
            self.drive_connect_button.setText("Rozłącz")
        else:
            status = "Nie połączono."
            self.drive_connect_button.setText("Połącz z Google…")
        if connected:
            status += f" Kopie trafiają do folderu „{gdrive.FOLDER_NAME}”"
            status += f", zostaje {gdrive.COPIES_KEPT} najnowszych."
            if self.drive_upload.running():
                status += "\nWysyłanie kopii…"
            elif config.get("last_upload"):
                status += f"\nOstatnia kopia: {config['last_upload']}."
        self.drive_status.setText(status)
        self.drive_upload_button.setEnabled(connected and not self.drive_upload.running())
        self.drive_auto.blockSignals(True)
        self.drive_auto.setChecked(bool(config.get("auto")))
        self.drive_auto.blockSignals(False)
        self.drive_auto.setEnabled(connected)

    def _save_drive(self, **changes):
        try:
            gdrive.save_config(self.database, **changes)
        except OSError as error:
            common.show_errors(self, [f"Nie udało się zapisać ustawień Google Drive: {error}"])
            return False
        return True

    def _save_drive_client(self):
        if gdrive.is_connected(self._drive_config()):
            return
        self._save_drive(
            client_id=self.drive_client_id.text().strip() or None,
            client_secret=self.drive_client_secret.text().strip() or None,
        )

    def load_drive_client_file(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Wybierz plik klienta OAuth", "", "Pliki JSON (*.json);;Wszystkie pliki (*)"
            )
            if not path:
                return
        try:
            client_id, client_secret = gdrive.read_client_file(path)
        except gdrive.DriveError as error:
            common.show_errors(self, [str(error)])
            return
        if self._save_drive(client_id=client_id, client_secret=client_secret or None):
            self.drive_client_id.setText(client_id)
            self.drive_client_secret.setText(client_secret)
        self._show_drive()

    def _drive_connect_clicked(self):
        if self.drive_connect.running():
            self.drive_cancel.set()
        elif gdrive.is_connected(self._drive_config()):
            self.disconnect_drive()
        else:
            self.connect_drive()

    def connect_drive(self, open_browser=None):
        self._save_drive_client()
        config = self._drive_config()
        if not config.get("client_id"):
            common.show_errors(
                self,
                [
                    "Podaj Client ID klienta OAuth albo wczytaj jego plik JSON."
                    " Instrukcja jest w README, w części „Kopia na Google Drive”."
                ],
            )
            return
        self.drive_cancel = threading.Event()
        cancel = self.drive_cancel
        options = {"open_browser": open_browser} if open_browser else {}
        self.drive_connect.start(
            lambda: gdrive.authorize(
                config["client_id"], config.get("client_secret", ""), cancel=cancel, **options
            )
        )
        self._show_drive()

    def _drive_connected(self, token):
        self._save_drive(refresh_token=token["refresh_token"], email=token.get("email"),
                         folder_id=None)  # fmt: skip
        self._show_drive()

    def _drive_connect_failed(self, message):
        self._show_drive()
        if not self.drive_cancel.is_set():
            common.show_errors(self, [message])

    def disconnect_drive(self):
        question = (
            "Rozłączyć konto Google? Kopie zostaną na Dysku,"
            " ale aplikacja przestanie wysyłać nowe."
        )
        if common.confirm(self, question, "Rozłącz"):
            self._save_drive(refresh_token=None, email=None, folder_id=None, auto=None)
            self._show_drive()

    def _drive_auto_toggled(self, checked):
        self._save_drive(auto=checked or None)

    def drive_ready(self):
        return gdrive.is_connected(self._drive_config())

    def upload_to_drive(self, interactive=True):
        """Wysyła kopię w tle; `interactive` pokazuje wynik w okienku, a nie tylko na pasku."""
        if not self.drive_ready():
            if interactive:
                common.show_errors(self, ["Najpierw połącz konto Google w Ustawieniach."])
            return False
        database = self.database
        if not self.drive_upload.start(lambda: gdrive.upload_backup(database)):
            return False
        self.drive_upload_interactive = interactive
        self._show_drive()
        return True

    def _drive_uploaded(self, name):
        self._show_drive()
        if self.drive_upload_interactive:
            common.show_info(self, f"Wysłano kopię „{name}” na Google Drive.")

    def _drive_upload_failed(self, message):
        self._show_drive()
        if self.drive_upload_interactive:
            common.show_errors(self, [f"Nie udało się wysłać kopii na Google Drive.\n{message}"])
