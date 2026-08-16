import json
import sys
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from notify import send_discord_message
from sheets import append_lottery_row

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

SEPARATOR = "ー" * 18


def _suppress_embed(url: str) -> str:
    """URLを <...> で囲み、Discord側のリンクプレビュー(埋め込みカード)を抑制する。"""
    return f"<{url}>"


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


def fetch_html_playwright(url: str) -> str | None:
    try:
        browser = _get_browser()
        page = browser.new_page(user_agent=HEADERS["User-Agent"], locale="ja-JP")
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        html = page.content()
        page.close()
        return html
    except Exception as exc:
        print(f"[WARN] headless browser failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        print(
            f"[WARN] plain request failed for {url} ({exc}); retrying with headless browser",
            file=sys.stderr,
        )
        return fetch_html_playwright(url)


def fetch_text(url: str) -> str | None:
    html = fetch_html(url)
    if html is None:
        return None
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def check_keyword_target(target: dict, state: dict) -> bool:
    """既存の「単一ページのキーワード出現/消失」監視。戻り値は state が変化したか。"""
    name = target["name"]
    url = target["url"]
    keyword = target["keyword"]
    alert_on = target["alert_on"]
    bot_name = target.get("bot_name")

    text = fetch_text(url)
    if text is None:
        return False

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
                f"🔔 **{name}**\n条件(「{keyword}」が{alert_on}) が成立しました。\n"
                f"{_suppress_embed(url)}\n{SEPARATOR}",
                username=bot_name,
            )

    if previous != present:
        state[name] = present
        return True

    print(f"[OK] {name}: no change (present={present})")
    return False


def _parse_pokeca_navi(soup: BeautifulSoup, url: str, area_filter: str | None) -> dict[str, dict[str, str]]:
    """pokeca-navi.jp形式: 受付中カードに .lottery-card-open クラスが付く。エリアは日本語表記。"""
    entries: dict[str, dict[str, str]] = {}
    for card in soup.select(".lottery-card-open"):
        shop_el = card.select_one(".lottery-card__shop")
        product_el = card.select_one(".lottery-card__product")
        if not shop_el or not product_el:
            continue
        area_el = card.select_one(".lottery-card__area-pill")
        area = area_el.get_text(strip=True) if area_el else ""
        # "全国"(郵送などで全国どこからでも応募できる抽選)は area_filter の値に関わらず常に含める
        if area_filter and area_filter not in area and area != "全国":
            continue
        shop = shop_el.get_text(strip=True)
        product = product_el.get_text(strip=True)
        deadline_el = card.select_one(".lottery-card__deadline-urgent")
        method_el = card.select_one(".lottery-card__method-pill")
        summary_el = card.select_one(".lottery-card__application-summary-text")
        link_el = card.select_one(".lottery-card__apply-button")
        entries[f"{shop} / {product}"] = {
            "shop": shop,
            "product": product,
            "area": area,
            "deadline": deadline_el.get_text(strip=True) if deadline_el else "",
            "method": method_el.get_text(strip=True) if method_el else "",
            "summary": summary_el.get_text(strip=True) if summary_el else "",
            "link": link_el["href"] if link_el and link_el.has_attr("href") else url,
        }
    return entries


def _parse_cardchusen(soup: BeautifulSoup, url: str, area_filter: str | None) -> dict[str, dict[str, str]]:
    """cardchusen.com形式: article.board-card 単位。エリアは data-area 属性にローマ字の県名が
    スペース区切りで入る(店頭のみの抽選は空のことが多い)。area_filter はローマ字("aichi"等)で指定する。"""
    entries: dict[str, dict[str, str]] = {}
    for card in soup.select("article.board-card"):
        area = card.get("data-area", "")
        if area_filter and area_filter not in area.split():
            continue
        store_el = card.select_one(".board-card__store")
        if not store_el:
            continue
        shop = store_el.get_text(strip=True)
        product = store_el.get("title", "") or "(商品名不明)"
        due_el = card.select_one(".board-card__due")
        how_el = card.select_one(".board-card__how")
        cta_el = card.select_one(".board-card__cta")
        entry_id = card.get("id") or f"{shop} / {product}"
        entries[entry_id] = {
            "shop": shop,
            "product": product,
            "area": area,
            "deadline": due_el.get_text(strip=True).removeprefix("締切").strip() if due_el else "",
            "method": how_el.get("data-method-label", "") if how_el else "",
            "summary": how_el.get("data-method-note", "") if how_el else "",
            "link": cta_el["href"] if cta_el and cta_el.has_attr("href") else url,
        }
    return entries


PARSERS = {
    "pokeca_navi": _parse_pokeca_navi,
    "cardchusen": _parse_cardchusen,
}


def check_lottery_list_target(target: dict, state: dict) -> bool:
    """抽選まとめサイトの「受付中一覧」ページを監視し、新しく追加された抽選エントリーごとに
    通知する。対応サイトごとにHTML構造が違うため PARSERS で切り替える。戻り値は state が変化したか。"""
    name = target["name"]
    url = target["url"]
    area_filter = target.get("area_filter")
    game_label = target.get("game_label", "TCG")
    bot_name = target.get("bot_name")
    parser = PARSERS[target.get("parser", "pokeca_navi")]

    html = fetch_html(url)
    if html is None:
        return False

    soup = BeautifulSoup(html, "html.parser")
    entries = parser(soup, url, area_filter)

    exclude_keywords = target.get("exclude_keywords") or []
    if exclude_keywords:
        entries = {
            entry_id: info
            for entry_id, info in entries.items()
            if not any(kw in info["product"] or kw in info["shop"] for kw in exclude_keywords)
        }

    state_key = f"__list__{name}"
    previous_ids = set(state.get(state_key) or [])
    current_ids = set(entries.keys())

    if state_key not in state:
        print(f"[INIT] {name}: baseline recorded ({len(current_ids)} open lotteries)")
    else:
        for entry_id in sorted(current_ids - previous_ids):
            info = entries[entry_id]
            print(f"[ALERT] {name}: new lottery - {info['shop']} / {info['product']}")
            send_discord_message(
                f"🎴【{game_label}】{info['product']} の抽選\n"
                f"店舗: {info['shop']}\n"
                f"抽選期限: {info['deadline'] or '不明'}\n"
                f"応募方法: {info['method'] or '不明'}\n"
                f"詳細: {info['summary'] or 'なし'}\n"
                f"{_suppress_embed(info['link'])}\n{SEPARATOR}",
                username=bot_name,
            )
            memo = info["link"]
            if info["deadline"]:
                memo = f"締切: {info['deadline']} / {memo}"
            try:
                append_lottery_row(game_label, info["product"], info["shop"], memo)
            except Exception as exc:
                print(f"[WARN] failed to append to spreadsheet: {exc}", file=sys.stderr)

    if previous_ids != current_ids:
        print(f"[OK] {name}: {len(current_ids)} open lotteries ({len(current_ids - previous_ids)} new, {len(previous_ids - current_ids)} closed/removed)")
        state[state_key] = sorted(current_ids)
        return True

    print(f"[OK] {name}: no change ({len(current_ids)} open lotteries)")
    return False


def main() -> None:
    targets = load_targets()
    state = load_state()
    changed = False

    try:
        for target in targets:
            target_type = target.get("type", "keyword")
            if target_type == "lottery_list":
                if check_lottery_list_target(target, state):
                    changed = True
            else:
                if check_keyword_target(target, state):
                    changed = True
    finally:
        close_browser()

    if changed:
        save_state(state)
        print("state.json updated")
    else:
        print("no state change")


if __name__ == "__main__":
    main()
