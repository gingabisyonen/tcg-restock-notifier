import sys
from datetime import date, datetime, timedelta

from calendar_sync import upsert_pending_count_event
from notify import send_discord_message
from sheets import (
    DATE_SHEET_NAME,
    DATE_TOURAKU_COL_INDEX,
    SPREADSHEET_ID,
    STATUS_APPLIED,
    STATUS_DRAFTED,
    STATUS_NOT_APPLIED,
    get_or_create_header_col,
    get_spreadsheet,
    header_index_map,
)

# append_lottery_row (sheets.py) が書き込む行構成に合わせた固定位置(0始まり)。
# 締切・リマインド済フラグは後から追加した列なのでヘッダー名で探すが、
# ステータス(当落, F列)/商品名/店舗/URL/当選発表日は元からある列で位置決め打ちのため、ここでも合わせる。
PRODUCT_COL_INDEX = 6   # G列
SHOP_COL_INDEX = 7      # H列
ANNOUNCE_DATE_COL_INDEX = 9  # J列
LINK_COL_INDEX = 11     # L列

# 締切リマインドの対象(まだ本人が送信していない状態)。当選発表リマインドはSTATUS_APPLIEDのみ対象。
PENDING_SUBMISSION_STATUSES = (STATUS_NOT_APPLIED, STATUS_DRAFTED)

SEPARATOR = "ー" * 18


def _cell(row: list[str], col_index: int) -> str:
    return row[col_index] if col_index < len(row) else ""


def _parse_date(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y/%m/%d").date()
    except ValueError:
        return None


def main() -> None:
    spreadsheet = get_spreadsheet()
    if spreadsheet is None:
        print("[WARN] GOOGLE_SERVICE_ACCOUNT_JSON not set; skipping reminders", file=sys.stderr)
        return

    ws = spreadsheet.worksheet(DATE_SHEET_NAME)
    idx = header_index_map(ws)
    deadline_col = get_or_create_header_col(ws, idx, "締切")
    announce_flag_col = get_or_create_header_col(ws, idx, "当選発表リマインド済")

    rows = ws.get_all_values()
    today = date.today()
    sheet_url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={ws.id}"
    sent = 0
    pending_count = 0

    for row_num, row in enumerate(rows[1:], start=2):
        status = _cell(row, DATE_TOURAKU_COL_INDEX)
        if status not in PENDING_SUBMISSION_STATUSES and status != STATUS_APPLIED:
            continue

        product = _cell(row, PRODUCT_COL_INDEX)
        shop = _cell(row, SHOP_COL_INDEX)
        link = _cell(row, LINK_COL_INDEX)

        if status in PENDING_SUBMISSION_STATUSES:
            # 締切が近い「未応募/下書き済み」は行ごとに個別通知せず、件数をまとめて1通で知らせる(下記参照)。
            deadline = _parse_date(_cell(row, deadline_col - 1))
            if deadline is not None and deadline - today <= timedelta(days=1):
                pending_count += 1

        elif status == STATUS_APPLIED:
            announce = _parse_date(_cell(row, ANNOUNCE_DATE_COL_INDEX))
            already_reminded = _cell(row, announce_flag_col - 1) == "TRUE"
            if announce is None or already_reminded or announce > today:
                continue
            print(f"[ALERT] row {row_num}: announce date reached - {product} / {shop}")
            send_discord_message(
                f"🎉【当選発表日】{product}\n店舗: {shop}\n応募済みです。結果を確認してください。\n{link}\n{SEPARATOR}"
            )
            ws.update_cell(row_num, announce_flag_col, "TRUE")
            sent += 1

    if pending_count > 0:
        print(f"[ALERT] {pending_count} lottery(ies) marked 未応募 with a deadline within 1 day")
        send_discord_message(f"⏰未応募が{pending_count}件あります。\n{sheet_url}\n{SEPARATOR}")
        sent += 1

    try:
        upsert_pending_count_event(pending_count, sheet_url)
    except Exception as exc:
        print(f"[WARN] failed to sync Google Calendar: {exc}", file=sys.stderr)

    print(f"reminders sent: {sent}")


if __name__ == "__main__":
    main()
