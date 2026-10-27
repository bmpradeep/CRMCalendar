"""The match list is the regression net.

If a later change glues the Fund VII roadshow to the dinner, or splits the
Pinnacle copies back apart, these fail. The oddities in the JSON (bad date,
[at] address, UTC timestamp) have to stay in the files — we parse them,
we don't rewrite them.
"""

import json
import unittest
from pathlib import Path

from sync.present import load_report

ROOT = Path(__file__).resolve().parent.parent

# crm id -> calendar ids it should absorb. Order is earliest start first.
LINKS = {
    "CRM-1001": ["CAL-A1"],
    "CRM-1002": ["CAL-A2"],
    "CRM-1004": ["CAL-A4"],
    "CRM-1005": ["CAL-A5", "CAL-A6"],
    "CRM-1006": ["CAL-A7"],
    "CRM-1007": ["CAL-A8"],
    "CRM-1008": ["CAL-A9"],
    "CRM-1009": ["CAL-A10"],
    "CRM-1011": ["CAL-A12"],
    "CRM-1012": ["CAL-A13"],
    "CRM-1013": ["CAL-A14"],
    "CRM-1014": ["CAL-A15"],
    "CRM-1015": ["CAL-A16"],
    "CRM-1016": ["CAL-A17"],
    "CRM-1017": ["CAL-A20"],
    "CRM-1018": ["CAL-A21"],
    "CRM-1019": ["CAL-A22"],
}
CRM_ONLY = ["CRM-1003", "CRM-1010", "CRM-1020"]
CAL_ONLY = ["CAL-A3", "CAL-A11", "CAL-A18", "CAL-A19"]

CONFLICTS = {
    "CRM-1002+CAL-A2": {"Place"},
    "CRM-1004+CAL-A4": {"Time"},
    "CRM-1005+CAL-A5+CAL-A6": {"Calendar copies"},
    "CRM-1009+CAL-A10": {"Status"},
    "CRM-1016+CAL-A17": {"Time"},
}


def report():
    return load_report(ROOT / "data")


def by_id(payload):
    return {row["id"]: row for row in payload["meetings"]}


def cal_sort(source_id):
    # "CAL-A10" sorts before "CAL-A2" as text. Compare the number.
    return int(source_id.removeprefix("CAL-A"))


class ReconcileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = report()
        cls.rows = by_id(cls.payload)

    def test_counts(self):
        summary = self.payload["summary"]
        self.assertEqual(summary["crm_records"], 20)
        self.assertEqual(summary["calendar_records"], 22)
        self.assertEqual(summary["meetings"], 24)
        self.assertEqual(summary["in_both"], 17)
        self.assertEqual(summary["crm_only"], 3)
        self.assertEqual(summary["calendar_only"], 4)
        self.assertEqual(summary["with_conflicts"], 5)
        self.assertEqual(summary["collapsed_duplicates"], 1)

    def test_every_source_id_lands_once(self):
        crm_ids = []
        cal_ids = []
        for row in self.payload["meetings"]:
            crm_ids.extend(row["crm_ids"])
            cal_ids.extend(row["calendar_ids"])
        self.assertEqual(sorted(crm_ids), [f"CRM-{n}" for n in range(1001, 1021)])
        self.assertEqual(sorted(cal_ids, key=cal_sort), [f"CAL-A{n}" for n in range(1, 23)])
        self.assertEqual(len(crm_ids), len(set(crm_ids)))
        self.assertEqual(len(cal_ids), len(set(cal_ids)))

    def test_expected_links(self):
        got = {}
        crm_only = []
        cal_only = []
        for row in self.payload["meetings"]:
            if row["crm_ids"] and row["calendar_ids"]:
                self.assertEqual(len(row["crm_ids"]), 1)
                got[row["crm_ids"][0]] = row["calendar_ids"]
            elif row["crm_ids"]:
                crm_only.extend(row["crm_ids"])
            else:
                cal_only.extend(row["calendar_ids"])
        self.assertEqual(got, LINKS)
        self.assertEqual(sorted(crm_only), CRM_ONLY)
        self.assertEqual(sorted(cal_only, key=cal_sort), CAL_ONLY)

    def test_conflict_fields_and_nothing_else(self):
        got = {
            row_id: {item["field"] for item in row["conflicts"]}
            for row_id, row in self.rows.items()
            if row["conflicts"]
        }
        self.assertEqual(got, CONFLICTS)

    def test_summit_is_the_place_fight(self):
        row = self.rows["CRM-1002+CAL-A2"]
        detail = row["conflicts"][0]["detail"]
        self.assertIn("In-Person", detail)
        self.assertIn("NYC Office", detail)
        self.assertIn("Zoom", detail)
        self.assertTrue(any(field["label"] == "Location" and field["conflict"] for field in row["fields"]))
        self.assertTrue(any("Anna Lee" in note for note in row["observations"]))

    def test_crestview_hour_depends_on_dst(self):
        row = self.rows["CRM-1004+CAL-A4"]
        detail = row["conflicts"][0]["detail"]
        self.assertIn("14:00", detail)
        self.assertIn("15:00", detail)
        self.assertIn("DST started 9 March 2025", detail)
        self.assertIn("2025-03-13T19:00:00Z", detail)

    def test_pinnacle_copies_stay_one_meeting(self):
        self.assertNotIn("CRM-1005+CAL-A5", self.rows)
        self.assertNotIn("CRM-1005+CAL-A6", self.rows)
        row = self.rows["CRM-1005+CAL-A5+CAL-A6"]
        detail = row["conflicts"][0]["detail"]
        self.assertIn("kevin.obrien@pinnaclegp.com", detail)
        self.assertIn("sandra.mills@pinnaclegp.com only on CAL-A6", detail)
        self.assertIn("agrees with CAL-A5", detail)
        self.assertTrue(any("Sandra Mills" in note for note in row["observations"]))

    def test_board_prep_is_cancelled_on_one_side_only(self):
        row = self.rows["CRM-1009+CAL-A10"]
        detail = row["conflicts"][0]["detail"]
        self.assertIn("Cancelled", detail)
        self.assertIn("confirmed", detail)
        self.assertIn("rescheduled", detail.lower())

    def test_esg_is_two_hours_apart(self):
        detail = self.rows["CRM-1016+CAL-A17"]["conflicts"][0]["detail"]
        self.assertIn("13:00", detail)
        self.assertIn("15:00", detail)
        self.assertIn("120 minutes", detail)

    def test_weekly_syncs_are_not_duplicates(self):
        self.assertIn("CAL-A3", self.rows)
        self.assertIn("CAL-A18", self.rows)
        self.assertTrue(any("CAL-A18" in note for note in self.rows["CAL-A3"]["observations"]))
        self.assertTrue(any("CAL-A3" in note for note in self.rows["CAL-A18"]["observations"]))

    def test_roadshow_is_not_the_dinner(self):
        dinner = self.rows["CRM-1017+CAL-A20"]
        self.assertEqual(dinner["calendar_ids"], ["CAL-A20"])
        self.assertEqual(self.rows["CAL-A19"]["crm_ids"], [])
        self.assertEqual(self.rows["CAL-A19"]["when"], "2025-03-28")

    def test_lpac_organizer_is_not_the_owner(self):
        notes = self.rows["CRM-1013+CAL-A14"]["observations"]
        self.assertTrue(any("Priya Sharma" in note and "Sarah Chen" in note for note in notes))
        self.assertEqual(self.rows["CRM-1013+CAL-A14"]["conflicts"], [])

    def test_bad_inputs_are_repaired_not_rewritten(self):
        lunch = self.rows["CRM-1008+CAL-A9"]
        self.assertEqual(lunch["when"], "2025-03-15")
        self.assertEqual(lunch["raw"]["crm"][0]["meeting_date"], "03-15/2025")
        self.assertTrue(any("2025-03-15" in issue["message"] for issue in lunch["issues"]))

        pitch = self.rows["CRM-1015+CAL-A16"]
        self.assertTrue(any("raj.patel@atlasvc.com" in issue["message"] for issue in pitch["issues"]))
        self.assertTrue(any("[at]" in attendee for attendee in pitch["raw"]["calendar"][0]["attendees"]))
        self.assertTrue(any("Raj Patel" in note for note in pitch["observations"]))

        follow = self.rows["CRM-1007+CAL-A8"]
        self.assertIsNone(follow["raw"]["crm"][0]["meeting_time"])
        self.assertIn("15:00", follow["time_label"])
        self.assertEqual(follow["conflicts"], [])

    def test_reception_is_not_called_internal(self):
        row = self.rows["CAL-A11"]
        self.assertEqual(row["client"], "")
        self.assertGreaterEqual(len(row["issues"]), 3)

    def test_source_files_still_have_the_mess(self):
        # Running the reconcile must not "helpfully" clean the exports.
        load_report(ROOT / "data")
        crm = json.loads((ROOT / "data" / "crm_events.json").read_text(encoding="utf-8"))
        cal = json.loads((ROOT / "data" / "calendar_events.json").read_text(encoding="utf-8"))
        self.assertEqual(len(crm), 20)
        self.assertEqual(len(cal), 22)
        lunch = next(row for row in crm if row["crm_id"] == "CRM-1008")
        self.assertEqual(lunch["meeting_date"], "03-15/2025")
        follow = next(row for row in crm if row["crm_id"] == "CRM-1007")
        self.assertIsNone(follow["meeting_time"])
        crest = next(row for row in cal if row["event_id"] == "CAL-A4")
        self.assertTrue(crest["start_time"].endswith("Z"))
        atlas = next(row for row in cal if row["event_id"] == "CAL-A16")
        self.assertTrue(any("[at]" in attendee for attendee in atlas["attendees"]))

    def test_second_run_matches_the_first(self):
        again = [row["id"] for row in report()["meetings"]]
        self.assertEqual(again, [row["id"] for row in self.payload["meetings"]])


if __name__ == "__main__":
    unittest.main()
