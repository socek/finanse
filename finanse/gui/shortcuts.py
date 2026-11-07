"""Skróty klawiszowe: lista działań, ustawienia użytkownika i aktualizacja przypisań."""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from shiboken6 import isValid

MAIN, DIALOG = "main", "dialog"


@dataclass(frozen=True)
class Action:
    key: str
    label: str
    default: str
    scope: str = MAIN


ACTIONS = (
    Action("new_transaction", "Nowa transakcja", "Ctrl+N"),
    Action("new_transfer", "Nowy przelew", "Ctrl+Shift+N"),
    Action("new_wallet", "Nowy portfel", "Ctrl+Shift+W"),
    Action("new_recurring", "Nowa transakcja cykliczna", "Ctrl+Shift+R"),
    Action("import_csv", "Import CSV do podświetlonego portfela", "Ctrl+I"),
    Action("edit_wallet", "Edycja podświetlonego portfela", "Ctrl+Shift+E"),
    Action("delete_wallet", "Usunięcie podświetlonego portfela", "Ctrl+Shift+Del"),
    Action("edit_selected", "Edycja zaznaczonej pozycji", "F2"),
    Action("delete_selected", "Usunięcie zaznaczonej pozycji", "Del"),
    Action("duplicate_selected", "Duplikowanie zaznaczonej transakcji", "Ctrl+Shift+C"),
    Action("pay_selected", "Zapłata zaznaczonej transakcji cyklicznej", "Ctrl+P"),
    Action("search", "Przejście do szukania", "Ctrl+F"),
    Action("clear_filters", "Wyczyszczenie filtrów", "Ctrl+Shift+F"),
    Action("expand_all", "Rozwinięcie wszystkiego", "Ctrl+Shift+Down"),
    Action("collapse_all", "Zwinięcie wszystkiego", "Ctrl+Shift+Up"),
    Action("check_all", "Zaznaczenie wszystkich portfeli", "Ctrl+Shift+A"),
    Action("uncheck_all", "Odznaczenie wszystkich portfeli", "Ctrl+Shift+D"),
    Action("previous_month", "Poprzedni miesiąc w raporcie", "Alt+Left"),
    Action("next_month", "Następny miesiąc w raporcie", "Alt+Right"),
    Action("refresh", "Odświeżenie widoku", "F5"),
    Action("tab_1", "Zakładka Portfele", "Ctrl+1"),
    Action("tab_2", "Zakładka Produkty", "Ctrl+2"),
    Action("tab_3", "Zakładka Cykliczne", "Ctrl+3"),
    Action("tab_4", "Zakładka Raporty", "Ctrl+4"),
    Action("tab_5", "Zakładka Kategorie", "Ctrl+5"),
    Action("tab_6", "Zakładka Historia", "Ctrl+6"),
    Action("tab_7", "Zakładka Pliki", "Ctrl+7"),
    Action("tab_8", "Zakładka Ustawienia", "Ctrl+8"),
    Action("tab_9", "Zakładka O programie", "Ctrl+9"),
    Action("quit", "Zamknięcie aplikacji", "Ctrl+Q"),
    Action("add_product", "Okno transakcji: kolejny produkt", "Return", DIALOG),
    Action("save", "Okno transakcji: zapis", "Shift+Return", DIALOG),
    Action("today", "Okno transakcji: dzisiejsza data", "Ctrl+T", DIALOG),
)
_BY_KEY = {action.key: action for action in ACTIONS}
_MODIFIERS = (
    Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
    | Qt.KeyboardModifier.MetaModifier
)
_EDITING_KEYS = tuple(
    getattr(QKeySequence.StandardKey, name)
    for name in (
        "Cut", "Copy", "Paste", "Undo", "Redo", "SelectAll", "Delete",
        "DeleteEndOfLine", "DeleteStartOfWord", "DeleteEndOfWord",
        "MoveToEndOfLine", "MoveToStartOfLine",
    )
)  # fmt: skip

# Lista standardowych skrótów zależy od platformy, a te działają w polach tekstowych
# na Linuksie, także gdy Qt ich tam nie wymienia.
_ALWAYS_RESERVED = (
    "Esc", "Tab", "Shift+Tab", "Backtab", "Ctrl+D", "Ctrl+E", "Ctrl+K", "Ctrl+U",
    "Ctrl+Y",
)  # fmt: skip

_overrides = {}
_bound = []
_hinted = []


def normalize(text):
    """Klawisz Enter z bloku numerycznego i główny mają działać tak samo."""
    return text.replace("Num+", "").replace("Enter", "Return")


def text_of(sequence):
    return normalize(sequence.toString(QKeySequence.SequenceFormat.PortableText))


def sequence_text(key):
    """Bieżący skrót działania; pusty tekst oznacza, że jest wyłączony."""
    return _overrides.get(key, _BY_KEY[key].default)


def default_text(key):
    return _BY_KEY[key].default


def display_text(text):
    return text.replace("Return", "Enter")


def tooltip(key, text=""):
    """Podpowiedź z aktualnym skrótem, ewentualnie po własnym tekście."""
    shortcut = sequence_text(key)
    hint = f"Skrót: {display_text(shortcut)}" if shortcut else ""
    return "\n".join(part for part in (text, hint) if part)


def show_on(widget, key):
    """Pokazuje skrót w podpowiedzi przycisku i aktualizuje ją po zmianie w ustawieniach."""
    widget.setToolTip(tooltip(key))
    _hinted[:] = [(k, w) for k, w in _hinted if isValid(w)]
    _hinted.append((key, widget))


def _blocks_typing(text):
    combination = QKeySequence(text)[0]
    key = combination.key()
    if combination.keyboardModifiers() & _MODIFIERS:
        return False
    return not Qt.Key.Key_F1.value <= key.value <= Qt.Key.Key_F35.value


def _is_reserved(text):
    if text in _ALWAYS_RESERVED:
        return True
    return any(
        text_of(sequence) == text
        for standard in _EDITING_KEYS
        for sequence in QKeySequence.keyBindings(standard)
    )


def validation_error(key, text):
    """Komunikat, dlaczego skrótu nie można przypisać, albo None."""
    if not text:
        return None
    action = _BY_KEY[key]
    if text != action.default:
        if _is_reserved(text):
            return f"Skrót {display_text(text)} jest zajęty przez edycję tekstu lub zamykanie okien."
        allowed_plain = action.scope == DIALOG and text in ("Return", "Shift+Return")
        if _blocks_typing(text) and not allowed_plain:
            return (
                "Skrót musi zawierać Ctrl lub Alt albo być klawiszem funkcyjnym, "
                "bo inaczej blokowałby pisanie."
            )
    for other in ACTIONS:
        if other.key != key and other.scope == action.scope and sequence_text(other.key) == text:
            return f"Skrót {display_text(text)} jest już przypisany do: {other.label}."
    return None


def load(saved):
    """Wczytuje zapisane skróty; niepoprawne wpisy, np. po ręcznej edycji, są pomijane."""
    _overrides.clear()
    if not isinstance(saved, dict):
        return
    for key, text in saved.items():
        if key in _BY_KEY and isinstance(text, str):
            text = normalize(text)
            if text != _BY_KEY[key].default and validation_error(key, text) is None:
                _overrides[key] = text


def saved_values():
    return dict(_overrides)


def set_sequence(key, text):
    """Ustawia skrót i aktualizuje wszystkie przypisania. Pusty tekst go wyłącza."""
    if text == _BY_KEY[key].default:
        _overrides.pop(key, None)
    else:
        _overrides[key] = text
    _bound[:] = [(k, shortcut) for k, shortcut in _bound if isValid(shortcut)]
    for bound_key, shortcut in _bound:
        if bound_key == key:
            shortcut.setKey(QKeySequence(text))
    _hinted[:] = [(k, widget) for k, widget in _hinted if isValid(widget)]
    for hinted_key, widget in _hinted:
        if hinted_key == key:
            widget.setToolTip(tooltip(key))


def reset_all():
    for key in list(_overrides):
        set_sequence(key, _BY_KEY[key].default)


def bind(key, parent, callback, context=Qt.ShortcutContext.WindowShortcut):
    shortcut = QShortcut(QKeySequence(sequence_text(key)), parent, context=context)
    shortcut.activated.connect(callback)
    _bound[:] = [(k, s) for k, s in _bound if isValid(s)]
    _bound.append((key, shortcut))
    return shortcut


def matches(event, key):
    """Czy zdarzenie klawisza to skrót działania. Okna używają tego do klawisza Enter."""
    current = sequence_text(key)
    if not current:
        return False
    combination = event.keyCombination()
    return text_of(QKeySequence(combination)) == current


def forget():
    """Stan początkowy, potrzebny testom."""
    _overrides.clear()
    _bound.clear()
    _hinted.clear()
