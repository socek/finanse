"""Przybliżone wyszukiwanie: litery w kolejności, a przy literówkach podobieństwo."""

import unicodedata
from difflib import SequenceMatcher

MIN_TYPO_SIMILARITY = 0.7
_TYPO_SCORE_LIMIT = 10  # zawsze mniej niż dopasowanie liter w kolejności


def normalize(text):
    """Bez wielkości liter i polskich znaków, żeby „zywn” znalazło „Żywność”."""
    text = text.casefold().replace("ł", "l")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).strip()


def _subsequence_score(query, text):
    """Punkty za litery zapytania w kolejności albo None, gdy się tak nie da."""
    score = 100
    position = -1
    for index, char in enumerate(query):
        found = text.find(char, position + 1)
        if found < 0:
            return None
        if found == position + 1 and index > 0:
            score += 8  # kolejne litery obok siebie
        else:
            score -= min(found - position - 1, 10)
        if found == 0:
            score += 20  # początek nazwy
        elif not text[found - 1].isalnum():
            score += 10  # początek słowa
        position = found
    return score - len(text) / 10


def score(query, text):
    """Im więcej, tym lepiej; None oznacza brak dopasowania."""
    query, text = normalize(query), normalize(text)
    if not query:
        return 0
    if query == text:
        return 1000
    result = _subsequence_score(query, text)
    if result is not None:
        return result + _TYPO_SCORE_LIMIT
    candidates = [text, *text.split()]
    similarity = max(SequenceMatcher(None, query, word).ratio() for word in candidates)
    return similarity * _TYPO_SCORE_LIMIT if similarity >= MIN_TYPO_SIMILARITY else None


def search(query, names):
    """Pasujące nazwy od najlepszej; puste zapytanie zwraca wszystkie."""
    scored = [(score(query, name), name) for name in names]
    matches = [item for item in scored if item[0] is not None]
    return [name for _, name in sorted(matches, key=lambda item: (-item[0], normalize(item[1])))]
