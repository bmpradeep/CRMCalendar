"""HTTP checks. The page uses these routes, so a broken query param is a regression."""

import json
import unittest
from urllib.parse import quote

from fastapi.testclient import TestClient

from app import apply_view, app, reset


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset()
        cls.client = TestClient(app)

    def get(self, path):
        response = self.client.get(path)
        return response.status_code, response.headers.get("content-type", ""), response.content

    def test_filters_match_the_reconcile_counts(self):
        payload = reset()
        meetings = payload["meetings"]
        self.assertEqual(len(apply_view(meetings, "conflicts", "")), 5)
        self.assertEqual(len(apply_view(meetings, "both", "")), 17)
        self.assertEqual(len(apply_view(meetings, "crm", "")), 3)
        self.assertEqual(len(apply_view(meetings, "calendar", "")), 4)
        self.assertEqual(len(apply_view(meetings, "issues", "")), payload["summary"]["with_issues"])
        zoom = apply_view(meetings, "all", "zoom")
        self.assertTrue(any(row["id"] == "CRM-1002+CAL-A2" for row in zoom))
        lakeshore = apply_view(meetings, "all", "lakeshore")
        self.assertEqual([row["id"] for row in lakeshore], ["CRM-1003"])
        with self.assertRaises(ValueError):
            apply_view(meetings, "nope", "")

    def test_list_route(self):
        status, content_type, body = self.get("/api/meetings?view=conflicts")
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        payload = json.loads(body)
        self.assertEqual(payload["summary"]["meetings"], 24)
        self.assertEqual(len(payload["meetings"]), 5)
        ids = {row["id"] for row in payload["meetings"]}
        self.assertIn("CRM-1002+CAL-A2", ids)
        self.assertIn("CRM-1004+CAL-A4", ids)

    def test_one_meeting_and_a_miss(self):
        status, _, body = self.get("/api/meetings/" + quote("CRM-1004+CAL-A4", safe=""))
        self.assertEqual(status, 200)
        row = json.loads(body)
        self.assertEqual(row["crm_ids"], ["CRM-1004"])
        self.assertEqual(row["calendar_ids"], ["CAL-A4"])
        status, _, _ = self.get("/api/meetings/no-such")
        self.assertEqual(status, 404)

    def test_unknown_view_is_400(self):
        status, _, _ = self.get("/api/meetings?view=nope")
        self.assertEqual(status, 400)

    def test_page_assets(self):
        status, content_type, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(b"Meeting sync", body)
        status, content_type, js = self.get("/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", content_type)
        self.assertIn(b"/api/meetings", js)
        status, content_type, _css = self.get("/style.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", content_type)


if __name__ == "__main__":
    unittest.main()
