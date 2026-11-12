# Historia zmian

## 0.3 (w przygotowaniu)

- Suma pod listą w zakładkach Cykliczne (wydatki i przychody) oraz Kategorie (budżety),
  osobno dla każdej waluty.
- Zawieszanie transakcji cyklicznych przyciskiem Zawieś/Wznów. Zawieszona zostaje na liście
  z wyszarzonym opisem i terminem, ale nie liczy się do sumy, prognozy salda ani liczby płatności
  po terminie.
- Menu pod prawym przyciskiem myszy na wierszach w zakładkach Cykliczne oraz Kategorie i tagi.
- Kopiowanie kwot z Raportów: Ctrl+C lub menu pod prawym przyciskiem w tabelach i przy kwotach.
  Do schowka trafia sama liczba, bez spacji i waluty (np. `1234,56`), a kilka komórek tabeli
  wkleja się do arkusza w tym samym układzie.

## 0.2 (2026-11-07)

- Przywracanie kopii bazy z okna Kopie i pliki danych albo z dowolnego pliku, bez zamykania
  aplikacji. Kopia jest najpierw sprawdzana, starsza wersja od razu migrowana, a obecne dane
  zapisywane jako `finanse.db.przed-przywroceniem-…`, więc przywrócenie da się cofnąć.
- Reguły importu CSV: gdy opis z wyciągu zawiera tekst reguły, transakcja dostaje kategorię,
  nazwę produktu i tagi. Dopasowanie pomija wielkość liter i polskie znaki, reguła może
  dotyczyć tylko wydatków lub przychodów, a wygrywa pierwsza z listy. Podgląd importu pokazuje
  kategorie, a dwuklik w wiersz tworzy regułę z jego opisu.
- Pasek menu: Plik, Edycja, Widok, Portfel, Transakcja, Raport i Pomoc, z aktualnymi skrótami
  i wyszarzeniem działań bez zaznaczenia. Zostało pięć zakładek z danymi, a Historia, Pliki,
  Ustawienia i O programie otwierają się w osobnych oknach. Ustawienia mają skrót Ctrl+,,
  a skróty Ctrl+6–Ctrl+9 są wolne.
- Tagi transakcji niezależne od kategorii, np. „Wakacje 2026” albo „Remont”: pole z podpowiedziami
  w oknie transakcji, tagi przy opisie na liście, filtr po tagu, sekcja „Według tagów” w raporcie
  oraz zmiana nazwy i usuwanie w zakładce Kategorie.
- Duplikowanie transakcji w zakładkach Portfele i Produkty, przyciskiem, z menu pod prawym
  przyciskiem myszy i skrótem Ctrl+Shift+C. Kopia otwiera się jako nowa transakcja, w której
  przed zapisem można zmienić datę, portfel i produkty.
- Podpowiedzi nazw produktów z historii w oknach transakcji, płatności i transakcji
  cyklicznych. Wybrana nazwa uzupełnia puste pola: kategorię, ostatnią cenę i stawkę VAT.
- Prognoza salda na koniec miesiąca w zakładce Portfele i okno prognozy na wybrany dzień,
  z płatnościami cyklicznymi, także zaległymi, i operacjami wpisanymi z późniejszą datą.
- Historia ceny produktu w zakładce Produkty: ostatnia, najniższa, najwyższa i średnia cena,
  zmiana od pierwszego zakupu, wykres ceny w czasie i porównanie sklepów.
- Raporty za rok i za dowolny zakres dat, obok miesięcznych. Wykres pokazuje miesiące okresu,
  a przy długim zakresie lata, a budżety są przeliczane na długość okresu.
- Pasek tytułowy w każdym oknie aplikacji, z tytułem, przyciskiem zamknięcia i przesuwaniem
  okna. Domyślnie włączony na pulpitach bez dekoracji okien, np. Hyprland, i przełączany
  w Ustawieniach.
- Miesięczne budżety kategorii, ustawiane w zakładce Kategorie osobno dla każdej waluty.
  Raport pokazuje, ile z limitu wydano i ile zostało, z wyróżnieniem budżetów bliskich
  wyczerpania i przekroczonych.
- Terminy transakcji cyklicznych: okres powtarzania i data następnej płatności, którą
  płatność przesuwa o jeden okres. Lista pokazuje zaległe i zbliżające się płatności,
  a nazwa zakładki liczbę płatności po terminie lub na dzisiaj. Przycisk Pomiń termin
  przesuwa termin bez płatności.
- Portfel z VAT: stawki, ceny i wartości netto oraz brutto w formularzu, kolumny netto
  i VAT na listach oraz zestawienie VAT w raporcie miesięcznym.
- Kategorię produktu można wpisać z klawiatury, z przybliżonym wyszukiwaniem. Wejście na
  pole zaznacza jego tekst, więc pisanie zaczyna się od zera.
- Ilość, cena i wartość produktu mogą mieć do 5 miejsc po przecinku. Listy pokazują je
  zaokrąglone do 2 miejsc, a salda i raporty liczą wartości zaokrąglone do groszy.
- Minus wpisany lub wklejony w ilość, cenę albo wartość produktu jest usuwany.
- Okno nowej transakcji otwiera się z kursorem w nazwie pierwszego produktu.
- Wydatki i przychody mają inne tło wiersza na listach transakcji i produktów.
- Skróty klawiszowe są pokazywane w podpowiedziach przycisków, a nie w ich nazwach.
- Usunąć można tylko pustą kategorię, bez produktów i produktów transakcji cyklicznych.
- Transakcje cykliczne nie mają już własnej kwoty ani kategorii. Wyznaczają je produkty,
  a bez produktów podaje się je przy płatności.

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
