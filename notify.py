import os
import requests

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


def send_discord_message(content: str) -> None:
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set")
    resp = requests.post(WEBHOOK_URL, json={"content": content}, timeout=15)
    resp.raise_for_status()
