# InPost Air Map

Osobna aplikacja pokazująca paczkomaty na mapie OpenStreetMap i sprawdzająca,
które **aktualnie zwracają liczbowe pomiary**. Kliknięcie punktu wyświetla
wszystkie pola z `air_sensors`, także nowe typy czujników. Pole
`air_index_level: null` nie ukrywa pomiarów.

## Uruchomienie

Wymagany Python 3.11 lub nowszy.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Otwórz `http://127.0.0.1:8765`. Przy pierwszym wejściu aplikacja pobierze
listę paczkomatów z InPost. Wyszukaj kod, np. `SPA01N`, lub zbliż mapę i kliknij
**Sprawdź widoczne punkty**. Jedno uruchomienie sprawdza najwyżej 30 punktów;
serwer zachowuje odstęp między zapytaniami. Wyniki i lista punktów są zapisywane
w `data/`, dzięki czemu pozostają po restarcie aplikacji.

## Znaczenie statusów

- **Aktualne pomiary**: odpowiedź InPost zawiera co najmniej jeden poprawny
  pomiar liczbowy pobrany w ostatnich 15 minutach.
- **Starszy pomiar**: ostatni poprawny odczyt ma ponad 15 minut.
- **Brak danych**: nie znaleziono adresu danych czujnika albo odpowiedź nie
  zawiera pomiarów liczbowych. To nie jest diagnoza sprzętu paczkomatu.
- **Błąd sprawdzenia**: serwer InPost odmówił dostępu lub wystąpił błąd
  połączenia. Punkt nie jest wtedy oznaczany jako nieposiadający czujnika.
- **Niesprawdzony**: nie wykonano jeszcze zapytania dla punktu.

Mapa nie skanuje automatycznie całej Polski. Statusy pojawiają się po
sprawdzeniu wybranych punktów i są pamiętane lokalnie. W dużym obszarze mapa
pokazuje maksymalnie 500 punktów, dlatego należy zbliżyć widok.

Aplikacja używa tego samego endpointu strony InPost co integracja Home Assistant.
Nie jest to oficjalnie udokumentowane API pomiarowe; InPost może zmienić jego
działanie. Do publicznego wdrożenia trzeba zapewnić własny serwer aplikacji
i dostawcę kafelków zgodnego z przewidywanym ruchem. Dane mapowe i kafelki
pochodzą z [OpenStreetMap](https://www.openstreetmap.org/copyright).

## Testy

```powershell
python -m unittest discover -s tests -v
```

Testy nie łączą się z InPost. Sprawdzają parsowanie odpowiedzi, rozróżnianie
statusów oraz działanie API aplikacji.
