"""
AkusticStatus - wersja POŁĄCZONA (statusik.py + lyric_status_light.py + ssman.py + sasana biją w domy.py)
======================================================================
Pokazuje aktualną linijkę tekstu piosenki (Spotify / YouTube Music / telefon)
jako Discord Rich Presence, a jednocześnie:

  • wystawia panel WWW z okładką, tekstem i przyciskami play/pauza/next/
    previous - otwierany albo jako NATYWNE OKNO appki (pywebview, gdy
    zainstalowane - tak wygląda to po zbudowaniu do .exe), albo w zwykłej
    przeglądarce (fallback, gdy pywebview nie jest zainstalowane),
  • wystawia lokalne API dla moda do Minecrafta (http://127.0.0.1:47474/now-playing),
  • przyjmuje "co teraz gra" z telefonu przez Tasker/Skróty (zwykły token)
    ORAZ przez natywną appkę-pilota (parowanie kodem + szyfrowanie AES-GCM,
    z podglądem stanu i sterowaniem play/pause/next/previous/search),
  • pobiera teksty piosenek w kolejności: LRCLIB (zsynchronizowane) ->
    syncedlyrics (wiele serwisów) -> LRCLIB (zwykłe) -> lyrics.ovh -> Genius,
    z rozkładem przybliżonym gdy nie ma prawdziwej synchronizacji,
  • obsługuje komendy z terminala: on/off (status na Discordzie), status,
    delay <sekundy> (ręczne przesunięcie tekstu) - dostępne tylko gdy skrypt
    ma konsolę (przy zbudowanym .exe bez konsoli te same funkcje są w panelu WWW).

INSTALACJA:
    pip install requests pypresence cryptography syncedlyrics pywebview

URUCHOMIENIE (development, z konsolą):
    python statusik.py

BUDOWANIE .EXE (patrz też komentarz na końcu pliku, sekcja "BUDOWANIE .EXE"):
    pip install pyinstaller
    pyinstaller --onefile --noconsole --name "AkusticStatus" statusik.py
"""

import base64
import hashlib
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import requests

if sys.stdout is None or sys.stderr is None:
    def print(*args, **kwargs):
        pass
else:
    _builtin_print = print
    def print(*args, **kwargs):
        try:
            _builtin_print(*args, **kwargs)
        except UnicodeEncodeError:
            try:
                safe_args = [str(a).encode("ascii", "ignore").decode("ascii") for a in args]
                _builtin_print(*safe_args, **kwargs)
            except Exception:
                pass

try:
    import webview
except ImportError:
    webview = None

# ============================================================
# FOLDER DANYCH APLIKACJI (AppData/Local/AcusticSquad/Liryc)
# ============================================================

def _get_app_data_dir():
    """Zwraca (i tworzy, jeśli trzeba) folder na dane aplikacji:
    Windows:  %LOCALAPPDATA%\\AcusticSquad\\Liryc
    macOS:    ~/Library/Application Support/AcusticSquad/Liryc
    Linux:    $XDG_DATA_HOME/AcusticSquad/Liryc (albo ~/.local/share/...)
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")

    app_dir = os.path.join(base, "AcusticSquad", "Liryc")
    try:
        os.makedirs(app_dir, exist_ok=True)
    except Exception as e:
        print(f"[appdata] Nie udało się utworzyć {app_dir}: {e}")
    return app_dir

APP_DATA_DIR = _get_app_data_dir()

def _ensure_app_data_dir():
    """Upewnia się, że folder danych istnieje - wywoływane tuż przed każdym
    zapisem pliku, żeby nic nie ginęło w ciszy, jeśli folder z jakiegoś
    powodu nie powstał na starcie (np. chwilowy brak uprawnień)."""
    try:
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        return True
    except Exception as e:
        print(f"[appdata] Nie udało się utworzyć {APP_DATA_DIR}: {e}")
        return False

def _migrate_legacy_file(old_relative_name, new_path):
    """Jednorazowo przenosi plik z poprzedniej lokalizacji (obok skryptu/.exe,
    tak jak było wcześniej) do nowego folderu w AppData - żeby przy aktualizacji
    nikt nie stracił zapisanych kluczy / tokenu / kodu parowania."""
    if os.path.exists(new_path):
        return
    candidates = [
        old_relative_name,
        os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), old_relative_name),
    ]
    for old_path in candidates:
        try:
            if os.path.exists(old_path):
                import shutil
                shutil.copy2(old_path, new_path)
                print(f"[migracja] Przeniesiono {old_path} -> {new_path}")
                return
        except Exception as e:
            print(f"[migracja] Nie udało się przenieść {old_path}: {e}")

# ============================================================
# KONFIGURACJA I ZAPIS USTAWIEN (settings.json)
# ============================================================

SETTINGS_FILE = os.path.join(APP_DATA_DIR, "settings.json")
DEFAULT_SETTINGS = {
    "DISCORD_CLIENT_ID": "",
    "SPOTIFY_CLIENT_ID": "",
    "SPOTIFY_CLIENT_SECRET": "",
    "THEME": "pink",
    "CUSTOM_COLOR": "#ffffff",
    "PRESENCE_ENABLED": True,
    "DISPLAY_MODE": "none",
    "QUEUE_COUNT": 5,
    "LYRIC_LINE_MODE": "single",
    "SPOTIFY_MODE": "native"
}

_migrate_legacy_file(".settings.json", SETTINGS_FILE)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in DEFAULT_SETTINGS.items():
                    data.setdefault(k, v)
                return data
        except Exception as e:
            print(f"[settings] Błąd odczytu {SETTINGS_FILE}: {e}")
    return dict(DEFAULT_SETTINGS)

def save_settings(settings):
    _ensure_app_data_dir()
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"[settings] Błąd zapisu ustawień do {SETTINGS_FILE}: {e}")

current_settings = load_settings()

DISCORD_CLIENT_ID = current_settings["DISCORD_CLIENT_ID"]
SPOTIFY_CLIENT_ID = current_settings["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = current_settings["SPOTIFY_CLIENT_SECRET"]

print(f"[dane] Ustawienia i pliki aplikacji zapisywane są w: {APP_DATA_DIR}")

SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"
SPOTIFY_TOKEN_FILE = os.path.join(APP_DATA_DIR, "spotify_token.json")
_migrate_legacy_file(".spotify_token_light.json", SPOTIFY_TOKEN_FILE)

YTMDESKTOP_HOST = "127.0.0.1"
YTMDESKTOP_PORT = 26538
WEB_SERVER_PORT = 5050
NOW_PLAYING_HTTP_PORT = 47474
PHONE_RECEIVER_HTTP_PORT = 47475
PHONE_SHARED_SECRET = "8011428185"
PHONE_STALE_AFTER_SECONDS = 12

PAIRING_CODE_FILE = os.path.join(APP_DATA_DIR, "phone_pairing_code.txt")
_migrate_legacy_file(".phone_pairing_code.txt", PAIRING_CODE_FILE)
PAIRING_CODE_DIGITS = 10

PREFERRED_SOURCE_ORDER = ["spotify", "youtube", "phone"]
POLL_INTERVAL_SECONDS = 2
LYRIC_TICK_SECONDS = 0.25
QUEUE_POLL_INTERVAL_SECONDS = 5

WINDOW_TITLE = "AkusticSatus"
WINDOW_WIDTH = 470
WINDOW_HEIGHT = 890
WINDOW_RESIZABLE = True

# ============================================================
# STAN GLOBALNY APLIKACJI
# ============================================================
state_lock = threading.Lock()
app_state = {
    "track": "Czekam na muzykę...",
    "artist": "",
    "line": "🎵 Uruchom utwór na Spotify / YouTube Music / telefonie",
    "next_line": "",
    "is_playing": False,
    "cover_url": None,
    "active_source": None,
    "status_discord": False,
    "status_spotify": False,
    "status_ytm": False,
    "status_phone": False,
    "presence_enabled": bool(current_settings.get("PRESENCE_ENABLED", True)),
    "lyric_offset_seconds": 0.0,
    "position_sec": 0.0,
    "duration_sec": 0.0,
    "queue": [],
}

def _update_app_state(**kwargs):
    with state_lock:
        app_state.update(kwargs)

def get_now_playing_snapshot():
    with state_lock:
        return {
            "track": app_state["track"],
            "artist": app_state["artist"],
            "line": app_state["line"],
            "is_playing": app_state["is_playing"],
            "cover_url": app_state["cover_url"],
        }

_session = requests.Session()
_session.headers.update({
    "User-Agent": "lyric-status-merged/1.0 (+personal Discord RPC / web panel script)"
})

class _QuietHTTPServer(HTTPServer):
    def handle_error(self, request, client_address):
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

# ============================================================
# SPOTIFY
# ============================================================
_SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
_SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
_SPOTIFY_SCOPE = "user-read-currently-playing user-read-playback-state user-modify-playback-state"

_spotify_tokens = None
_spotify_backoff_until = 0.0

class _CallbackHandler(BaseHTTPRequestHandler):
    received_code = None
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        _CallbackHandler.received_code = query.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("Zalogowano w Spotify. Możesz zamknąć tę kartę.".encode("utf-8"))
    def log_message(self, *args):
        pass

def _spotify_load_tokens():
    global _spotify_tokens
    if os.path.exists(SPOTIFY_TOKEN_FILE):
        try:
            with open(SPOTIFY_TOKEN_FILE, "r", encoding="utf-8") as f:
                _spotify_tokens = json.load(f)
        except Exception:
            _spotify_tokens = None

def _spotify_save_tokens():
    _ensure_app_data_dir()
    try:
        with open(SPOTIFY_TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(_spotify_tokens, f)
    except Exception as e:
        print(f"[spotify] Błąd zapisu tokenu do {SPOTIFY_TOKEN_FILE}: {e}")

def _spotify_first_login():
    global _spotify_tokens
    auth_url = (
        f"{_SPOTIFY_AUTH_URL}?client_id={SPOTIFY_CLIENT_ID}"
        f"&response_type=code&redirect_uri={SPOTIFY_REDIRECT_URI}"
        f"&scope={_SPOTIFY_SCOPE.replace(' ', '%20')}"
    )
    print(f"\n[SPOTIFY] Otwórz link autoryzacyjny w przeglądarce, jeśli nie otworzy się sam:\n{auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    server = HTTPServer(("127.0.0.1", 8888), _CallbackHandler)
    server.handle_request()
    code = _CallbackHandler.received_code
    if not code:
        return

    try:
        resp = _session.post(_SPOTIFY_TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": SPOTIFY_REDIRECT_URI,
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        })
        resp.raise_for_status()
        data = resp.json()
        _spotify_tokens = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "expires_at": time.time() + data.get("expires_in", 3600) - 30,
        }
        _spotify_save_tokens()
    except Exception as exc:
        print(f"[spotify] Błąd logowania: {exc}")

def _spotify_refresh_if_needed():
    global _spotify_tokens
    if not _spotify_tokens or time.time() < _spotify_tokens.get("expires_at", 0):
        return
    try:
        resp = _session.post(_SPOTIFY_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": _spotify_tokens["refresh_token"],
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        })
        resp.raise_for_status()
        data = resp.json()
        _spotify_tokens["access_token"] = data["access_token"]
        _spotify_tokens["expires_at"] = time.time() + data.get("expires_in", 3600) - 30
        _spotify_save_tokens()
    except Exception as exc:
        print(f"[spotify] Błąd odświeżania tokenu: {exc}")

def _spotify_auth_header():
    if _spotify_tokens is None:
        _spotify_load_tokens()
    if _spotify_tokens is None:
        _spotify_first_login()
    _spotify_refresh_if_needed()
    return {"Authorization": f"Bearer {_spotify_tokens['access_token']}"} if _spotify_tokens else {}

def _spotify_now_playing_webapi():
    """Stary tryb: odpytuje Spotify Web API (podatny na limit 429 przy
    dłuższym działaniu). Używany tylko jako fallback - patrz get_spotify_now_playing()."""
    global _spotify_backoff_until
    if _spotify_tokens is None:
        _spotify_load_tokens()
    if _spotify_tokens is None:
        _spotify_first_login()
    if not _spotify_tokens:
        return None
    if time.time() < _spotify_backoff_until:
        return None
    _spotify_refresh_if_needed()

    try:
        resp = _session.get(
            "https://api.spotify.com/v1/me/player/currently-playing",
            headers={"Authorization": f"Bearer {_spotify_tokens['access_token']}"},
            timeout=5,
        )
    except requests.RequestException as exc:
        print(f"[spotify] Błąd połączenia przy sprawdzaniu co gra: {exc}")
        return None

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        wait_seconds = float(retry_after) if retry_after else 30.0
        _spotify_backoff_until = time.time() + wait_seconds
        print(f"[spotify] Limit zapytań (429) - wstrzymuję na {wait_seconds:.0f}s.")
        return None

    if resp.status_code == 204:
        return None
    if resp.status_code != 200:
        return None
    if not resp.content:
        return None

    data = resp.json()
    item = data.get("item")
    if not item:
        return None

    artists = ", ".join(a["name"] for a in item.get("artists", []))
    images = (item.get("album") or {}).get("images") or []
    cover_url = images[0]["url"] if images else None

    return {
        "track": item.get("name"),
        "artist": artists,
        "duration_sec": item.get("duration_ms", 0) / 1000,
        "position_sec": data.get("progress_ms", 0) / 1000,
        "is_playing": data.get("is_playing", False),
        "cover_url": cover_url,
    }

# ============================================================
# NATYWNY ODCZYT "CO GRA" BEZPOŚREDNIO Z APLIKACJI SPOTIFY
# (macOS: AppleScript / Windows: tytuł okna + UI Automation)
# ------------------------------------------------------------
# Zamiast pytać Spotify Web API co POLL_INTERVAL_SECONDS (co przy
# dłuższym działaniu programu potrafiło skończyć się limitem 429),
# rozmawiamy bezpośrednio z lokalnie działającą aplikacją Spotify.
# Web API zostaje tylko do sterowania (play/pause/next) i kolejki -
# to są rzadkie, pojedyncze zapytania, które nie powodują limitu.
# ============================================================

_SPOTIFY_NATIVE_WARNED = False
_SPOTIFY_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


_COVER_LOOKUP_CACHE = {}
_COVER_LOOKUP_CACHE_MAX = 300


def _fetch_cover_online(track, artist):
    """Dogrywa okładkę utworu z Deezer (publiczne, darmowe API - bez klucza,
    bez logowania) - używane, gdy tryb natywny (np. Windows przez UI
    Automation) sam nie potrafi dostarczyć URL-a okładki. Wynik jest
    cache'owany per (utwór, artysta), więc Deezer jest odpytywany raz na
    zmianę utworu, a nie przy każdym pollu."""
    key = (track or "", artist or "")
    if key in _COVER_LOOKUP_CACHE:
        return _COVER_LOOKUP_CACHE[key]

    cover_url = None
    try:
        query = f"{artist} {track}".strip()
        resp = _session.get(
            "https://api.deezer.com/search",
            params={"q": query, "limit": 1},
            timeout=4,
        )
        if resp.status_code == 200:
            items = (resp.json() or {}).get("data") or []
            if items:
                album = items[0].get("album") or {}
                cover_url = album.get("cover_big") or album.get("cover_medium") or album.get("cover")
    except requests.RequestException as exc:
        print(f"[cover] Błąd pobierania okładki z Deezer: {exc}")
    except Exception as exc:
        print(f"[cover] Błąd przetwarzania odpowiedzi Deezer: {exc}")

    if len(_COVER_LOOKUP_CACHE) >= _COVER_LOOKUP_CACHE_MAX:
        _COVER_LOOKUP_CACHE.pop(next(iter(_COVER_LOOKUP_CACHE)))
    _COVER_LOOKUP_CACHE[key] = cover_url
    return cover_url


def _spotify_native_available():
    """Sprawdza, czy da się użyć natywnego odczytu na tym systemie."""
    if sys.platform == "darwin":
        return True  # osascript jest wbudowany w macOS
    if sys.platform == "win32":
        try:
            import uiautomation  # noqa: F401
            return True
        except ImportError:
            return False
    return False


# --------------------- macOS: AppleScript ---------------------

def _spotify_native_macos():
    """Pyta bezpośrednio aplikację Spotify (AppleScript / osascript) o to,
    co aktualnie gra. Oficjalnie wspierane API samej appki, więc pozycja
    utworu jest zawsze aktualna i dokładna - bez zapytań sieciowych."""
    import subprocess

    delim = "\x1f"  # unit separator - praktycznie nie występuje w nazwach utworów
    script = (
        'if application "Spotify" is running then\n'
        '    tell application "Spotify"\n'
        '        set playerState to player state as string\n'
        '        if playerState is "stopped" then\n'
        '            return "STOPPED"\n'
        '        end if\n'
        '        set trackName to name of current track\n'
        '        set trackArtist to artist of current track\n'
        '        set trackDuration to duration of current track\n'
        '        set trackPosition to player position\n'
        '        set trackArt to artwork url of current track\n'
        '        set trackDurationMs to round trackDuration\n'
        '        set trackPositionMs to round (trackPosition * 1000)\n'
        f'        return playerState & (ASCII character 31) & trackName & (ASCII character 31) & trackArtist & (ASCII character 31) & (trackDurationMs as string) & (ASCII character 31) & (trackPositionMs as string) & (ASCII character 31) & trackArt\n'
        '    end tell\n'
        'else\n'
        '    return "NOTRUNNING"\n'
        'end if\n'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=3,
        )
    except Exception as exc:
        print(f"[spotify-mac] Błąd wywołania AppleScript: {exc}")
        return None

    out = (result.stdout or "").strip()
    if not out or out in ("NOTRUNNING", "STOPPED"):
        return None

    parts = out.split(delim)
    if len(parts) < 6:
        return None

    state, track, artist, duration_ms_str, position_ms_str, art_url = parts[:6]
    # UWAGA: obie wartości to całkowite milisekundy (AppleScript "round"),
    # celowo NIE liczby rzeczywiste - "x as string" na macOS z polskim
    # regionem zwracał ułamek z przecinkiem ("45,821"), co float() nie
    # parsuje i powodowało zerowanie się pozycji (efekt "0,1,0,1 w kółko").
    try:
        duration_sec = float(duration_ms_str) / 1000.0
    except ValueError:
        duration_sec = 0.0
    try:
        position_sec = float(position_ms_str) / 1000.0
    except ValueError:
        position_sec = 0.0

    return {
        "track": track,
        "artist": artist,
        "duration_sec": duration_sec,
        "position_sec": position_sec,
        "is_playing": state == "playing",
        "cover_url": art_url or None,
    }


# --------------------- Windows: tytuł okna + UI Automation ---------------------

def _spotify_native_windows_find_window():
    """Szuka głównego, widocznego okna procesu Spotify.exe i zwraca jego
    uchwyt (hwnd) oraz tytuł. Tytuł okna Spotify na Windowsie to "Artist -
    Utwór" w trakcie odtwarzania, a sama nazwa "Spotify" (bez myślnika),
    gdy nic nie gra / jest pauza - to zachowanie appki jest stabilne od lat
    (korzysta z niego wiele podobnych narzędzi "now playing")."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi

    found = {"hwnd": None, "title": None}

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd, lparam):
        if found["hwnd"] is not None:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h_process = kernel32.OpenProcess(0x0400 | 0x0010, False, pid.value)
        if not h_process:
            return True
        try:
            exe_buf = ctypes.create_unicode_buffer(260)
            psapi.GetModuleBaseNameW(h_process, None, exe_buf, 260)
            exe_name = exe_buf.value
        finally:
            kernel32.CloseHandle(h_process)

        if exe_name.lower() == "spotify.exe":
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            found["hwnd"] = hwnd
            found["title"] = buf.value
        return True

    user32.EnumWindows(_enum_proc, 0)
    return found["hwnd"], found["title"]


def _spotify_native_windows_progress(hwnd):
    """Best-effort: przeszukuje drzewo UI Automation okna Spotify w
    poszukiwaniu dwóch "etykiet czasu" (np. "1:23" i "3:45") stojących
    przy pasku postępu - to elapsed/duration. Zwraca (position_sec,
    duration_sec) albo (None, None), jeśli się nie uda (np. brak
    biblioteki `uiautomation` albo Spotify zmieniło coś w UI)."""
    try:
        import uiautomation as auto
    except ImportError:
        return None, None

    try:
        window = auto.ControlFromHandle(hwnd)
    except Exception:
        return None, None
    if not window:
        return None, None

    found = []
    visited = [0]
    MAX_NODES = 4000
    MAX_DEPTH = 40

    def _walk(control, depth):
        if len(found) >= 2 or visited[0] >= MAX_NODES or depth > MAX_DEPTH:
            return
        visited[0] += 1
        try:
            name = control.Name
        except Exception:
            name = None
        if name and _SPOTIFY_TIME_RE.match(name):
            found.append(name)
            if len(found) >= 2:
                return
        try:
            children = control.GetChildren()
        except Exception:
            children = []
        for child in children:
            _walk(child, depth + 1)
            if len(found) >= 2:
                return

    try:
        _walk(window, 0)
    except Exception:
        return None, None

    if len(found) < 2:
        return None, None

    def _to_sec(txt):
        m, s = txt.split(":")
        return int(m) * 60 + int(s)

    return _to_sec(found[0]), _to_sec(found[1])


def _spotify_native_windows():
    """Odczyt "co gra" na Windowsie bez Spotify Web API: tytuł okna daje
    utwór/artystę/czy gra, a UI Automation (jeśli dostępne) dobiera
    pozycję/długość utworu z etykiet czasu przy pasku postępu. Okładka nie
    jest tu dostępna (Chromium nie ujawnia URL obrazka przez UI Automation)
    - front zamiast niej pokaże lokalny placeholder (patrz zmiana z okładką)."""
    hwnd, title = _spotify_native_windows_find_window()
    if not hwnd or not title:
        return None

    title = title.strip()
    if not title or title.lower() in ("spotify", "spotify premium", "spotify free"):
        return None  # nic nie gra / pauza bez wznowienia

    if " - " not in title:
        return None

    artist, _, track = title.partition(" - ")
    artist = artist.strip()
    track = track.strip()
    if not track:
        return None

    position_sec, duration_sec = _spotify_native_windows_progress(hwnd)
    cover_url = _fetch_cover_online(track, artist)

    return {
        "track": track,
        "artist": artist,
        "duration_sec": float(duration_sec or 0),
        "position_sec": float(position_sec or 0),
        "is_playing": True,
        "cover_url": cover_url,
    }


def get_spotify_now_playing():
    """Punkt wejścia używany przez resztę appki: odczytuje co gra w Spotify.
    Zależnie od ustawienia SPOTIFY_MODE ("native" / "api"):
      - "native" (domyślnie): łączy się BEZPOŚREDNIO z aplikacją Spotify
        (AppleScript na macOS / tytuł okna + UI Automation na Windowsie) -
        bez Spotify Web API, więc nie ma ryzyka limitu zapytań (429) przy
        dłuższym działaniu programu.
      - "api": wymusza stary tryb przez Spotify Web API (przydatne np. gdy
        natywny odczyt nie działa poprawnie na czyimś komputerze).
    Web API (_spotify_now_playing_webapi) jest też automatycznym fallbackiem
    na Windowsie, gdy brakuje biblioteki `uiautomation` (pip install
    uiautomation), niezależnie od wybranego trybu."""
    global _SPOTIFY_NATIVE_WARNED

    mode = current_settings.get("SPOTIFY_MODE", "native")
    if mode == "api":
        return _spotify_now_playing_webapi()

    if sys.platform == "darwin":
        return _spotify_native_macos()

    if sys.platform == "win32":
        if _spotify_native_available():
            return _spotify_native_windows()
        if not _SPOTIFY_NATIVE_WARNED:
            print(
                "[spotify] Brak biblioteki 'uiautomation' - zainstaluj: "
                "pip install uiautomation. Na razie korzystam z awaryjnego "
                "trybu przez Spotify Web API (może trafić na limit 429 "
                "przy dłuższym działaniu)."
            )
            _SPOTIFY_NATIVE_WARNED = True
        return _spotify_now_playing_webapi()

    # inne systemy (np. Linux) - zostaje stary tryb przez Web API
    return _spotify_now_playing_webapi()


def spotify_control(action):
    method_and_path = {
        "play": ("PUT", "https://api.spotify.com/v1/me/player/play"),
        "pause": ("PUT", "https://api.spotify.com/v1/me/player/pause"),
        "next": ("POST", "https://api.spotify.com/v1/me/player/next"),
        "previous": ("POST", "https://api.spotify.com/v1/me/player/previous"),
    }
    if action not in method_and_path:
        return {"ok": False, "error": f"nieznana akcja: {action}"}
    method, url = method_and_path[action]
    try:
        resp = _session.request(method, url, headers=_spotify_auth_header(), timeout=6)
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}
    if resp.status_code in (200, 202, 204):
        return {"ok": True}
    if resp.status_code == 404:
        return {"ok": False, "error": "Brak aktywnego urządzenia Spotify."}
    if resp.status_code == 403:
        return {"ok": False, "error": "Spotify odmówiło (403) - brak Premium?"}
    return {"ok": False, "error": f"Spotify zwróciło {resp.status_code}"}

def spotify_search(query, limit=8):
    try:
        resp = _session.get(
            "https://api.spotify.com/v1/search",
            headers=_spotify_auth_header(),
            params={"q": query, "type": "track", "limit": limit},
            timeout=6,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}
    if resp.status_code != 200:
        return {"ok": False, "error": f"Spotify search zwróciło {resp.status_code}"}
    items = (resp.json().get("tracks") or {}).get("items") or []
    results = [{
        "uri": t["uri"],
        "track": t.get("name"),
        "artist": ", ".join(a["name"] for a in t.get("artists", [])),
        "cover_url": ((t.get("album") or {}).get("images") or [{}])[0].get("url"),
    } for t in items]
    return {"ok": True, "results": results}

def spotify_play_track(uri):
    try:
        resp = _session.put(
            "https://api.spotify.com/v1/me/player/play",
            headers=_spotify_auth_header(),
            json={"uris": [uri]},
            timeout=6,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}
    if resp.status_code in (200, 202, 204):
        return {"ok": True}
    return {"ok": False, "error": f"Spotify zwróciło {resp.status_code}"}

def get_spotify_queue(limit=5):
    """Zwraca listę max `limit` kolejnych utworów z kolejki Spotify
    (bez aktualnie odtwarzanego). Działa tylko, gdy źródłem jest Spotify."""
    try:
        resp = _session.get(
            "https://api.spotify.com/v1/me/player/queue",
            headers=_spotify_auth_header(),
            timeout=5,
        )
    except requests.RequestException as exc:
        print(f"[spotify] Błąd pobierania kolejki: {exc}")
        return []
    if resp.status_code != 200 or not resp.content:
        return []
    try:
        data = resp.json()
    except Exception:
        return []

    items = data.get("queue") or []
    result = []
    for it in items[:limit]:
        artists = ", ".join(a["name"] for a in it.get("artists", []))
        images = (it.get("album") or {}).get("images") or []
        cover_url = images[0]["url"] if images else None
        result.append({
            "track": it.get("name"),
            "artist": artists,
            "cover_url": cover_url,
        })
    return result


# ============================================================
# YOUTUBE MUSIC
# ============================================================
_YTM_BASE_URL = f"http://{YTMDESKTOP_HOST}:{YTMDESKTOP_PORT}"

def get_youtube_now_playing():
    try:
        resp = _session.get(f"{_YTM_BASE_URL}/api/v1/song", timeout=3)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None

    data = resp.json()
    if not data or not data.get("title"):
        return None

    return {
        "track": data.get("title"),
        "artist": data.get("artist"),
        "duration_sec": data.get("songDuration", 0),
        "position_sec": data.get("elapsedSeconds", 0),
        "is_playing": not data.get("isPaused", True),
        "cover_url": data.get("imageSrc"),
    }

def youtube_control(action):
    endpoint_map = {"play": "play", "pause": "pause", "next": "next", "previous": "previous"}
    if action not in endpoint_map:
        return {"ok": False, "error": f"nieznana akcja: {action}"}
    try:
        resp = _session.post(f"{_YTM_BASE_URL}/api/v1/{endpoint_map[action]}", timeout=4)
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}
    if resp.status_code in (200, 204):
        return {"ok": True}
    return {"ok": False, "error": f"YTMDesktop zwróciło {resp.status_code} dla '{action}'"}

def youtube_search(query):
    return {"ok": False, "error": "Wyszukiwanie w YouTube Music nie jest wspierane przez lokalne API"}


# ============================================================
# SZYFROWANIE DLA APPKI-PILOTA (TELEFON)
# ============================================================
_pairing_key = None

def get_or_create_pairing_code():
    if os.path.exists(PAIRING_CODE_FILE):
        with open(PAIRING_CODE_FILE, "r", encoding="utf-8") as f:
            code = f.read().strip()
            if code:
                return code

    code = "".join(secrets.choice("0123456789") for _ in range(PAIRING_CODE_DIGITS))
    _ensure_app_data_dir()
    try:
        with open(PAIRING_CODE_FILE, "w", encoding="utf-8") as f:
            f.write(code)
    except Exception as e:
        print(f"[parowanie] Błąd zapisu kodu do {PAIRING_CODE_FILE}: {e}")
    return code

def _load_pairing_key():
    global _pairing_key
    code = get_or_create_pairing_code()
    _pairing_key = hashlib.sha256(code.encode("utf-8")).digest()
    print("=" * 60)
    print(f"  KOD PAROWANIA APPKI: {code}")
    print("=" * 60)

def _aes_encrypt(plaintext_dict):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(_pairing_key)
    nonce = secrets.token_bytes(12)
    plaintext = json.dumps(plaintext_dict).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return json.dumps({
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }).encode("utf-8")

def _aes_decrypt(raw_body):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    envelope = json.loads(raw_body.decode("utf-8"))
    nonce = base64.b64decode(envelope["nonce"])
    ciphertext = base64.b64decode(envelope["ciphertext"])
    aesgcm = AESGCM(_pairing_key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))


# ============================================================
# TELEFON - ODBIORNIK
# ============================================================
_phone_lock = threading.Lock()
_phone_state = {
    "track": None, "artist": None, "duration_sec": 0, "position_sec": 0,
    "is_playing": False, "cover_url": None, "received_at": 0.0,
}

# Osobne śledzenie "czy appka-pilot na telefonie żyje" - niezależne od tego,
# czy telefon akurat jest AKTYWNYM ŹRÓDŁEM muzyki. Appka-pilot łączy się przez
# /status (podgląd) i /control (sterowanie), a to właśnie te zapytania mają
# świadczyć o tym, że telefon jest połączony - a nie fakt bycia źródłem.
PHONE_APP_CONNECTION_TIMEOUT_SECONDS = 10.0
_phone_app_lock = threading.Lock()
_phone_app_last_seen = 0.0

def _mark_phone_app_seen():
    global _phone_app_last_seen
    with _phone_app_lock:
        _phone_app_last_seen = time.time()

def is_phone_app_connected():
    with _phone_app_lock:
        last_seen = _phone_app_last_seen
    if last_seen <= 0:
        return False
    return (time.time() - last_seen) <= PHONE_APP_CONNECTION_TIMEOUT_SECONDS

class _PhoneReceiverHTTPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/phone-now-playing":
            self._handle_legacy_now_playing()
        elif path == "/status":
            self._handle_encrypted_status()
        elif path == "/control":
            self._handle_encrypted_control()
        else:
            self.send_response(404)
            self.end_headers()

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _send_json(self, code, payload_dict):
        body = json.dumps(payload_dict).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_encrypted(self, code, payload_dict):
        body = _aes_encrypt(payload_dict)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_legacy_now_playing(self):
        raw_body = self._read_body()
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        if payload.get("token") != PHONE_SHARED_SECRET:
            self.send_response(401)
            self.end_headers()
            return

        with _phone_lock:
            _phone_state["track"] = payload.get("track")
            _phone_state["artist"] = payload.get("artist")
            _phone_state["duration_sec"] = float(payload.get("duration_sec") or 0)
            _phone_state["position_sec"] = float(payload.get("position_sec") or 0)
            _phone_state["is_playing"] = bool(payload.get("is_playing", True))
            _phone_state["cover_url"] = payload.get("cover_url")
            _phone_state["received_at"] = time.time()
        _mark_phone_app_seen()
        self._send_json(200, {"ok": True})

    def _handle_encrypted_status(self):
        try:
            _aes_decrypt(self._read_body())
        except Exception:
            self.send_response(401)
            self.end_headers()
            return
        _mark_phone_app_seen()
        self._send_encrypted(200, get_now_playing_snapshot())

    def _handle_encrypted_control(self):
        try:
            command = _aes_decrypt(self._read_body())
        except Exception:
            self.send_response(401)
            self.end_headers()
            return
        _mark_phone_app_seen()
        target = command.get("target")
        action = command.get("action")

        if target == "spotify":
            if action == "search": result = spotify_search(command.get("query", ""))
            elif action == "play_track": result = spotify_play_track(command.get("uri", ""))
            else: result = spotify_control(action)
        elif target == "youtube":
            if action == "search": result = youtube_search(command.get("query", ""))
            else: result = youtube_control(action)
        else:
            result = {"ok": False, "error": f"nieznany target: {target}"}

        self._send_encrypted(200, result)

    def log_message(self, *args):
        pass

def _start_phone_receiver_http_server():
    try:
        server = _QuietHTTPServer(("0.0.0.0", PHONE_RECEIVER_HTTP_PORT), _PhoneReceiverHTTPHandler)
    except OSError as exc:
        print(f"[phone] Błąd portu {PHONE_RECEIVER_HTTP_PORT}: {exc}")
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()

def get_phone_now_playing():
    with _phone_lock:
        state = dict(_phone_state)

    if not state.get("track"): return None
    if time.time() - state["received_at"] > PHONE_STALE_AFTER_SECONDS: return None
    if not state.get("is_playing"): return None

    return {
        "track": state["track"], "artist": state["artist"],
        "duration_sec": state["duration_sec"], "position_sec": state["position_sec"],
        "is_playing": True, "cover_url": state.get("cover_url"),
    }


# ============================================================
# TEKSTY PIOSENEK
# ============================================================
_LRC_PATTERN = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\](.*)")

def parse_lrc(lrc_text):
    lines = []
    for raw_line in lrc_text.splitlines():
        match = _LRC_PATTERN.match(raw_line.strip())
        if not match: continue
        minutes, seconds, fraction, text = match.groups()
        total_seconds = int(minutes) * 60 + int(seconds)
        if fraction: total_seconds += int(fraction) / (10 ** len(fraction))
        text = text.strip()
        if text: lines.append((total_seconds, text))
    lines.sort(key=lambda l: l[0])
    return lines

_TITLE_JUNK_PATTERN = re.compile(r"[\(\[][^)\]]*?(official|lyrics?|audio|video|visualizer|hd|4k|remaster\w*|clip|mv|prod\.?)[^)\]]*[\)\]]", re.IGNORECASE)
_FEAT_SPLIT_PATTERN = re.compile(r"\s*[\(\[]?\b(feat\.?|ft\.?|featuring)\b.*$", re.IGNORECASE)

def _clean_title(title):
    if not title: return title
    cleaned = _TITLE_JUNK_PATTERN.sub("", title)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" -–—") or title

def _strip_feat(text):
    if not text: return text
    return _FEAT_SPLIT_PATTERN.sub("", text).strip(" -–—") or text

def _title_artist_variants(track_name, artist_name):
    seen, variants = set(), []
    def add(t, a):
        t, a = (t or "").strip(), (a or "").strip()
        if not t or (t.lower(), a.lower()) in seen: return
        seen.add((t.lower(), a.lower()))
        variants.append((t, a))

    add(track_name, artist_name)
    cleaned = _clean_title(track_name)
    add(cleaned, artist_name)
    add(_strip_feat(cleaned), artist_name)
    if artist_name and any(c in artist_name for c in [",", " i ", " & "]):
        first_artist = re.split(r",| i | & ", artist_name)[0].strip()
        add(track_name, first_artist)
        add(cleaned, first_artist)
    return variants

def _fetch_synced_lyrics_multi_provider(track_name, artist_name):
    try:
        import syncedlyrics
    except ImportError:
        return None
    query = f"{track_name} {artist_name}".strip()
    if not query: return None
    try:
        lrc_text = syncedlyrics.search(query, synced_only=True)
    except Exception: return None
    return parse_lrc(lrc_text) if lrc_text else None

def _lrclib_get(track_name, artist_name, duration_sec=None):
    attempts = []
    if duration_sec: attempts.append({"track_name": track_name, "artist_name": artist_name, "duration": int(duration_sec)})
    attempts.append({"track_name": track_name, "artist_name": artist_name})
    for params in attempts:
        try:
            resp = _session.get("https://lrclib.net/api/get", params=params, timeout=5)
            if resp.status_code == 200: return resp.json()
        except requests.RequestException: continue
    return None

def _fetch_synced_lyrics_raw(track_name, artist_name, duration_sec=None):
    data = _lrclib_get(track_name, artist_name, duration_sec)
    synced = (data or {}).get("syncedLyrics")
    return parse_lrc(synced) if synced else None

def fetch_synced_lyrics(track_name, artist_name, duration_sec=None):
    variants = _title_artist_variants(track_name, artist_name)
    for title, artist in variants:
        lines = _fetch_synced_lyrics_raw(title, artist, duration_sec)
        if lines: return lines
    for title, artist in variants:
        lines = _fetch_synced_lyrics_multi_provider(title, artist)
        if lines: return lines
    return None

def get_current_line(lines, pos):
    curr = None
    for t, text in lines:
        if t <= pos: curr = text
        else: break
    return curr

# Ile sekund musi minąć od ostatniej zaśpiewanej linijki (albo od jej
# rozpoczęcia, gdy nie wiemy kiedy się kończy - patrz niżej), zanim uznamy,
# że nie ma teraz aktywnego tekstu (np. solówka, przejście instrumentalne,
# outro) i zamiast "zamrożonej" starej linijki pokażemy "🎵 Muzyka".
LYRIC_GAP_THRESHOLD_SECONDS = 7.0

def get_current_line_info(lines, pos):
    """Zwraca (tekst_aktualnej_linijki_albo_None, czy_to_przerwa_muzyczna).

    W odróżnieniu od get_current_line(), potrafi wykryć sytuację, w której
    ostatnia zaśpiewana linijka jest w rzeczywistości "stara" - bo od jej
    startu minęło już więcej czasu niż zwykle trwa jedna linijka (czy to
    dlatego, że to naprawdę ostatnia linijka przed outro, czy dlatego, że
    następna linijka jest daleko w czasie - przerwa muzyczna w środku
    utworu)."""
    if not lines:
        return None, False

    idx = None
    for i, (t, _text) in enumerate(lines):
        if t <= pos:
            idx = i
        else:
            break

    if idx is None:
        # Jeszcze przed pierwszą linijką (np. intro utworu).
        return None, False

    line_time, line_text = lines[idx]
    since_line_started = pos - line_time

    if idx + 1 < len(lines):
        gap_to_next = lines[idx + 1][0] - line_time
    else:
        gap_to_next = None  # to ostatnia znana linijka tekstu

    if gap_to_next is None:
        is_gap = since_line_started > LYRIC_GAP_THRESHOLD_SECONDS
    else:
        is_gap = gap_to_next > LYRIC_GAP_THRESHOLD_SECONDS and since_line_started > LYRIC_GAP_THRESHOLD_SECONDS

    return line_text, is_gap

def get_next_line(lines, pos):
    """Zwraca tekst KOLEJNEJ (jeszcze nie zaśpiewanej) linijki - używane przy
    wyświetlaniu dwóch linijek na raz."""
    for t, text in lines:
        if t > pos:
            return text
    return None

# ============================================================
# LOKALNY SERWER DLA MODA MC
# ============================================================
class _NowPlayingHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/now-playing":
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(get_now_playing_snapshot()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
    def log_message(self, *args): pass

def _start_now_playing_http_server():
    try:
        server = _QuietHTTPServer(("127.0.0.1", NOW_PLAYING_HTTP_PORT), _NowPlayingHTTPHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    except OSError: pass

# ============================================================
# DISCORD RICH PRESENCE
# ============================================================
_rpc = None
_rpc_start_time = None
_MAX_LEN = 128

# Prawdziwy stan połączenia z Discordem. Samo istnienie obiektu `_rpc` NIE
# oznacza, że jesteśmy połączeni - `Presence(...)` tworzy obiekt od razu,
# a dopiero `.connect()` faktycznie łączy się z klientem Discorda (przez IPC).
# Jeśli Discord jest zamknięty albo brak DISCORD_CLIENT_ID, `.connect()`
# rzuca wyjątkiem, ale `_rpc` i tak zostawał ustawiony - stąd status
# pokazywał "połączono", mimo że w rzeczywistości nic nie działało.
_discord_connected = False

def discord_connect():
    global _rpc, _rpc_start_time, _discord_connected
    if not DISCORD_CLIENT_ID:
        _discord_connected = False
        raise RuntimeError("Brak DISCORD_CLIENT_ID - nie mam się z czym połączyć.")

    from pypresence import Presence
    rpc = Presence(DISCORD_CLIENT_ID)
    rpc.connect()
    # Dopiero po udanym .connect() uznajemy to za nowy, aktywny obiekt RPC.
    _rpc = rpc
    _rpc_start_time = time.time()
    _discord_connected = True

def _reconnect_discord():
    global _discord_connected
    try:
        discord_connect()
        return True
    except Exception:
        _discord_connected = False
        return False

def _truncate(text, fallback):
    if not text: return fallback
    return text if len(text) <= _MAX_LEN else text[:_MAX_LEN - 1] + "…"

def discord_update(track, artist, current_line, cover_url=None):
    global _discord_connected
    if not _discord_connected or _rpc is None:
        return
    track_artist = f"{track} - {artist}" if artist else track
    kwargs = {
        "details": _truncate(current_line, "🎵 Muzyka"),
        "state": _truncate(track_artist, ""),
        "start": _rpc_start_time,
    }
    if cover_url:
        kwargs["large_image"] = cover_url
        kwargs["large_text"] = _truncate(track_artist, "")

    try:
        _rpc.update(**kwargs)
    except Exception:
        if _reconnect_discord():
            try:
                _rpc.update(**kwargs)
            except Exception:
                _discord_connected = False
        else:
            _discord_connected = False

def discord_clear():
    global _discord_connected
    if _rpc and _discord_connected:
        try:
            _rpc.clear()
        except Exception:
            _discord_connected = False
            _reconnect_discord()

def discord_close():
    global _discord_connected
    if _rpc:
        try: _rpc.close()
        except Exception: pass
    _discord_connected = False

def is_discord_connected():
    return _discord_connected

def is_presence_enabled():
    with state_lock: return app_state["presence_enabled"]

def get_lyric_offset_seconds():
    with state_lock: return app_state["lyric_offset_seconds"]


# ============================================================
# GŁÓWNA PĘTLA
# ============================================================
_SOURCES = {
    "spotify": get_spotify_now_playing,
    "youtube": get_youtube_now_playing,
    "phone": get_phone_now_playing,
}

def get_now_playing_from_sources():
    active = None
    for name in PREFERRED_SOURCE_ORDER:
        fetch = _SOURCES.get(name)
        if not fetch: continue
        info = fetch()
        if info and info.get("is_playing"): return name, info
        if info and active is None: active = (name, info)
    return active if active else (None, None)

def background_loop():
    current_track_key = None
    current_lines = None
    last_sent_line = "__unset__"
    snapshot = None
    snapshot_fetched_at = 0.0
    last_poll_time = 0.0
    active_source = None
    consecutive_empty_polls = 0
    EMPTY_POLL_GRACE = 3
    last_queue_poll_time = 0.0

    while True:
        try:
            now = time.time()
            _update_app_state(
                status_discord=is_discord_connected(),
                status_phone=is_phone_app_connected(),
            )
            if not is_discord_connected() and DISCORD_CLIENT_ID and int(now) % 15 == 0:
                _reconnect_discord()

            if snapshot is None or (now - last_poll_time) >= POLL_INTERVAL_SECONDS:
                src, polled = get_now_playing_from_sources()
                last_poll_time = now

                if polled:
                    snapshot = polled
                    snapshot_fetched_at = now
                    active_source = src
                    consecutive_empty_polls = 0
                else:
                    consecutive_empty_polls += 1
                    if consecutive_empty_polls >= EMPTY_POLL_GRACE or snapshot is None:
                        snapshot = None
                        active_source = None

                _update_app_state(
                    status_spotify=active_source == "spotify",
                    status_ytm=active_source == "youtube",
                    active_source=active_source,
                )

            # --- Wyświetlanie następnego utworu / kolejki (tylko Spotify) ---
            display_mode = current_settings.get("DISPLAY_MODE", "none")
            if display_mode != "none" and active_source == "spotify":
                if (now - last_queue_poll_time) >= QUEUE_POLL_INTERVAL_SECONDS:
                    last_queue_poll_time = now
                    if display_mode == "next":
                        queue_limit = 1
                    else:
                        try:
                            queue_limit = int(current_settings.get("QUEUE_COUNT", 5))
                        except (TypeError, ValueError):
                            queue_limit = 5
                        queue_limit = max(2, min(9, queue_limit))
                    fetched_queue = get_spotify_queue(limit=queue_limit)
                    _update_app_state(queue=fetched_queue)
            else:
                with state_lock:
                    queue_is_empty = not app_state["queue"]
                if not queue_is_empty:
                    _update_app_state(queue=[])
                last_queue_poll_time = 0.0

            if not snapshot:
                _update_app_state(
                    track="Brak odtwarzania",
                    artist="Włącz muzykę na Spotify / YouTube Music / telefonie",
                    line="🎵 ...",
                    next_line="",
                    is_playing=False,
                    cover_url=None,
                    position_sec=0.0,
                    duration_sec=0.0,
                )
                if current_track_key is not None:
                    discord_clear()
                    current_track_key = None
                    current_lines = None
                    last_sent_line = "__unset__"
                time.sleep(LYRIC_TICK_SECONDS)
                continue

            track = snapshot["track"]
            artist = snapshot.get("artist") or ""
            duration = snapshot.get("duration_sec") or 0.0
            cover_url = snapshot.get("cover_url")
            track_key = (track, artist)

            if track_key != current_track_key:
                current_track_key = track_key
                current_lines = fetch_synced_lyrics(track, artist, duration)
                last_sent_line = "__unset__"

            if snapshot.get("is_playing"):
                position = snapshot["position_sec"] + (now - snapshot_fetched_at)
                if duration:
                    position = min(position, duration)
            else:
                position = snapshot["position_sec"]

            lookup_position = position - get_lyric_offset_seconds()
            next_line_for_display = ""
            if current_lines:
                current_line, is_lyric_gap = get_current_line_info(current_lines, lookup_position)
                if current_line is None or is_lyric_gap:
                    # Piosenka ma tekst, ale w tym momencie nie ma żadnej
                    # aktywnej linijki - np. intro, solówka, przejście
                    # instrumentalne albo outro po ostatniej linijce tekstu.
                    line_for_display = "🎵 Muzyka"
                else:
                    line_for_display = current_line
                next_line_text = get_next_line(current_lines, lookup_position)
                next_line_for_display = next_line_text or ""
            else:
                # Nie udało się w ogóle znaleźć/zsynchronizować tekstu dla tego utworu
                current_line = None
                line_for_display = "🎵 (Brak zsynchronizowanego tekstu)"

            _update_app_state(
                track=track,
                artist=artist,
                line=line_for_display,
                next_line=next_line_for_display,
                is_playing=bool(snapshot.get("is_playing")),
                cover_url=cover_url,
                position_sec=position,
                duration_sec=duration,
            )

            if is_presence_enabled() and snapshot.get("is_playing"):
                if line_for_display != last_sent_line:
                    discord_update(track, artist, line_for_display, cover_url)
                    last_sent_line = line_for_display

            time.sleep(LYRIC_TICK_SECONDS)
        except Exception:
            time.sleep(1)

# ============================================================
# HTML WEB SERWER
# ============================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lyric Status & Control</title>
    <style>
        :root {
            --accent: #FF3D9A;
            --accent-hover: #ff6bb5;
            --accent-glow-strong: rgba(255, 61, 154, 0.65);
            --accent-glow-mid: rgba(255, 61, 154, 0.45);
            --accent-glow-soft: rgba(255, 61, 154, 0.35);
            --bg-from: #2a0a1c;
            --bg-to: #000000;
        }
        body[data-theme="green"] {
            --accent: #22C55E;
            --accent-hover: #3ddb75;
            --accent-glow-strong: rgba(34, 197, 94, 0.6);
            --accent-glow-mid: rgba(34, 197, 94, 0.4);
            --accent-glow-soft: rgba(34, 197, 94, 0.3);
            --bg-from: #0b1a12;
            --bg-to: #000000;
        }
        body[data-theme="purple"] {
            --accent: #8B5CF6;
            --accent-hover: #a78bfa;
            --accent-glow-strong: rgba(139, 92, 246, 0.6);
            --accent-glow-mid: rgba(139, 92, 246, 0.4);
            --accent-glow-soft: rgba(139, 92, 246, 0.3);
            --bg-from: #150b1a;
            --bg-to: #000000;
        }
        * {
            box-sizing: border-box;
        }
        html {
            overflow-x: hidden;
            width: 100%;
        }
        body {
            background: radial-gradient(circle at top left, var(--bg-from), var(--bg-to) 80%);
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            width: 100%;
            margin: 0;
            padding: 20px;
            box-sizing: border-box;
            text-align: center;
            transition: background 0.4s ease;
            overflow-x: hidden;
            /* Ukrywamy pasek przewijania z boku (Firefox) - okno appki ma
               stały rozmiar, więc widoczny scrollbar tylko przeszkadza. */
            scrollbar-width: none;
        }
        /* Ukrywamy pasek przewijania z boku (przeglądarki oparte na
           Chromium/WebView2, których używa zbudowana appka desktopowa). */
        body::-webkit-scrollbar {
            width: 0;
            height: 0;
            display: none;
        }
        .container {
            background: rgba(40, 40, 40, 0.4);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 36px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255,255,255,0.1);
            max-width: 420px;
            width: 100%;
            padding: 25px 20px;
            box-sizing: border-box;
            overflow-x: hidden;
        }

        /* Nawigacja w stylu Apple Segmented Control */
        .tab-nav {
            display: flex;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 20px;
            padding: 4px;
            margin-bottom: 20px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        .tab-btn {
            flex: 1;
            background: transparent;
            border: none;
            color: rgba(255, 255, 255, 0.6);
            padding: 10px;
            border-radius: 16px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .tab-btn.active {
            background: rgba(255, 255, 255, 0.15);
            color: #ffffff;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }

        /* Treść zakładek */
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }

        /* Elementy odtwarzacza */
        img {
            width: 250px;
            height: 250px;
            border-radius: 20px;
            object-fit: cover;
            box-shadow: 0 12px 32px rgba(0,0,0,0.5);
            margin-bottom: 20px;
            transition: transform 0.3s ease;
        }
        img:hover {
            transform: scale(1.02);
        }
        .lyric {
            font-size: 21px;
            font-weight: 700;
            color: var(--accent);
            min-height: 30px;
            margin-bottom: 6px;
            text-shadow: 0 2px 10px var(--accent-glow-soft);
            word-wrap: break-word;
            overflow-wrap: break-word;
            max-width: 100%;
        }
        /* Druga linijka (podgląd kolejnej linijki tekstu) - miejsce jest
           ZAWSZE zarezerwowane w layoucie (stała wysokość), a zmienia się
           tylko widoczność. Dzięki temu przełączanie 1/2 linijki w
           Ustawieniach nigdy nie zmienia całkowitej wysokości zakładki
           Odtwarzacz i nie wywołuje paska przewijania z boku okna. */
        .lyric-second {
            font-size: 14px;
            font-weight: 600;
            color: rgba(255, 255, 255, 0.45);
            max-width: 100%;
            height: 18px;
            line-height: 18px;
            overflow: hidden;
            white-space: nowrap;
            text-overflow: ellipsis;
            margin-bottom: 15px;
            visibility: hidden;
        }
        .lyric-second.visible {
            visibility: visible;
        }
        .track {
            font-size: 19px;
            font-weight: 600;
            margin-bottom: 4px;
            letter-spacing: -0.5px;
        }
        .artist {
            font-size: 14px;
            color: rgba(255, 255, 255, 0.6);
            margin-bottom: 20px;
        }

        /* Pasek postępu utworu */
        .progress-wrap {
            margin-bottom: 20px;
        }
        .progress-track {
            position: relative;
            width: 100%;
            height: 6px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 6px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            width: 0%;
            background: var(--accent);
            border-radius: 6px;
            box-shadow: 0 0 8px var(--accent-glow-strong);
            transition: width 0.3s linear;
        }
        .progress-times {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: rgba(255, 255, 255, 0.5);
            margin-top: 6px;
        }

        .controls {
            display: flex;
            justify-content: center;
            gap: 12px;
            margin-bottom: 20px;
        }
        button {
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.05);
            color: white;
            padding: 12px 20px;
            border-radius: 30px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            transition: all 0.2s ease;
        }
        button:active {
            transform: scale(0.94);
        }
        button.primary {
            background: var(--accent);
            color: #fff;
            box-shadow: 0 4px 15px var(--accent-glow-mid);
            border: none;
        }
        button.primary:hover {
            background: var(--accent-hover);
        }
        button.small {
            padding: 8px 16px;
            font-size: 13px;
            border-radius: 20px;
        }

        /* Sekcja Ustawień (Karty/Panele) */
        .card {
            background: rgba(0, 0, 0, 0.25);
            border-radius: 20px;
            padding: 16px;
            margin-bottom: 16px;
            text-align: left;
            font-size: 13px;
            color: rgba(255, 255, 255, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        .card h4 {
            margin: 0 0 12px 0;
            font-size: 13px;
            color: var(--accent);
            text-transform: uppercase;
            letter-spacing: 1px;
            text-align: center;
        }
        .card p {
            margin: 8px 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .card a {
            color: var(--accent);
            text-decoration: none;
            font-weight: bold;
        }

        /* Pastylki ze statusami połączeń */
        .status-pills {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 15px;
        }
        .pill {
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.05);
            padding: 10px;
            border-radius: 16px;
            font-size: 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 6px;
        }
        .pill span:first-child {
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .dot {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }
        .dot-on { background: var(--accent); box-shadow: 0 0 8px var(--accent-glow-strong); }
        .dot-off { background: #444; }

        /* Serduszka statusu (motyw Elcia) */
        .heart-icon {
            font-size: 15px;
            line-height: 1;
        }
        .heart-on {
            color: var(--accent);
            text-shadow: 0 0 8px var(--accent-glow-strong);
        }
        .heart-off {
            color: #555;
        }

        /* Pastylki "następny utwór / kolejka" pod sterowaniem */
        .next-wrap {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-bottom: 20px;
        }
        .next-pill {
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(0, 0, 0, 0.25);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 40px;
            padding: 6px 16px 6px 6px;
            text-align: left;
        }
        .next-pill img {
            width: 38px;
            height: 38px;
            border-radius: 50%;
            object-fit: cover;
            margin-bottom: 0;
            flex-shrink: 0;
        }
        .next-pill-info {
            min-width: 0;
            flex: 1;
        }
        .next-pill-label {
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--accent);
        }
        .next-pill-track {
            font-size: 13px;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .next-pill-artist {
            font-size: 11px;
            color: rgba(255, 255, 255, 0.55);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /* Formularze w ustawieniach */
        .form-group {
            margin-bottom: 10px;
        }
        .form-group label {
            display: block;
            font-size: 11px;
            color: rgba(255, 255, 255, 0.5);
            margin-bottom: 4px;
        }
        .form-group input {
            width: 100%;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 8px 10px;
            color: #fff;
            box-sizing: border-box;
            font-size: 12px;
        }
        .form-group input:focus {
            outline: none;
            border-color: var(--accent);
        }

        /* Wybór motywu */
        .theme-picker {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .theme-option {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 8px;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            padding: 12px 8px;
            color: rgba(255, 255, 255, 0.6);
            font-size: 12px;
            font-weight: 600;
        }
        .theme-option.active {
            color: #fff;
            border-color: var(--accent);
            box-shadow: 0 0 0 1px var(--accent) inset;
        }
        .theme-swatch {
            width: 22px;
            height: 22px;
            border-radius: 50%;
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
        }
        .swatch-pink { background: linear-gradient(135deg, #FF3D9A, #ffc1e3); }
        .swatch-green { background: linear-gradient(135deg, #16A34A, #86efac); }
        .swatch-purple { background: linear-gradient(135deg, #8B5CF6, #d8c9ff); }
        .swatch-custom {
            background: conic-gradient(from 180deg, #ff0000, #ff8800, #ffee00, #22c55e, #00c2ff, #8b5cf6, #ff0080, #ff0000);
        }

        /* Panel wyboru koloru custom */
        .custom-color-picker {
            margin-top: 12px;
        }
        .custom-color-picker input[type="text"] {
            font-family: monospace;
            text-transform: uppercase;
        }

        /* Suwak liczby utworów w kolejce - stylizowany pod motyw appki */
        .slider-row {
            margin-top: 14px;
            padding-top: 12px;
            border-top: 1px solid rgba(255, 255, 255, 0.08);
        }
        .slider-label {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: rgba(255, 255, 255, 0.6);
            margin-bottom: 8px;
        }
        .slider-label strong {
            color: var(--accent);
            font-size: 13px;
        }
        input[type="range"] {
            -webkit-appearance: none;
            appearance: none;
            width: 100%;
            height: 6px;
            border-radius: 6px;
            background: rgba(255, 255, 255, 0.1);
            outline: none;
            margin: 6px 0 4px 0;
            cursor: pointer;
        }
        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: var(--accent);
            box-shadow: 0 2px 8px var(--accent-glow-mid), 0 0 0 4px rgba(255,255,255,0.06);
            cursor: pointer;
            transition: transform 0.15s ease;
            margin-top: -7px;
        }
        input[type="range"]::-webkit-slider-thumb:active {
            transform: scale(1.15);
        }
        input[type="range"]::-moz-range-thumb {
            width: 20px;
            height: 20px;
            border: none;
            border-radius: 50%;
            background: var(--accent);
            box-shadow: 0 2px 8px var(--accent-glow-mid);
            cursor: pointer;
        }
        input[type="range"]::-moz-range-track {
            height: 6px;
            border-radius: 6px;
            background: rgba(255, 255, 255, 0.1);
        }
        .slider-ticks {
            display: flex;
            justify-content: space-between;
            font-size: 9px;
            color: rgba(255, 255, 255, 0.35);
            padding: 0 2px;
        }
    </style>
</head>
<body data-theme="__INITIAL_THEME__">
    <div class="container">
        <!-- Nawigacja zakładek -->
        <div class="tab-nav">
            <button class="tab-btn active" onclick="switchTab('player')">🎵 Odtwarzacz</button>
            <button class="tab-btn" onclick="switchTab('settings')">⚙️ Ustawienia</button>
        </div>

        <!-- ZAKŁADKA 1: ODTWARZACZ -->
        <div id="tab-player" class="tab-content active">
            <img id="cover" src="" alt="Cover" onerror="this.onerror=null;this.src=NO_COVER_SRC;">
            <div class="lyric" id="lyric">Ładowanie...</div>
            <div class="lyric-second" id="lyricSecond"></div>
            <div class="track" id="track">-</div>
            <div class="artist" id="artist">-</div>

            <div class="progress-wrap">
                <div class="progress-track">
                    <div class="progress-fill" id="progressFill"></div>
                </div>
                <div class="progress-times">
                    <span id="posTime">0:00</span>
                    <span id="durTime">0:00</span>
                </div>
            </div>

            <div class="controls">
                <button onclick="sendCmd('previous')">⏪</button>
                <button class="primary" id="playBtn" onclick="sendCmd('toggle')">⏯ Play/Pause</button>
                <button onclick="sendCmd('next')">⏩</button>
            </div>

            <!-- Następny utwór / kolejka (widoczne, gdy włączone w Ustawieniach) -->
            <div class="next-wrap" id="nextWrap" style="display: none;"></div>
        </div>

        <!-- ZAKŁADKA 2: USTAWIENIA -->
        <div id="tab-settings" class="tab-content">
            <!-- Pastylki statusów -->
            <div class="status-pills">
                <div class="pill"><span>Spotify</span> <span id="st-spotify">🌑</span></div>
                <div class="pill"><span>YouTube Music</span> <span id="st-ytm">🌑</span></div>
                <div class="pill"><span>Telefon</span> <span id="st-phone">🌑</span></div>
                <div class="pill"><span>Discord</span> <span id="st-discord">🌑</span></div>
            </div>

            <!-- Discord RPC -->
            <div class="card">
                <h4>Discord RPC</h4>
                <p>
                    <span>Status prezencji:</span>
                    <button class="small" id="presenceBtn" onclick="togglePresence()">...</button>
                </p>
            </div>

            <!-- Wyświetlanie następnego utworu / kolejki -->
            <div class="card">
                <h4>Wyświetl</h4>
                <div class="theme-picker" style="grid-template-columns: 1fr 1fr 1fr;">
                    <button class="theme-option" data-display-btn="next" onclick="setDisplayMode('next')">
                        Następny utwór
                    </button>
                    <button class="theme-option" data-display-btn="queue" onclick="setDisplayMode('queue')">
                        Kolejka
                    </button>
                    <button class="theme-option" data-display-btn="none" onclick="setDisplayMode('none')">
                        Nic
                    </button>
                </div>

                <!-- Suwak widoczny tylko przy trybie "Kolejka" -->
                <div class="slider-row" id="queueCountRow" style="display: none;">
                    <div class="slider-label">
                        <span>Liczba utworów w kolejce</span>
                        <strong id="queueCountValue">5</strong>
                    </div>
                    <input type="range" id="queueCountSlider" min="2" max="9" step="1" value="5"
                           oninput="onQueueCountInput(this.value)" onchange="setQueueCount(this.value)">
                    <div class="slider-ticks"><span>2</span><span>9</span></div>
                </div>
            </div>

            <!-- Ile linijek tekstu piosenki wyświetlać jednocześnie -->
            <div class="card">
                <h4>Tekst piosenki</h4>
                <div class="theme-picker">
                    <button class="theme-option" data-lyriclines-btn="single" onclick="setLyricLineMode('single')">
                        1 linijka
                    </button>
                    <button class="theme-option" data-lyriclines-btn="double" onclick="setLyricLineMode('double')">
                        2 linijki
                    </button>
                </div>
            </div>

            <!-- Wybór motywu -->
            <div class="card">
                <h4>Motyw</h4>
                <div class="theme-picker">
                    <button class="theme-option" data-theme-btn="pink" onclick="setTheme('pink')">
                        <span class="theme-swatch swatch-pink"></span>
                        Elcia
                    </button>
                    <button class="theme-option" data-theme-btn="purple" onclick="setTheme('purple')">
                        <span class="theme-swatch swatch-purple"></span>
                        Sasan
                    </button>
                    <button class="theme-option" data-theme-btn="green" onclick="setTheme('green')">
                        <span class="theme-swatch swatch-green"></span>
                        Zielony
                    </button>
                    <button class="theme-option" data-theme-btn="custom" onclick="setTheme('custom')">
                        <span class="theme-swatch swatch-custom" id="customSwatch"></span>
                        Własny
                    </button>
                </div>
                <div class="custom-color-picker" id="customColorPicker" style="display: none;">
                    <div class="form-group">
                        <label>Kolor HEX (np. #8B5CF6)</label>
                        <input type="text" id="cfg-custom-color" placeholder="#8B5CF6" maxlength="7" oninput="previewCustomColor()">
                    </div>
                    <button class="primary small" style="width: 100%;" onclick="saveCustomColor()">Zastosuj kolor</button>
                </div>
            </div>

            <!-- Informacje o parowaniu i IP -->
            <div class="card">
                <h4>Informacje o Parowaniu</h4>
                <p><span>Kod parowania:</span> <strong id="api-code" style="color: var(--accent);">-</strong></p>
                <p><span>IP Komputera:</span> <strong id="api-ip">-</strong></p>
                <p><span>Panel WWW:</span> <a id="api-link" href="#" target="_blank">Otwórz link</a></p>
                <p style="flex-direction: column; align-items: flex-start; gap: 4px;">
                    <span>Folder z danymi (ustawienia, tokeny):</span>
                    <strong id="api-datadir" style="color: var(--accent); word-break: break-all; font-size: 11px;">-</strong>
                </p>
                <button class="small" style="width: 100%; margin-top: 6px;" onclick="openDataFolder()">Otwórz folder z danymi</button>
            </div>

            <!-- Tryb połączenia ze Spotify -->
            <div class="card">
                <h4>Połączenie ze Spotify</h4>
                <div class="theme-picker" style="grid-template-columns: 1fr 1fr;">
                    <button class="theme-option" data-spotifymode-btn="native" onclick="setSpotifyMode('native')">
                        Bezpośrednio z appki
                    </button>
                    <button class="theme-option" data-spotifymode-btn="api" onclick="setSpotifyMode('api')">
                        Przez Spotify Web API
                    </button>
                </div>
                <p style="font-size: 12px; opacity: 0.75; margin-top: 6px;">
                    "Bezpośrednio z appki" (zalecane) - łączy się wprost z aplikacją Spotify
                    na tym komputerze, bez limitu zapytań. Wymaga nie zniminalozowanej aplikacji Spotify. "Przez Spotify Web API" wymaga
                    kluczy poniżej i może po dłuższym działaniu trafić na limit zapytań (429).
                </p>
            </div>

            <!-- Formularz Kluczy API -->
            <div class="card">
                <h4>Konfiguracja API</h4>
                <div class="form-group">
                    <label>Discord Client ID</label>
                    <input type="text" id="cfg-discord" placeholder="Wpisz ID aplikacji Discord">
                </div>
                <div class="form-group">
                    <label>Spotify Client ID</label>
                    <input type="text" id="cfg-spotify-id" placeholder="Wpisz Client ID Spotify">
                </div>
                <div class="form-group">
                    <label>Spotify Client Secret</label>
                    <input type="password" id="cfg-spotify-secret" placeholder="Wpisz Client Secret Spotify">
                </div>
                <button class="primary small" style="width: 100%; margin-top: 10px;" onclick="saveApiSettings()">Zapisz Ustawienia</button>
            </div>
        </div>
    </div>

    <script>
        let presenceEnabled = true;
        let currentTheme = 'pink';
        let lastCustomColor = '#3B82F6';
        let lyricLineMode = 'single';

        function switchTab(tabName) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

            if (tabName === 'player') {
                document.querySelectorAll('.tab-btn')[0].classList.add('active');
                document.getElementById('tab-player').classList.add('active');
            } else {
                document.querySelectorAll('.tab-btn')[1].classList.add('active');
                document.getElementById('tab-settings').classList.add('active');
                loadApiSettings(); // Pobierz aktualne klucze przy wejściu w zakładkę
            }
        }

        // Lokalny placeholder okładki (SVG jako data URI) - działa zawsze,
        // bez zapytania do zewnętrznego serwisu (via.placeholder.com potrafił
        // się nie załadować / działać wolno, co powodowało miganie okładki).
        const NO_COVER_SRC = "data:image/svg+xml;utf8," + encodeURIComponent(
            "<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'>" +
            "<rect width='100%' height='100%' rx='20' fill='#2b2b3d'/>" +
            "<text x='50%' y='50%' font-family='sans-serif' font-size='20' fill='#ffffff' " +
            "text-anchor='middle' dominant-baseline='middle'>Brak okładki</text></svg>"
        );
        document.getElementById('cover').src = NO_COVER_SRC;

        function formatTime(sec) {
            if (!sec || sec < 0 || !isFinite(sec)) return "0:00";
            const m = Math.floor(sec / 60);
            const s = Math.floor(sec % 60);
            return m + ":" + String(s).padStart(2, '0');
        }

        function updateState() {
            fetch('/state')
                .then(res => res.json())
                .then(data => {
                    // Aktualizacja Odtwarzacza
                    document.getElementById('lyric').innerText = data.line;
                    document.getElementById('track').innerText = data.track;
                    document.getElementById('artist').innerText = data.artist;
                    const coverEl = document.getElementById('cover');
                    const wantedCoverSrc = data.cover_url || NO_COVER_SRC;
                    if (coverEl.dataset.currentSrc !== wantedCoverSrc) {
                        coverEl.dataset.currentSrc = wantedCoverSrc;
                        coverEl.src = wantedCoverSrc;
                    }
                    document.getElementById('playBtn').innerText = data.is_playing ? "⏸ Pauza" : "▶ Start";

                    // Druga linijka tekstu (podgląd kolejnej linijki) - pokazywana
                    // tylko w trybie "2 linijki" i tylko gdy faktycznie jest co pokazać
                    if (data.lyric_line_mode && data.lyric_line_mode !== lyricLineMode) {
                        lyricLineMode = data.lyric_line_mode;
                        applyLyricLineModeButtons(lyricLineMode);
                    }
                    const lyricSecondEl = document.getElementById('lyricSecond');
                    if (lyricLineMode === 'double' && data.next_line) {
                        lyricSecondEl.innerText = data.next_line;
                        lyricSecondEl.classList.add('visible');
                    } else {
                        lyricSecondEl.classList.remove('visible');
                    }

                    // Pasek postępu utworu
                    const dur = data.duration_sec || 0;
                    const pos = dur ? Math.min(data.position_sec || 0, dur) : (data.position_sec || 0);
                    const pct = dur > 0 ? Math.min(100, (pos / dur) * 100) : 0;
                    document.getElementById('progressFill').style.width = pct + '%';
                    document.getElementById('posTime').innerText = formatTime(pos);
                    document.getElementById('durTime').innerText = formatTime(dur);

                    presenceEnabled = data.presence_enabled;
                    document.getElementById('presenceBtn').innerText =
                        presenceEnabled ? "WŁĄCZONY" : "WYŁĄCZONY";

                    // Aktualizacja Ustawień / Parowania
                    document.getElementById('api-code').innerText = data.pairing_code || "Brak";
                    document.getElementById('api-ip').innerText = data.local_ip || "Nieznane";
                    if(data.local_ip && data.web_port) {
                        let webUrl = `http://${data.local_ip}:${data.web_port}`;
                        document.getElementById('api-link').href = webUrl;
                        document.getElementById('api-link').innerText = webUrl;
                    }

                    // Pastylki statusowe: w motywie Elcia - różowe/szare serduszka,
                    // w pozostałych motywach - neutralna kropka w kolorze motywu
                    const dotOn = currentTheme === 'pink'
                        ? '<span class="heart-icon heart-on">♥</span>'
                        : '<span class="dot dot-on"></span>';
                    const dotOff = currentTheme === 'pink'
                        ? '<span class="heart-icon heart-off">♥</span>'
                        : '<span class="dot dot-off"></span>';

                    document.getElementById('st-spotify').innerHTML = data.status_spotify ? dotOn : dotOff;
                    document.getElementById('st-ytm').innerHTML = data.status_ytm ? dotOn : dotOff;
                    document.getElementById('st-phone').innerHTML = data.status_phone ? dotOn : dotOff;
                    document.getElementById('st-discord').innerHTML = data.status_discord ? dotOn : dotOff;

                    document.getElementById('api-datadir').innerText = data.app_data_dir || '-';

                    // Pastylka "następny utwór" / "kolejka" pod sterowaniem
                    renderNextWrap(data.display_mode || 'none', data.queue || [], data.queue_count || 5);
                })
                .catch(err => console.log(err));
        }

        function escapeHtml(str) {
            const div = document.createElement('div');
            div.innerText = str == null ? '' : str;
            return div.innerHTML;
        }

        function renderNextWrap(mode, queue, queueCount) {
            const wrap = document.getElementById('nextWrap');
            if (mode === 'none' || !queue || queue.length === 0) {
                wrap.style.display = 'none';
                wrap.innerHTML = '';
                return;
            }
            const limit = mode === 'queue' ? Math.max(2, Math.min(9, queueCount || 5)) : 1;
            const items = queue.slice(0, limit);
            wrap.innerHTML = items.map((t, idx) => {
                const label = mode === 'queue' ? ('W kolejce #' + (idx + 1)) : 'Następny utwór';
                const cover = t.cover_url || NO_COVER_SRC;
                return `
                    <div class="next-pill">
                        <img src="${cover}" alt="">
                        <div class="next-pill-info">
                            <div class="next-pill-label">${label}</div>
                            <div class="next-pill-track">${escapeHtml(t.track || '-')}</div>
                            <div class="next-pill-artist">${escapeHtml(t.artist || '')}</div>
                        </div>
                    </div>
                `;
            }).join('');
            wrap.style.display = 'flex';
        }

        function setDisplayMode(mode) {
            applyDisplayMode(mode);
            fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ DISPLAY_MODE: mode })
            }).catch(err => console.log(err));
        }

        function applyDisplayMode(mode) {
            document.querySelectorAll('[data-display-btn]').forEach(el => {
                el.classList.toggle('active', el.dataset.displayBtn === mode);
            });
            // Suwak liczby utworów pokazujemy tylko wtedy, gdy wybrano "Kolejka"
            document.getElementById('queueCountRow').style.display = (mode === 'queue') ? 'block' : 'none';
        }

        // --- Liczba utworów widocznych w trybie "Kolejka" (suwak 2-9) ---
        function updateQueueSliderFill(value) {
            const slider = document.getElementById('queueCountSlider');
            const min = 2, max = 9;
            const pct = ((value - min) / (max - min)) * 100;
            slider.style.background =
                `linear-gradient(to right, var(--accent) 0%, var(--accent) ${pct}%, rgba(255,255,255,0.1) ${pct}%, rgba(255,255,255,0.1) 100%)`;
        }

        function onQueueCountInput(value) {
            document.getElementById('queueCountValue').innerText = value;
            updateQueueSliderFill(value);
        }

        function setQueueCount(value) {
            const v = Math.max(2, Math.min(9, parseInt(value, 10) || 5));
            document.getElementById('queueCountSlider').value = v;
            document.getElementById('queueCountValue').innerText = v;
            updateQueueSliderFill(v);
            fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ QUEUE_COUNT: v })
            }).catch(err => console.log(err));
        }

        // --- Ile linijek tekstu piosenki wyświetlać na raz (1 lub 2) ---
        function applyLyricLineModeButtons(mode) {
            document.querySelectorAll('[data-lyriclines-btn]').forEach(el => {
                el.classList.toggle('active', el.dataset.lyriclinesBtn === mode);
            });
            if (mode !== 'double') {
                document.getElementById('lyricSecond').classList.remove('visible');
            }
        }

        function setLyricLineMode(mode) {
            lyricLineMode = mode;
            applyLyricLineModeButtons(mode);
            fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ LYRIC_LINE_MODE: mode })
            }).catch(err => console.log(err));
        }

        // --- Tryb połączenia ze Spotify: bezpośrednio z appki / przez Web API ---
        function applySpotifyMode(mode) {
            document.querySelectorAll('[data-spotifymode-btn]').forEach(el => {
                el.classList.toggle('active', el.dataset.spotifymodeBtn === mode);
            });
        }

        function setSpotifyMode(mode) {
            applySpotifyMode(mode);
            fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ SPOTIFY_MODE: mode })
            }).catch(err => console.log(err));
        }

        function openDataFolder() {
            fetch('/open-data-folder').catch(err => console.log(err));
        }

        function sendCmd(cmd) {
            fetch('/control?action=' + cmd).catch(err => console.log(err));
        }

        function togglePresence() {
            fetch('/presence?state=' + (presenceEnabled ? 'off' : 'on')).catch(err => console.log(err));
        }

        function loadApiSettings() {
            fetch('/api/settings')
                .then(res => res.json())
                .then(cfg => {
                    document.getElementById('cfg-discord').value = cfg.DISCORD_CLIENT_ID || '';
                    document.getElementById('cfg-spotify-id').value = cfg.SPOTIFY_CLIENT_ID || '';
                    document.getElementById('cfg-spotify-secret').value = cfg.SPOTIFY_CLIENT_SECRET || '';

                    lastCustomColor = cfg.CUSTOM_COLOR || lastCustomColor;
                    document.getElementById('cfg-custom-color').value = lastCustomColor;
                    document.getElementById('customSwatch').style.background = lastCustomColor;

                    applyTheme(cfg.THEME || 'pink');
                    applyDisplayMode(cfg.DISPLAY_MODE || 'none');

                    const qCount = Math.max(2, Math.min(9, parseInt(cfg.QUEUE_COUNT, 10) || 5));
                    document.getElementById('queueCountSlider').value = qCount;
                    document.getElementById('queueCountValue').innerText = qCount;
                    updateQueueSliderFill(qCount);

                    lyricLineMode = cfg.LYRIC_LINE_MODE || 'single';
                    applyLyricLineModeButtons(lyricLineMode);

                    applySpotifyMode(cfg.SPOTIFY_MODE || 'native');
                })
                .catch(err => console.log(err));
        }

        function isValidHex(hex) {
            return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(hex);
        }

        function hexToRgb(hex) {
            hex = hex.replace('#', '');
            if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
            const num = parseInt(hex, 16);
            return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
        }

        function lightenColor(hex, amount) {
            const { r, g, b } = hexToRgb(hex);
            const lr = Math.min(255, Math.round(r + (255 - r) * amount));
            const lg = Math.min(255, Math.round(g + (255 - g) * amount));
            const lb = Math.min(255, Math.round(b + (255 - b) * amount));
            return `rgb(${lr}, ${lg}, ${lb})`;
        }

        function applyCustomColor(hex) {
            if (!isValidHex(hex)) return;
            const { r, g, b } = hexToRgb(hex);
            document.body.style.setProperty('--accent', hex);
            document.body.style.setProperty('--accent-hover', lightenColor(hex, 0.25));
            document.body.style.setProperty('--accent-glow-strong', `rgba(${r}, ${g}, ${b}, 0.6)`);
            document.body.style.setProperty('--accent-glow-mid', `rgba(${r}, ${g}, ${b}, 0.4)`);
            document.body.style.setProperty('--accent-glow-soft', `rgba(${r}, ${g}, ${b}, 0.3)`);
            document.body.style.setProperty('--bg-from', `rgba(${Math.round(r * 0.15)}, ${Math.round(g * 0.15)}, ${Math.round(b * 0.15)}, 1)`);
        }

        function clearCustomColor() {
            ['--accent', '--accent-hover', '--accent-glow-strong', '--accent-glow-mid', '--accent-glow-soft', '--bg-from', '--bg-to']
                .forEach(p => document.body.style.removeProperty(p));
        }

        function previewCustomColor() {
            const hex = document.getElementById('cfg-custom-color').value.trim();
            if (isValidHex(hex)) applyCustomColor(hex);
        }

        function saveCustomColor() {
            const hex = document.getElementById('cfg-custom-color').value.trim();
            if (!isValidHex(hex)) {
                alert('Podaj poprawny kolor HEX, np. #8B5CF6');
                return;
            }
            lastCustomColor = hex;
            applyCustomColor(hex);
            document.getElementById('customSwatch').style.background = hex;

            fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ THEME: 'custom', CUSTOM_COLOR: hex })
            }).catch(err => console.log(err));
        }

        function applyTheme(theme) {
            currentTheme = theme;
            document.body.setAttribute('data-theme', theme);
            document.querySelectorAll('.theme-option').forEach(el => {
                el.classList.toggle('active', el.dataset.themeBtn === theme);
            });

            const customPicker = document.getElementById('customColorPicker');
            if (theme === 'custom') {
                customPicker.style.display = 'block';
                applyCustomColor(lastCustomColor);
            } else {
                customPicker.style.display = 'none';
                clearCustomColor();
            }
        }

        function setTheme(theme) {
            applyTheme(theme);
            fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ THEME: theme })
            }).catch(err => console.log(err));
        }

        function saveApiSettings() {
            const newCfg = {
                DISCORD_CLIENT_ID: document.getElementById('cfg-discord').value.trim(),
                SPOTIFY_CLIENT_ID: document.getElementById('cfg-spotify-id').value.trim(),
                SPOTIFY_CLIENT_SECRET: document.getElementById('cfg-spotify-secret').value.trim()
            };

            fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newCfg)
            })
            .then(res => res.json())
            .then(data => {
                if(data.ok) alert('Ustawienia zostały zapisane!');
            })
            .catch(err => alert('Błąd zapisu: ' + err));
        }

        loadApiSettings();
        setInterval(updateState, 500);
        updateState();
    </script>
</body>
</html>
"""

class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            initial_theme = current_settings.get("THEME", "pink")
            page = HTML_PAGE.replace("__INITIAL_THEME__", initial_theme)
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
        elif parsed.path == "/state":
            with state_lock:
                data = dict(app_state)
            
            # --- NOWE LINIE DODANE DLA USTAWIEŃ API ---
            # Pobieramy kod za pomocą już wbudowanej funkcji
            data["pairing_code"] = get_or_create_pairing_code()
            # Pobieramy IP komputera w sieci lokalnej
            data["local_ip"] = get_local_ip()
            # Przekazujemy port serwera WEB do zbudowania linku
            data["web_port"] = WEB_SERVER_PORT
            # Tryb wyświetlania następnego utworu / kolejki + folder z danymi
            data["display_mode"] = current_settings.get("DISPLAY_MODE", "none")
            data["queue_count"] = current_settings.get("QUEUE_COUNT", 5)
            data["lyric_line_mode"] = current_settings.get("LYRIC_LINE_MODE", "single")
            data["app_data_dir"] = APP_DATA_DIR
            # ------------------------------------------

            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        elif parsed.path == "/api/settings":
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(current_settings).encode("utf-8"))
        elif parsed.path == "/control":
            query = parse_qs(parsed.query)
            action = query.get("action", [None])[0]
            with state_lock:
                active = app_state["active_source"]
                is_play = app_state["is_playing"]

            cmd = ("pause" if is_play else "play") if action == "toggle" else action
            if active == "spotify": threading.Thread(target=spotify_control, args=(cmd,)).start()
            elif active == "youtube": threading.Thread(target=youtube_control, args=(cmd,)).start()

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        elif parsed.path == "/presence":
            query = parse_qs(parsed.query)
            state_param = query.get("state", [None])[0]
            if state_param == "on":
                _update_app_state(presence_enabled=True)
                current_settings["PRESENCE_ENABLED"] = True
                save_settings(current_settings)
            elif state_param == "off":
                _update_app_state(presence_enabled=False)
                discord_clear()
                current_settings["PRESENCE_ENABLED"] = False
                save_settings(current_settings)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        elif parsed.path == "/open-data-folder":
            _ensure_app_data_dir()
            try:
                if sys.platform == "win32":
                    os.startfile(APP_DATA_DIR)
                elif sys.platform == "darwin":
                    import subprocess
                    subprocess.Popen(["open", APP_DATA_DIR])
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", APP_DATA_DIR])
            except Exception as e:
                print(f"[appdata] Nie udało się otworzyć folderu {APP_DATA_DIR}: {e}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/settings":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                new_settings = json.loads(body.decode("utf-8"))
                
                global current_settings, DISCORD_CLIENT_ID, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
                old_discord_id = DISCORD_CLIENT_ID
                current_settings.update(new_settings)
                save_settings(current_settings)
                
                DISCORD_CLIENT_ID = current_settings.get("DISCORD_CLIENT_ID", DISCORD_CLIENT_ID)
                SPOTIFY_CLIENT_ID = current_settings.get("SPOTIFY_CLIENT_ID", SPOTIFY_CLIENT_ID)
                SPOTIFY_CLIENT_SECRET = current_settings.get("SPOTIFY_CLIENT_SECRET", SPOTIFY_CLIENT_SECRET)

                if DISCORD_CLIENT_ID != old_discord_id:
                    # ID Discorda się zmieniło (albo zostało dodane/usunięte) -
                    # od razu próbujemy się połączyć/rozłączyć zamiast czekać
                    # do 15 sekund na kolejną automatyczną próbę.
                    discord_close()
                    if DISCORD_CLIENT_ID:
                        threading.Thread(target=_reconnect_discord, daemon=True).start()

                self.send_response(200)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args): pass


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def _command_listener():
    while True:
        try: command = input().strip().lower()
        except (EOFError, KeyboardInterrupt, OSError): return

        if command == "off":
            _update_app_state(presence_enabled=False)
            discord_clear()
        elif command == "on":
            _update_app_state(presence_enabled=True)
        elif command == "status":
            with state_lock:
                enabled = app_state["presence_enabled"]
                offset = app_state["lyric_offset_seconds"]
            print(f"Status: {'WŁĄCZONY' if enabled else 'WYŁĄCZONY'}, Przesunięcie: {offset:+.1f}s")
        elif command.startswith("delay"):
            parts = command.split(maxsplit=1)
            if len(parts) == 2:
                try: _update_app_state(lyric_offset_seconds=float(parts[1].replace(",", ".")))
                except ValueError: pass

def _start_command_listener_if_possible():
    if sys.stdin is not None:
        threading.Thread(target=_command_listener, daemon=True).start()

# ============================================================
# START
# ============================================================
if __name__ == "__main__":
    _load_pairing_key()

    if DISCORD_CLIENT_ID:
        _CONNECT_RETRIES = 5
        for attempt in range(1, _CONNECT_RETRIES + 1):
            try:
                discord_connect()
                break
            except Exception:
                if attempt != _CONNECT_RETRIES: time.sleep(min(2 * attempt, 10))
    else:
        print("[discord] Brak DISCORD_CLIENT_ID w ustawieniach - pomijam łączenie z Discordem.")

    threading.Thread(target=background_loop, daemon=True).start()
    _start_command_listener_if_possible()
    _start_now_playing_http_server()
    _start_phone_receiver_http_server()

    local_ip = get_local_ip()

    web_server = _QuietHTTPServer(("0.0.0.0", WEB_SERVER_PORT), WebServerHandler)
    threading.Thread(target=web_server.serve_forever, daemon=True).start()

    try:
        if webview is not None:
            webview.create_window(
                WINDOW_TITLE, f"http://127.0.0.1:{WEB_SERVER_PORT}",
                width=WINDOW_WIDTH, height=WINDOW_HEIGHT, resizable=WINDOW_RESIZABLE
            )
            webview.start()
        else:
            try: webbrowser.open(f"http://127.0.0.1:{WEB_SERVER_PORT}")
            except Exception: pass
            while True: time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        discord_clear()
        discord_close()


"""
Pozdrawiam misiaczki <3
"""