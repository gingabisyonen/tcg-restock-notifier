import json
import sys
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from notify import send_discord_message
from sheets import (
    DATE_SHEET_NAME,
    DATE_TOURAKU_COL_INDEX,
    STATUS_DRAFTED,
    STATUS_NOT_APPLIED,
    find_row_by_url,
    get_spreadsheet,
)

ROOT = Path(__file__).parent
APPLICANT_FILE = ROOT / "applicant.local.json"

SEPARATOR = "ー" * 18

# textとして扱ってよい<input>のtype。checkbox/radio/select/file/password/hiddenなどは対象外。
FILLABLE_INPUT_TYPES = {"text", "email", "tel", "number", ""}

# キーワードにマッチしても、これらの語を含むフィールドは絶対に自動入力しない(決済情報)。
SKIP_FIELD_MARKERS = (
    "カード番号", "card number", "cvv", "セキュリティコード", "有効期限",
    "クレジット", "credit", "口座", "決済", "security code",
)

FIELD_KEYWORDS = {
    "name": ("お名前", "氏名", "名前", "full name"),
    "name_kana": ("フリガナ", "ふりがな", "カナ", "kana"),
    "postal_code": ("郵便番号", "〒", "postal", "zip"),
    "address": ("住所", "address"),
    "phone": ("電話番号", "電話", "tel", "phone"),
    "email": ("メールアドレス", "メール", "mail", "email"),
}


def _load_applicant() -> dict:
    if not APPLICANT_FILE.exists():
        print(
            f"[ERROR] {APPLICANT_FILE.name} が見つかりません。"
            f"applicant.example.json をコピーして applicant.local.json を作成し、値を入力してください。",
            file=sys.stderr,
        )
        sys.exit(1)
    return json.loads(APPLICANT_FILE.read_text(encoding="utf-8"))


def _context_text(page, el) -> str:
    """フィールドのlabel/aria-label/placeholder/name/idをまとめて1つの文字列にする。
    キーワードマッチと決済系フィールドの除外判定の両方に使う。"""
    parts = []
    for attr in ("aria-label", "placeholder", "name", "id"):
        value = el.get_attribute(attr)
        if value:
            parts.append(value)
    el_id = el.get_attribute("id")
    if el_id:
        try:
            label = page.locator(f'label[for="{el_id}"]').first
            if label.count() > 0:
                parts.append(label.inner_text(timeout=1000))
        except Exception:
            pass
    return " ".join(parts)


def _match_field(context_text: str) -> str | None:
    lowered = context_text.lower()
    if any(marker.lower() in lowered for marker in SKIP_FIELD_MARKERS):
        return None
    for key, keywords in FIELD_KEYWORDS.items():
        if any(kw.lower() in lowered for kw in keywords):
            return key
    return None


def _is_google_form(url: str) -> bool:
    return "docs.google.com/forms" in url or "forms.gle" in url


def _mark_drafted(url: str) -> None:
    """スプレッドシートで元のURLと一致する行を探し、ステータス(当落, F列)をSTATUS_DRAFTEDにする。
    既に「未応募」以外(応募済み/落選/当選など、より進んだ状態)なら上書きしない。
    シートが未接続、または該当行が見つからない場合は何もしない(applyの本質的な動作には影響しない)。"""
    spreadsheet = get_spreadsheet()
    if spreadsheet is None:
        return

    ws = spreadsheet.worksheet(DATE_SHEET_NAME)
    row_num = find_row_by_url(ws, url)
    if row_num is None:
        print("[INFO] スプレッドシートに一致するURLの行が見つからなかったため、ステータスは更新していません。", file=sys.stderr)
        return

    status_col = DATE_TOURAKU_COL_INDEX + 1
    current = ws.cell(row_num, status_col).value or ""
    if current not in ("", STATUS_NOT_APPLIED):
        print(f"[INFO] ステータスが既に「{current}」のため上書きしていません(row {row_num})。", file=sys.stderr)
        return

    ws.update_cell(row_num, status_col, STATUS_DRAFTED)
    print(f"[OK] スプレッドシートのステータスを「{STATUS_DRAFTED}」に更新しました(row {row_num})")


def _build_google_form_prefill_url(url: str, applicant: dict) -> tuple[str, list[str], list[str]] | None:
    """Googleフォームをヘッドレスで開いて構造だけ読み取り、事前入力済みURLを組み立てる。
    画面は表示せず、フォームへの入力・送信も一切行わない(読み取り専用)。
    戻り値は (事前入力URL, 自動入力できた項目, できなかった項目)。フォームとして開けなければNone。"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ja-JP")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            print(f"[WARN] Googleフォームを開けませんでした: {exc}", file=sys.stderr)
            browser.close()
            return None

        params: dict[str, str] = {}
        filled: list[str] = []
        unfilled: list[str] = []

        for el in page.locator("input, textarea").all():
            name = el.get_attribute("name") or ""
            if not name.startswith("entry."):
                continue
            if not el.is_visible():
                continue

            context = _context_text(page, el)
            label = context or name
            key = _match_field(context)

            if key and applicant.get(key):
                params[name] = str(applicant[key])
                filled.append(label)
            else:
                unfilled.append(label)

        base_url = page.url.split("?")[0]
        browser.close()

    if not params:
        return None

    query = urlencode({"usp": "pp_url", **params})
    return f"{base_url}?{query}", filled, unfilled


def main(url: str) -> None:
    applicant = _load_applicant()

    if _is_google_form(url):
        result = _build_google_form_prefill_url(url, applicant)
        if result is None:
            print(
                "[WARN] Googleフォームとして認識しましたが、自動入力できるフィールドが見つかりませんでした。"
                "通常通り手動で応募してください。",
                file=sys.stderr,
            )
            return

        prefill_url, filled, unfilled = result
        print(f"[OK] 事前入力済みURLを作成しました({len(filled)}件自動入力、{len(unfilled)}件は未入力)")
        for line in filled:
            print(f"  - {line}")
        if unfilled:
            print(f"[INFO] 自動入力できなかったフィールド: {len(unfilled)}件")
            for line in unfilled:
                print(f"  - {line}")

        send_discord_message(
            "📝 応募フォームの下書きができました。リンクを開くと入力済みの状態で表示されます。\n"
            "内容を確認のうえ、ご自身の判断で送信してください。\n"
            f"{prefill_url}\n{SEPARATOR}"
        )
        _mark_drafted(url)
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(locale="ja-JP")
        page.goto(url, wait_until="domcontentloaded")

        filled: list[str] = []
        unfilled: list[str] = []

        for el in page.locator("input, textarea").all():
            if not el.is_visible():
                continue
            if el.get_attribute("disabled") is not None or el.get_attribute("readonly") is not None:
                continue

            tag = el.evaluate("e => e.tagName.toLowerCase()")
            if tag == "input":
                input_type = (el.get_attribute("type") or "text").lower()
                if input_type not in FILLABLE_INPUT_TYPES:
                    continue

            context = _context_text(page, el)
            label = context or f"({tag})"
            key = _match_field(context)

            if key and applicant.get(key):
                try:
                    el.fill(str(applicant[key]))
                    filled.append(f"{label} -> {key}")
                except Exception as exc:
                    print(f"[WARN] failed to fill field ({label}): {exc}", file=sys.stderr)
                    unfilled.append(label)
            else:
                unfilled.append(label)

        print(f"\n[OK] 自動入力できたフィールド: {len(filled)}件")
        for line in filled:
            print(f"  - {line}")

        print(f"\n[INFO] 自動入力できなかった(手動で確認が必要な)フィールド: {len(unfilled)}件")
        for line in unfilled:
            print(f"  - {line}")

        input(
            "\n内容を確認・修正のうえ、ご自身の判断で送信してください。"
            "送信ボタンはこのツールでは絶対に押しません。"
            "Enterキーを押すとブラウザを閉じます..."
        )
        browser.close()

    _mark_drafted(url)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("使い方: python apply.py <応募ページのURL>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
