"""一度だけ実行する保守用スクリプト。
「計算」シートを作り直し、Dateシートを自動集計する表(担当者別・種別)とグラフを設置する。
formulaはDateシートを参照する形にしてあるので、以降は自動更新される(再実行不要)。
実行後は build_calc_sheet.py と build_calc_sheet.yml を削除する想定。"""

import json
import os

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1hG8mwRu4Df4gkZ-Th6F9MZBedCiRC-NR8V16wxOtOVs"
CALC_SHEET_NAME = "計算"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

RESPONSIBLE_PEOPLE = ["のり", "しゅん"]
GAME_TYPES = ["ポケカ", "ワンピース", "ドラゴンボール", "遊戯王", "ユニオンアリーナ"]


def rate_formula(win_cell: str, lose_cell: str) -> str:
    return f'=IF({win_cell}+{lose_cell}=0,0,ROUND({win_cell}/({win_cell}+{lose_cell})*100,1))'


def build_values() -> list[list[str]]:
    rows: list[list[str]] = []

    rows.append(["【全体】"])
    rows.append(["総件数", "=COUNTA(Date!A2:A)"])
    rows.append(["当選", '=COUNTIF(Date!F2:F,"当選")'])
    rows.append(["落選", '=COUNTIF(Date!F2:F,"落選")'])
    rows.append(["保留(未定)", "=B2-B3-B4"])
    rows.append(["当選率(%)", rate_formula("B3", "B4")])
    rows.append([])
    rows.append([])

    rows.append(["【担当者別】"])
    rows.append(["担当者", "総件数", "当選", "落選", "保留", "当選率(%)"])
    for person in RESPONSIBLE_PEOPLE:
        r = len(rows) + 1  # このあと追加する行の1始まり行番号
        rows.append([
            person,
            f'=COUNTIF(Date!D:D,"{person}")',
            f'=COUNTIFS(Date!D:D,"{person}",Date!F:F,"当選")',
            f'=COUNTIFS(Date!D:D,"{person}",Date!F:F,"落選")',
            f"=B{r}-C{r}-D{r}",
            rate_formula(f"C{r}", f"D{r}"),
        ])
    rows.append([])
    rows.append([])

    rows.append(["【ゲーム種別】"])
    rows.append(["種別", "総件数", "当選", "落選", "保留", "当選率(%)"])
    for game in GAME_TYPES:
        r = len(rows) + 1
        rows.append([
            game,
            f'=COUNTIF(Date!E:E,"{game}")',
            f'=COUNTIFS(Date!E:E,"{game}",Date!F:F,"当選")',
            f'=COUNTIFS(Date!E:E,"{game}",Date!F:F,"落選")',
            f"=B{r}-C{r}-D{r}",
            rate_formula(f"C{r}", f"D{r}"),
        ])

    return rows


def make_chart_request(sheet_id: int, title: str, header_row: int, last_data_row: int,
                        anchor_row: int, anchor_col: int) -> dict:
    def source(col_1idx: int) -> dict:
        return {
            "sources": [{
                "sheetId": sheet_id,
                "startRowIndex": header_row - 1,
                "endRowIndex": last_data_row,
                "startColumnIndex": col_1idx - 1,
                "endColumnIndex": col_1idx,
            }]
        }

    series = []
    for col, name in ((3, "当選"), (4, "落選"), (5, "保留")):
        series.append({
            "series": {"sourceRange": source(col)},
            "targetAxis": "LEFT_AXIS",
        })

    return {
        "addChart": {
            "chart": {
                "spec": {
                    "title": title,
                    "basicChart": {
                        "chartType": "COLUMN",
                        "legendPosition": "BOTTOM_LEGEND",
                        "axis": [
                            {"position": "BOTTOM_AXIS"},
                            {"position": "LEFT_AXIS", "title": "件数"},
                        ],
                        "domains": [{"domain": {"sourceRange": source(1)}}],
                        "series": series,
                        "headerCount": 1,
                    },
                },
                "position": {
                    "overlayPosition": {
                        "anchorCell": {
                            "sheetId": sheet_id,
                            "rowIndex": anchor_row,
                            "columnIndex": anchor_col,
                        }
                    }
                },
            }
        }
    }


def main() -> None:
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    ws = spreadsheet.worksheet(CALC_SHEET_NAME)

    ws.clear()
    # 既存のグラフが残っていれば削除する
    sheet_meta = spreadsheet.fetch_sheet_metadata()
    for sheet in sheet_meta["sheets"]:
        if sheet["properties"]["sheetId"] != ws.id:
            continue
        chart_ids = [c["chartId"] for c in sheet.get("charts", [])]
        if chart_ids:
            spreadsheet.batch_update({
                "requests": [{"deleteEmbeddedObject": {"objectId": cid}} for cid in chart_ids]
            })

    values = build_values()
    ws.update("A1", values, value_input_option="USER_ENTERED")

    person_header_row = 9
    person_last_row = person_header_row + len(RESPONSIBLE_PEOPLE)
    game_header_row = person_last_row + 3
    game_last_row = game_header_row + len(GAME_TYPES)

    requests = [
        make_chart_request(ws.id, "担当者別 当選/落選", person_header_row, person_last_row, 0, 7),
        make_chart_request(ws.id, "ゲーム種別 当選/落選", game_header_row, game_last_row, 18, 7),
    ]
    spreadsheet.batch_update({"requests": requests})
    print("done")


if __name__ == "__main__":
    main()
