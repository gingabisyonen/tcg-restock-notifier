import json
import os
import re
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1hG8mwRu4Df4gkZ-Th6F9MZBedCiRC-NR8V16wxOtOVs"
DATE_SHEET_NAME = "Date"
MASTER_SHEET_NAME = "Master"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

RESPONSIBLE_PERSON = "のり"

# ゲームラベル(Masterシート「種類」列の表記と一致させる) -> Masterシートの商品名リストの列番号(A=1)
# C列に「店舗」列を追加したため、ポケカ以降は1列ずつ右にずれている
MASTER_GAME_COLUMNS = {
    "ポケカ": 4,        # D列
    "ワンピース": 5,     # E列
    "ドラゴンボール": 6,  # F列
}

ANNOUNCE_DATE_PATTERN = re.compile(r"(?:当選発表|抽選結果|結果発表)\D{0,10}?(\d{1,2})月(\d{1,2})日")

# 商品名に含まれる型番(例: OP-17, ST01, FB01)を拾うためのパターン。
# 表記ゆれ(語順・括弧の種類違いなど)があっても型番さえ一致すれば同一商品とみなす。
PRODUCT_CODE_PATTERN = re.compile(r"[A-Z]{1,4}-?\d{2,3}[A-Z]?")


def _extract_product_code(name: str) -> str | None:
    match = PRODUCT_CODE_PATTERN.search(name.upper().replace(" ", ""))
    return match.group(0) if match else None

_client = None
_spreadsheet = None
_tried = False


def _get_spreadsheet():
    global _client, _spreadsheet, _tried
    if _tried:
        return _spreadsheet
    _tried = True

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        return None

    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    _client = gspread.authorize(creds)
    _spreadsheet = _client.open_by_key(SPREADSHEET_ID)
    return _spreadsheet


def _resolve_product_name(game: str, product: str) -> str:
    """Masterシートの商品名リスト(D/E/F列)と突き合わせる。
    1. 型番(OP-17など)が一致すれば表記ゆれがあっても同一商品とみなし、既存名を返す
    2. 型番がない/一致しない場合は部分一致で判定する
    3. どちらでも判断できない場合は既存名を推測せず、新規行として最下行に追加する"""
    spreadsheet = _get_spreadsheet()
    col = MASTER_GAME_COLUMNS.get(game)
    if spreadsheet is None or col is None:
        return product

    master = spreadsheet.worksheet(MASTER_SHEET_NAME)
    existing = master.col_values(col)[1:]  # 先頭行(見出し)を除く

    product_code = _extract_product_code(product)
    if product_code:
        for name in existing:
            if name and _extract_product_code(name) == product_code:
                return name

    for name in existing:
        if name and (name == product or name in product or product in name):
            return name

    master.update_cell(len(existing) + 2, col, product)
    return product


def _extract_announce_date(text: str) -> str:
    """説明文から「当選発表は8月26日」のような表記を探し、yyyy/mm/dd形式にして返す。
    見つからなければ空文字を返す(無理に埋めない)。"""
    if not text:
        return ""
    match = ANNOUNCE_DATE_PATTERN.search(text)
    if not match:
        return ""
    month, day = (int(g) for g in match.groups())
    year = date.today().year
    return f"{year}/{month:02d}/{day:02d}"


def append_lottery_row(game: str, product: str, shop: str, link: str, description: str = "") -> None:
    """新規抽選を検知した際にDateシートへ1行追記する。
    K列(当選通知方法)には分かっている範囲の説明文、L列(URL)には応募先URLを入れる。
    GOOGLE_SERVICE_ACCOUNT_JSON が未設定の場合は何もしない(Discord通知のみで動作継続)。"""
    spreadsheet = _get_spreadsheet()
    if spreadsheet is None:
        return

    resolved_product = _resolve_product_name(game, product)
    announce_date = _extract_announce_date(description)

    today = date.today()
    row = [
        today.year,
        today.month,
        today.day,
        RESPONSIBLE_PERSON,
        game,
        "告知",
        resolved_product,
        shop,
        "-",
        announce_date,
        description,
        link,
    ]
    spreadsheet.worksheet(DATE_SHEET_NAME).append_row(row, value_input_option="USER_ENTERED")
