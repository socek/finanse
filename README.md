# Finanse

Okienkowa aplikacja do spisywania finansów na jednym komputerze: wiele portfeli,
portfel ma wiele transakcji, a transakcja wiele produktów. Interfejs jest w Qt
(PySide6). Aplikacja nie ma kont ani logowania, a baza SQLite nie jest szyfrowana,
więc dostęp do danych chronią tylko uprawnienia do pliku.

## Funkcje

- portfele z własną walutą i saldem początkowym, w tym portfele z VAT
- transakcje z wieloma produktami oraz osobne listy transakcji i produktów według
  dni, z wielu wybranych portfeli naraz, z szukaniem po nazwie i filtrami po dacie,
  kategorii i kwocie
- kategorie przypisywane do produktów, więc jeden paragon może mieć kilka kategorii
- tagi transakcji niezależne od kategorii, np. „Wakacje 2026”, z filtrem na listach
  i podsumowaniem w raporcie
- historia ceny produktu: najniższa, najwyższa i średnia cena, wykres oraz porównanie sklepów
- podpowiedzi nazw produktów z historii, które uzupełniają kategorię, ostatnią cenę i stawkę VAT
- przelewy między portfelami, także w różnych walutach
- duplikowanie transakcji: nowa transakcja z kopią produktów, opisu i portfela
- transakcje cykliczne opłacane jednym przyciskiem, z opcjonalnymi produktami, licznikiem
  i terminem płatności, z wyróżnieniem zaległych i zbliżających się płatności
- prognoza salda na koniec miesiąca lub wybrany dzień, z płatności cyklicznych i operacji
  wpisanych z późniejszą datą
- raporty za miesiąc, rok lub dowolny zakres dat z wybranych portfeli jednej waluty:
  bilans, rozbicie na portfele, podział na kategorie i wykres według miesięcy lub lat
- miesięczne budżety kategorii, osobno dla każdej waluty, z paskiem wykorzystania
  w raporcie
- import wyciągów bankowych z plików CSV z ochroną przed duplikatami i regułami, które
  nadają kategorię, nazwę produktu i tagi według opisu
- historia zmian danych i automatyczna kopia bazy przy każdym uruchomieniu
- motywy kolorystyczne: systemowy, jasny, ciemny, sepia i kolorowy, zapisywane w `settings.json`
  obok bazy
- pasek menu ze wszystkimi działaniami i pięć zakładek z danymi; historia, pliki, ustawienia
  i informacje o programie otwierają się w osobnych oknach
- skróty klawiszowe do większości działań, zmieniane w oknie **Edycja → Ustawienia** (Ctrl+,)
- własny pasek tytułowy w każdym oknie, dla menedżerów okien bez dekoracji, np. Hyprland

## Uruchomienie

```sh
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/finanse
```

Baza powstaje przy pierwszym uruchomieniu jako `~/.finanse/finanse.db`. Inną bazę
można wskazać argumentem: `.venv/bin/finanse /sciezka/do/bazy.db`.

Aby dodać aplikację do menu programów, zainstaluj plik `.desktop`. Trzeba to powtórzyć
po przeniesieniu projektu, bo plik zawiera jego ścieżkę:

```sh
sed "s|@PROJECT_DIR@|$PWD|g" finanse.desktop.in > ~/.local/share/applications/finanse.desktop
```

## Pasek tytułowy

Menedżery okien takie jak Hyprland czy sway nie rysują pasków tytułowych, więc aplikacja
może dodać własny do każdego okna: głównego, formularzy, komunikatów i zapytań. Pasek
pokazuje tytuł okna i przycisk zamknięcia, a przeciągnięcie go przesuwa pływające okno.
Domyślnie jest włączony, gdy `XDG_CURRENT_DESKTOP` wskazuje taki pulpit. Przełącznik
w menu **Widok** i w oknie ustawień zapisuje wybór w `settings.json`.

## Wersja i historia zmian

Wersja jest w `finanse/__init__.py`, a historia zmian w `finanse/CHANGELOG.md`.
Obie widać w oknie **Pomoc → O programie**. Nową wersję trzeba dopisać do historii zmian.

## Aktualizacja bazy

Zmiany schematu są w `finanse/migrations/NNN_nazwa.sql` i wykonują się same przy
starcie aplikacji. Przed migracją istniejącej bazy aplikacja zapisuje jej kopię
jako `~/.finanse/finanse.db.backup-vN`, gdzie `N` to wersja sprzed migracji.

Migracja 3 usuwa konta. Baza z więcej niż jednym kontem nie zostanie zmigrowana,
bo ich danych nie da się bezpiecznie scalić: aplikacja pokaże błąd i nic nie zmieni.
Kopie sprzed tej migracji nadal zawierają tabelę `users` z hashami haseł.

## Historia i kopie

Triggery zapisują każdą zmianę w tabeli `change_log`, razem ze starymi i nowymi
wartościami, także zmiany wykonane poza aplikacją, np. w konsoli `sqlite3`. Okno
**Pomoc → Historia zmian danych** pokazuje je jako tekst. Dziennik nie jest czyszczony, więc zostają w nim
również usunięte dane. Nie ma jeszcze przycisku cofania zmian. Nowa kolumna lub tabela
wymaga przebudowy triggerów w migracji.

Przy każdym uruchomieniu aplikacja zapisuje kopię całej bazy w `~/.finanse/backups/`
i zostawia 30 najnowszych. Aby wrócić do kopii, zamknij aplikację i podmień nią plik
`~/.finanse/finanse.db`.

Okno **Plik → Kopie i pliki danych** pokazuje pliki z katalogu bazy i podkatalogu `backups`, ich rozmiar
oraz sumy dla każdej grupy i całości.

## Import z banku

Kliknij portfel prawym przyciskiem myszy, wybierz **Import CSV** i wskaż plik z banku. Aplikacja rozpoznaje
kodowanie, separator i kolumny, a przed zapisem pokazuje podgląd, w którym można
to poprawić. Każdy wiersz staje się transakcją z jednym produktem: kwoty ujemne
to wydatki, a dodatnie to przychody.

Reguły importu (**Plik → Reguły importu** albo przycisk w oknie importu) nadają transakcji
kategorię, nazwę produktu i tagi, gdy opis z wyciągu zawiera tekst reguły. Wielkość liter,
polskie znaki i nadmiarowe spacje nie mają znaczenia, więc „Żabka” pasuje do „ZABKA 1234
KRAKOW”. Reguła może dotyczyć tylko wydatków albo tylko przychodów. Wygrywa pierwsza pasująca
reguła z listy, a kolejność można zmieniać. Wiersz bez reguły, albo z regułą bez kategorii,
dostaje kategorię wybraną w oknie importu. Podgląd pokazuje kategorię każdego wiersza,
a dwuklik w wiersz tworzy regułę z jego opisu. Reguły działają tylko przy imporcie i nie
zmieniają transakcji już zapisanych.

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
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Testy okien działają bez ekranu, na platformie Qt `offscreen`.

## Model danych

- `wallets` – portfele
- `categories` – kategorie
- `transactions` – wydatki i przychody w portfelu
- `products` – pozycje transakcji: nazwa, kategoria, ilość, cena, wartość
- `transfers` – przelewy między portfelami, z kwotą po każdej stronie
- `recurring_transactions`, `recurring_products` – szablony transakcji cyklicznych
- `budgets` – miesięczne limity wydatków kategorii w danej walucie
- `tags`, `transaction_tags` – tagi i ich przypisanie do transakcji
- `import_rules` – reguły importu wyciągów
- `operations`, `change_log` – dziennik zmian

W portfelu z VAT wartość produktu to kwota brutto, od której zależą saldo i raporty, a netto
to wartość pomniejszona o `vat_cents`. Stawki to 23%, 8%, 5%, 0% i zwolnienie. Zestawienie
VAT sumuje stawki z transakcji wybranego okresu raportu, według ich daty, i nie zastępuje
rozliczenia z księgowością.

Transakcja cykliczna może mieć termin następnej płatności i okres: co ileś dni, tygodni,
miesięcy lub lat. Płatność i przycisk **Pomiń termin** przesuwają termin o jeden okres,
licząc od poprzedniego terminu, a nie od daty płatności. Termin miesięczny lub roczny
wraca do pierwotnego dnia, np. 31 stycznia, 28 lutego, 31 marca. Zakładka pokazuje
w nazwie liczbę płatności po terminie lub na dzisiaj, a na liście wyróżnia zaległe
oraz te z terminem w ciągu 7 dni.

Raport obejmuje miesiąc, rok albo zakres dat z oboma końcami. Wykres pokazuje 12 miesięcy
do wybranego miesiąca, miesiące wybranego roku, a dla zakresu jego miesiące albo, przy
zakresie dłuższym niż 24 miesiące, lata. Kliknięcie słupka otwiera raport tego miesiąca
lub roku. Przyciski poprzedni i następny przesuwają okres o jego długość.

Budżet to miesięczny limit wydatków w kategorii, ustawiany w zakładce **Kategorie i tagi**
osobno dla każdej waluty i taki sam w każdym miesiącu. Raport porównuje go z wydatkami
z portfeli wybranych w raporcie, bez przychodów i przelewów. W raporcie za rok lub zakres dat limit
jest mnożony przez liczbę miesięcy, a niepełny miesiąc liczy się według dni. Od 80% limitu pasek jest
bursztynowy, a po przekroczeniu czerwony. Usunięcie kategorii usuwa też jej budżet.

Historia ceny, otwierana w zakładce **Produkty**, zbiera wydatki na produkt o tej samej
nazwie, bez względu na wielkość liter i nadmiarowe spacje, osobno dla każdej waluty.
Sklepem jest opis transakcji. Średnia to kwota zapłacona za jednostkę: suma wartości
podzielona przez sumę ilości.

Prognoza salda to saldo na koniec dzisiejszego dnia, operacje i przelewy wpisane już
z późniejszą datą oraz płatności cykliczne z terminem do wybranego dnia, także zaległe
i powtarzające się kilka razy w okresie, z uwzględnieniem licznika. Płatności szablonów
bez produktów są wymienione, ale nie zmieniają prognozy, bo nie mają kwoty. Zakładka
**Portfele** pokazuje prognozę zaznaczonych portfeli na koniec miesiąca, a przycisk
**Prognoza salda** otwiera szczegóły z wyborem dnia.

Pole nazwy produktu podpowiada znane nazwy, od najczęściej używanych, po fragmencie
nazwy i bez względu na wielkość liter. Wybór nazwy albo wpisanie znanej uzupełnia puste
pola z ostatniego użycia: kategorię, cenę z ostatniego zakupu w walucie portfela i, w portfelu
z VAT, stawkę. Wpisanych już wartości podpowiedź nie zmienia.

Tagi wpisuje się w oknie transakcji po przecinku, a nowy tag powstaje przy zapisie. Nazwy
porównuje się bez wielkości liter, także polskich. Tag ma cała transakcja, nie pojedynczy
produkt. Listy można filtrować po tagu, szukanie znajduje transakcje także po nazwie tagu,
a raport pokazuje przychody, wydatki i bilans każdego tagu w okresie. Zmiana nazwy i usuwanie
tagów są w zakładce **Kategorie i tagi**; usunięcie tagu nie usuwa transakcji.

Kwota transakcji to suma wartości jej produktów. Saldo portfela to saldo początkowe
plus przychody i przelewy przychodzące, minus wydatki i przelewy wychodzące.
Przelewy nie liczą się do przychodów ani wydatków w raportach. Portfela z przelewami
nie można usunąć, dopóki ich nie usuniesz, bo zmieniłoby to saldo drugiego portfela.

Ilość, cena i wartość produktu są przechowywane w stutysięcznych częściach, czyli
z 5 miejscami po przecinku. Salda, raporty i listy korzystają z wartości produktu
zaokrąglonej do groszy, a pozostałe kwoty są zapisywane w groszach, zawsze jako liczby
całkowite.
