"""Decide which CRM rows and calendar rows are the same meeting.

No shared id exists, so this is a same-day comparison with a few gates:

- More than 3 hours apart is a different meeting. That is what keeps the
  Fund VII roadshow prep (14:00) off the closing dinner (19:00).
- A named client has to show up in an attendee address or the title.
  "Sarah Chen organized both" is not enough — she organizes half the file.
- Internal holds (no client) need overlapping titles, or the same room at
  the same time. Otherwise "Client Reception" sticks to "Pipeline Review".
- Calendar rows are collapsed first when they share an external attendee
  and start within 90 minutes. CAL-A5 and CAL-A6 are that case (Pinnacle,
  11:00 and 11:30, both have Kevin O'Brien). The weekly syncs are not:
  same series, different days.

The two weekly syncs stay as two meetings. Recurrence is a label, not a merge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sync.normalize import Record

# See the module note. 180 covers ESG (13:00 vs 15:00) and Crestview after
# the UTC conversion (14:00 vs 15:00 ET). 90 is the duplicate window.
MAX_SKEW_MINUTES = 180
DUP_WINDOW_MINUTES = 90
MATCH_THRESHOLD = 0.55

_TITLE_STOP = {
    "the", "a", "an", "and", "or", "with", "for", "to", "of", "on", "in",
    "at", "re", "meeting", "session", "call", "sync", "discussion",
}
_ALIASES = (
    (re.compile(r"\blpac\b"), "lp advisory committee"),
    (re.compile(r"\bqbr\b"), "quarterly business review"),
    (re.compile(r"\bdd\b"), "due diligence"),
)
_CO_SUFFIX = {
    "capital", "advisors", "advisor", "holdings", "holding", "group",
    "partners", "partner", "ventures", "venture", "institutional",
    "investments", "investment", "wealth", "investors", "investor",
    "llc", "inc", "co", "company", "the", "lp", "llp",
}
_PLACE_NOISE = {
    "hq", "office", "room", "floor", "the", "virtual", "meeting",
    "conference", "main", "building",
}
_VIRTUAL = ("zoom", "teams", "google meet", "webex", "virtual")


@dataclass
class CalGroup:
    records: list[Record]

    def __post_init__(self) -> None:
        self.records = sorted(
            self.records,
            key=lambda rec: (rec.start_min is None, rec.start_min or 0, rec.source_id),
        )

    @property
    def key(self) -> tuple[str, ...]:
        return tuple(rec.source_id for rec in self.records)

    @property
    def ids(self) -> list[str]:
        return [rec.source_id for rec in self.records]

    @property
    def date(self):
        return self.records[0].date

    @property
    def start_min(self) -> int | None:
        mins = [rec.start_min for rec in self.records if rec.start_min is not None]
        return min(mins) if mins else None

    @property
    def end_min(self) -> int | None:
        mins = [rec.end_min for rec in self.records if rec.end_min is not None]
        return max(mins) if mins else None

    @property
    def location(self) -> str | None:
        locs = [rec.location for rec in self.records if rec.location]
        if not locs:
            return None
        return max(locs, key=len)

    @property
    def external_emails(self) -> list[str]:
        seen: list[str] = []
        for rec in self.records:
            for email in rec.external_emails:
                if email not in seen:
                    seen.append(email)
        return seen

    @property
    def all_emails(self) -> list[str]:
        seen: list[str] = []
        for rec in self.records:
            for email in rec.all_emails:
                if email and email not in seen:
                    seen.append(email)
        return seen


@dataclass
class Link:
    crm: Record | None
    group: CalGroup | None
    score: float
    reasons: list[str] = field(default_factory=list)


def cluster_calendar(records: list[Record]) -> list[CalGroup]:
    by_id = {rec.source_id: rec for rec in records}
    parent = {source_id: source_id for source_id in by_id}

    def find(source_id: str) -> str:
        while parent[source_id] != source_id:
            parent[source_id] = parent[parent[source_id]]
            source_id = parent[source_id]
        return source_id

    ids = list(by_id)
    for i, left_id in enumerate(ids):
        for right_id in ids[i + 1 :]:
            if _same_calendar_meeting(by_id[left_id], by_id[right_id]):
                parent[find(right_id)] = find(left_id)

    buckets: dict[str, list[Record]] = {}
    for source_id in ids:
        buckets.setdefault(find(source_id), []).append(by_id[source_id])
    return [CalGroup(recs) for recs in buckets.values()]


def match(crm_rows: list[Record], groups: list[CalGroup]) -> list[Link]:
    candidates: list[Link] = []
    for crm in crm_rows:
        for group in groups:
            score, reasons = assess(crm, group)
            if score >= MATCH_THRESHOLD:
                candidates.append(Link(crm, group, score, reasons))

    candidates.sort(key=lambda link: (-link.score, link.crm.source_id, link.group.ids[0]))
    used_crm: set[str] = set()
    used_cal: set[tuple[str, ...]] = set()
    chosen: list[Link] = []
    for link in candidates:
        if link.crm.source_id in used_crm or link.group.key in used_cal:
            continue
        used_crm.add(link.crm.source_id)
        used_cal.add(link.group.key)
        chosen.append(link)

    linked = list(chosen)
    for crm in crm_rows:
        if crm.source_id not in used_crm:
            linked.append(Link(crm, None, 0.0, ["No calendar row matched."]))
    for group in groups:
        if group.key not in used_cal:
            linked.append(Link(None, group, 0.0, ["No CRM row matched."]))
    return linked


def assess(crm: Record, group: CalGroup) -> tuple[float, list[str]]:
    if crm.date is None or group.date is None or crm.date != group.date:
        return 0.0, []

    delta = None
    if crm.start_min is not None and group.start_min is not None:
        delta = abs(crm.start_min - group.start_min)
        if delta > MAX_SKEW_MINUTES:
            return 0.0, []

    person = _person_reason(crm, group)
    company = bool(crm.company) and company_matches(crm.company, group)
    if crm.specific_client and not person and not company:
        return 0.0, []

    title_score = max(
        (title_jaccard(crm.title, rec.title) for rec in group.records),
        default=0.0,
    )
    same_place = bool(
        crm.location and group.location and locations_compatible(crm.location, group.location)
    )

    # No named client. Don't let a shared owner glue two internal holds together.
    if not crm.specific_client and not company:
        close = delta is not None and delta <= 30
        if title_score < 0.34 and not (same_place and close):
            return 0.0, []

    reasons = [f"Same date ({crm.date.isoformat()})"]
    score = 0.0
    if delta is None:
        score += 0.12
        reasons.append("One side has no start time")
    elif delta <= 15:
        score += 0.34
        reasons.append(f"Starts are {delta} min apart")
    elif delta <= 60:
        score += 0.22
        reasons.append(f"Starts are {delta} min apart")
    elif delta <= 120:
        score += 0.12
        reasons.append(f"Starts are {delta} min apart")
    else:
        score += 0.05
        reasons.append(f"Starts are {delta} min apart")

    if person:
        score += 0.36
        reasons.append(person)
    if company:
        score += 0.24
        reasons.append(f"Company lines up ({crm.company})")
    if _owner_on_calendar(crm, group):
        score += 0.08
        reasons.append(f"{crm.owner} is on the calendar")
    if title_score >= 0.34:
        score += 0.2 * title_score
        reasons.append("Titles overlap")
    elif title_score:
        score += 0.2 * title_score
    if same_place:
        score += 0.08
        reasons.append("Locations look like the same place")
    return score, reasons


def title_tokens(title: str | None) -> set[str]:
    text = (title or "").lower().replace("&", " and ").replace("+", " ")
    for pattern, replacement in _ALIASES:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return {token for token in text.split() if token not in _TITLE_STOP and len(token) > 1}


def title_jaccard(left: str | None, right: str | None) -> float:
    a = title_tokens(left)
    b = title_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def company_matches(company: str, group: CalGroup) -> bool:
    phrase = _company_phrase(company)
    if not phrase:
        return False
    title_blob = _norm_words(" ".join(rec.title for rec in group.records))
    if phrase in title_blob:
        return True
    compact = phrase.replace(" ", "")
    keys = [token for token in phrase.split() if len(token) >= 5]
    for email in group.external_emails:
        stem = _domain_stem(email)
        if len(compact) >= 4 and (stem.startswith(compact) or (len(stem) >= 4 and compact.startswith(stem))):
            return True
        for key in keys:
            if stem.startswith(key):
                return True
    for key in keys:
        if re.search(rf"\b{re.escape(key)}\b", title_blob):
            return True
    return False


def locations_compatible(left: str | None, right: str | None) -> bool:
    """True when we should NOT call this a conflict.

    Missing is unknown, not a disagreement. "Boston Office" and
    "Boston Office - Room 301" are the same place. "Zoom" and an NYC
    office are not. "The Palm - DC" and "The Palm Restaurant" share
    the venue name, so those count as the same place.
    """
    if not left or not right:
        return True
    a = _norm_words(left)
    b = _norm_words(right)
    if a == b or a in b or b in a:
        return True
    if looks_virtual(a) and looks_virtual(b):
        return True
    ta = _place_tokens(left)
    tb = _place_tokens(right)
    if not ta or not tb:
        return False
    return bool(ta & tb)


def looks_virtual(value: str | None) -> bool:
    if not value:
        return False
    text = value.lower()
    return any(hint in text for hint in _VIRTUAL)


def place_kind(meeting_type: str | None, location: str | None) -> str:
    if looks_virtual(location):
        return "virtual"
    if location:
        return "physical"
    kind = (meeting_type or "").strip().lower()
    if kind == "virtual":
        return "virtual"
    if kind == "in-person":
        return "physical"
    return "unknown"


def status_bucket(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().lower()
    if text in {"cancelled", "canceled"}:
        return "cancelled"
    if text == "tentative":
        return "tentative"
    # Completed / confirmed / scheduled are lifecycle words, not a disagreement.
    if text in {"completed", "complete", "confirmed", "scheduled"}:
        return "active"
    return text


def _same_calendar_meeting(left: Record, right: Record) -> bool:
    if left.date is None or left.date != right.date:
        return False
    if left.start_min is None or right.start_min is None:
        return False
    if abs(left.start_min - right.start_min) > DUP_WINDOW_MINUTES:
        return False
    shared = set(left.external_emails) & set(right.external_emails)
    if shared:
        return True
    if left.external_emails or right.external_emails:
        return False
    if not left.organizer_email or left.organizer_email != right.organizer_email:
        return False
    return title_jaccard(left.title, right.title) >= 0.5


def _person_reason(crm: Record, group: CalGroup) -> str | None:
    if not crm.specific_client or not crm.client_name:
        return None
    target = _person_key(crm.client_name)
    target_parts = set(target.split())
    for email in group.external_emails:
        candidate = _person_key(_email_local(email))
        parts = set(candidate.split())
        if candidate == target or (target_parts and target_parts <= parts):
            return f"{crm.client_name} matches {email}"
    blob = _person_key(" ".join(rec.title for rec in group.records))
    if target and target in blob:
        return f"{crm.client_name} is in the calendar title"
    return None


def _owner_on_calendar(crm: Record, group: CalGroup) -> bool:
    if not crm.owner:
        return False
    target = set(_person_key(crm.owner).split())
    if not target:
        return False
    for email in group.all_emails:
        if "@" not in email:
            continue
        parts = set(_person_key(_email_local(email)).split())
        if target <= parts:
            return True
    return False


def _company_phrase(company: str) -> str:
    tokens = [
        token
        for token in _norm_words(company).split()
        if token not in _CO_SUFFIX
    ]
    return " ".join(tokens)


def _domain_stem(email: str) -> str:
    host = email.split("@")[-1].lower()
    labels = host.split(".")
    if len(labels) >= 2:
        labels = labels[:-1]
    return "".join(labels)


def _place_tokens(value: str) -> set[str]:
    text = re.sub(r"https?://\S+", " ", value.lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return {token for token in text.split() if token not in _PLACE_NOISE and not token.isdigit() and len(token) > 1}


def _norm_words(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _person_key(value: str) -> str:
    text = value.lower().replace("'", "").replace("’", "").replace("`", "")
    text = re.sub(r"[^a-z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _email_local(email: str) -> str:
    local = email.split("@")[0]
    return re.sub(r"[._-]+", " ", local)
