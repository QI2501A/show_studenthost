"""main.py — fired once the student says the IGNITE keyword.

Dialogue.py spawns this as its own process the moment IGNITE is confirmed
(see fire_main_py() in Dialogue.py) rather than signalling the show start
inline, matching the deck's own ignite chip: "What fires: main.py · all
units". Its only job is to tell hub_dashboard to start the robot show —
POST /api/show/start — then exit. hub_dashboard (app.py) owns everything
about *how* the show actually runs (which actions, which robots, timing);
this script only fires the starting gun.

  python main.py [--hub-url http://localhost:5050]
"""
from __future__ import annotations

import argparse
import sys
import urllib.request


def start_show(hub_url: str, timeout: float = 5.0) -> bool:
    url = hub_url.rstrip("/") + "/api/show/start"
    try:
        req = urllib.request.Request(url, data=b"{}", method="POST",
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
        print(f"IGNITE -> {url} ok: {body}")
        return True
    except Exception as exc:
        print(f"IGNITE -> {url} failed: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Signal hub_dashboard to start the robot show (fired on IGNITE).")
    parser.add_argument("--hub-url", default="http://localhost:5050")
    args = parser.parse_args()
    ok = start_show(args.hub_url)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
