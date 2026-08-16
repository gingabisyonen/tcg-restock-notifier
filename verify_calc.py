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
    ws = client.open_by_key(SPREADSHEET_ID).worksheet("計算")

    values = ws.get_all_values()
    for i, row in enumerate(values[:25], start=1):
        if any(cell for cell in row):
            print(i, row)

    meta = client.open_by_key(SPREADSHEET_ID).fetch_sheet_metadata()
    for sheet in meta["sheets"]:
        if sheet["properties"]["sheetId"] == ws.id:
            print("charts:", len(sheet.get("charts", [])))
            for c in sheet.get("charts", []):
                print(" -", c["spec"].get("title"))


if __name__ == "__main__":
    main()
