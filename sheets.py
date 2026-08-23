import json
import os
import re
from datetime import date, timedelta

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "1hG8mwRu4Df4gkZ-Th6F9MZBedCiRC-NR8V16wxOtOVs"
DATE_SHEET_NAME = "抽選"  # 旧シート名は "Date"(2026-08-23にユーザーがリネーム)
MASTER_SHEET_NAME = "Master"
CALC_SHEET_NAME = "計算"

# 「計算」シートの【商品別】表の位置(2026-08-23作成時点でハードコード)。
# A=種別 B=商品名 C=定価額 D=相場額 E=総件数 F=当選 G=落選 H=保留 I=当選率(%)
# 定価額・相場額はtcg-collection-tracker側のupdate_lottery_prices.pyが日次で埋める(手入力の値は上書きしない)。
CALC_PRODUCT_HEADER_ROW = 24
CALC_PRODUCT_DATA_START_ROW = 25

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# 抽選シートの列位置(0始まり)。当落(F)・抽選結果発表日(J)は列を追加/移動しない前提でハードコードする。
DATE_TOURAKU_COL_INDEX = 5
DATE_ANNOUNCE_DATE_COL_INDEX = 9
DATE_VIEW_LAST_COL_INDEX = 16  # A:P

RESPONSIBLE_PERSON = "のり"

# 当落(F列)の値。DRAFTED(下書き済み)はapply.pyが下書きを用意した時点で自動で入るステータスで、
# まだ本人が送信していないため、締切リマインドの対象には含めつつ当選発表リマインドの対象には含めない。
STATUS_NOT_APPLIED = "未応募"
STATUS_DRAFTED = "下書き済み"
STATUS_APPLIED = "応募済み"
STATUS_LOST = "落選"
STATUS_WON = "当選"

# ゲームラベル(Masterシート「種類」列の表記と一致させる) -> Masterシートの商品名リストの列番号(A=1)
# B列にステータス列を追加したため、ポケカ以降は1列ずつ右にずれている
MASTER_GAME_COLUMNS = {
    "ポケカ": 5,        # E列
    "ワンピース": 6,     # F列
    "ドラゴンボール": 7,  # G列
}

ANNOUNCE_DATE_PATTERN = re.compile(r"(?:当選発表|抽選結果|結果発表)\D{0,10}?(\d{1,2})月(\d{1,2})日")

# 抽選まとめサイトの deadline フィールドは "8/16(日)まで" "8/3(月) 20:00" のような M/D 形式。
# ("月...日" ではなく "/" 区切り。当選発表日のフリーテキストとはソースも書式も別物なので別パターンにする)
DEADLINE_MD_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})")

# 商品名に含まれる型番(例: OP-17, ST01, FB01)を拾うためのパターン。
# 表記ゆれ(語順・括弧の種類違いなど)があっても型番さえ一致すれば同一商品とみなす。
PRODUCT_CODE_PATTERN = re.compile(r"[A-Z]{1,4}-?\d{2,3}[A-Z]?")


def _extract_product_code(name: str) -> str | None:
    match = PRODUCT_CODE_PATTERN.search(name.upper().replace(" ", ""))
    return match.group(0) if match else None

_client = None
_spreadsheet = None
_tried = False
_creds = None
_sheets_service = None


def _get_spreadsheet():
    global _client, _spreadsheet, _tried, _creds
    if _tried:
        return _spreadsheet
    _tried = True

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        return None

    info = json.loads(creds_json)
    _creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    _client = gspread.authorize(_creds)
    _spreadsheet = _client.open_by_key(SPREADSHEET_ID)
    return _spreadsheet


def _get_sheets_service():
    """setBasicFilterなどgspreadに無いSheets API v4呼び出し用。_get_spreadsheet()と認証情報を共有する。"""
    global _sheets_service
    if _sheets_service is not None:
        return _sheets_service
    if _get_spreadsheet() is None or _creds is None:
        return None
    _sheets_service = build("sheets", "v4", credentials=_creds)
    return _sheets_service


def get_spreadsheet():
    """remind.py など他モジュールからも使う公開ラッパー。認証・キャッシュの実体は _get_spreadsheet。"""
    return _get_spreadsheet()


def header_index_map(ws) -> dict[str, int]:
    """1行目のヘッダーを {ヘッダー名: 0始まり列インデックス} に変換する(空文字・重複は先勝ち)。"""
    headers = ws.row_values(1)
    idx: dict[str, int] = {}
    for i, header in enumerate(headers):
        if header and header not in idx:
            idx[header] = i
    return idx


def get_or_create_header_col(ws, idx: dict[str, int], header_name: str) -> int:
    """header_nameの列番号(1始まり)を返す。既存シートに無ければ最終列の次に見出しを追加する。
    列番号をハードコードせず、シート側に既にある未知の列(例: I列)と衝突しないようにするため。"""
    if header_name in idx:
        return idx[header_name] + 1
    col = len(ws.row_values(1)) + 1
    ws.update_cell(1, col, header_name)
    idx[header_name] = col - 1
    return col


def find_row_by_url(ws, url: str) -> int | None:
    """「URL」列の値が完全一致する行番号(1始まり)を探す。見つからなければNone。
    apply.pyがどの行の応募状況を更新すべきか判断するために使う。"""
    idx = header_index_map(ws)
    url_col = idx.get("URL")
    if url_col is None:
        return None
    values = ws.col_values(url_col + 1)
    target = url.strip()
    for i, value in enumerate(values[1:], start=2):
        if value.strip() == target:
            return i
    return None


def _append_product_to_calc_table(game: str, product: str) -> None:
    """Masterシートに新商品が追加された時、「計算」シートの【商品別】表の最下行にも
    集計行を1行追加する(種別ごとのグループ分けはせず、単純に表全体の最後に追記する)。
    定価額・相場額は空欄で追加し、tcg-collection-tracker側の日次更新スクリプトが後から埋める。"""
    spreadsheet = _get_spreadsheet()
    service = _get_sheets_service()
    if spreadsheet is None or service is None:
        return

    calc = spreadsheet.worksheet(CALC_SHEET_NAME)
    existing_names = calc.get(f"A{CALC_PRODUCT_DATA_START_ROW}:A1000")
    new_row = CALC_PRODUCT_DATA_START_ROW + len(existing_names)

    total = f"=COUNTIF('{DATE_SHEET_NAME}'!$G:$G,B{new_row})"
    won = f"=COUNTIFS('{DATE_SHEET_NAME}'!$G:$G,B{new_row},'{DATE_SHEET_NAME}'!$F:$F,\"{STATUS_WON}\")"
    lost = f"=COUNTIFS('{DATE_SHEET_NAME}'!$G:$G,B{new_row},'{DATE_SHEET_NAME}'!$F:$F,\"{STATUS_LOST}\")"
    pending = f"=E{new_row}-F{new_row}-G{new_row}"
    rate = f"=IF(F{new_row}+G{new_row}=0,0,ROUND(F{new_row}/(F{new_row}+G{new_row})*100,1))"
    calc.update(
        range_name=f"A{new_row}:I{new_row}",
        values=[[game, product, "", "", total, won, lost, pending, rate]],
        value_input_option="USER_ENTERED",
    )

    border_style = {"style": "SOLID", "width": 1}
    request = {
        "updateBorders": {
            "range": {
                "sheetId": calc.id,
                "startRowIndex": CALC_PRODUCT_HEADER_ROW - 1,
                "endRowIndex": new_row,
                "startColumnIndex": 0,
                "endColumnIndex": 9,
            },
            "top": border_style,
            "bottom": border_style,
            "left": border_style,
            "right": border_style,
            "innerHorizontal": border_style,
            "innerVertical": border_style,
        }
    }
    service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID, body={"requests": [request]}
    ).execute()


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
    _append_product_to_calc_table(game, product)
    return product


def _resolve_year_with_rollover(month: int, day: int, reference: date | None = None) -> date | None:
    """month/dayに年を補う。基準日から60日以上過去になる場合は年またぎとみなし翌年にする
    (例: 12月に「1月5日」を検知した場合、今年の1月ではなく来年の1月と解釈する)。"""
    reference = reference or date.today()
    try:
        candidate = date(reference.year, month, day)
    except ValueError:
        return None
    if candidate < reference - timedelta(days=60):
        try:
            candidate = date(reference.year + 1, month, day)
        except ValueError:
            return None
    return candidate


def _extract_announce_date(text: str) -> str:
    """説明文から「当選発表は8月26日」のような表記を探し、yyyy/mm/dd形式にして返す。
    見つからなければ空文字を返す(無理に埋めない)。"""
    if not text:
        return ""
    match = ANNOUNCE_DATE_PATTERN.search(text)
    if not match:
        return ""
    month, day = (int(g) for g in match.groups())
    resolved = _resolve_year_with_rollover(month, day)
    return resolved.strftime("%Y/%m/%d") if resolved else ""


def _extract_deadline_date(deadline_text: str) -> str:
    """抽選まとめサイトの deadline フィールド("8/16(日)まで" "本日 23:59" 等)を
    yyyy/mm/dd形式にして返す。"本日"/"明日"は日付が書かれていないため特別扱いする。
    解釈できなければ空文字を返す(無理に埋めない)。
    「8/19(火)から受付開始」のように、まだ始まっていない抽選の開始日を知らせているだけの
    文言は「まで」(締切)を含まないため、日付があっても締切として扱わず空文字を返す
    (受付開始日を締切と誤認識して記録してしまう不具合の対策)。"""
    if not deadline_text:
        return ""
    if "開始" in deadline_text and "まで" not in deadline_text:
        return ""
    if "本日" in deadline_text:
        return date.today().strftime("%Y/%m/%d")
    if "明日" in deadline_text:
        return (date.today() + timedelta(days=1)).strftime("%Y/%m/%d")
    match = DEADLINE_MD_PATTERN.search(deadline_text)
    if not match:
        return ""
    month, day = (int(g) for g in match.groups())
    resolved = _resolve_year_with_rollover(month, day)
    return resolved.strftime("%Y/%m/%d") if resolved else ""


_APPENDED_RANGE_ROW_PATTERN = re.compile(r"![A-Z]+(\d+):")


def _appended_row_number(append_result: dict) -> int | None:
    """append_row()のレスポンスから追記された行番号を取り出す。取れなければNoneを返す。"""
    try:
        updated_range = append_result["updates"]["updatedRange"]
    except (KeyError, TypeError):
        return None
    match = _APPENDED_RANGE_ROW_PATTERN.search(updated_range)
    return int(match.group(1)) if match else None


def append_lottery_row(game: str, product: str, shop: str, link: str, description: str = "", deadline: str = "") -> None:
    """新規抽選を検知した際に抽選シートへ1行追記する。
    K列(当選通知方法)には分かっている範囲の説明文、L列(URL)には応募先URLを入れる。
    F列(当落=ステータス)は新規追加時点では「未応募」で初期化する(未応募/下書き済み/応募済み/落選/当選の5値)。
    締切・リマインド済フラグはヘッダー名で列を探し(無ければ追加し)書き込む。
    GOOGLE_SERVICE_ACCOUNT_JSON が未設定の場合は何もしない(Discord通知のみで動作継続)。"""
    spreadsheet = _get_spreadsheet()
    if spreadsheet is None:
        return

    resolved_product = _resolve_product_name(game, product)
    announce_date = _extract_announce_date(description)
    deadline_date = _extract_deadline_date(deadline)

    today = date.today()
    row = [
        today.year,
        today.month,
        today.day,
        RESPONSIBLE_PERSON,
        game,
        STATUS_NOT_APPLIED,
        resolved_product,
        shop,
        "-",
        announce_date,
        description,
        link,
    ]
    ws = spreadsheet.worksheet(DATE_SHEET_NAME)
    result = ws.append_row(row, value_input_option="USER_ENTERED")
    row_num = _appended_row_number(result)
    if row_num is None:
        return

    idx = header_index_map(ws)
    deadline_col = get_or_create_header_col(ws, idx, "締切")
    ws.update_cell(row_num, deadline_col, deadline_date)
    # 応募状況・リマインド済フラグは列の存在だけ保証しておく(値はここでは書かない)
    get_or_create_header_col(ws, idx, "応募状況")
    get_or_create_header_col(ws, idx, "締切リマインド済")
    get_or_create_header_col(ws, idx, "当選発表リマインド済")


def sync_date_sheet_view() -> None:
    """抽選シートの表示を最新状態に合わせる:
    - 並び替え: 当落(F)が「未応募」(=ユーザー側でまだ対応していない案件)の行は最下部にまとめ、
      それ以外は抽選結果発表日(J)の昇順。「未応募」を末尾固定する複合キーはSheets標準の単一列
      ソート(setBasicFilterのsortSpecs)では表現できないため、Python側で計算して物理的に
      並び替える。
    - 非表示: 当落(F)が「落選」または「当選」(=結果が確定して対応不要になった案件)の行を
      基本フィルタで非表示にする。こちらは条件付き書式と同様、セルの値が変わるたびにGoogle
      Sheets側で自動的に再評価される(呼び直し不要)。
    どちらもcheck.pyの実行(5分おき)のたびに呼び直すことで、手動でのステータス変更を追従させる。
    GOOGLE_SERVICE_ACCOUNT_JSON が未設定の場合は何もしない。"""
    spreadsheet = _get_spreadsheet()
    service = _get_sheets_service()
    if spreadsheet is None or service is None:
        return

    ws = spreadsheet.worksheet(DATE_SHEET_NAME)
    values = ws.get_all_values()
    if len(values) > 1:
        data_rows = values[1:]

        def sort_key(row: list[str]) -> tuple[bool, str]:
            f_val = row[DATE_TOURAKU_COL_INDEX] if len(row) > DATE_TOURAKU_COL_INDEX else ""
            j_val = row[DATE_ANNOUNCE_DATE_COL_INDEX] if len(row) > DATE_ANNOUNCE_DATE_COL_INDEX else ""
            return (f_val == STATUS_NOT_APPLIED, j_val)

        data_rows.sort(key=sort_key)
        padded_rows = [
            (row + [""] * DATE_VIEW_LAST_COL_INDEX)[:DATE_VIEW_LAST_COL_INDEX] for row in data_rows
        ]
        ws.update(
            range_name=f"A2:{gspread.utils.rowcol_to_a1(1 + len(padded_rows), DATE_VIEW_LAST_COL_INDEX)}",
            values=padded_rows,
            value_input_option="USER_ENTERED",
        )

    request = {
        "setBasicFilter": {
            "filter": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 0,
                    "endRowIndex": ws.row_count,
                    "startColumnIndex": 0,
                    "endColumnIndex": DATE_VIEW_LAST_COL_INDEX,
                },
                "criteria": {
                    str(DATE_TOURAKU_COL_INDEX): {"hiddenValues": [STATUS_LOST, STATUS_WON]}
                },
            }
        }
    }
    service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID, body={"requests": [request]}
    ).execute()
