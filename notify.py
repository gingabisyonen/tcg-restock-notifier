import os
import requests

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


def send_discord_message(content: str, username: str | None = None) -> None:
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set")
    payload = {"content": content}
    if username:
        payload["username"] = username
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()
