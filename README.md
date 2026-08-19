# AkusticStatus 🎵

**AkusticStatus** to wszechstronna aplikacja desktopowa do automatycznego synchronizowania i wyświetlania tekstu aktualnie odtwarzanej piosenki (z **Spotify**, **YouTube Music** lub **telefonu**) w formie **Discord Rich Presence**, eleganckiego **panelu WWW / okna aplikacji** oraz bezpośrednio w grze **Minecraft** poprzez dedykowany mod.

---

## 🌟 Główne Funkcje

- **Discord Rich Presence**: Pokazuje aktualną linijkę tekstu piosenki oraz okładkę albumu jako Twój status na Discordzie.
- **Natywne Okno / Panel WWW**: Elegancki interfejs w natywnym oknie (lub w przeglądarce pod adresem `http://127.0.0.1:5050`) pozwalający na podgląd tekstu, sterowanie odtwarzaniem oraz zmianę motywów.
- **Wsparcie dla Minecrafta**: Posiada wbudowany serwer API (`http://127.0.0.1:47474/now-playing`), z którym automatycznie łączy się mod do Minecrafta (mod działa od razu bez żadnej dodatkowej konfiguracji – wystarczy, że **AkusticStatus.exe** jest uruchomiony).
- **Aplikacja mobilna / Pilot**: Integracja z telefonem (pilot z szyfrowaniem AES-GCM i bezpiecznym parowaniem kodem PIN).
- **Inteligentne Pobieranie Tekstów**: Automatyczne wyszukiwanie zsynchronizowanych tekstów piosenek z wielu źródeł (LRCLIB, syncedlyrics, Genius i inne).
- **Bezpośrednie połączenie ze Spotify**: Natywna obsługa odczytu odtwarzacza Spotify bez limitów zapytań (error 429).

---

## 🚀 Szybki Start (Pobranie i Uruchomienie)

1. Przejdź do zakładki **Releases** na GitHubie i pobierz najnowszą skompilowaną wersję: **`AkusticStatus.exe`**.
2. Uruchom plik **`AkusticStatus.exe`**. Program otworzy się jako gotowe, eleganckie okno aplikacji.

> **Nie musisz instalować Pythona ani żadnych bibliotek!** Wszystkie zależności są już wbudowane w plik wykonywalny `.exe`.

---

## ⚙️ Pierwsza Konfiguracja

Po pierwszym uruchomieniu pliku `.exe`, pliki konfiguracyjne i ustawienia tworzone są automatycznie w bezpiecznym folderze danych systemowych:
- **Windows**: `%LOCALAPPDATA%\AcusticSquad\Liryc`

### 1. Konfiguracja Discord Rich Presence
1. Przejdź do [Discord Developer Portal](https://discord.com/developers/applications) i zaloguj się.
2. Utwórz nową aplikację (kliknij *New Application*).
3. Skopiuj **APPLICATION ID** (Client ID).
4. W oknie aplikacji **AkusticStatus** przejdź do zakładki **⚙️ Ustawienia** ➔ **Konfiguracja API**.
5. Wklej skopiowany ID w polu **Discord Client ID** i kliknij **Zapisz Ustawienia**.

### 2. Konfiguracja Spotify (Opcjonalnie - dla sterowania odtwarzaniem)
Aplikacja automatycznie odczytuje odtwarzany utwór ze Spotify. Jeśli chcesz dodatkowo sterować odtwarzaczem z poziomu panelu (pauza, zmiana utworów, kolejka):
1. Przejdź do [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) i utwórz aplikację.
2. W ustawieniach wklej **Redirect URI**: `http://127.0.0.1:8888/callback`.
3. Skopiuj **Client ID** oraz **Client Secret** i wklej je w zakładce **⚙️ Ustawienia** w aplikacji **AkusticStatus**.

---

## 🎮 Integracja z Minecraftem

Mod do Minecrafta współpracuje z aplikacją **AkusticStatus** całkowicie bezobsługowo:
1. Pobierz i zainstaluj mod do Minecrafta (Fabric/Forge).
2. **Brak jakiejkolwiek konfiguracji!** Mod automatycznie wykrywa uruchomioną aplikację i łączy się z lokalnym API (`http://127.0.0.1:47474/now-playing`).
3. Mod działa natychmiast po uruchomieniu gry, o ile w tle działa **AkusticStatus.exe**.

---

## 📱 Sterowanie Telefonem (Appka Pilot)

Aby połączyć telefon z aplikacją na komputerze:
1. Otwórz **AkusticStatus** na komputerze i przejdź do zakładki **⚙️ Ustawienia**.
2. Odczytaj **Kod parowania** oraz **IP Komputera** wyświetlone w sekcji *Informacje o Parowaniu*.
3. Wprowadź te dane w aplikacji na telefonie. Połączenie jest w pełni chronione szyfrowaniem **AES-GCM**.
