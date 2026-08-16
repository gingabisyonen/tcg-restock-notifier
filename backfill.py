"""一度だけ実行する保守用スクリプト。
現在受付中の抽選のうち、Dateシートにまだ記録されていないものをすべて
Discord通知+Dateシートへの記録で追いつかせる(state.json の新規/既存判定とは無関係に、
Dateシートの実際の記載内容と突き合わせる)。
実行後は backfill.yml とあわせて削除する想定。"""

from bs4 import BeautifulSoup

from check import PARSERS, close_browser, fetch_html, load_targets, SEPARATOR, _suppress_embed
from notify import send_discord_message
from sheets import DATE_SHEET_NAME, _get_spreadsheet, append_lottery_row


def _loosely_matches(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def get_existing_pairs() -> set[tuple[str, str]]:
    spreadsheet = _get_spreadsheet()
    if spreadsheet is None:
        return set()
    rows = spreadsheet.worksheet(DATE_SHEET_NAME).get_all_values()[1:]
    pairs = set()
    for row in rows:
        if len(row) >= 8:
            product = row[6].strip()
            shop = row[7].strip()
            if product and shop:
                pairs.add((shop, product))
    return pairs


def already_logged(shop: str, product: str, pairs: set[tuple[str, str]]) -> bool:
    return any(
        _loosely_matches(shop, existing_shop) and _loosely_matches(product, existing_product)
        for existing_shop, existing_product in pairs
    )


def main() -> None:
    targets = load_targets()
    pairs = get_existing_pairs()
    print(f"Dateシート既存件数(照合対象): {len(pairs)}")

    for target in targets:
        if target.get("type") != "lottery_list":
            continue

        name = target["name"]
        url = target["url"]
        area_filter = target.get("area_filter")
        game_label = target.get("game_label", "TCG")
        bot_name = target.get("bot_name")
        exclude_keywords = target.get("exclude_keywords") or []
        parser = PARSERS[target.get("parser", "pokeca_navi")]

        html = fetch_html(url)
        if html is None:
            print(f"[WARN] failed to fetch {url}")
            continue

        soup = BeautifulSoup(html, "html.parser")
        entries = parser(soup, url, area_filter)

        if exclude_keywords:
            entries = {
                entry_id: info
                for entry_id, info in entries.items()
                if not any(kw in info["product"] or kw in info["shop"] for kw in exclude_keywords)
            }

        for info in entries.values():
            if already_logged(info["shop"], info["product"], pairs):
                continue

            print(f"[BACKFILL] {name}: {info['shop']} / {info['product']}")
            send_discord_message(
                f"🎴【{game_label}】{info['product']} の抽選\n"
                f"店舗: {info['shop']}\n"
                f"抽選期限: {info['deadline'] or '不明'}\n"
                f"応募方法: {info['method'] or '不明'}\n"
                f"詳細: {info['summary'] or 'なし'}\n"
                f"{_suppress_embed(info['link'])}\n{SEPARATOR}",
                username=bot_name,
            )
            append_lottery_row(game_label, info["product"], info["shop"], info["link"], info["summary"])
            pairs.add((info["shop"], info["product"]))

    close_browser()


if __name__ == "__main__":
    main()
