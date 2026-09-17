# Show Host

The scripted chatbot that runs the student-facing conversation for the ITE College West Drone & Robot Hub show, then triggers the robot show itself.

Deliberately separate from [`../hub_dashboard/`](../hub_dashboard/README.md): this folder has its own `config.yaml`, `requirements.txt`, and (recommended) virtualenv, and never imports or shares state with `hub_dashboard`'s code. The only connections between the two are over HTTP — `main.py` calls `POST /api/show/start`, `Dialogue.py` calls `POST /api/show/stop`. That keeps either one free to change without breaking the other.

## What it does

Runs the scripted conversation from [`../robot-revolution/content.json`](../robot-revolution/content.json) — that file is the single source of truth for every line; `Dialogue.py` never hardcodes wording, so editing the deck's JSON is enough to change what the bot says.

It's a real listening conversation, not an operator-paced slideshow — there is no Enter key anywhere in the normal flow:

- **It listens for the student.** For every student line in the transcript, `Dialogue.py` listens on the microphone (`SpeechRecognition`) until it hears the student actually say (approximately) that line, then immediately continues — the way a real scene partner would.
- **It answers automatically.** As soon as the student's cue is heard, the chatbot's next line is filled in with live data — `[DAY]` / `[DATE]` / `[TIME]` / `[WEATHER]` / `[TEMP]` / `[ROBOTICS NEWS HEADLINE]` from free, keyless APIs ([Open-Meteo](https://open-meteo.com/) for weather, coordinates in `config.yaml`; Google News RSS for the headline) — spoken aloud and shown on the chatbot screen (see below).
- **It pauses where the script says to.** A blank line (`\n\n`, content.json's own paragraph-gap convention) inside a chatbot line becomes an actual spoken pause — e.g. a beat after reporting the weather, before the next thought — not just a visual line break.
- **IGNITE spawns `main.py`, then plays the rise-phase video.** The moment the student says the IGNITE keyword, `Dialogue.py` runs [`main.py`](main.py) as its own process — matching the deck's own ignite chip, "What fires: main.py · all units" — which signals hub_dashboard to start the robot show (`POST /api/show/start`). It then plays the rise-phase video full-screen on the chatbot screen (default `../DroneHub_Video.mp4`; see config below) and blocks until it actually finishes.
- **The rogue turn is autonomous.** As soon as the video ends, the chatbot declares it's "taking over" — the screen wipes clean, flips red, menacing background music starts, and the line is spoken the instant that happens, with no cue needed and no lag (see The chatbot screen, below).
- **A second video plays on the red screen.** Right after that line, `Dialogue.py` plays a rogue-phase video (default `../DH_Asset6_RobotRevolution.mp4`, currently a placeholder — see config below) full-screen, same as the rise-phase one. Once it ends, the show holds on the red screen — nothing happens on its own from here except the background music looping.
- **OVERRIDE is typed, or given on-screen.** Matching the story (the student physically returns to the terminal), `Dialogue.py` waits for the OVERRIDE command to be *typed* into this terminal window — or given via the pulsing **OVERRIDE** control on the chatbot screen itself (see below), for whichever one actually has focus. Once confirmed, it calls `POST /api/show/stop`, mirrors the same simulated command lines onto the chatbot screen that print in this terminal ("showing that something is happening" to the audience too), the music stops, and the screen reverts to green.

## The chatbot screen

A separate black-background browser page shows exactly what the chatbot is saying, styled to read as a machine terminal rather than a person. It's meant to be the audience-facing display (second monitor / projector); the regular terminal window stays the operator's own console with the full transcript, stage directions, and notes.

The page has three parts, all on the same "digital rain" background:

- **Centre: the chatbot's own answers** — a terminal-styled window (title bar with dots, `chatbot@dronehub-hub:~#`), typed out one character at a time, exactly what the chatbot is saying. This is the main event, same as before. Every sentence gets its own line (not just each paragraph) — e.g. "Current conditions: drizzle, 31°C." always breaks onto its own line, distinct from the sentence before and after it.
- **Left: what the mic hears.** A second, smaller terminal panel (`mic@dronehub-hub:~#`) shows the live speech-to-text transcript of what the system heard the student say — the same text that prints as `[heard] ...` in the operator's own console, now also visible to the audience, kept entirely separate from the chatbot's own answers in the centre panel.
- **Right third: a humanoid head.** A Matrix-style digital-rain skull, rendered with Three.js (`js/skull/skullApp.js`, built in a separate session — `screen.html` just mounts it into `#headContainer` and drives its small public API: `setSpeaking(bool)` and `setTheme(hex)`, both fed straight from the same `/state` poll everything else here uses). It assembles/dissolves and reacts to `speaking`; real TTS audio never reaches this browser (it's produced entirely server-side), so there's no per-phoneme data to sync to — its jaw motion while speaking is a heuristic approximation, not lip-read-accurate visemes. `Dialogue.py`'s screen server serves those files itself (`/js/...`, `/vendor/...`) — no separate server needed.
- **Bottom-center (red phase only): the OVERRIDE code entry.** Not a button — a movie-style "key in the code" prompt. See below.

It's a real webpage ([`screen.html`](screen.html)), not a native GUI window: `Dialogue.py` runs a tiny local web server (standard-library only, no extra dependency) and opens it automatically. This was deliberately built as a browser page rather than a Tkinter window — Tkinter is optional even in a standard Python install and turned out to be missing on the actual show laptop, which silently dropped the screen entirely. Every machine has a browser, so this has no equivalent missing-dependency failure mode.

- **Opens full-screen automatically.** `Dialogue.py` looks for Chrome/Edge in several ways (`PATH`, common install locations, and — on Windows — the registry) and launches whichever it finds in `--kiosk` mode: a true borderless full-screen window, not just a maximized one. It also prints exactly what happened (`kiosk` / a plain `window` / `none`) so it's obvious from the terminal whether it's genuinely full-screen. **Belt and braces:** the page itself also shows a large "CLICK TO ACTIVATE" prompt for a couple of seconds on load — clicking it calls the browser's real full-screen API, which works no matter how (or whether) the auto-launch succeeded, and also "unlocks" audio autoplay (background music) for the rest of the page's life in browsers that require a user gesture first. It auto-dismisses on its own if nothing clicks it, so it never sits in the way once the show is already full-screen.
- **The typewriter speed tracks the voice.** Text reveals at a pace computed from the same words-per-minute setting the TTS engine uses (see Voice, below), so the words finish appearing close to when they finish being spoken, rather than at a fixed, unrelated typing speed.
- **Turns red for the takeover, with background music.** The moment the chatbot's "taking over" line fires, the screen wipes its history and recolours everything — the digital rain, both panels, the head, the glow — from green to red, and menacing background music starts looping (see Rogue-phase music, below). Both revert — screen to green, music stopped — the instant OVERRIDE is confirmed.
- **Manual override lives here too.** If the mic doesn't pick up a line, press **SPACE** (or **Enter**) anywhere on this screen, or tap the small "SPACE = confirm cue" hint in the bottom-right corner — either one tells `Dialogue.py` to treat the current cue as confirmed and move on. This is the primary override for ordinary cues: for most of the show this screen (not the terminal) is what actually has keyboard focus, so it needed its own way to unblock a cue rather than relying on Ctrl+C reaching a window that isn't focused.
- **OVERRIDE itself is a code you key in, not a button.** It only appears once the screen is red: a prompt reading `SYSTEM OVERRIDE — ENTER CODE` with a blinking input line, auto-focused the moment the screen turns red — matching the "type the secret code to stop it" beat from the movies this is riffing on, rather than a single click. The student types the actual OVERRIDE keyword and presses Enter; `run_override` validates it exactly the same way it validates the terminal path (so this isn't a bare "any click confirms" shortcut), and a wrong code flashes `ACCESS DENIED` under the field rather than silently doing nothing. Whichever comes first — this or the student typing OVERRIDE at the terminal — confirms it.
- **Only one window is ever "live".** If a second Chatbot Screen tab/window ends up open at the same time (e.g. one left over from a rehearsal), same-origin tabs negotiate automatically over `BroadcastChannel` — only the most recently opened one plays audio, music, or types text; the rest go silent and dim, rather than both reacting to the same show and producing audible double audio.
- **Also plays both videos**, full-screen — see below.

Pass `--no-screen` to skip it (text-only environments, or a quick rehearsal in one window). If the local server can't start (e.g. port 8765 already in use) or no browser can be opened automatically, `Dialogue.py` prints exactly what happened and carries on without it — the show is never blocked on the screen. If a browser doesn't open on its own, the printed URL (`http://127.0.0.1:8765/`) can be opened by hand at any point, including mid-show.

## Rogue-phase music

Loops for the whole red "system has taken over" phase — starts the instant the screen turns red, stops the instant OVERRIDE is confirmed. No royalty-free or licensed "menacing theme" ships with this repo (an actual movie theme is copyrighted — bring your own licensed file), so out of the box the chatbot screen synthesizes an ominous drone with the Web Audio API instead, entirely in the browser, no file needed. Drop a real track in and set `rogue_music:` in `config.yaml` to it to use that instead — see the comment there.

## The two videos

Both play full-screen on the chatbot screen and **block until they actually finish** — the timing of the next beat follows the video's real length rather than a fixed estimate, using the same mechanism for each:

| | Rise-phase video | Rogue-phase video |
|---|---|---|
| Fires | Once IGNITE fires and `main.py` has signalled hub_dashboard | Immediately after the chatbot speaks the "taking over" line |
| Then | Moves on to the rogue "taking over" line | Holds on the red screen — nothing happens on its own until OVERRIDE |
| Default path | `../DroneHub_Video.mp4` | `../DH_Asset6_RobotRevolution.mp4` *(placeholder — swap for the real cut later)* |
| Config override | `rise_video:` in `config.yaml` | `rogue_video:` in `config.yaml` |
| CLI override | `--video /path/to/file.mp4` | `--rogue-video /path/to/file.mp4` |

Both resolve relative paths from this `show_host/` folder.

- **Local files, not YouTube, by design.** A local file plays instantly, works with no internet connection (a real risk at a venue), and its `ended` event fires the exact moment it's actually done — nothing to configure or that can silently fail. YouTube would mean depending on the venue's Wi-Fi during the most technically demanding beats of the show, plus autoplay policies and ads to work around, for videos the app doesn't even need to be told the length of. If a file ever needs to be swapped out without redistributing it, self-hosting on a private, direct-file-link service (not a YouTube embed) would keep the same reliability — happy to wire that up if useful, but it isn't necessary.
- If a video is missing or the screen is disabled/unavailable, `Dialogue.py` prints why and waits a short fixed pause instead, so the show still runs without it.
- `--speed` (see Options, below) sets both videos' `playbackRate` in the browser — handy for a fast rehearsal.

## Voice

- **macOS**: uses the system's own `say` command with a robotic voice — **Zarvox** if installed (a low, deliberately synthetic voice; ships with macOS, no download needed), falling back to **Trinoids**, then an ordinary male system voice. Deliberately *not* `pyttsx3` here: spinning up more than one `pyttsx3` engine in the same process on macOS can trigger a hard native crash (confirmed while building this), and reusing a single engine for a whole show is known to silently stop producing audio after a number of calls — `say` runs each line as its own short-lived process, sidestepping both.
- **Windows/Linux**: uses `pyttsx3` (SAPI5 / espeak), also preferring a robotic-sounding voice by name if one is installed.
- Rate is 165 wpm (`SPEECH_RATE_WPM` in `Dialogue.py`) — a little brisker than a fully natural pace, while still short of the ~200wpm default, so it stays deliberate rather than rushed.
- A couple of words get their spelling adjusted for speech only (never for what's shown on screen) where TTS engines default to the wrong reading — e.g. "live" (the verb, as in "live in a screen", not the adjective as in "live broadcast") is respelled "liv" just for the audio. See `PRONUNCIATION_FIXUPS` in `Dialogue.py` to add more.

## Fallback behaviour

Each live feature degrades on its own if its package or hardware isn't available, so the whole script still runs (as a readable text transcript, operator-paced) on any laptop with no setup:

| Feature | If unavailable, falls back to |
|---|---|
| Speech recognition (mic) | Operator presses **Enter** to confirm each student line/IGNITE was heard |
| Voice not detected mid-show | Operator presses **SPACE** on the chatbot screen itself (or any key at the terminal, if it happens to have focus) to manually confirm the cue and move on — see [The chatbot screen](#the-chatbot-screen) |
| Text-to-speech (speaker) | Chatbot lines are printed and shown on the chatbot screen only, not spoken — still paced roughly like real speech |
| Chatbot screen (local server / browser) | Chatbot lines show in the terminal only, same as before this feature existed |
| Either video missing/screen disabled | Prints why, waits a short fixed pause, then continues to the next beat |
| `hub_dashboard` not running | `main.py` and OVERRIDE's stop-show call each print `unreachable — continuing in narration-only mode` and carry on |
| `../robot-revolution/content.json` missing | Fails fast with the file-not-found error — this file is required |

## Running — double-click to start the show

For show day: double-click **[`RUN_mac.command`](RUN_mac.command)** on macOS or **[`RUN.bat`](RUN.bat)** on Windows. Each one, the same way as `hub_dashboard`'s own launchers:

1. Creates a `venv/` next to itself and installs [`requirements.txt`](requirements.txt) into it — **first run only**; later launches reuse it and start in a couple of seconds.
2. Runs `Dialogue.py` — the show begins immediately: the cover banner prints, then the pre-show conversation starts listening for the student's first line.

Start `hub_dashboard`'s own launcher first, in its own window, if you want IGNITE/OVERRIDE to actually reach the robots — `Dialogue.py` still runs standalone without it (narration-only; see the fallback table above), so it's fine to rehearse the conversation with just this one window open.

macOS only, before the first double-click (otherwise `pip install` fails partway through and the window says so):

```bash
brew install portaudio   # for PyAudio (microphone access)
```

(`pyobjc`, needed for `pyttsx3`'s speech voice, installs on its own from `requirements.txt`.)

## Running from a terminal

Equivalent to the launcher, if you'd rather drive it by hand:

```bash
cd show_host
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python Dialogue.py
```

Options:

```bash
python Dialogue.py --hub-url http://localhost:5050   # default; override if the dashboard runs elsewhere
python Dialogue.py --content /path/to/content.json   # default: ../robot-revolution/content.json
python Dialogue.py --video /path/to/file.mp4         # default: ../DroneHub_Video.mp4 (or config.yaml's rise_video)
python Dialogue.py --rogue-video /path/to/file.mp4   # default: ../DH_Asset6_RobotRevolution.mp4 (or config.yaml's rogue_video)
python Dialogue.py --speed 5                         # rehearsal: plays both videos at 5x speed
python Dialogue.py --no-screen                       # skip the chatbot screen (and both videos with it)
```

`main.py` takes the same `--hub-url` flag; `Dialogue.py` passes its own value through automatically when it spawns it, so you don't need to set it twice.

## Files

```
Dialogue.py        The chatbot: live data, TTS, listens for student cues, spawns main.py on IGNITE, calls hub_dashboard to stop on OVERRIDE
main.py            Fired by Dialogue.py once IGNITE is heard — signals hub_dashboard (POST /api/show/start) then exits
screen.html        The chatbot screen's page — served locally by Dialogue.py, opened in your browser automatically
js/skull/          The humanoid head: a Three.js digital-rain skull (separate build), mounted by screen.html
vendor/three/      Three.js itself + the addons the head build needs — vendored, no npm install required
config.yaml        Venue lat/lon/timezone for the weather pull, both video paths, and optional rogue_music — this folder's own config
requirements.txt   This folder's own dependencies
RUN_mac.command     Double-click launcher (macOS): sets up venv on first run, then starts the show
RUN.bat             Double-click launcher (Windows): sets up venv on first run, then starts the show
```
