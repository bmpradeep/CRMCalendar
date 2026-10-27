"""Turn the two exports into one shape.

The files are not clean. CRM-1008's date is "03-15/2025", CAL-A4 is the only
timestamp with a Z, CAL-A11's end time has no seconds, and one Atlas attendee
is written as "raj.patel[at]atlasvc.com". Fix those here and keep a note,
instead of editing the source files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# HQ, NYC, Boston, and DC are all on this clock. The single UTC timestamp
# (CAL-A4, Crestview) is converted before we compare it to a CRM time.
FIRM_TZ = ZoneInfo("America/New_York")
INTERNAL_DOMAIN = "firma.com"

_EMAIL_AT = re.compile(r"\s*\[at\]\s*", re.IGNORECASE)
_EMAIL_DOT = re.compile(r"\s*\[dot\]\s*", re.IGNORECASE)


@dataclass
class Record:
    source: str
    source_id: str
    title: str
    date: date | None
    start_min: int | None
    end_min: int | None
    start_raw: str | None
    tz_note: str | None
    client_name: str | None
    company: str | None
    specific_client: bool
    owner: str | None
    organizer_email: str | None
    location: str | None
    meeting_type: str | None
    status: str | None
    notes: str | None
    attendees: list[str]
    external_emails: list[str]
    is_recurring: bool
    issues: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def all_emails(self) -> list[str]:
        emails = []
        if self.organizer_email:
            emails.append(self.organizer_email)
        emails.extend(self.attendees)
        return emails


def hhmm(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def load_crm(path: Path) -> list[Record]:
    return [_crm_record(row) for row in _read_list(path)]


def load_calendar(path: Path) -> list[Record]:
    return [_calendar_record(row) for row in _read_list(path)]


def _read_list(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"{path} should be a JSON list")
    return [row for row in payload if isinstance(row, dict)]


def _crm_record(row: dict) -> Record:
    issues: list[str] = []
    day, date_issues = _parse_crm_date(row.get("meeting_date"))
    start, time_issues = _parse_crm_time(row.get("meeting_time"))
    issues.extend(date_issues)
    issues.extend(time_issues)

    client = _blank_to_none(row.get("client_name"))
    company = _blank_to_none(row.get("client_company"))
    return Record(
        source="crm",
        source_id=str(row.get("crm_id") or ""),
        title=_blank_to_none(row.get("subject")) or "(no subject)",
        date=day,
        start_min=start,
        end_min=None,
        start_raw=_as_text(row.get("meeting_time")),
        tz_note=None,
        client_name=client,
        company=company,
        specific_client=_is_specific_person(client),
        owner=_blank_to_none(row.get("relationship_owner")),
        organizer_email=None,
        location=_blank_to_none(row.get("location")),
        meeting_type=_blank_to_none(row.get("meeting_type")),
        status=_blank_to_none(row.get("status")),
        notes=_blank_to_none(row.get("notes")),
        attendees=[],
        external_emails=[],
        is_recurring=False,
        issues=issues,
        raw=row,
    )


def _calendar_record(row: dict) -> Record:
    issues: list[str] = []
    start_day, start_min, tz_note, start_issues = _parse_clock(row.get("start_time"), "start time")
    _end_day, end_min, _end_note, end_issues = _parse_clock(row.get("end_time"), "end time")
    issues.extend(start_issues)
    issues.extend(end_issues)

    attendees: list[str] = []
    external: list[str] = []
    for raw in row.get("attendees") or []:
        cleaned, note = clean_attendee(raw)
        if note:
            issues.append(note)
        if not cleaned:
            continue
        attendees.append(cleaned)
        if "@" in cleaned and not cleaned.lower().endswith("@" + INTERNAL_DOMAIN):
            external.append(cleaned.lower())

    if not attendees and not (row.get("attendees") or []):
        issues.append("No attendees listed.")

    organizer = _blank_to_none(row.get("organizer"))
    if organizer:
        organizer, note = clean_attendee(organizer)
        if note:
            issues.append(note)

    location = _blank_to_none(row.get("location"))
    description = _blank_to_none(row.get("description"))
    if location is None and description is None and not attendees:
        issues.append("Location and description are empty.")

    return Record(
        source="calendar",
        source_id=str(row.get("event_id") or ""),
        title=_blank_to_none(row.get("title")) or "(no title)",
        date=start_day,
        start_min=start_min,
        end_min=end_min,
        start_raw=_as_text(row.get("start_time")),
        tz_note=tz_note,
        client_name=None,
        company=None,
        specific_client=False,
        owner=None,
        organizer_email=organizer.lower() if organizer and "@" in organizer else organizer,
        location=location,
        meeting_type=None,
        status=_blank_to_none(row.get("status")),
        notes=description,
        attendees=attendees,
        external_emails=external,
        is_recurring=bool(row.get("is_recurring")),
        issues=issues,
        raw=row,
    )


def clean_attendee(value) -> tuple[str, str | None]:
    """Return (cleaned, note). A note means the value was odd and we kept a trace."""
    if not isinstance(value, str):
        return "", f"Attendee {value!r} is not text."
    text = value.strip()
    if not text:
        return "", None
    fixed = re.sub(r"\s+", "", _EMAIL_DOT.sub(".", _EMAIL_AT.sub("@", text)))
    if "@" in fixed and fixed != text:
        return fixed, f"Attendee {text!r} rewritten to {fixed}."
    if "@" in text:
        return text, None
    return text, f"Attendee {text!r} is not an email; kept as a label."


def _parse_crm_date(value) -> tuple[date | None, list[str]]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, ["Meeting date is missing."]
    if not isinstance(value, str):
        return None, [f"Meeting date is not text ({value!r})."]
    raw = value.strip()
    for fmt, odd in (("%Y-%m-%d", False), ("%m-%d/%Y", True), ("%m/%d/%Y", True)):
        try:
            parsed = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        if odd:
            return parsed, [f"Date was {raw!r}; read as {parsed.isoformat()}."]
        return parsed, []
    return None, [f"Could not read meeting date {raw!r}."]


def _parse_crm_time(value) -> tuple[int | None, list[str]]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, ["No start time on the CRM record."]
    if not isinstance(value, str):
        return None, ["Start time is not text."]
    raw = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return parsed.hour * 60 + parsed.minute, []
    return None, [f"Could not read start time {raw!r}."]


def _parse_clock(value, field: str) -> tuple[date | None, int | None, str | None, list[str]]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None, None, []
    if not isinstance(value, str):
        return None, None, None, [f"{field.capitalize()} is not text ({value!r})."]
    raw = value.strip()
    is_utc = raw.endswith("Z")
    text = raw[:-1] if is_utc else raw
    parsed = None
    used = None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            used = fmt
            break
        except ValueError:
            continue
    if parsed is None:
        return None, None, None, [f"Could not read {field} {raw!r}."]

    issues: list[str] = []
    note = None
    if used == "%Y-%m-%dT%H:%M":
        issues.append(
            f"{field.capitalize()} {raw!r} had no seconds; read as {parsed.hour:02d}:{parsed.minute:02d}."
        )
    if is_utc:
        local = parsed.replace(tzinfo=timezone.utc).astimezone(FIRM_TZ)
        note = "utc"
        issues.append(
            f"{field.capitalize()} {raw} converted to {local.strftime('%H:%M')} US Eastern ({local.tzname()})."
        )
        parsed = local.replace(tzinfo=None)
    return parsed.date(), parsed.hour * 60 + parsed.minute, note, issues


def _is_specific_person(name: str | None) -> bool:
    if not name:
        return False
    return name.strip().lower() not in {"multiple", "n/a", "na", "tbd", "unknown"}


def _blank_to_none(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    text = value.strip()
    return text or None


def _as_text(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
