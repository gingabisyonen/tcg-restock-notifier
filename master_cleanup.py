"""一度だけ実行する保守用スクリプト。
Masterシートのワンピース列(表記ゆれ・重複)を短い正式名に統一する。
実行後は master_cleanup.yml とあわせて削除する想定。"""

import json
import os
import re

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1hG8mwRu4Df4gkZ-Th6F9MZBedCiRC-NR8V16wxOtOVs"
MASTER_SHEET_NAME = "Master"
ONEPIECE_COL = 5  # E列

CODE_QUOTED = re.compile(r"^(OP-\d+)「(.+)」$")


def normalize(raw: str) -> str:
    raw = raw.replace("ONE PIECEカードゲーム ブースターパック ", "").strip()
    match = CODE_QUOTED.match(raw)
    if match:
        code, name = match.groups()
        return f"{name}【{code}】"
    return raw


def main() -> None:
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    client = gspread.authorize(creds)
    master = client.open_by_key(SPREADSHEET_ID).worksheet(MASTER_SHEET_NAME)

    raw_values = master.col_values(ONEPIECE_COL)[1:]
    seen = set()
    cleaned = []
    for raw in raw_values:
        raw = raw.strip()
        if not raw:
            continue
        name = normalize(raw)
        if name not in seen:
            seen.add(name)
            cleaned.append(name)

    print(f"整理前: {len(raw_values)}件 -> 整理後: {len(cleaned)}件")
    print(cleaned)

    # 既存の列内容を一旦クリアしてから書き直す
    max_rows = len(raw_values)
    if max_rows:
        master.update(
            f"E2:E{max_rows + 1}",
            [[""]] * max_rows,
            value_input_option="USER_ENTERED",
        )
    master.update(
        f"E2:E{len(cleaned) + 1}",
        [[name] for name in cleaned],
        value_input_option="USER_ENTERED",
    )
    print("done")


if __name__ == "__main__":
    main()
