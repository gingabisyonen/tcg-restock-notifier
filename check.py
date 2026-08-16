import json
import sys
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

from notify import send_discord_message

ROOT = Path(__file__).parent
TARGETS_FILE = ROOT / "targets.yaml"
STATE_FILE = ROOT / "state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def load_targets() -> list[dict]:
    data = yaml.safe_load(TARGETS_FILE.read_text(encoding="utf-8"))
    return data.get("targets") or []


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def fetch_text(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[WARN] failed to fetch {url}: {exc}", file=sys.stderr)
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def main() -> None:
    targets = load_targets()
    state = load_state()
    changed = False

    for target in targets:
        name = target["name"]
        url = target["url"]
        keyword = target["keyword"]
        alert_on = target["alert_on"]

        text = fetch_text(url)
        if text is None:
            continue

        present = keyword in text
        previous = state.get(name)

        if previous is not None:
            triggered = (alert_on == "appear" and not previous and present) or (
                alert_on == "disappear" and previous and not present
            )
            if triggered:
                print(f"[ALERT] {name}: {alert_on} condition met")
                send_discord_message(
                    f"🔔 **{name}**\n条件(「{keyword}」が{alert_on}) が成立しました。\n{url}"
                )

        if previous != present:
            state[name] = present
            changed = True
        else:
            print(f"[OK] {name}: no change (present={present})")

    if changed:
        save_state(state)
        print("state.json updated")
    else:
        print("no state change")


if __name__ == "__main__":
    main()
