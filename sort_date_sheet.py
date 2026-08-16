"""一度だけ実行する保守用スクリプト。
DateシートをF列(当落)昇順 → J列(抽選結果発表日)昇順で並び替える。
実行後は sort_date_sheet.yml とあわせて削除する想定。"""

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

    values = ws.get_all_values()
    last_row = len(values)
    print(f"対象行数(見出し除く): {last_row - 1}")

    ws.sort((6, "asc"), (10, "asc"), range=f"A2:L{last_row}")
    print("done")


if __name__ == "__main__":
    main()
