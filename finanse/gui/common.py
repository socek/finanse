"""Drobne elementy wspólne dla okien aplikacji."""

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDateEdit, QLabel, QMessageBox

from .themes import color_override


NO_CATEGORY_NAME = "Bez kategorii"
NO_CATEGORY_HINT = "Można tak zostawić, ale kategoria ułatwia czytanie raportów."


def _message_box(parent, icon, text):
    box = QMessageBox(icon, "Finanse", text, QMessageBox.StandardButton.NoButton, parent)
    # Treść może zawierać dane użytkownika, których nie wolno czytać jako HTML.
    box.setTextFormat(Qt.TextFormat.PlainText)
    return box


def attach_row_menu(table, build_menu):
    """Prawy przycisk zaznacza wiersz tabeli i pokazuje menu z build_menu."""

    def show(position):
        # rowAt, bo komórki z przyciskiem nie mają elementu, który znalazłoby itemAt.
        row = table.rowAt(position.y())
        if row < 0:
            return
        table.setCurrentCell(row, 0)
        build_menu().exec(table.viewport().mapToGlobal(position))

    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(show)


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


def _themed(name, light, dark):
    return QColor(color_override(name) or (dark if _is_dark() else light))


def positive_color():
    return _themed("positive", "#1a7a52", "#5cc99a")


def negative_color():
    return _themed("negative", "#b3362b", "#f0857a")


def income_row_background():
    return _themed("income_row", "#e6f4ea", "#1c3327")


def expense_row_background():
    return _themed("expense_row", "#fbeaea", "#3a2023")


def mark_row_kind(item, income, column_count):
    """Barwi cały wiersz według rodzaju; później można wyróżnić w nim pojedynczą komórkę."""
    color = income_row_background() if income else expense_row_background()
    for column in range(column_count):
        item.setBackground(column, color)


def warning_background():
    """Tło tego, co jest dozwolone, ale niezalecane; takie samo w obu motywach."""
    return QColor("#f5b83d")


def warning_text():
    return QColor("#2b1d00")


def overdue_background():
    """Tło tego, co wymaga działania, np. płatności po terminie; takie samo w obu motywach."""
    return QColor("#c62828")


def overdue_text():
    return QColor("#ffffff")


def muted_text():
    """Tekst tego, co chwilowo nie obowiązuje, np. terminu zawieszonej płatności."""
    return _themed("muted", "#8c8c8c", "#7f7f7f")


def mark_no_category(item, column):
    """Wyróżnia w wierszu listy brak kategorii, także obok innych kategorii."""
    if NO_CATEGORY_NAME in item.text(column).split(", "):
        item.setBackground(column, warning_background())
        item.setForeground(column, warning_text())
        item.setToolTip(column, NO_CATEGORY_HINT)


def mark_no_category_cell(item):
    """Wyróżnia brak kategorii w komórce tabeli."""
    item.setBackground(warning_background())
    item.setForeground(warning_text())
    item.setToolTip(NO_CATEGORY_HINT)


def mark_no_category_label(label):
    """Wyróżnia brak kategorii w etykiecie."""
    label.setStyleSheet(
        f"background: {warning_background().name()};"
        f" color: {warning_text().name()};"
        " padding: 1px 4px; border-radius: 3px;"
    )
    label.setToolTip(NO_CATEGORY_HINT)


def color_no_category_item(combo):
    """Wyróżnia pozycję braku kategorii na rozwijanej liście."""
    index = combo.findText(NO_CATEGORY_NAME)
    if index >= 0:
        combo.setItemData(index, warning_background(), Qt.ItemDataRole.BackgroundRole)
        combo.setItemData(index, warning_text(), Qt.ItemDataRole.ForegroundRole)
        combo.setItemData(index, NO_CATEGORY_HINT, Qt.ItemDataRole.ToolTipRole)


def style_category_combo(combo):
    """Wyróżnia brak kategorii na liście oraz wtedy, gdy jest wybrany."""
    color_no_category_item(combo)

    def update():
        selected = combo.currentText() == NO_CATEGORY_NAME
        palette = QPalette(combo.palette())
        default = QApplication.palette()
        for role, color in (
            (QPalette.ColorRole.Button, warning_background()),
            (QPalette.ColorRole.Base, warning_background()),
            (QPalette.ColorRole.ButtonText, warning_text()),
            (QPalette.ColorRole.Text, warning_text()),
        ):
            palette.setColor(role, color if selected else default.color(role))
        combo.setPalette(palette)
        combo.setToolTip(NO_CATEGORY_HINT if selected else "")

    combo.currentIndexChanged.connect(update)
    update()


def income_series():
    return _themed("income", "#2a78d6", "#3987e5")


def expense_series():
    return _themed("expense", "#eb6834", "#d95926")
