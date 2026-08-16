"""一度だけ実行する保守用スクリプト。
Masterシートに「店舗」列をC列として挿入し(ポケカ/ワンピース/ドラゴンボールは1列ずつ右へ)、
Dateシートの抽選先(H列)から重複を除いた一覧を書き込む。
実行後は master_shops.yml とあわせて削除する想定。"""

import json
import os

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1hG8mwRu4Df4gkZ-Th6F9MZBedCiRC-NR8V16wxOtOVs"
DATE_SHEET_NAME = "Date"
MASTER_SHEET_NAME = "Master"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def main() -> None:
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    date_ws = spreadsheet.worksheet(DATE_SHEET_NAME)
    shop_column = date_ws.col_values(8)[1:]  # H列(抽選先)、見出し除く

    seen = set()
    unique_shops = []
    for shop in shop_column:
        shop = shop.strip()
        if shop and shop not in seen:
            seen.add(shop)
            unique_shops.append(shop)

    print(f"Dateシートの店舗(重複除去後): {len(unique_shops)}件")

    master_ws = spreadsheet.worksheet(MASTER_SHEET_NAME)
    master_ws.insert_cols([[]], col=3)
    master_ws.update_cell(1, 3, "店舗")
    master_ws.update(
        f"C2:C{len(unique_shops) + 1}",
        [[shop] for shop in unique_shops],
        value_input_option="USER_ENTERED",
    )
    print("done: inserted Master column C (店舗) and filled it")


if __name__ == "__main__":
    main()
