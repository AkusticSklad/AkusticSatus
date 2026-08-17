# AkusticSatus

Aplikacja, która pokazuje aktualnie odtwarzaną linijkę tekstu piosenki (Spotify / YouTube Music / telefon) jako status na Discordzie (Rich Presence), a przy okazji daje Ci:

* panel WWW / okienko appki z okładką, tekstem piosenki i przyciskami play / pauza / next / previous,
* lokalne API dla moda do Minecrafta (`http://127.0.0.1:47474s/now-playing`),
* odbiornik "co teraz gra" z telefonu przez Tasker/Skróty albo przez appkę-pilota (parowanie kodem + szyfrowanie),
* automatyczne pobieranie tekstów piosenek (LRCLIB, syncedlyrics, lyrics.ovh, Genius).

Ten plik to instrukcja **dla osoby, która pobrała gotowe `.exe`** — jak odpalić program, skonfigurować go pierwszy raz i zdobyć potrzebne tokeny/klucze. To nie jest dokumentacja kodu.



## 1\. Wymagania

* Windows (gotowe `.exe` jest budowane pod Windows).
* Konto Discord (do statusu Rich Presence) — Discord musi być uruchomiony w tle.
* Konto Spotify (jeśli chcesz obsługi Spotify) — **działa też na koncie darmowym**, Spotify Web API nie wymaga Premium do samego odczytu/sterowania odtwarzaniem w większości przypadków, ale niektóre akcje sterujące wymagają aktywnego urządzenia z odtwarzaczem.
* (Opcjonalnie) [YouTube Music Desktop App](https://ytmdesktop.app/) z włączonym lokalnym API, jeśli chcesz obsługi YouTube Music zamiast/obok Spotify.
* (Opcjonalnie) Tasker / Skróty na telefonie, jeśli chcesz przesyłać "co gra" z telefonu.

## 2\. Pierwsze uruchomienie

1. Pobierz `AkusticSatus.exe` z wydania (Release) tego repozytorium.
2. Odpal plik. Ponieważ `.exe` jest budowany z flagą `--noconsole`, **nie zobaczysz czarnego okna terminala** — program działa w tle, a sterowanie odbywa się przez panel WWW/okno appki, które otworzy się automatycznie.
3. Przy pierwszym starcie program sam utworzy folder z danymi:

   * Windows: `%LOCALAPPDATA%\\AcusticSquad\\Liryc`

   Tam trzymane są: `settings.json` (Twoja konfiguracja), `spotify\_token.json` (tokeny Spotify) oraz kod parowania telefonu. Folder możesz szybko otworzyć przyciskiem w panelu WWW ("Otwórz folder z danymi").

4. Jeśli nie uzupełnisz jeszcze żadnych kluczy — program mimo to się uruchomi, po prostu status na Discordzie i pobieranie muzyki nie zadziałają, dopóki nie wykonasz konfiguracji poniżej.

## 3\. Pierwsza konfiguracja (panel WWW → zakładka „⚙️ Ustawienia”)

Po uruchomieniu aplikacji przejdź do zakładki **Ustawienia**. Będziesz tam wklejać dwa rodzaje danych:

* **Discord Client ID** — do wyświetlania statusu na Discordzie,
* **Spotify Client ID** i **Spotify Client Secret** — do odczytu/sterowania Spotify.

Skąd je wziąć — patrz sekcje 4 i 5 poniżej. Po wklejeniu kliknij **„Zapisz Ustawienia”**. Zmiany działają "na żywo" — nie trzeba restartować programu.

W tej samej zakładce znajdziesz też:

* wybór motywu kolorystycznego panelu,
* tryb wyświetlania kolejki/następnego utworu (tylko Spotify),
* **kod parowania telefonu** (do appki-pilota),
* adres IP komputera w sieci lokalnej i port panelu (przydatne przy konfiguracji telefonu),
* przycisk do szybkiego otwarcia folderu z danymi aplikacji.

## 4\. Pozyskanie tokenu Discord (Client ID)

Rich Presence na Discordzie wymaga własnej "aplikacji Discorda" (to nic nie kosztuje i nie wymaga bota):

1. Wejdź na [Discord Developer Portal](https://discord.com/developers/applications) i zaloguj się swoim kontem Discord.
2. Kliknij **New Application**, nadaj dowolną nazwę (to ona pojawi się jako nazwa statusu) i zatwierdź.
3. Na stronie aplikacji, w zakładce **General Information**, skopiuj wartość **APPLICATION ID** — to jest Twój `DISCORD\_CLIENT\_ID`.
4. Wklej go w panelu aplikacji w polu **Discord Client ID** i zapisz ustawienia.
5. Discord musi być uruchomiony na komputerze — program łączy się z nim lokalnie przez RPC. Jeśli status się nie pojawia, zrestartuj Discorda albo samą aplikację.

## 5\. Pozyskanie tokenów Spotify (Client ID + Client Secret)

1. Wejdź na [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) i zaloguj się swoim kontem Spotify.
2. Kliknij **Create app**.
3. Uzupełnij formularz:

   * **App name / App description** — dowolne.
   * **Redirect URI** — wpisz dokładnie:

```
     http://127.0.0.1:8888/callback
     ```

     (to jest adres, na który program odbiera odpowiedź logowania — musi być identyczny co do znaku).

   * Zaznacz zgodę na warunki i zapisz (**Save**).
4. Wejdź w ustawienia utworzonej aplikacji (**Settings**). Znajdziesz tam:

   * **Client ID** — skopiuj do pola **Spotify Client ID** w panelu programu,
   * **Client Secret** — kliknij "View client secret", skopiuj do pola **Spotify Client Secret**.
5. Zapisz ustawienia w panelu programu.
6. Włącz odtwarzanie czegokolwiek na Spotify (na dowolnym urządzeniu zalogowanym na Twoje konto) i poczekaj chwilę — program przy pierwszej próbie odczytu sam otworzy w przeglądarce stronę logowania Spotify:

   * Zaloguj się i kliknij **Agree/Zgadzam się**.
   * Zostaniesz przekierowany na `127.0.0.1:8888` z komunikatem, że logowanie się powiodło — możesz zamknąć tę kartę.
   * Program zapisze token w folderze danych (`spotify\_token.json`) i będzie go sam odświeżał — logowanie robisz tylko raz (chyba że usuniesz ten plik albo cofniesz dostęp aplikacji w ustawieniach konta Spotify).

**Uwaga:** jeśli okno logowania Spotify się nie otworzy automatycznie, program wypisze link w logach — na `.exe` bez konsoli tego nie zobaczysz, więc jeśli logowanie nie następuje, sprawdź, czy Client ID/Secret i Redirect URI są wpisane poprawnie (literówka w Redirect URI to najczęstsza przyczyna błędu `INVALID\_CLIENT: Invalid redirect URI`).

## 6\. YouTube Music (opcjonalnie)

Jeśli chcesz, żeby program czytał, co gra w YouTube Music (zamiast/obok Spotify):

1. Zainstaluj [YouTube Music Desktop App](https://ytmdesktop.app/).
2. W jego ustawieniach włącz **lokalny serwer API** (Integrations/Companion server) na porcie **26538** (to domyślny port, z którym program się komunikuje).
3. Autoryzuj połączenie, jeśli YTMDesktop o to poprosi.

Nie trzeba niczego wpisywać w panelu AkusticSatus — program sam wykryje działające YTMDesktop.

## 7\. Telefon — przesyłanie "co teraz gra"

1. W panelu programu, w zakładce Ustawienia, znajdź pole **Kod parowania**.
2. W Aplikacji na telefonie wpisz adres IP komputera (z panelu Ustawienia) oraz ten kod parowania.

Kod parowania jest generowany raz i zapisywany w folderze danych — nie trzeba go wpisywać ponownie po restarcie programu.

## 8\. Integracja z modem do Minecrafta

Mod może pobierać dane o aktualnie granym utworze z lokalnego, niewymagającego autoryzacji adresu:

```
http://127.0.0.1:47474/now-playing
```

Działa automatycznie, gdy program jest uruchomiony — nic nie trzeba konfigurować.

## 9\. Porty używane przez program

|Port|Do czego służy|
|-|-|
|5050|Panel WWW / okno appki (interfejs użytkownika)|
|8888|Lokalny callback logowania Spotify (tylko podczas autoryzacji)|
|26538|Połączenie z YouTube Music Desktop App|
|47474|Lokalne API dla moda do Minecrafta|
|47475|Odbiornik danych z telefonu (token / appka-pilot)|

Jeśli któryś port jest zajęty przez inny program, dana funkcja może nie zadziałać — zamknij aplikację blokującą port albo zmień port w kodzie źródłowym.

## 10\. Gdzie są zapisywane dane

Wszystko trzymane jest w `%LOCALAPPDATA%\\AcusticSquad\\Liryc`:

* `settings.json` — Twoja konfiguracja (Discord/Spotify ID, motyw, tryb wyświetlania),
* `spotify\_token.json` — tokeny dostępu do Spotify (odświeżane automatycznie),
* `phone\_pairing\_code.txt` — kod parowania appki-pilota.

Usunięcie `spotify\_token.json` wymusi ponowne zalogowanie do Spotify. Usunięcie `settings.json` przywróci ustawienia domyślne.

## 11\. Rozwiązywanie problemów

* **Status na Discordzie się nie pokazuje** — sprawdź, czy Discord jest uruchomiony, czy Client ID jest poprawny, i czy w panelu status Discorda (ikonka/wskaźnik) świeci na zielono. Spróbuj zrestartować program.
* **Spotify się nie loguje / błąd `INVALID\_CLIENT`** — sprawdź literówki w Redirect URI (`http://127.0.0.1:8888/callback`) w ustawieniach aplikacji na Spotify Developer Dashboard.
* **Nic nie gra, mimo że coś leci na Spotify** — sprawdź, czy jest aktywne urządzenie odtwarzające w aplikacji Spotify (czasem trzeba raz kliknąć play bezpośrednio w apce Spotify).
* **YouTube Music nie jest wykrywane** — upewnij się, że YTMDesktop ma włączone lokalne API na porcie 26538 i że aplikacja jest uruchomiona.
* **Telefon się nie łączy** — upewnij się, że telefon i komputer są w tej samej sieci lokalnej (Wi-Fi), a firewall Windows nie blokuje portu 47475.

Pytania, błędy, sugestie — zgłoś w zakładce **Issues** tego repozytorium.

