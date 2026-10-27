"""Build the payload the API and the page both use.

A missing value is a gap, not a conflict. "Completed" vs "confirmed" is the
same idea in two products, so that is not a conflict either. A cancelled CRM
row against a live calendar hold is.

When the copies disagree with each other (Pinnacle), that is its own note.
We do not also file a CRM time conflict if one of the copies agrees with the CRM.
"""

from __future__ import annotations

from pathlib import Path

from sync.normalize import hhmm, load_calendar, load_crm
from sync.reconcile import (
    CalGroup,
    Link,
    cluster_calendar,
    locations_compatible,
    looks_virtual,
    match,
    place_kind,
    status_bucket,
)
from sync.reconcile import _email_local, _owner_on_calendar, _person_key

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def load_report(data_dir: Path | None = None) -> dict:
    data_dir = Path(data_dir) if data_dir else DATA_DIR
    crm_rows = load_crm(data_dir / "crm_events.json")
    cal_rows = load_calendar(data_dir / "calendar_events.json")
    groups = cluster_calendar(cal_rows)
    links = match(crm_rows, groups)
    meetings = [build_meeting(link) for link in links]
    _attach_series(meetings)
    meetings.sort(key=lambda row: (row["when"] or "9999", row["sort_start"] or "99", row["id"]))
    for meeting in meetings:
        meeting.pop("sort_start", None)
    collapsed = sum(1 for group in groups if len(group.records) > 1)
    return {
        "summary": _summary(meetings, len(crm_rows), len(cal_rows), collapsed),
        "meetings": meetings,
    }


def build_meeting(link: Link) -> dict:
    crm = link.crm
    group = link.group
    conflicts = [item for item in (
        _time_conflict(crm, group),
        _place_conflict(crm, group),
        _status_conflict(crm, group),
        _copy_conflict(crm, group),
    ) if item]
    conflict_fields = {item["field"] for item in conflicts}

    issues = []
    if crm:
        issues.extend({"id": crm.source_id, "message": note} for note in crm.issues)
    if group:
        for rec in group.records:
            issues.extend({"id": rec.source_id, "message": note} for note in rec.issues)

    parts = []
    if crm:
        parts.append(crm.source_id)
    if group:
        parts.extend(group.ids)

    copies_differ = _copies_differ(group)
    when = None
    if crm and crm.date:
        when = crm.date.isoformat()
    elif group and group.date:
        when = group.date.isoformat()

    return {
        "id": "+".join(parts),
        "title": _title(crm, group),
        "when": when,
        "sort_start": _sort_start(crm, group),
        "time_label": _time_label(crm, group, "Time" in conflict_fields, copies_differ),
        "client": _client(crm, group),
        "company": crm.company if crm and crm.company else "",
        "owner": _owner(crm, group),
        "where": _where(crm, group, "Place" in conflict_fields),
        "status": _status_label(crm, group),
        "crm_ids": [crm.source_id] if crm else [],
        "calendar_ids": group.ids if group else [],
        "conflicts": conflicts,
        "observations": _observations(crm, group),
        "issues": issues,
        "why": list(link.reasons),
        "fields": _fields(crm, group, conflict_fields, copies_differ),
        "raw": {
            "crm": [crm.raw] if crm else [],
            "calendar": [rec.raw for rec in group.records] if group else [],
        },
        "_series": _series_key(group),
    }


def _title(crm, group) -> str:
    if crm:
        return crm.title
    return group.records[0].title


def _client(crm, group) -> str:
    if crm and crm.client_name:
        return crm.client_name
    if crm and (crm.meeting_type or "").lower() == "internal":
        return "Internal"
    if group:
        names = _external_names(group)
        if names:
            return ", ".join(names)
        if _all_internal(group):
            return "Internal"
    return ""


def _owner(crm, group) -> str:
    if crm and crm.owner:
        return crm.owner
    if group and group.records[0].organizer_email:
        return _pretty_email(group.records[0].organizer_email)
    return ""


def _where(crm, group, place_conflicts: bool) -> str:
    if place_conflicts:
        return ""
    if group and group.location:
        return group.location
    if crm and crm.location:
        return crm.location
    return ""


def _status_label(crm, group) -> str:
    if crm and crm.status:
        return crm.status
    if group:
        for rec in group.records:
            if rec.status:
                return rec.status
    return ""


def _sort_start(crm, group) -> str | None:
    mins = []
    if crm and crm.start_min is not None:
        mins.append(crm.start_min)
    if group and group.start_min is not None:
        mins.append(group.start_min)
    return hhmm(min(mins)) if mins else None


def _time_label(crm, group, time_conflicts: bool, copies_differ: bool) -> str:
    if group and copies_differ:
        return _join_copies(group, lambda rec: hhmm(rec.start_min)) or "time not set"
    if time_conflicts and crm and group:
        crm_clock = hhmm(crm.start_min)
        cal_clock = _one_clock(group)
        return f"{crm_clock} / {cal_clock}"
    if group and group.start_min is not None:
        label = hhmm(group.start_min)
        if any(rec.tz_note for rec in group.records):
            label += " ET"
        if group.end_min is not None and not copies_differ:
            label += "–" + hhmm(group.end_min)
        return label
    if crm and crm.start_min is not None:
        return hhmm(crm.start_min)
    return "time not set"


def _fields(crm, group, conflict_fields: set[str], copies_differ: bool) -> list[dict]:
    cal_start = _join_copies(group, _start_text) if group else None
    cal_end = _join_copies(group, lambda rec: hhmm(rec.end_min)) if group else None
    cal_title = _join_copies(group, lambda rec: rec.title) if group else None
    cal_loc = _join_copies(group, lambda rec: rec.location) if group else None
    cal_status = _join_copies(group, lambda rec: rec.status) if group else None
    cal_notes = _join_copies(group, lambda rec: rec.notes) if group else None
    cal_type = _calendar_type(group) if group else None
    cal_who = ", ".join(_external_names(group)) if group else None
    cal_owner = _join_copies(group, lambda rec: _pretty_email(rec.organizer_email) if rec.organizer_email else None) if group else None
    cal_people = _join_copies(group, lambda rec: ", ".join(rec.attendees) if rec.attendees else None) if group else None

    type_conflict = False
    if crm and group:
        left = place_kind(crm.meeting_type, crm.location)
        right = place_kind(None, group.location)
        type_conflict = left in {"virtual", "physical"} and right in {"virtual", "physical"} and left != right

    rows = [
        ("Title", crm.title if crm else None, cal_title, False),
        ("Date", crm.date.isoformat() if crm and crm.date else None, group.date.isoformat() if group and group.date else None, False),
        ("Start", hhmm(crm.start_min) if crm else None, cal_start, "Time" in conflict_fields or copies_differ),
        ("End", None, cal_end, copies_differ and _copies_field_differs(group, lambda rec: rec.end_min)),
        ("Client", crm.client_name if crm else None, cal_who or None, False),
        ("Company", crm.company if crm else None, None, False),
        ("Owner", crm.owner if crm else None, cal_owner, False),
        ("Location", crm.location if crm else None, cal_loc, "Place" in conflict_fields),
        ("Type", crm.meeting_type if crm else None, cal_type, type_conflict),
        ("Status", crm.status if crm else None, cal_status, "Status" in conflict_fields),
        ("Attendees", None, cal_people, copies_differ and _attendees_differ(group)),
        ("Notes", crm.notes if crm else None, cal_notes, False),
    ]
    return [
        {"label": label, "crm": left, "calendar": right, "conflict": flag}
        for label, left, right, flag in rows
    ]


def _time_conflict(crm, group) -> dict | None:
    if crm is None or group is None or crm.start_min is None:
        return None
    clocks = [(rec, rec.start_min) for rec in group.records if rec.start_min is not None]
    if not clocks:
        return None
    off = [(rec, mins) for rec, mins in clocks if abs(mins - crm.start_min) > 15]
    if not off:
        return None
    # One of the copies agrees with the CRM. The copy note is the right place.
    if len(clocks) > 1 and len(off) < len(clocks):
        return None
    cal_text = _one_clock(group) if len(clocks) == 1 else _join_copies(group, _start_text)
    detail = f"CRM has {hhmm(crm.start_min)}. Calendar has {cal_text}."
    rec, mins = clocks[0]
    if len(clocks) == 1 and rec.tz_note:
        detail += _dst_sentence(rec, crm.start_min, mins)
    else:
        detail += f" {abs(mins - crm.start_min)} minutes apart."
    return {"field": "Time", "detail": detail}


def _dst_sentence(rec, crm_min: int, local_min: int) -> str:
    sentence = f" The raw value is {rec.start_raw}, which is {hhmm(local_min)} US Eastern (EDT)."
    est = _est_hhmm(rec.start_raw)
    if est and est == hhmm(crm_min) and hhmm(local_min) != hhmm(crm_min):
        sentence += (
            f" Read as EST (UTC−5) it would be {est}, matching the CRM."
            " DST started 9 March 2025, so the hour depends on which offset you assume."
        )
    return sentence


def _est_hhmm(start_raw: str | None) -> str | None:
    if not start_raw or not start_raw.endswith("Z"):
        return None
    from datetime import datetime

    text = start_raw[:-1]
    parsed = None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return None
    total = (parsed.hour * 60 + parsed.minute - 5 * 60) % (24 * 60)
    return hhmm(total)


def _place_conflict(crm, group) -> dict | None:
    if crm is None or group is None:
        return None
    calendar_location = group.location
    left = place_kind(crm.meeting_type, crm.location)
    right = "unknown"
    if any(looks_virtual(rec.location) for rec in group.records):
        right = "virtual"
    elif any(rec.location for rec in group.records):
        right = "physical"
    loc_off = bool(
        crm.location and calendar_location and not locations_compatible(crm.location, calendar_location)
    )
    kind_off = left in {"virtual", "physical"} and right in {"virtual", "physical"} and left != right
    if not loc_off and not kind_off:
        return None
    if crm.meeting_type and crm.location:
        crm_text = f"{crm.meeting_type} at {crm.location}"
    else:
        crm_text = crm.location or crm.meeting_type or "blank"
    cal_text = _join_copies(group, lambda rec: rec.location) or "blank"
    return {
        "field": "Place",
        "detail": f"CRM has this as {crm_text}. Calendar location is {cal_text}.",
    }


def _status_conflict(crm, group) -> dict | None:
    if crm is None or group is None or not crm.status:
        return None
    crm_bucket = status_bucket(crm.status)
    if not crm_bucket:
        return None
    off = False
    for rec in group.records:
        bucket = status_bucket(rec.status)
        if bucket and bucket != crm_bucket:
            off = True
    if not off:
        return None
    cal_text = _join_copies(group, lambda rec: rec.status) or "blank"
    detail = f"CRM status is {crm.status}; calendar status is {cal_text}."
    if crm.notes and "cancel" in crm.notes.lower():
        detail += f" CRM note: {crm.notes}"
    return {"field": "Status", "detail": detail}


def _copy_conflict(crm, group: CalGroup | None) -> dict | None:
    if group is None or len(group.records) < 2 or not _copies_differ(group):
        return None
    bits = []
    if _copies_field_differs(group, lambda rec: rec.start_min):
        rendered = ", ".join(f"{rec.source_id} {hhmm(rec.start_min)}" for rec in group.records)
        bits.append(f"starts differ ({rendered})")
    partial = _partial_attendees(group)
    if partial:
        bits.append("attendees differ: " + "; ".join(partial))
    if _copies_field_differs(group, lambda rec: rec.location):
        rendered = ", ".join(f"{rec.source_id} \"{rec.location or 'blank'}\"" for rec in group.records)
        if all(locations_compatible(group.records[0].location, rec.location) for rec in group.records[1:]):
            bits.append(f"location wording differs ({rendered})")
        else:
            bits.append(f"locations differ ({rendered})")
    if _copies_field_differs(group, lambda rec: rec.title):
        bits.append("titles differ")
    if crm is not None and crm.start_min is not None:
        agrees = [
            rec.source_id
            for rec in group.records
            if rec.start_min is not None and abs(rec.start_min - crm.start_min) <= 15
        ]
        if agrees:
            bits.append(f"CRM start {hhmm(crm.start_min)} agrees with {', '.join(agrees)}")
    shared_emails = set(group.records[0].external_emails)
    for rec in group.records[1:]:
        shared_emails &= set(rec.external_emails)
    who = _english_join(sorted(shared_emails)) if shared_emails else "the same organizer"
    if bits:
        bits[0] = bits[0][0].upper() + bits[0][1:]
    detail = f"Two calendar records share {who} and overlap, so they are one meeting. " + "; ".join(bits) + "."
    return {"field": "Calendar copies", "detail": detail}


def _english_join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + " and " + items[-1]


def _observations(crm, group) -> list[str]:
    if crm is None or group is None:
        return []
    notes = []
    if crm.specific_client and crm.client_name:
        target = set(_person_key(crm.client_name).split())
        extras = []
        for email in group.external_emails:
            parts = set(_person_key(_email_local(email)).split())
            if target and not target <= parts:
                extras.append(_pretty_email(email))
        if extras:
            notes.append(
                "Also on the invite, not named on the CRM row: " + ", ".join(extras) + "."
            )
    if crm.owner and group.records:
        organizer = group.records[0].organizer_email
        if organizer and "@" in organizer:
            org_parts = set(_person_key(_email_local(organizer)).split())
            owner_parts = set(_person_key(crm.owner).split())
            if owner_parts and org_parts and not owner_parts <= org_parts and _owner_on_calendar(crm, group):
                notes.append(
                    f"{_pretty_email(organizer)} organized the calendar hold. "
                    f"CRM owner is {crm.owner}, who is on the invite."
                )
    return notes


def _copies_differ(group: CalGroup | None) -> bool:
    if group is None or len(group.records) < 2:
        return False
    return (
        _copies_field_differs(group, lambda rec: rec.start_min)
        or _attendees_differ(group)
        or _copies_field_differs(group, lambda rec: rec.location)
        or _copies_field_differs(group, lambda rec: rec.title)
    )


def _copies_field_differs(group: CalGroup | None, getter) -> bool:
    if group is None or len(group.records) < 2:
        return False
    values = [getter(rec) for rec in group.records]
    return any(value != values[0] for value in values[1:])


def _attendees_differ(group: CalGroup | None) -> bool:
    if group is None or len(group.records) < 2:
        return False
    sets = [set(rec.attendees) for rec in group.records]
    return any(items != sets[0] for items in sets[1:])


def _partial_attendees(group: CalGroup) -> list[str]:
    union: set[str] = set()
    for rec in group.records:
        union.update(rec.attendees)
    notes = []
    for email in sorted(union):
        owners = [rec.source_id for rec in group.records if email in rec.attendees]
        if len(owners) != len(group.records):
            notes.append(f"{email} only on {', '.join(owners)}")
    return notes


def _join_copies(group: CalGroup | None, getter) -> str | None:
    if group is None:
        return None
    pairs = [(rec.source_id, getter(rec)) for rec in group.records]
    shown = [value for _, value in pairs if value]
    if not shown:
        return None
    if len(group.records) == 1 or all(value == shown[0] for _, value in pairs):
        return shown[0]
    return "; ".join(f"{value} ({source_id})" for source_id, value in pairs if value)


def _start_text(rec) -> str | None:
    if rec.start_min is None:
        return None
    text = hhmm(rec.start_min)
    if rec.tz_note:
        text += " ET"
    return text


def _one_clock(group: CalGroup) -> str:
    rec = group.records[0]
    return _start_text(rec) or "blank"


def _calendar_type(group: CalGroup) -> str | None:
    if any(looks_virtual(rec.location) for rec in group.records):
        return "Virtual"
    if any(rec.location for rec in group.records):
        return "In-person"
    return None


def _external_names(group: CalGroup) -> list[str]:
    names = []
    for email in group.external_emails:
        label = _pretty_email(email)
        if label not in names:
            names.append(label)
    return names


def _all_internal(group: CalGroup) -> bool:
    """True only when the invite actually lists people and none are outside the firm.

    An empty attendee list is not 'internal' — Client Reception is that case,
    and calling it internal would be a guess.
    """
    attendees: list[str] = []
    for rec in group.records:
        attendees.extend(rec.attendees)
    if any("@" not in person for person in attendees):
        return False
    emails = [person for person in attendees if "@" in person]
    if not emails:
        return False
    return all(person.lower().endswith("@firma.com") for person in emails)


def _pretty_email(email: str) -> str:
    if "@" not in email:
        return email
    local = email.split("@")[0]
    local = local.replace(".", " ").replace("_", " ").replace("-", " ")
    return " ".join(part.capitalize() for part in local.split() if part)


def _series_key(group: CalGroup | None) -> str | None:
    if group is None:
        return None
    for rec in group.records:
        if rec.is_recurring:
            return f"{rec.title.strip().lower()}|{(rec.organizer_email or '').lower()}"
    return None


def _attach_series(meetings: list[dict]) -> None:
    buckets: dict[str, list[dict]] = {}
    for meeting in meetings:
        key = meeting.get("_series")
        if key:
            buckets.setdefault(key, []).append(meeting)
    for rows in buckets.values():
        if len(rows) < 2:
            continue
        for meeting in rows:
            others = [row for row in rows if row["id"] != meeting["id"]]
            text = "Recurring series, kept as separate meetings. Other occurrence: " + ", ".join(
                f"{(row['calendar_ids'] or ['?'])[0]} on {row['when']}" for row in others
            ) + "."
            meeting["observations"].append(text)
    for meeting in meetings:
        meeting.pop("_series", None)


def _summary(meetings: list[dict], crm_count: int, cal_count: int, collapsed: int) -> dict:
    return {
        "crm_records": crm_count,
        "calendar_records": cal_count,
        "meetings": len(meetings),
        "in_both": sum(1 for row in meetings if row["crm_ids"] and row["calendar_ids"]),
        "crm_only": sum(1 for row in meetings if row["crm_ids"] and not row["calendar_ids"]),
        "calendar_only": sum(1 for row in meetings if row["calendar_ids"] and not row["crm_ids"]),
        "with_conflicts": sum(1 for row in meetings if row["conflicts"]),
        "with_issues": sum(1 for row in meetings if row["issues"]),
        "collapsed_duplicates": collapsed,
    }

