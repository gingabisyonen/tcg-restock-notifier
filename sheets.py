import json
import os
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1hG8mwRu4Df4gkZ-Th6F9MZBedCiRC-NR8V16wxOtOVs"
SHEET_NAME = "Date"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_worksheet = None
_tried = False


def _get_worksheet():
    global _worksheet, _tried
    if _tried:
        return _worksheet
    _tried = True

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        return None

    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    _worksheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    return _worksheet


def append_lottery_row(game: str, product: str, shop: str, memo: str) -> None:
    """新規抽選を検知した日付・ゲーム・商品・店舗・メモをスプレッドシートに1行追記する。
    担当者/当落/支払い/抽選結果発表日は手入力用に空欄のままにする。
    GOOGLE_SERVICE_ACCOUNT_JSON が未設定の場合は何もしない(Discord通知のみで動作継続)。"""
    ws = _get_worksheet()
    if ws is None:
        return

    today = date.today()
    row = [today.year, today.month, today.day, "", game, "", product, shop, "", "", memo]
    ws.append_row(row, value_input_option="USER_ENTERED")
