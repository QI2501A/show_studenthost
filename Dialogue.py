"""Dialogue.py — ITE College West Drone & Robot Hub show host.

Lives in its own show_host/ folder, deliberately separate from
hub_dashboard/ — the only connection between the two is HTTP
(POST /api/show/stop) plus spawning main.py, which itself only talks to
hub_dashboard over HTTP. No shared code, config, or virtualenv, so changes
here can't break the dashboard and vice versa.

This runs as a real listening conversation, not an operator-paced slideshow:
it listens on the microphone for the *student* to say each of their scripted
lines, and as soon as it hears one, speaks the chatbot's next line back
automatically (with live data filled in) — no Enter key involved. Falls back
to typed Enter only if a microphone genuinely isn't available.

Runs the scripted conversation from ../robot-revolution/content.json (the
single source of truth for wording — never hardcode lines here, read them
from that file). Fills the live [DAY]/[DATE]/[TIME]/[WEATHER]/[TEMP]/
[ROBOTICS NEWS HEADLINE] placeholders from free, keyless APIs and speaks the
chatbot's lines with text-to-speech.

Once the student says the IGNITE keyword, this spawns main.py (a separate
process, per the deck's own "What fires: main.py" note) to signal
hub_dashboard to start the robot show. From there the rise/rogue narration
plays out automatically on a real-time clock — including the chatbot
autonomously declaring it's "taking over" once the show reaches the rogue
beat, unprompted, exactly as scripted. To stop it, the student then goes to
this terminal and types the OVERRIDE command directly (matching the story:
they return to the keyboard, not the microphone) — Dialogue.py then calls
hub_dashboard's POST /api/show/stop.

  python Dialogue.py [--hub-url http://localhost:5050] [--content PATH] [--speed 1.0]

Own config: show_host/config.yaml (venue lat/lon/tz for the weather pull).
Own deps: show_host/requirements.txt — pip install -r requirements.txt
  # macOS also needs: brew install portaudio   (for pyaudio)
  #                    pip install pyobjc       (for pyttsx3's speech voice)
All are optional and degrade gracefully to console/typed-input if missing.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import platform
import re
import shutil
import socketserver
import string
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_CONTENT = ROOT.parent / "robot-revolution" / "content.json"
DEFAULT_VIDEO = ROOT.parent / "DroneHub_Video.mp4"
DEFAULT_ROGUE_VIDEO = ROOT.parent / "DH_Asset6_RobotRevolution.mp4"  # placeholder, to be replaced later

ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "italic": "\033[3m",
    "cyan": "\033[96m",
    "amber": "\033[93m",
    "green": "\033[92m",
    "red": "\033[91m",
    "gray": "\033[90m",
}

WEATHER_CODES = {
    0: "clear skies", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "severe thunderstorms",
}

FALLBACK_NEWS = (
    "Researchers worldwide continue pushing embodied AI out of the lab and into the real world"
)


# --------------------------------------------------------------------------- content

def load_content(path: str | None) -> dict:
    p = Path(path) if path else DEFAULT_CONTENT
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_meta_value(meta_list, label, default=None):
    for m in meta_list or []:
        if m.get("label") == label:
            return m.get("value")
    return default


# --------------------------------------------------------------------------- live data

def fetch_weather(lat: float, lon: float, tz: str) -> tuple[str, int]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code&timezone={urllib.parse.quote(tz)}"
    )
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        cur = payload["current"]
        code = int(cur.get("weather_code", -1))
        temp = round(cur.get("temperature_2m", 27))
        return WEATHER_CODES.get(code, "mild conditions"), temp
    except Exception as exc:
        print(f"[data] weather fetch failed ({exc}); using fallback.")
        return "mild conditions", 27


def fetch_news(query: str = "robotics") -> str:
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-SG&gl=SG&ceid=SG:en"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            root = ET.fromstring(resp.read())
        item = root.find("./channel/item")
        title = item.findtext("title") if item is not None else None
        if not title:
            raise ValueError("no items in feed")
        if " - " in title:
            title = title.rsplit(" - ", 1)[0]
        return title.strip()
    except Exception as exc:
        print(f"[data] news fetch failed ({exc}); using fallback headline.")
        return FALLBACK_NEWS


def fetch_live_data(cfg: dict) -> dict:
    now = datetime.now()
    daypart = "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"
    weather, temp = fetch_weather(cfg["venue_lat"], cfg["venue_lon"], cfg["venue_tz"])
    return {
        "day": now.strftime("%A"),
        "date": now.strftime("%-d %B %Y") if os.name != "nt" else now.strftime("%#d %B %Y"),
        "time": now.strftime("%I:%M %p").lstrip("0"),
        "daypart": daypart,
        "weather": weather,
        "temp": str(temp),
        "news": fetch_news(),
    }


def fill_placeholders(text: str, live: dict) -> str:
    if not text:
        return text
    repl = {
        "[morning/afternoon]": live["daypart"],
        "[DAY]": live["day"],
        "[DATE]": live["date"],
        "[TIME]": live["time"],
        "[WEATHER]": live["weather"],
        "[TEMP]": live["temp"],
        "[ROBOTICS NEWS HEADLINE]": live["news"],
    }
    for k, v in repl.items():
        text = text.replace(k, v)
    return text


def load_show_host_config() -> dict:
    """Reads show_host/config.yaml (this folder's own config — separate from
    hub_dashboard/config.yaml, which app.py owns)."""
    defaults = {
        "venue_lat": 1.3840, "venue_lon": 103.7470, "venue_tz": "Asia/Singapore",
        "rise_video": None, "rogue_video": None,
    }
    config_path = ROOT / "config.yaml"
    try:
        import yaml

        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        defaults.update({k: cfg[k] for k in defaults if k in cfg})
    except Exception as exc:
        print(f"[data] {config_path.name} not read ({exc}); using default venue coordinates.")
    return defaults


def resolve_video_path(cli_value: str | None, cfg: dict, config_key: str, default_path: Path) -> Path:
    raw = cli_value or cfg.get(config_key)
    if not raw:
        return default_path
    p = Path(raw)
    return p if p.is_absolute() else (ROOT / p)


# --------------------------------------------------------------------------- markup

def render_markup(text: str) -> str:
    if not text:
        return ""
    out = re.sub(r"\[\[(.+?)\]\]", lambda m: ANSI["cyan"] + m.group(1) + ANSI["reset"], text)
    out = re.sub(r"\*\*(.+?)\*\*", lambda m: ANSI["bold"] + m.group(1) + ANSI["reset"], out)
    out = re.sub(r"_(.+?)_", lambda m: ANSI["italic"] + ANSI["gray"] + m.group(1) + ANSI["reset"], out)
    return out


def strip_for_speech(text: str) -> str:
    if not text:
        return ""
    out = re.sub(r"_\(.*?\)_", " ", text)  # drop stage directions from speech
    out = re.sub(r"\[\[(.+?)\]\]", r"\1", out)
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", out)
    out = re.sub(r"_(.+?)_", r"\1", out)
    out = out.replace("\n", " ")
    return re.sub(r"\s+", " ", out).strip()


def speech_segments(text: str) -> list[str]:
    """Splits a line on paragraph gaps (content.json's own \\n\\n convention)
    into separate spoken segments, so a deliberate pause can be inserted
    between them — e.g. a beat after reporting the weather, before the next
    thought. Each segment is independently cleaned with strip_for_speech."""
    if not text:
        return []
    segments = [strip_for_speech(p) for p in re.split(r"\n\s*\n", text)]
    return [s for s in segments if s]


# "live" is a heteronym: TTS engines default to the adjective (rhymes with
# "hive", as in "live broadcast"), but the script uses it as the verb (rhymes
# with "give", as in "live in a screen" / "living"). Respelling it is the
# simple, broadly-portable fix — reliable across `say` and pyttsx3/espeak,
# unlike embedding synthesizer-specific phoneme codes. Audio-only: the
# original spelling is what's shown on the chatbot screen and in the
# terminal, this is applied just before the text reaches the TTS engine.
PRONUNCIATION_FIXUPS = [
    (re.compile(r"\blive\b", re.IGNORECASE), "liv"),
]


def apply_pronunciation_fixups(text: str) -> str:
    for pattern, replacement in PRONUNCIATION_FIXUPS:
        text = pattern.sub(replacement, text)
    return text


_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "is",
    "are", "was", "were", "it", "its", "this", "that", "we", "you", "i", "do",
    "does", "did", "for", "with", "as", "be", "been", "have", "has", "had",
    "not", "so", "just", "what", "your", "our", "they", "them",
}


def _significant_words(text: str) -> list[str]:
    text = strip_for_speech(text).lower().translate(str.maketrans("", "", string.punctuation))
    return [w for w in text.split() if w not in _STOPWORDS and len(w) > 2]


def phrase_match(expected_text: str, heard_text: str, threshold: float = 0.35) -> bool:
    """True once enough of expected_text's distinctive words have turned up in
    heard_text — a real actor won't recite a line word-for-word and ASR will
    mishear some of it, so this checks overlap of content words rather than
    an exact or substring match."""
    expected_words = set(_significant_words(expected_text))
    if not expected_words:
        return True
    heard_words = set(_significant_words(heard_text))
    overlap = expected_words & heard_words
    return (len(overlap) / len(expected_words)) >= threshold


# --------------------------------------------------------------------------- blocking-call safety net

def run_with_timeout(fn, timeout: float):
    """Runs fn() in a daemon thread; returns (True, result) or (False, None) if
    it doesn't finish within timeout seconds. Audio drivers can hang forever
    on a machine with no mic/speaker permission granted yet (exactly the state
    right after a double-clicked launcher first opens) — without this, that
    hang would freeze the whole show before a single line is shown, with no
    way to recover short of killing the process. A stuck fn leaks one daemon
    thread instead, which is harmless."""
    result: dict = {}

    def worker():
        try:
            result["value"] = fn()
        except Exception as exc:
            result["error"] = exc

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return False, None
    if "error" in result:
        raise result["error"]
    return True, result.get("value")


# --------------------------------------------------------------------------- chatbot screen (visual output)

# Single source of truth for the speaking rate, shared between Voice (actual
# TTS) and the chatbot screen (so its typewriter reveal is paced to roughly
# match, per request — see Voice and ChatbotScreen.show below).
SPEECH_RATE_WPM = 165

# Chrome/Edge/Chromium launched with --kiosk opens truly full-screen with no
# window chrome — much stronger "we are talking to a machine" effect than a
# normal browser window, and doesn't depend on the Fullscreen API (which
# browsers block from running without a user gesture, so screen.html can't
# just request it on load by itself — see the on-page "click to enter
# full-screen" button in screen.html, which covers that case). Falls back to
# a normal window/tab via webbrowser.open if none of these are found — exact
# install paths vary a lot machine to machine, hence checking several ways.
_KIOSK_APP_PATHS: dict[str, list[str]] = {
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "Windows": [
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ],
}
_KIOSK_PATH_COMMANDS: dict[str, list[str]] = {
    "Darwin": ["google-chrome", "chromium", "microsoft-edge"],
    "Windows": ["chrome.exe", "chrome", "msedge.exe", "msedge"],
    "Linux": ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "microsoft-edge"],
}


def _windows_registry_browser_paths() -> list[str]:
    """The App Paths registry key is how Windows itself resolves `chrome.exe`
    /`msedge.exe` regardless of which drive/folder they were installed to —
    more reliable than guessing Program Files variants."""
    found = []
    try:
        import winreg
    except ImportError:
        return found  # not on Windows
    for exe in ("chrome.exe", "msedge.exe"):
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    if value:
                        found.append(value)
            except OSError:
                continue
    return found


def _find_kiosk_browser() -> str | None:
    system = platform.system()
    candidates = [shutil.which(n) for n in _KIOSK_PATH_COMMANDS.get(system, [])]
    candidates += [os.path.expandvars(p) for p in _KIOSK_APP_PATHS.get(system, [])]
    if system == "Windows":
        candidates += _windows_registry_browser_paths()
    for path in candidates:
        if path and Path(path).exists():
            return path
    return None


def launch_browser(url: str) -> str:
    """Opens the chatbot screen and reports what actually happened: 'kiosk'
    (a true full-screen, chrome-less window), 'window' (an ordinary browser
    window/tab — full-screen still reachable with F11 or the on-page
    button), or 'none' (nothing could be opened automatically). Reporting
    this accurately matters: an earlier version of this claimed "full-screen"
    even when it had silently fallen back to an ordinary tab, which made it
    easy to miss that any window had opened at all."""
    browser = _find_kiosk_browser()
    if browser:
        try:
            subprocess.Popen([browser, f"--app={url}", "--kiosk", "--new-window"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "kiosk"
        except Exception:
            pass
    try:
        if webbrowser.open(url):
            return "window"
    except Exception:
        pass
    return "none"


class _ScreenHTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _ScreenHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args) -> None:
        pass  # keep the operator's console free of HTTP access logs

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            body = self.server.screen_html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/state":
            with self.server.state_lock:
                body = json.dumps(self.server.state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/video"):
            self._serve_video()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/video-ended":
            self.server.screen_ref._video_ended.set()
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_video(self) -> None:
        path = self.server.screen_ref._video_path
        if not path or not path.exists():
            self.send_response(404)
            self.end_headers()
            return
        file_size = path.stat().st_size
        start, end = 0, file_size - 1
        range_header = self.headers.get("Range")
        m = re.match(r"bytes=(\d+)-(\d*)", range_header or "")
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else file_size - 1
            end = min(end, file_size - 1)
        length = end - start + 1
        self.send_response(206 if range_header else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if range_header:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()
        try:
            with path.open("rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser navigated away / seeked — not an error


class ChatbotScreen:
    """A dedicated black-background, green-monospace browser page that types
    out whatever the chatbot is saying, one character at a time — a visible
    "robot terminal" for the audience, separate from the operator's own
    scrollback (which mixes in stage directions, notes, and everything else).
    Also plays the rise-phase video full-screen on the same page, on request
    (see play_video), switching back once it ends.

    Runs as a tiny local HTTP server (stdlib only) serving screen.html, which
    polls it for updates — a real browser tab, not a native GUI toolkit
    window. Deliberately NOT Tkinter: it's an optional stdlib module that a
    real-world Python install can easily be missing (confirmed on the actual
    show laptop), which would silently drop this feature entirely. Every
    machine has a browser, so this has no missing-dependency failure mode."""

    PORT = 8765

    def __init__(self, enabled: bool = True) -> None:
        self.available = False
        self.url = None
        self.httpd = None
        self._video_path: Path | None = None
        self._video_ended = threading.Event()
        self._state_lock = threading.Lock()
        self._state = {
            "seq": 0, "mode": "chat", "segments": [], "rate_wpm": SPEECH_RATE_WPM,
            "theme": "green", "clear_seq": 0,
        }
        if not enabled:
            return
        html_path = ROOT / "screen.html"
        try:
            html = html_path.read_text(encoding="utf-8")
            self.httpd = _ScreenHTTPServer(("127.0.0.1", self.PORT), _ScreenHandler)
            self.httpd.screen_html = html
            self.httpd.state_lock = self._state_lock
            self.httpd.state = self._state
            self.httpd.screen_ref = self
            threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
            self.url = f"http://127.0.0.1:{self.PORT}/"
            self.available = True
        except Exception as exc:
            print(f"[screen] chatbot screen unavailable ({exc}); chatbot lines will only show in this terminal.")
            return
        result = launch_browser(self.url)
        bar = "=" * 64
        if result == "kiosk":
            print(f"[screen] chatbot screen opened FULL-SCREEN at {self.url}")
        elif result == "window":
            print(f"\n{bar}\n"
                  f"CHATBOT SCREEN opened in a browser window/tab — it may not be\n"
                  f"in front. Find it and click the on-page button (or press F11)\n"
                  f"to go full-screen:\n\n  {self.url}\n{bar}\n")
        else:
            print(f"\n{bar}\n"
                  f"Could not open a browser automatically. Open this URL yourself\n"
                  f"to see the chatbot screen and video:\n\n  {self.url}\n{bar}\n")

    def show(self, segments: list[str]) -> None:
        """Safe to call even when the screen is unavailable — becomes a no-op."""
        if self.available and segments:
            with self._state_lock:
                self._state["seq"] += 1
                self._state["mode"] = "chat"
                self._state["segments"] = list(segments)

    def play_video(self, path: Path, speed: float = 1.0, timeout_s: float = 900) -> bool:
        """Switches the screen to full-screen video playback and blocks until
        the browser reports the video has finished (screen.html POSTs
        /video-ended), or timeout_s elapses as a safety net so the show can
        never hang forever on a video that fails to play. Returns True if the
        video actually finished normally."""
        if not self.available:
            print("[screen] chatbot screen unavailable; cannot play the rise-phase video, skipping wait.")
            return False
        if not path.exists():
            print(f"[screen] video not found: {path}; skipping.")
            return False
        self._video_path = path
        self._video_ended.clear()
        with self._state_lock:
            self._state["seq"] += 1
            self._state["mode"] = "video"
            self._state["video_speed"] = max(speed, 0.01)
        finished = self._video_ended.wait(timeout_s)
        if not finished:
            print(f"[screen] video did not report finishing within {timeout_s:.0f}s; continuing anyway.")
        with self._state_lock:
            self._state["mode"] = "chat"
        return finished

    def set_theme(self, theme: str) -> None:
        """'green' (normal) or 'red' (system taken over) — recolours the
        screen's rain background, panel border/glow, and text."""
        if self.available:
            with self._state_lock:
                self._state["theme"] = theme

    def clear(self) -> None:
        """Wipes the screen's accumulated chat history — used at the rogue
        takeover (fresh red screen, not another line tacked onto the green
        log) and again once OVERRIDE restores manual control."""
        if self.available:
            with self._state_lock:
                self._state["clear_seq"] += 1
                self._state["segments"] = []

    def close(self) -> None:
        if self.httpd:
            try:
                self.httpd.shutdown()
            except Exception:
                pass


# --------------------------------------------------------------------------- voice out (TTS)

# Robotic-sounding system voices, most menacing first. Zarvox and Trinoids are
# stock macOS speech voices (no download needed) built for exactly this kind
# of low, synthetic, "machine talking" effect — a good fit for a system that's
# meant to sound unsettling once it goes rogue. Falls through to ordinary male
# voices if neither is installed (e.g. on Windows/Linux).
PREFERRED_VOICES = ["Zarvox", "Trinoids", "Fred", "Bruce", "Ralph", "Daniel", "David", "Alex"]


class Voice:
    INIT_TIMEOUT_S = 8
    SAY_TIMEOUT_S = 90  # generous — real speech should always finish well inside this
    RATE_WPM = SPEECH_RATE_WPM
    PARAGRAPH_PAUSE_S = 1.1

    def __init__(self, screen: "ChatbotScreen | None" = None) -> None:
        self.screen = screen
        self.mode: str | None = None  # "say" (macOS) or "pyttsx3" (Windows/Linux) or None (text-only)
        self.engine = None            # persistent pyttsx3 engine, only when mode == "pyttsx3"
        self.say_voice: str | None = None

        if sys.platform == "darwin" and shutil.which("say"):
            # macOS's own `say` command gives the same system voices pyttsx3
            # would (Zarvox, Trinoids, ...) with none of the crash risk below:
            # spinning up more than one NSSpeechSynthesizer-backed pyttsx3
            # engine in the same process can trigger a hard, uncatchable
            # native crash (an NSSpeechSynthesizer completion callback firing
            # into an already-freed engine) — confirmed while testing this
            # exact script. `say` runs each line as its own short-lived
            # process, so there's no shared engine state to corrupt.
            self.mode = "say"
            self.say_voice = self._pick_say_voice()
            return

        try:
            ok, built = run_with_timeout(self._build_pyttsx3, self.INIT_TIMEOUT_S)
            if ok:
                self.engine, voice_id = built
                self.mode = "pyttsx3"
                if voice_id:
                    self.engine.setProperty("voice", voice_id)
            else:
                print(f"[voice] TTS init did not respond within {self.INIT_TIMEOUT_S}s "
                      "(no speaker / permission not granted yet?); chatbot lines will be shown as text only.")
        except ImportError:
            print("[voice] pyttsx3 not installed; chatbot lines will be shown as text only. "
                  "Run: pip install pyttsx3")
        except Exception as exc:
            print(f"[voice] TTS engine unavailable ({exc}); chatbot lines will be shown as text only.")

    @property
    def available(self) -> bool:
        return self.mode is not None

    @staticmethod
    def _pick_say_voice() -> str | None:
        try:
            out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=5).stdout
        except Exception:
            return None
        names = {line.split()[0] for line in out.splitlines() if line.strip()}
        return next((v for v in PREFERRED_VOICES if v in names), None)

    @staticmethod
    def _build_pyttsx3():
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", Voice.RATE_WPM)
        try:
            voices = engine.getProperty("voices") or []
            by_name = {(getattr(v, "name", "") or "").lower(): v.id for v in voices}
            voice_id = next((by_name[w.lower()] for w in PREFERRED_VOICES if w.lower() in by_name), None)
        except Exception:
            voice_id = None
        return engine, voice_id

    def _speak_say_cmd(self, text: str) -> None:
        cmd = ["say", "-r", str(self.RATE_WPM)]
        if self.say_voice:
            cmd += ["-v", self.say_voice]
        cmd.append(text)
        subprocess.run(cmd, timeout=self.SAY_TIMEOUT_S, check=False)

    def _speak_pyttsx3(self, text: str) -> None:
        self.engine.say(text)
        self.engine.runAndWait()

    def say(self, text: str) -> None:
        segments = speech_segments(text)
        if not segments:
            return
        if self.screen:
            self.screen.show(segments)

        if not self.available:
            # No audio — still pace the narration roughly like real speech,
            # including the scripted pause, so timing feels natural either way.
            word_count = sum(len(s.split()) for s in segments)
            time.sleep(min(8.0, max(0.6, word_count / 2.5)) + self.PARAGRAPH_PAUSE_S * (len(segments) - 1))
            return

        speak_fn = self._speak_say_cmd if self.mode == "say" else self._speak_pyttsx3
        for i, segment in enumerate(segments):
            spoken = apply_pronunciation_fixups(segment)
            try:
                ok, _ = run_with_timeout(lambda spoken=spoken: speak_fn(spoken), self.SAY_TIMEOUT_S)
                if not ok:
                    print(f"[voice] TTS playback did not finish within {self.SAY_TIMEOUT_S}s; "
                          "skipping audio for this line.")
            except Exception as exc:
                print(f"[voice] TTS playback failed ({exc}).")
            if i < len(segments) - 1:
                time.sleep(self.PARAGRAPH_PAUSE_S)


# --------------------------------------------------------------------------- voice in (listens for the student's cues)

class VoiceListener:
    INIT_TIMEOUT_S = 8
    LISTEN_MARGIN_S = 15  # safety margin added on top of each listen()'s own timeout/phrase_time_limit

    def __init__(self) -> None:
        self.sr = None
        self.recognizer = None
        self.mic = None
        try:
            import speech_recognition as sr

            ok, built = run_with_timeout(self._build_mic, self.INIT_TIMEOUT_S)
            if ok:
                self.sr = sr
                self.recognizer, self.mic = built
            else:
                print(f"[voice] microphone init did not respond within {self.INIT_TIMEOUT_S}s "
                      "(no mic / permission not granted yet?); falling back to typed keywords.")
        except ImportError:
            print("[voice] SpeechRecognition not installed; falling back to typed keywords. "
                  "Run: pip install SpeechRecognition pyaudio")
        except Exception as exc:
            print(f"[voice] microphone unavailable ({exc}); falling back to typed keywords.")

    @staticmethod
    def _build_mic():
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        mic = sr.Microphone()
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
        return recognizer, mic

    @property
    def available(self) -> bool:
        return self.sr is not None and self.mic is not None

    def _listen_once(self, phrase_time_limit: float = 4):
        try:
            with self.mic as source:
                audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=phrase_time_limit)
            return self.recognizer.recognize_google(audio)
        except (self.sr.WaitTimeoutError, self.sr.UnknownValueError):
            return None

    def wait_for_keyword(self, keyword: str, prompt: str) -> None:
        """Listens until the exact keyword is heard — used only for IGNITE,
        the one line where we need a hard trigger word rather than a fuzzy
        match on a whole sentence."""
        keyword_norm = keyword.strip().upper()
        if not self.available:
            input(f"{ANSI['gray']}{prompt}{ANSI['reset']} ")
            return
        print(f"{ANSI['amber']}> LISTENING FOR KEYWORD: {keyword_norm}{ANSI['reset']}  "
              f"(say it aloud, or Ctrl+C to type it instead)")
        budget = 4 + self.LISTEN_MARGIN_S
        while True:
            try:
                ok, heard = run_with_timeout(self._listen_once, budget)
                if not ok:
                    print(f"[voice] microphone stopped responding within {budget:.0f}s; "
                          "falling back to typed keyword.")
                    input(f"{ANSI['gray']}{prompt}{ANSI['reset']} ")
                    return
                if heard is None:
                    continue  # no speech detected that round — keep listening
                print(f"  [heard] {heard}")
                if keyword_norm in heard.strip().upper():
                    return
            except self.sr.RequestError as exc:
                print(f"[voice] recognition service error ({exc}); falling back to typed keyword.")
                input(f"{ANSI['gray']}{prompt}{ANSI['reset']} ")
                return
            except KeyboardInterrupt:
                typed = input(f"\n[operator] type to confirm ({keyword_norm}): ")
                if keyword_norm in typed.strip().upper():
                    return

    def wait_for_line(self, expected_text: str, prompt: str) -> None:
        """Listens until enough of expected_text has been heard (see
        phrase_match) — used for every other student line, so the chatbot
        replies as soon as the student actually says their part, the way a
        real conversation would work. Accumulates what it hears across
        listen cycles so a longer line split by a natural pause still
        matches."""
        if not self.available:
            input(f"{ANSI['gray']}{prompt}{ANSI['reset']} ")
            return
        word_count = len(_significant_words(expected_text)) or 1
        phrase_time_limit = max(6.0, min(30.0, word_count * 0.9))
        budget = phrase_time_limit + self.LISTEN_MARGIN_S
        print(f"{ANSI['amber']}> listening for the student's line...{ANSI['reset']}")
        heard_so_far = ""
        while True:
            try:
                ok, heard = run_with_timeout(lambda: self._listen_once(phrase_time_limit), budget)
                if not ok:
                    print(f"[voice] microphone stopped responding within {budget:.0f}s; "
                          "falling back to typed cue.")
                    input(f"{ANSI['gray']}{prompt}{ANSI['reset']} ")
                    return
                if heard:
                    print(f"  [heard] {heard}")
                    heard_so_far = (heard_so_far + " " + heard).strip()
                    if phrase_match(expected_text, heard_so_far):
                        return
            except self.sr.RequestError as exc:
                print(f"[voice] recognition service error ({exc}); falling back to typed cue.")
                input(f"{ANSI['gray']}{prompt}{ANSI['reset']} ")
                return
            except KeyboardInterrupt:
                input(f"\n{ANSI['gray']}[operator] press Enter to confirm the line was said: {ANSI['reset']}")
                return


# --------------------------------------------------------------------------- hub_dashboard client

class HubClient:
    """Only used for OVERRIDE (POST /api/show/stop). The IGNITE side of this
    — POST /api/show/start — deliberately lives in main.py instead, run as
    its own process (see fire_main_py below), matching the deck's own
    "What fires: main.py" note."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def stop_show(self) -> bool:
        url = self.base_url + "/api/show/stop"
        try:
            req = urllib.request.Request(url, data=b"{}", method="POST",
                                          headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
            return True
        except Exception as exc:
            print(f"[hub] {url} unreachable ({exc}) — continuing in narration-only mode.")
            return False


def fire_main_py(hub_url: str) -> None:
    """Spawns main.py as its own process once IGNITE is confirmed — it
    signals hub_dashboard to start the robot show. Kept as a separate
    script/process (rather than an inline call here) so it matches the
    deck's own ignite chip ("What fires: main.py · all units") and can be
    run and tested on its own."""
    script = ROOT / "main.py"
    if not script.exists():
        print(f"[hub] {script.name} not found next to Dialogue.py; skipping show trigger.")
        return
    try:
        subprocess.run([sys.executable, str(script), "--hub-url", hub_url], timeout=15)
    except Exception as exc:
        print(f"[hub] failed to run {script.name} ({exc}).")


# --------------------------------------------------------------------------- console rendering

def print_heading(title: str, subtitle: str | None = None) -> None:
    bar = "=" * 60
    print(f"\n{ANSI['bold']}{ANSI['cyan']}{bar}{ANSI['reset']}")
    print(f"{ANSI['bold']}{title}{ANSI['reset']}")
    if subtitle:
        print(f"{ANSI['gray']}{subtitle}{ANSI['reset']}")
    print(f"{ANSI['bold']}{ANSI['cyan']}{bar}{ANSI['reset']}")


def print_screen(text: str, color: str | None = None) -> None:
    color = color or ANSI["cyan"]
    print(f"  {ANSI['gray']}+{'-' * 40}+{ANSI['reset']}")
    for line in text.split("\n"):
        print(f"  {color}{line}{ANSI['reset']}")
    print(f"  {ANSI['gray']}+{'-' * 40}+{ANSI['reset']}")


def print_terminal(lines: list[dict]) -> None:
    for entry in lines:
        time.sleep(0.4)
        if "comment" in entry:
            print(f"  {ANSI['gray']}{entry['comment']}{ANSI['reset']}")
        elif "cmd" in entry:
            print(f"  {ANSI['cyan']}>>> {entry['cmd']}{ANSI['reset']}")
        elif "out" in entry:
            print(f"  {entry['out']}")


def print_banner(cover: dict) -> None:
    print_heading(f"{cover['title']} {cover['title_accent']}", cover.get("subtitle"))
    print(render_markup(cover.get("description", "")))
    print()
    for m in cover.get("meta", []):
        print(f"  {m['label']}: {m['value']}")


# --------------------------------------------------------------------------- show sections
#
# Everything below runs as a live conversation: a "student" line means
# VoiceListener actively listens on the mic until the student says
# (approximately) that line, then execution continues immediately — there is
# no operator keypress anywhere in this file. Stage directions ("scene",
# "screen") and narration rows have no one to listen for, so they print and
# move on with just enough of a pause to be readable/watchable.

def run_preshow(preshow: dict, live: dict, voice: Voice, listener: VoiceListener, ignite_keyword: str) -> None:
    print_heading(preshow["title"], preshow.get("subtitle"))
    for item in preshow["script"]:
        kind = item.get("type")
        if kind == "scene":
            print(f"  {ANSI['dim']}{item['text']}{ANSI['reset']}")
            time.sleep(1.5)
        elif kind == "screen":
            print_screen(item["text"])
            time.sleep(1.5)
        elif kind == "line":
            speaker = item.get("speaker")
            label = item.get("speaker_label", speaker)
            text = fill_placeholders(item.get("text", ""), live)
            cue = f"  [cue {item['cue']}]" if item.get("cue") else ""
            print(f"\n{ANSI['bold']}{label}{ANSI['reset']}{cue}  ({item.get('time', '')})")
            print(render_markup(text))
            if item.get("note"):
                print(f"  {ANSI['gray']}note: {item['note']}{ANSI['reset']}")
            if speaker == "chatbot":
                voice.say(text)
            elif ignite_keyword and ignite_keyword.upper() in text.upper():
                # The one line where we need the exact launch keyword, not a fuzzy match.
                listener.wait_for_keyword(
                    ignite_keyword, prompt=f'[operator] Press Enter once "{ignite_keyword}" is heard:'
                )
            else:
                listener.wait_for_line(text, prompt="[operator] Press Enter once the student has said this line:")


def run_ignite(ignite: dict, hub_url: str, voice: Voice) -> None:
    """IGNITE has already been confirmed inside run_preshow by the time this
    runs — this just replays the deck's reprise beat, fires main.py, and has
    the chatbot answer."""
    print_heading(ignite["eyebrow"], None)
    print(render_markup(ignite.get("stage_note", "")))
    for line in ignite["lines"]:
        text = line["text"]
        if line.get("style") == "parenthetical":
            print(f"  {ANSI['dim']}{text}{ANSI['reset']}")
        else:
            print(render_markup(text))
        time.sleep(1.2)
    print()
    for chip in ignite.get("chips", []):
        print(f"  {chip['label']}: {chip['value']}")

    print(f"\n{ANSI['cyan']}> KEYWORD CONFIRMED{ANSI['reset']}")
    fire_main_py(hub_url)

    chatbot_line = find_meta_value(ignite.get("chips", []), "Chatbot")
    if chatbot_line:
        text = chatbot_line.strip('"')
        print(render_markup(text))
        voice.say(text)


def run_flow_rise(flow: dict) -> None:
    """Prints the rise-phase narration for the operator's own reference —
    actual pacing for this beat now comes from the rise-phase video (see
    play_rise_video), since the video is the real visual for it, not these
    rows' own on-air durations."""
    print_heading(flow["title"], None)
    for row in flow["rows"]:
        if row.get("phase") != "rise":
            continue
        print(f"\n{ANSI['bold']}{row['time']} — {row['title']}{ANSI['reset']}")
        print(render_markup(row.get("desc", "")))
        if row.get("flag"):
            print(f"  {ANSI['amber']}flag: {row['flag']}{ANSI['reset']}")


def play_video_and_wait(screen: ChatbotScreen, video_path: Path | None, speed: float, label: str) -> None:
    """Plays a video full-screen on the chatbot screen and blocks until it
    ends — used for both the rise-phase video (cue: move on to the system
    going rogue) and the rogue-phase video (cue: hold on the red screen and
    wait for OVERRIDE). Falls back to a short fixed pause if no video is
    configured or found, so the show can still proceed on a machine without
    the file."""
    if not video_path or not video_path.exists():
        print(f"[video] no {label} video found ({video_path}); continuing without it.")
        time.sleep(3.0)
        return
    print(f"\n{ANSI['amber']}> Playing {label} video ({video_path.name})...{ANSI['reset']}")
    screen.play_video(video_path, speed=speed)
    print(f"{ANSI['amber']}> Video finished.{ANSI['reset']}")


def run_rogue_danger(danger: dict, voice: Voice, screen: ChatbotScreen) -> None:
    """The system going rogue is unprompted by design (deck note: "Operator
    F4 — fires without a prompt cue. Feels spontaneous.") — so this fires
    automatically the instant the rise-phase video ends. The "taking over"
    line is spoken as soon as that item is reached, not deferred until the
    whole section has printed — it used to wait through every other item's
    own pacing first, which read as a multi-second lag after the video."""
    print_heading(danger["label"], None)
    items = danger["items"]
    unprompted_idx = next(
        (i for i, it in enumerate(items) if "unprompted" in it.get("title", "").lower()), None
    )
    for i, item in enumerate(items):
        print(f"\n{item.get('icon', '')} {ANSI['bold']}{item['title']}{ANSI['reset']}")
        if item.get("body"):
            print(render_markup(item["body"]))
        if item.get("screen"):
            print_screen("\n".join(item["screen"]), color=ANSI["amber"])
        if item.get("note"):
            print(f"  {ANSI['gray']}note: {item['note']}{ANSI['reset']}")
        if i == unprompted_idx:
            # Takeover moment: wipe the screen's history and flip it red, so
            # this line reads as the system seizing the display, not just
            # another line appended to the same green log.
            screen.clear()
            screen.set_theme("red")
            voice.say(item.get("body"))
        elif i < len(items) - 1:
            time.sleep(0.3)


def run_override(override: dict, hub: HubClient, override_keyword: str, screen: ChatbotScreen) -> None:
    """The story has the student physically return to the terminal and type
    — so unlike every other cue in this file, OVERRIDE is typed here, not
    spoken. Blocks on real terminal input() until the command is entered."""
    print_heading(override["label"], None)
    print(f"{ANSI['amber']}> AWAITING OVERRIDE COMMAND ON TERMINAL...{ANSI['reset']}")
    while True:
        try:
            typed = input(f"{ANSI['gray']}${ANSI['reset']} ")
        except EOFError:
            typed = override_keyword
        if override_keyword.upper() in typed.strip().upper():
            break
        print(f"  {ANSI['gray']}(unrecognized command — type {override_keyword} to confirm manual override){ANSI['reset']}")
    print(f"{ANSI['green']}> OVERRIDE CONFIRMED{ANSI['reset']}")
    hub.stop_show()
    # Manual control restored — the screen goes back to green, fresh.
    screen.clear()
    screen.set_theme("green")

    for item in override["items"]:
        if item.get("type") == "terminal":
            print_terminal(item["lines"])
            continue
        print(f"\n{item.get('icon', '')} {ANSI['bold']}{item['title']}{ANSI['reset']}")
        if item.get("body"):
            print(render_markup(item["body"]))
        if item.get("screen_green"):
            print_screen("\n".join(item["screen_green"]), color=ANSI["green"])
        time.sleep(1.5)


def run_resolution(resolution: dict, voice: Voice, listener: VoiceListener) -> None:
    print_heading(resolution["eyebrow"], resolution["title"])
    for turn in resolution["convo"]:
        label = turn.get("speaker_label", turn.get("speaker"))
        text = turn["text"]
        print(f"\n{ANSI['bold']}{label}{ANSI['reset']}")
        print(render_markup(text))
        if turn.get("note"):
            print(f"  {ANSI['gray']}note: {turn['note']}{ANSI['reset']}")
        if turn.get("speaker") == "chatbot":
            voice.say(text)
        else:
            listener.wait_for_line(text, prompt="[operator] Press Enter once the student has finished:")

    theme = resolution["theme"]
    print()
    print(render_markup(theme.get("quote", "")))
    for p in theme.get("paragraphs", []):
        print()
        print(render_markup(p))
    if theme.get("footnote"):
        print(f"\n{ANSI['gray']}{theme['footnote']}{ANSI['reset']}")
    if theme.get("tags"):
        print("\n  " + "  ".join(f"[{t['label']}]" for t in theme["tags"]))


def run_close(credits: dict | None, close: dict) -> None:
    if credits:
        print_heading(credits.get("eyebrow", ""), credits.get("title"))
        if credits.get("subtitle"):
            print(f"  {ANSI['amber']}{credits['subtitle']}{ANSI['reset']}")
        for col in credits.get("columns", []):
            print(f"\n{col.get('icon', '')} {ANSI['bold']}{col['label']}{ANSI['reset']}")
            for it in col.get("items", []):
                print(f"  - {it}")

    print_heading(close["title"], f"{close.get('title_accent', '')} {close.get('title_tail', '')}".strip())
    for chip in close.get("chips", []):
        print(f"  {chip['label']}: {chip['value']}")


# --------------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description="ITE College West Drone & Robot Hub — show host chatbot")
    parser.add_argument("--hub-url", default=os.environ.get("HUB_URL", "http://localhost:5050"))
    parser.add_argument("--content", default=None, help="path to content.json (default: ../robot-revolution/content.json)")
    parser.add_argument("--speed", type=float, default=1.0,
                         help="playback speed multiplier for the rise/rogue videos (>1 = faster; for rehearsal)")
    parser.add_argument("--no-screen", action="store_true", help="skip the Matrix-style chatbot browser screen")
    parser.add_argument("--video", default=None,
                         help="path to the rise-phase video (default: ../DroneHub_Video.mp4, or config.yaml's rise_video)")
    parser.add_argument("--rogue-video", default=None,
                         help="path to the rogue-phase video (default: ../DH_Asset6_RobotRevolution.mp4, "
                              "or config.yaml's rogue_video)")
    args = parser.parse_args()

    screen = ChatbotScreen(enabled=not args.no_screen)
    try:
        content = load_content(args.content)
        cfg = load_show_host_config()
        live = fetch_live_data(cfg)
        rise_video_path = resolve_video_path(args.video, cfg, "rise_video", DEFAULT_VIDEO)
        rogue_video_path = resolve_video_path(args.rogue_video, cfg, "rogue_video", DEFAULT_ROGUE_VIDEO)
        voice = Voice(screen)
        listener = VoiceListener()
        hub = HubClient(args.hub_url)

        ignite_keyword = content["ignite"].get("keyword", "IGNITE").rstrip(".")
        override_keyword = find_meta_value(content["cover"].get("meta", []), "Override keyword", "OVERRIDE")

        print_banner(content["cover"])
        run_preshow(content["preshow"], live, voice, listener, ignite_keyword)
        run_ignite(content["ignite"], args.hub_url, voice)
        run_flow_rise(content["flow"])
        play_video_and_wait(screen, rise_video_path, args.speed, "rise-phase")
        run_rogue_danger(content["rogue"]["danger"], voice, screen)
        # Rogue-phase video plays on the same red, cleared screen the
        # "taking over" line just set up — once it ends, the show holds on
        # that red screen (nothing further happens on its own) until the
        # student types OVERRIDE, which is what run_override waits for next.
        play_video_and_wait(screen, rogue_video_path, args.speed, "rogue-phase")
        run_override(content["rogue"]["override"], hub, override_keyword, screen)
        run_resolution(content["resolution"], voice, listener)
        run_close(content.get("credits"), content["close"])
        print(f"\n{ANSI['cyan']}{ANSI['bold']}END OF SHOW{ANSI['reset']}\n")
    finally:
        screen.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[operator] Show host interrupted.")
        sys.exit(1)
