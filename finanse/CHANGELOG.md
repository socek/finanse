# Historia zmian

## 0.1 (2026-11-06)

Pierwsza wersja aplikacji okienkowej.

### Portfele i transakcje

- Portfele z własną walutą i saldem początkowym.
- Transakcje z wieloma produktami, także z kategoriami przypisanymi do produktów.
- Wpisywanie ilości i ceny albo ilości i wartości, z wyliczaniem brakującego pola.
- Propozycja opisu z nazwy jedynego produktu.
- Nowa transakcja pamięta ostatnią datę do zamknięcia aplikacji, a przycisk Dzisiaj
  i Ctrl+T ustawiają bieżący dzień.
- Ctrl+N otwiera nową transakcję, Enter dodaje produkt, a Shift+Enter zapisuje całość.
- Przelewy między portfelami, także w różnych walutach.
- Transakcje cykliczne z opcjonalnymi produktami i licznikiem płatności.
- Import wyciągów bankowych z plików CSV z ochroną przed duplikatami.

### Listy i raporty

- Listy transakcji i produktów według dni, z sumami przychodów i wydatków.
- Wybór wielu portfeli i data najnowszej transakcji.
- Szukanie po nazwie oraz filtry po dacie, kategorii i kwocie.
- Raporty miesięczne z wybranych portfeli, z podziałem na kategorie i portfele
  oraz wykresem z 12 miesięcy.

### Dane

- Dane w katalogu `~/.finanse`, bez kont i bez szyfrowania.
- Dziennik zmian z zakładką Historia.
- Kopia bazy przy każdym uruchomieniu.
- Zakładka Pliki z rozmiarem plików danych.
