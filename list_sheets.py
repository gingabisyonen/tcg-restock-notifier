"""一度だけ実行する保守用スクリプト。スプレッドシート内の全タブ名を確認する。"""

import json
import os

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1hG8mwRu4Df4gkZ-Th6F9MZBedCiRC-NR8V16wxOtOVs"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def main() -> None:
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    for ws in spreadsheet.worksheets():
        print(f"title={ws.title!r} rows={ws.row_count} cols={ws.col_count}")


if __name__ == "__main__":
    main()
