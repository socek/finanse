# Finanse

Okienkowa aplikacja do spisywania finansów na jednym komputerze: wiele portfeli,
portfel ma wiele transakcji, a transakcja wiele produktów. Interfejs jest w Qt
(PySide6). Aplikacja nie ma kont ani logowania, a baza SQLite nie jest szyfrowana,
więc dostęp do danych chronią tylko uprawnienia do pliku.

## Funkcje

- portfele z własną walutą i saldem początkowym
- transakcje z wieloma produktami i filtrowanie po dacie
- kategorie przypisywane do produktów, więc jeden paragon może mieć kilka kategorii
- przelewy między portfelami, także w różnych walutach
- raporty miesięczne z dowolnie wybranych portfeli jednej waluty: bilans, rozbicie na
  portfele, podział na kategorie i wykres z 12 miesięcy
- import wyciągów bankowych z plików CSV z ochroną przed duplikatami

## Uruchomienie

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m finanse
```

Baza powstaje przy pierwszym uruchomieniu jako `instance/finanse.db`. Inną bazę
można wskazać argumentem: `.venv/bin/python -m finanse /sciezka/do/bazy.db`.

## Aktualizacja bazy

Zmiany schematu są w `finanse/migrations/NNN_nazwa.sql` i wykonują się same przy
starcie aplikacji. Przed migracją istniejącej bazy aplikacja zapisuje jej kopię
jako `instance/finanse.db.backup-vN`, gdzie `N` to wersja sprzed migracji.

Migracja 3 usuwa konta. Baza z więcej niż jednym kontem nie zostanie zmigrowana,
bo ich danych nie da się bezpiecznie scalić: aplikacja pokaże błąd i nic nie zmieni.
Kopie sprzed tej migracji nadal zawierają tabelę `users` z hashami haseł.

## Import z banku

Wybierz portfel, kliknij **Import CSV** i wskaż plik z banku. Aplikacja rozpoznaje
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

Testy okien działają bez ekranu, na platformie Qt `offscreen`.

## Model danych

- `wallets` – portfele
- `categories` – kategorie
- `transactions` – wydatki i przychody w portfelu
- `products` – pozycje transakcji: nazwa, kategoria, ilość, cena, wartość
- `transfers` – przelewy między portfelami, z kwotą po każdej stronie

Kwota transakcji to suma wartości jej produktów. Saldo portfela to saldo początkowe
plus przychody i przelewy przychodzące, minus wydatki i przelewy wychodzące.
Przelewy nie liczą się do przychodów ani wydatków w raportach. Portfela z przelewami
nie można usunąć, dopóki ich nie usuniesz, bo zmieniłoby to saldo drugiego portfela.

Kwoty są przechowywane w groszach, a ilości w tysięcznych częściach jednostki,
zawsze jako liczby całkowite.
