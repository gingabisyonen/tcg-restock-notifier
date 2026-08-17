import json
import os
from datetime import date, timedelta

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

CALENDAR_ID = "asxagpe1@gmail.com"
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# 自分が作った予定だけを見分けるための目印(タイトル文字列の一致に頼らないため)。
EVENT_SOURCE_TAG = "tcg-restock-notifier-pending"

_service = None
_tried = False


def _get_service():
    global _service, _tried
    if _tried:
        return _service
    _tried = True

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        return None

    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(info, scopes=CALENDAR_SCOPES)
    _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _service


def _find_existing_event(service, day: date) -> dict | None:
    time_min = f"{day.isoformat()}T00:00:00Z"
    time_max = f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z"
    result = (
        service.events()
        .list(
            calendarId=CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            privateExtendedProperty=f"source={EVENT_SOURCE_TAG}",
            singleEvents=True,
        )
        .execute()
    )
    items = result.get("items", [])
    return items[0] if items else None


def upsert_pending_count_event(pending_count: int, detail_url: str, day: date | None = None) -> None:
    """締切が近い「未応募」の件数を、その日の終日予定として作成・更新する。
    pending_countが0の場合は、その日に既に作成済みの予定があれば削除する
    (全部応募済み/落選/当選になれば予定も消える)。
    GOOGLE_SERVICE_ACCOUNT_JSON が未設定、またはCalendar APIが有効化/共有されていない場合は何もしない。"""
    service = _get_service()
    if service is None:
        return

    day = day or date.today()
    existing = _find_existing_event(service, day)

    if pending_count <= 0:
        if existing:
            service.events().delete(calendarId=CALENDAR_ID, eventId=existing["id"]).execute()
        return

    body = {
        "summary": f"未抽選が{pending_count}件あります",
        "description": detail_url,
        "start": {"date": day.isoformat()},
        "end": {"date": (day + timedelta(days=1)).isoformat()},
        "extendedProperties": {"private": {"source": EVENT_SOURCE_TAG}},
    }

    if existing:
        service.events().update(calendarId=CALENDAR_ID, eventId=existing["id"], body=body).execute()
    else:
        service.events().insert(calendarId=CALENDAR_ID, body=body).execute()
