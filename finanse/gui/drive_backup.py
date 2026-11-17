"""Praca z Google Drive w tle, żeby okno nie zamarzało na czas sieci i przeglądarki."""

import threading

from PySide6.QtCore import QObject, Signal

from .. import gdrive


class Background(QObject):
    """Uruchamia funkcję w wątku; wynik lub błąd wraca sygnałem do wątku okna.

    Funkcja nie może używać połączenia z bazą okna: SQLite go nie współdzieli.
    """

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.busy = False

    def running(self):
        """Fałsz już w chwili sygnału, choć wątek jeszcze się kończy."""
        return self.busy

    def start(self, function):
        if self.running():
            return False

        def work():
            try:
                result = function()
            except gdrive.DriveError as error:
                self.busy = False
                self.failed.emit(str(error))
            except Exception as error:  # noqa: BLE001 - nieznany błąd też trzeba pokazać
                self.busy = False
                self.failed.emit(f"Nieoczekiwany błąd: {error}")
            else:
                self.busy = False
                self.finished.emit(result)

        # Wątek demona nie wstrzymuje zamknięcia aplikacji; przerwana wysyłka
        # wznawialna nie zostawia na Dysku pliku.
        self.busy = True
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        return True

    def wait(self, timeout=None):
        """Dla testów: czeka na koniec wątku."""
        if self.thread is not None:
            self.thread.join(timeout)
