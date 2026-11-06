"""Drobne elementy wspólne dla okien aplikacji."""

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDateEdit, QLabel, QMessageBox


def _message_box(parent, icon, text):
    box = QMessageBox(icon, "Finanse", text, QMessageBox.StandardButton.NoButton, parent)
    # Treść może zawierać dane użytkownika, których nie wolno czytać jako HTML.
    box.setTextFormat(Qt.TextFormat.PlainText)
    return box


def show_errors(parent, errors):
    box = _message_box(parent, QMessageBox.Icon.Warning, "\n".join(errors))
    box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
    box.exec()


def show_info(parent, text):
    box = _message_box(parent, QMessageBox.Icon.Information, text)
    box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
    box.exec()


def confirm(parent, text, action="Usuń"):
    box = _message_box(parent, QMessageBox.Icon.Question, text)
    accept = box.addButton(action, QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton("Anuluj", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is accept


def plain_label(text="", parent=None):
    """Etykieta na dane użytkownika: nigdy nie interpretuje ich jako HTML."""
    label = QLabel(text, parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def date_edit(iso=None, parent=None):
    edit = QDateEdit(parent)
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy-MM-dd")
    edit.setDate(QDate.fromString(iso, Qt.DateFormat.ISODate) if iso else QDate.currentDate())
    return edit


def iso_date(edit):
    return edit.date().toString(Qt.DateFormat.ISODate)


def _is_dark():
    return QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128


def _themed(light, dark):
    return QColor(dark if _is_dark() else light)


def positive_color():
    return _themed("#1a7a52", "#5cc99a")


def negative_color():
    return _themed("#b3362b", "#f0857a")


def income_series():
    return _themed("#2a78d6", "#3987e5")


def expense_series():
    return _themed("#eb6834", "#d95926")
