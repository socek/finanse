# Finanse

Aplikacja webowa do spisywania finansów: użytkownik ma wiele portfeli, portfel
ma wiele transakcji, a transakcja wiele produktów.

## Funkcje

- portfele z własną walutą i saldem początkowym
- transakcje z wieloma produktami i filtrowanie po dacie
- kategorie przypisywane do produktów, więc jeden paragon może mieć kilka kategorii
- przelewy między portfelami, także w różnych walutach
- raporty miesięczne: bilans, podział na kategorie i wykres z 12 miesięcy
- import wyciągów bankowych z plików CSV z ochroną przed duplikatami
- zmiana hasła oraz reset hasła kodem odzyskiwania

## Uruchomienie

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/flask --app finanse run
```

Aplikacja działa pod adresem <http://127.0.0.1:5000>. Baza SQLite i klucz sesji
powstają przy pierwszym uruchomieniu w katalogu `instance/`.

Ten serwer jest przeznaczony do użytku lokalnego. Przy wystawianiu aplikacji do
sieci użyj serwera WSGI za proxy HTTPS i ustaw `SESSION_COOKIE_SECURE`.

## Aktualizacja bazy

Zmiany schematu są w `finanse/migrations/NNN_nazwa.sql` i wykonują się same przy
starcie aplikacji. Przed migracją istniejącej bazy aplikacja zapisuje jej kopię
jako `instance/finanse.db.backup-vN`, gdzie `N` to wersja sprzed migracji.

## Reset hasła

Aplikacja nie wysyła e-maili. Przy rejestracji użytkownik dostaje jednorazowo
pokazywany kod odzyskiwania, którym może ustawić nowe hasło na stronie logowania.
Konta sprzed wprowadzenia tej funkcji mogą wygenerować kod na stronie **Konto**.

Właściciel serwera może też ustawić hasło z konsoli:

```sh
.venv/bin/flask --app finanse reset-password NAZWA_UZYTKOWNIKA
```

## Import z banku

W portfelu wybierz **Import CSV** i wskaż plik z banku. Aplikacja rozpoznaje
kodowanie, separator i kolumny, a przed zapisem pokazuje podgląd, w którym można
to poprawić. Każdy wiersz staje się transakcją z jednym produktem: kwoty ujemne
to wydatki, a dodatnie to przychody.

- Plik musi mieć jedną kolumnę kwoty ze znakiem. Układ z osobnymi kolumnami
  obciążeń i uznań nie jest obsługiwany.
- Daty w formacie liczbowym są czytane jako dzień przed miesiącem.
- Waluta z pliku nie jest sprawdzana, więc importuj wyciąg do portfela w tej samej
  walucie.
- Wiersze bez poprawnej daty lub kwoty, np. stopki, są pomijane i liczone w podsumowaniu.
- Ponowny import tego samego wiersza do portfela jest pomijany, nawet po edycji
  transakcji. Po usunięciu transakcji można ją zaimportować ponownie.

## Testy

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

## Model danych

- `users` – konta użytkowników
- `wallets` – portfele użytkownika
- `categories` – kategorie użytkownika
- `transactions` – wydatki i przychody w portfelu
- `products` – pozycje transakcji: nazwa, kategoria, ilość, cena, wartość
- `transfers` – przelewy między portfelami, z kwotą po każdej stronie

Kwota transakcji to suma wartości jej produktów. Saldo portfela to saldo początkowe
plus przychody i przelewy przychodzące, minus wydatki i przelewy wychodzące.
Przelewy nie liczą się do przychodów ani wydatków w raportach. Portfela z przelewami
nie można usunąć, dopóki ich nie usuniesz, bo zmieniłoby to saldo drugiego portfela.

Kwoty są przechowywane w groszach, a ilości w tysięcznych częściach jednostki,
zawsze jako liczby całkowite.
