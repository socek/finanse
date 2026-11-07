# Historia zmian

## 0.2 (w przygotowaniu)

Na razie bez zmian względem wersji 0.1.

## 0.1 (2026-11-07)

Pierwsza wersja aplikacji okienkowej.

### Portfele i transakcje

- Portfele z własną walutą i saldem początkowym.
- Transakcje z wieloma produktami, także z kategoriami przypisanymi do produktów.
- Wpisywanie ilości i ceny albo ilości i wartości, z wyliczaniem brakującego pola.
- Propozycja opisu z nazwy jedynego produktu.
- Nowa transakcja pamięta ostatnią datę do zamknięcia aplikacji, a przycisk Dzisiaj
  i Ctrl+T ustawiają bieżący dzień.
- Przelewy między portfelami, także w różnych walutach.
- Transakcje cykliczne z opcjonalnymi produktami i licznikiem płatności.
- Import wyciągów bankowych z plików CSV z ochroną przed duplikatami.
- Usuwanie transakcji z menu pod prawym przyciskiem myszy i klawiszem Delete.

### Listy i raporty

- Listy transakcji i produktów według dni, z sumami przychodów i wydatków.
- Wybór wielu portfeli i data najnowszej transakcji.
- Salda portfeli na koniec dnia wybranego w filtrze „Do”.
- Szukanie po nazwie oraz filtry po dacie, kategorii i kwocie.
- Przyciski rozwijania i zwijania list.
- Raporty miesięczne z wybranych portfeli, z podziałem na kategorie i portfele
  oraz wykresem z 12 miesięcy.

### Wygląd i obsługa

- Zakładka Ustawienia z wyborem motywu: systemowy, jasny, ciemny, sepia lub kolorowy.
- Skróty klawiszowe do większości działań, z możliwością zmiany w Ustawieniach.
- W oknie transakcji Enter domyślnie dodaje produkt, a Shift+Enter zapisuje całość.
- Nowa transakcja miga na liście przez 2 sekundy.
- Wyróżnienie pozycji bez kategorii bursztynowym tłem.

### Dane

- Dane w katalogu `~/.finanse`, bez kont i bez szyfrowania.
- Dziennik zmian z zakładką Historia.
- Kopia bazy przy każdym uruchomieniu.
- Zakładka Pliki z rozmiarem plików danych.

### Instalacja

- Instalacja przez `pyproject.toml` i polecenie `finanse`.
- Plik `.desktop` z wpisem w menu programów i klasą okna `finanse`.
- Zakładka O programie z wersją i historią zmian.
