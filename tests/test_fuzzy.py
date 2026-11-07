import pytest

from finanse.fuzzy import normalize, score, search

NAMES = ["Bez kategorii", "Dom", "Inne", "Jedzenie", "Rachunki", "Rozrywka", "Transport",
         "Ubrania", "Wynagrodzenie", "Zdrowie", "Żywność", "Hetman Tymoteusz"]  # fmt: skip


@pytest.mark.parametrize(
    ("text", "expected"),
    [("ŻYWNOŚĆ", "zywnosc"), ("Łódź", "lodz"), ("  Dom ", "dom"), ("Państwowe", "panstwowe")],
)
def test_normalize(text, expected):
    assert normalize(text) == expected


@pytest.mark.parametrize(
    ("query", "best"),
    [
        ("jedzenie", "Jedzenie"),
        ("JED", "Jedzenie"),
        ("jdz", "Jedzenie"),  # brakujące litery
        ("jedzenei", "Jedzenie"),  # przestawione litery
        ("zdrowe", "Zdrowie"),
        ("zywn", "Żywność"),  # bez polskich znaków
        ("żywn", "Żywność"),
        ("tym", "Hetman Tymoteusz"),  # początek drugiego słowa
        ("dom", "Dom"),
        ("wyn", "Wynagrodzenie"),
    ],
)
def test_search_puts_expected_name_first(query, best):
    assert search(query, NAMES)[0] == best


@pytest.mark.parametrize("query", ["qqqq", "xyzxyz", "0000"])
def test_search_without_match(query):
    assert search(query, NAMES) == []


def test_empty_query_returns_all_names():
    assert sorted(search("", NAMES)) == sorted(NAMES)
    assert sorted(search("   ", NAMES)) == sorted(NAMES)


def test_exact_match_beats_everything():
    assert search("dom", ["Domek", "Dom", "Do mnie"])[0] == "Dom"


def test_better_matches_score_higher():
    assert score("ra", "Rachunki") > score("ra", "Ubrania")  # początek nazwy
    assert score("jed", "Jedzenie") > score("jdn", "Jedzenie")  # litery obok siebie
    # Literówka zawsze przegrywa z dopasowaniem liter w kolejności.
    assert score("jedzenei", "Jedzenie") < score("jz", "Jedzenie")
