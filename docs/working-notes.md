# Working notes

Looked at both files before writing a matcher. 20 CRM rows, 22 calendar rows, no shared id. An assistant in the editor was useful for trying a pairing and throwing it out. The rules below are the ones that survived that, checked against the actual ids.

## Same meeting, different words

These I was willing to call the same meeting on a first pass, by hand:

- CRM-1001 / CAL-A1 Meridian, Mar 10, 14:00, conference room B. Easy.
- CRM-1002 / CAL-A2 Summit, Mar 12, 10:00. Same people, and the location is the interesting part: CRM says the NYC office, in person; the invite is a Zoom link. Match them and show the fight. Don't average it into one location.
- CRM-1004 / CAL-A4 Crestview. Only row in the calendar file with a `Z`. 19:00 UTC is 15:00 EDT, CRM says 14:00. If someone converted as EST (UTC-5) they land on 14:00. DST started March 9. Flag the hour, don't drop the match. Offices in the file are all East Coast, so Eastern is the zone I assumed. If that assumption is wrong, this is the row that moves.
- CRM-1005 / CAL-A5 and CAL-A6. This is the in-file duplicate. Same day, Kevin on both, 11:00 and 11:30, the second copy adds Sandra Mills. CRM notes say Kevin may bring the CIO. One meeting. Collapse the calendar side first, then match the CRM row, and say which copy the CRM time agrees with (A5).
- CRM-1007 / CAL-A8. CRM time is null. Same client, next Meridian conversation, calendar has 15:00. Missing time is a gap, not a reason to refuse the match, and not a "conflict".
- CRM-1008 / CAL-A9. Date is `03-15/2025`. Read it as March 15, leave the file alone, show that we had to.
- CRM-1009 / CAL-A10. Cancelled in CRM, still confirmed on the calendar, note says rescheduled to 3/26. There is no 3/26 board-prep row to point at. Don't invent one.
- CRM-1016 / CAL-A17. Karen White, Redwood, Mar 27, 13:00 vs 15:00. Same meeting, two hours off. This is why the time window is 3 hours and not 30 minutes.
- CRM-1017 / CAL-A20. Closing dinner, 19:00, The Palm. "The Palm - DC" and "The Palm Restaurant" are the same place. `external-guests` is a label, not an address.

## Not the same meeting

- CAL-A3 and CAL-A18. Both "Weekly Team Sync", same organizer, both recurring, a week apart. Merging those would hide a real Tuesday. Show them as a series.
- CAL-A19 roadshow prep at 14:00 on Mar 28, and the dinner at 19:00. Both say Fund VII. A title-only match sticks them together. The 3 hour cap is there because of this pair. I tried "Fund VII in the title, same day, good enough" and it was wrong.
- CAL-A11 client reception. No attendees, no location, end time missing seconds, tentative. Same day as Lakeshore (CRM-1003, 15:00) and the pipeline review (16:00). It is not either of those. Empty attendee list also must not get labeled "internal" just because the organizer is @firma.com. We don't know.
- CRM-1003 Lakeshore, CRM-1010 and CRM-1020 Northwind. No calendar row. Leave them unmatched. The two Northwind rows are the same person on different days; I did not chain them.

## Other junk in the files

- `raj.patel[at]atlasvc.com` on CAL-A16. Rewrite to a real address so the person match works, and say we did. He then shows up as on the invite but not on the CRM row, which is right — the CRM notes say Lisa is bringing the CIO, they just didn't put him in the client field.
- Completed vs confirmed (Meridian Q1) is vocabulary. Cancelled vs confirmed is not.
- More specific room ("Room 301", "12th Floor", "HQ - Conference Room B") is not a conflict with the shorter CRM location.

## What I almost did

Score on title similarity alone, with a cutoff. Falls over on Fund VII and would also be jumpy on "Update" / "Review". People and company first, title as a tie-break for internal holds.

Pick the calendar whenever they disagree, and only show a warning icon. The page would look cleaner and hide the actual question (which source is wrong). The detail view is two columns on purpose.

Store it in sqlite. There are 42 rows. Reading the JSON at startup is the whole ingest.

Ship only `/docs` and call that the frontend. The brief asks for a page that shows the meetings, which source a field came from, and where they conflict. Swagger will not do the Summit row (CRM says the NYC office, calendar says Zoom). FastAPI serves the API. The files in `web/` are the UI. The matcher did not change when the server did.

A busier page: search, six filters, same-day links, the raw JSON. Cut that. The page is the list, "Conflicts only", and the two-column field table. Extra-attendee notes stay on the payload (`observations`) and in `python -m sync`. They are not a second panel.
