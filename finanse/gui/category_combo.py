"""Wybór kategorii wpisywany z klawiatury, z przybliżonym wyszukiwaniem."""

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QListWidget

from ..fuzzy import search

UNKNOWN_CATEGORY = -1  # nie ma takiego identyfikatora, więc zapis zgłosi błąd
MAX_VISIBLE_RESULTS = 8
MIN_RESULTS_WIDTH = 220


class CategoryCombo(QComboBox):
    """Lista wyników nie przejmuje fokusu, więc wpisywany tekst pozostaje nietknięty.

    QCompleter zastępowałby go wyróżnionym wynikiem, a kolejne litery trafiałyby wtedy
    na koniec cudzej nazwy. Lista jest częścią okna, a nie osobnym oknem, żeby działała
    tak samo na każdym systemie okien.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setCompleter(None)
        self.results = QListWidget()
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results.itemClicked.connect(lambda item: self._choose(item.text()))
        self.results.hide()
        self.destroyed.connect(self.results.deleteLater)
        self.lineEdit().installEventFilter(self)
        self.lineEdit().textEdited.connect(self._show_matches)
        self.lineEdit().editingFinished.connect(self.resolve)

    def focusInEvent(self, event):
        """Zaznacza nazwę, żeby pisanie ją zastąpiło.

        Odłożone, bo kliknięcie myszą ustawia kursor dopiero po nadaniu fokusu. Powrót do
        okna albo zamknięcie listy nie jest wejściem na pole i nie rusza kursora.
        """
        super().focusInEvent(event)
        if event.reason() not in (
            Qt.FocusReason.ActiveWindowFocusReason,
            Qt.FocusReason.PopupFocusReason,
        ):
            QTimer.singleShot(0, self.lineEdit().selectAll)

    def _names(self):
        return [self.itemText(index) for index in range(self.count())]

    def match_names(self):
        return [self.results.item(row).text() for row in range(self.results.count())]

    def _show_matches(self, text):
        self.results.clear()
        self.results.addItems(search(text, self._names()))
        if self.results.count() and (text.strip() or self.lineEdit().hasFocus()):
            # Enter ma wybrać najlepszy wynik bez użycia strzałek.
            self.results.setCurrentRow(0)
            self._place_results()
        else:
            self.results.hide()

    def _place_results(self):
        window = self.window()
        if self.results.parent() is not window:
            self.results.setParent(window)
        rows = min(self.results.count(), MAX_VISIBLE_RESULTS)
        size = QSize(
            max(self.width(), MIN_RESULTS_WIDTH),
            self.results.sizeHintForRow(0) * rows + 2 * self.results.frameWidth(),
        )
        position = self.mapTo(window, QPoint(0, self.height()))
        if position.y() + size.height() > window.height():
            position.setY(self.mapTo(window, QPoint(0, 0)).y() - size.height())
        position.setX(min(position.x(), window.width() - size.width()))
        self.results.setGeometry(max(position.x(), 0), max(position.y(), 0), size.width(), size.height())
        self.results.show()
        self.results.raise_()

    def keyPressEvent(self, event):
        """Fokus ma pole wyboru (pole tekstowe przekazuje mu fokus), więc klawisze
        trafiają najpierw tutaj, a nie przez filtr pola tekstowego."""
        if self._handle_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.lineEdit() and event.type() == QEvent.Type.KeyPress:
            if self._handle_key(event):
                return True
        return super().eventFilter(watched, event)

    def _handle_key(self, event):
        """Czy klawisz obsłużyła lista. Bez listy trafia on do pola i okna jak zwykle."""
        key = event.key()
        if not self.results.isVisible():
            if key == Qt.Key.Key_Down:
                self._show_matches("")
                return True
            return False
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            step = 1 if key == Qt.Key.Key_Down else -1
            row = (self.results.currentRow() + step) % self.results.count()
            self.results.setCurrentRow(row)
            return True
        if key == Qt.Key.Key_Escape:
            self.results.hide()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._choose(self.results.currentItem().text())
            # Skrót zapisu ma przejść dalej, a sam Enter tylko wybiera kategorię.
            return not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        return False

    def _choose(self, name):
        self.results.hide()
        self.setCurrentIndex(self.findText(name))
        self.setEditText(name)

    def _best_index(self):
        """Pozycja dla wpisanego tekstu, także niezatwierdzonego, albo -1."""
        if self.results.isVisible() and self.results.currentItem():
            return self.findText(self.results.currentItem().text())
        text = self.currentText().strip()
        if not text:
            return 0
        if text == self.itemText(self.currentIndex()):
            return self.currentIndex()
        matches = search(text, self._names())
        return self.findText(matches[0]) if matches else -1

    def selected_category(self):
        index = self._best_index()
        return self.itemData(index) if index >= 0 else UNKNOWN_CATEGORY

    def resolve(self):
        """Przy wyjściu z pola pokazuje wybraną nazwę; nietrafiony tekst cofa do poprzedniej."""
        index = self._best_index()
        self.results.hide()
        if index >= 0:
            self.setCurrentIndex(index)
        self.setEditText(self.itemText(self.currentIndex()))
