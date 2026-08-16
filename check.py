import json
import sys
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

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


_playwright = None
_browser = None


def _get_browser():
    global _playwright, _browser
    if _browser is None:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch()
    return _browser


def close_browser() -> None:
    global _playwright, _browser
    if _browser is not None:
        _browser.close()
        _browser = None
    if _playwright is not None:
        _playwright.stop()
        _playwright = None


def fetch_text_playwright(url: str) -> str | None:
    try:
        browser = _get_browser()
        page = browser.new_page(user_agent=HEADERS["User-Agent"], locale="ja-JP")
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        html = page.content()
        page.close()
    except Exception as exc:
        print(f"[WARN] headless browser failed to fetch {url}: {exc}", file=sys.stderr)
        return None
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def fetch_text(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(
            f"[WARN] plain request failed for {url} ({exc}); retrying with headless browser",
            file=sys.stderr,
        )
        return fetch_text_playwright(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def main() -> None:
    targets = load_targets()
    state = load_state()
    changed = False

    try:
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

            if previous is None:
                print(f"[INIT] {name}: baseline recorded (present={present})")
            else:
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
    finally:
        close_browser()

    if changed:
        save_state(state)
        print("state.json updated")
    else:
        print("no state change")


if __name__ == "__main__":
    main()
