"""一度だけ実行する保守用スクリプト。
Dateシートの既存K列(メモ)の前に新しい列を挿入し、
K列=当選通知方法、L列(旧メモ)=URL、という見出しに整える。
実行後は maintenance.yml とあわせて削除する想定。"""

import json
import os

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1hG8mwRu4Df4gkZ-Th6F9MZBedCiRC-NR8V16wxOtOVs"
DATE_SHEET_NAME = "Date"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def main() -> None:
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    ws = client.open_by_key(SPREADSHEET_ID).worksheet(DATE_SHEET_NAME)

    ws.insert_cols([[]], col=11)
    ws.update_cell(1, 11, "当選通知方法")
    ws.update_cell(1, 12, "URL")
    print("done: inserted column K, set K1/L1 headers")


if __name__ == "__main__":
    main()
