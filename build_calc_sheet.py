"""一度だけ実行する保守用スクリプト。
「計算」シートを作り直し、Dateシートを自動集計する表(担当者別・種別)とグラフを設置する。
見出しは黒塗り・白文字太字、表全体に罫線を付ける。
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

BLACK = {"red": 0, "green": 0, "blue": 0}
WHITE = {"red": 1, "green": 1, "blue": 1}


def rate_formula(win_cell: str, lose_cell: str) -> str:
    return f"=IF({win_cell}+{lose_cell}=0,0,ROUND({win_cell}/({win_cell}+{lose_cell})*100,1))"


def build_values():
    rows: list[list] = []

    def next_row() -> int:
        return len(rows) + 1

    rows.append(["【全体】"])
    rows.append(["総件数", "=COUNTA(Date!A2:A)"])
    rows.append(["当選", '=COUNTIF(Date!F2:F,"当選")'])
    rows.append(["落選", '=COUNTIF(Date!F2:F,"落選")'])
    rows.append(["保留(未定)", "=B2-B3-B4"])
    rows.append(["当選率(%)", rate_formula("B3", "B4")])
    overall_title_row = 1
    overall_last_row = next_row() - 1
    rows.append([])
    rows.append([])

    rows.append(["【担当者別】"])
    person_title_row = next_row()
    rows.append(["担当者", "総件数", "当選", "落選", "保留", "当選率(%)"])
    person_header_row = next_row()
    for person in RESPONSIBLE_PEOPLE:
        r = next_row()
        rows.append([
            person,
            f'=COUNTIF(Date!D:D,"{person}")',
            f'=COUNTIFS(Date!D:D,"{person}",Date!F:F,"当選")',
            f'=COUNTIFS(Date!D:D,"{person}",Date!F:F,"落選")',
            f"=B{r}-C{r}-D{r}",
            rate_formula(f"C{r}", f"D{r}"),
        ])
    person_last_row = next_row() - 1
    rows.append([])
    rows.append([])

    rows.append(["【ゲーム種別】"])
    game_title_row = next_row()
    rows.append(["種別", "総件数", "当選", "落選", "保留", "当選率(%)"])
    game_header_row = next_row()
    for game in GAME_TYPES:
        r = next_row()
        rows.append([
            game,
            f'=COUNTIF(Date!E:E,"{game}")',
            f'=COUNTIFS(Date!E:E,"{game}",Date!F:F,"当選")',
            f'=COUNTIFS(Date!E:E,"{game}",Date!F:F,"落選")',
            f"=B{r}-C{r}-D{r}",
            rate_formula(f"C{r}", f"D{r}"),
        ])
    game_last_row = next_row() - 1

    layout = {
        "overall_title_row": overall_title_row,
        "overall_last_row": overall_last_row,
        "person_title_row": person_title_row,
        "person_header_row": person_header_row,
        "person_last_row": person_last_row,
        "game_title_row": game_title_row,
        "game_header_row": game_header_row,
        "game_last_row": game_last_row,
    }
    return rows, layout


def range_(sheet_id, start_row, end_row, start_col, end_col):
    return {
        "sheetId": sheet_id,
        "startRowIndex": start_row - 1,
        "endRowIndex": end_row,
        "startColumnIndex": start_col - 1,
        "endColumnIndex": end_col,
    }


def header_format_request(sheet_id, start_row, end_row, start_col, end_col):
    return {
        "repeatCell": {
            "range": range_(sheet_id, start_row, end_row, start_col, end_col),
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": BLACK,
                    "textFormat": {"foregroundColor": WHITE, "bold": True},
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    }


def border_request(sheet_id, start_row, end_row, start_col, end_col):
    style = {"style": "SOLID", "width": 1, "color": BLACK}
    return {
        "repeatCell": {
            "range": range_(sheet_id, start_row, end_row, start_col, end_col),
            "cell": {
                "userEnteredFormat": {
                    "borders": {"top": style, "bottom": style, "left": style, "right": style}
                }
            },
            "fields": "userEnteredFormat.borders",
        }
    }


def chart_request(sheet_id, title, header_row, last_data_row, anchor_row, anchor_col):
    def source(col_1idx):
        return {"sources": [range_(sheet_id, header_row, last_data_row, col_1idx, col_1idx)]}

    series = [{"series": {"sourceRange": source(col)}, "targetAxis": "LEFT_AXIS"} for col in (3, 4, 5)]

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
                        "anchorCell": {"sheetId": sheet_id, "rowIndex": anchor_row, "columnIndex": anchor_col}
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
    sheet_meta = spreadsheet.fetch_sheet_metadata()
    for sheet in sheet_meta["sheets"]:
        if sheet["properties"]["sheetId"] != ws.id:
            continue
        chart_ids = [c["chartId"] for c in sheet.get("charts", [])]
        if chart_ids:
            spreadsheet.batch_update({
                "requests": [{"deleteEmbeddedObject": {"objectId": cid}} for cid in chart_ids]
            })

    values, layout = build_values()
    ws.update("A1", values, value_input_option="USER_ENTERED")
    print("layout:", layout)

    sid = ws.id
    requests = [
        # 見出し(黒塗り白太字)
        header_format_request(sid, layout["overall_title_row"], layout["overall_title_row"], 1, 6),
        header_format_request(sid, layout["person_title_row"], layout["person_title_row"], 1, 6),
        header_format_request(sid, layout["person_header_row"], layout["person_header_row"], 1, 6),
        header_format_request(sid, layout["game_title_row"], layout["game_title_row"], 1, 6),
        header_format_request(sid, layout["game_header_row"], layout["game_header_row"], 1, 6),
        # 罫線(表全体)
        border_request(sid, layout["overall_title_row"], layout["overall_last_row"], 1, 2),
        border_request(sid, layout["person_title_row"], layout["person_last_row"], 1, 6),
        border_request(sid, layout["game_title_row"], layout["game_last_row"], 1, 6),
        # グラフ(見出し行はheader_row、データはheader_row+1以降)
        chart_request(sid, "担当者別 当選/落選", layout["person_header_row"], layout["person_last_row"], 0, 7),
        chart_request(sid, "ゲーム種別 当選/落選", layout["game_header_row"], layout["game_last_row"], 20, 7),
    ]
    spreadsheet.batch_update({"requests": requests})
    print("done")


if __name__ == "__main__":
    main()
