# Meeting sync

Reads the CRM export and the calendar export, decides which rows are the same meeting, and serves that list. Disagreements stay visible. The JSON files are not rewritten.

## Run

Python 3.10 or newer (developed on 3.12). From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:8000. If 8000 is taken, `PORT=8001 python app.py`.

`python app.py` is the run command. Open the page for the meeting list. http://127.0.0.1:8000/docs is only the route list.

The page reads the same payload as these routes:

- `GET /api/meetings`
- `GET /api/meetings?view=conflicts|both|crm|calendar|issues&q=zoom`
- `GET /api/meetings/CRM-1002+CAL-A2`
- `GET /api/health`

`python -m sync` prints the same list in the terminal, which is useful when you don't want the browser.

With the same virtualenv active:

```bash
python -m unittest discover -s tests
```

Those tests are the regression check. They pin which CRM id joins which calendar id, which five rows actually disagree, and that the messy source values (`03-15/2025`, the `[at]` address, the `Z` timestamp) are still sitting in `data/`. Parsing them is the job. Editing the files to make the matcher easier is not.

## What the page is for

A row is one meeting. Sources says CRM, calendar, or both. Click the row and each field is shown from both sides. A highlighted field is a disagreement. "Boston Office" versus "Boston Office - Room 301" is not one — the calendar is just more specific. "Conflicts only" hides the rows that agree. Parse problems (the bad lunch date, the rewritten email, the UTC timestamp) are listed under that table.

Five rows disagree:

- Summit, Mar 12. CRM says in person at the NYC office. The invite is a Zoom link.
- Crestview, Mar 13. CRM says 14:00. The calendar is `19:00Z`, which is 15:00 EDT. Read as EST it would be 14:00. DST started 9 March 2025, so the hour depends on the offset you assume. I convert `Z` to US Eastern and still flag it.
- Pinnacle, Mar 17. `CAL-A5` and `CAL-A6` are the same hold: Kevin O'Brien on both, 30 minutes apart, the later copy adds Sandra Mills. CRM 11:00 agrees with `CAL-A5`.
- Board prep, Mar 19. CRM is cancelled (the note says it moved to 3/26). The calendar hold is still confirmed.
- ESG, Mar 27. Same people, 13:00 in the CRM and 15:00 on the calendar.

A few rows never find a partner. Lakeshore (CRM-1003) and both Northwind meetings (CRM-1010, CRM-1020) are CRM only. The two weekly syncs, the client reception, and the Fund VII roadshow prep are calendar only. The weekly syncs are one series on two days, so they stay two meetings. The roadshow at 14:00 on Mar 28 is not the closing dinner at 19:00.

## How a match is decided

Same calendar date is required. There is no shared id.

A named client has to show up on the invite (the address, or the title). Sarah Chen organizes a lot of these; "same owner" is a small bump, not a match on its own.

Company is the loose part. `meridiancap.com` counts for Meridian Capital, `summitadv.com` for Summit Advisors, and so on. "Fund VII" is matched as a phrase, because "fund" alone would stick to too many rows.

Times can be off by up to 3 hours and still match, if the people agree. That is wide enough for the ESG meeting and for Crestview after the timezone conversion. It is not wide enough to glue the 14:00 roadshow prep to the 19:00 dinner. If one side has no time (David Park's follow-up, CRM-1007), the time is not held against it, and a missing time is not called a conflict.

Internal holds (no client) need the titles to overlap, or the same room at the same time. Otherwise the client reception glues itself to the pipeline review just because both are on March 14. `LPAC` is treated as "LP advisory committee" and `QBR` as "quarterly business review" before that comparison. Those two would not match on the raw tokens.

Calendar duplicates are collapsed before any of that. Two rows, same day, start within 90 minutes, sharing an outside attendee. Pinnacle is the only pair that hits it. The rule is in `sync/reconcile.py` (`DUP_WINDOW_MINUTES`). If you think A5 and A6 are a pre-meeting plus the meeting, that constant is the knob, and the test `test_pinnacle_copies_stay_one_meeting` is what will break.

Offices in this file are HQ, NYC, Boston, and DC, so the one UTC timestamp is read in `America/New_York`.

## Decisions

CRM is where the client name comes from. The calendar is where the clock and the room come from when the two sides agree. When they don't agree, the page shows both and does not pick a winner.

Missing is unknown, not a conflict. "Completed" versus "confirmed" is the same meeting described by two products, not a conflict. Cancelled versus still-on-the-calendar is.

Title wording is almost always different (CRM "Investor Update", calendar "Pinnacle Group - Q1 Update"). Showing both is the point. Flagging every title would light up the whole list and hide Summit and Crestview.

An extra person on the invite is a note, not a conflict. Anna Lee at Summit, Sandra Mills at Pinnacle, Raj Patel at the Atlas pitch. Priya Sharma organized the LPAC prep; Sarah Chen owns it in the CRM and is on the invite. Those notes are on the meeting as `observations`, and `python -m sync` prints them. The page does not give them a separate panel.

Data notes are separate from disagreements: the Atlas lunch date `03-15/2025`, the missing time, `raj.patel[at]atlasvc.com`, `external-guests`, the reception with no attendees and no location, the Crestview timestamp that needed a timezone.

The service reads the files at startup and only reads them. Restart to pick up an edited export.

## What I left alone

No login, no database, no write-back to either system. No attempt to guess which of two conflicting times is the true one. The two Northwind CRM rows are the same client on different days and were left as two meetings. Client reception has nothing to match on, so it stays calendar-only instead of being called internal.

## Time
Most of the time went into the pairings (The UTC hour, the two Fund VII events on March 28). Compare the Calendar and CRM data and noted in `docs/working-notes.md`.
On working session, with an AI assistant in the editor used to build the web page (index.js, app.js) to populated those reports and analyze the data workflow.
