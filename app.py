#!/usr/bin/env python3
"""Meeting list API plus the page in web/.

The matcher lives in sync/. This file only serves it.
`python app.py` after the packages in requirements.txt are installed.
"""

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sync.present import load_report

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
VIEWS = {"all", "conflicts", "both", "crm", "calendar", "issues"}

app = FastAPI(title="Meeting sync", docs_url="/docs", redoc_url=None)

_report = None


def reset(data_dir=None):
    global _report
    _report = load_report(data_dir) if data_dir else load_report()
    return _report


def get_report():
    if _report is None:
        return reset()
    return _report


def apply_view(meetings, view, query):
    if view not in VIEWS:
        raise ValueError(view)
    rows = list(meetings)
    if view == "conflicts":
        rows = [row for row in rows if row["conflicts"]]
    elif view == "both":
        rows = [row for row in rows if row["crm_ids"] and row["calendar_ids"]]
    elif view == "crm":
        rows = [row for row in rows if row["crm_ids"] and not row["calendar_ids"]]
    elif view == "calendar":
        rows = [row for row in rows if row["calendar_ids"] and not row["crm_ids"]]
    elif view == "issues":
        rows = [row for row in rows if row["issues"]]
    needle = (query or "").strip().lower()
    if needle:
        rows = [row for row in rows if needle in _haystack(row)]
    return rows


def _haystack(row):
    parts = [
        row["title"],
        row["client"],
        row["company"],
        row["owner"],
        row["where"],
        row["when"] or "",
        row["status"],
        row["time_label"],
        *row["crm_ids"],
        *row["calendar_ids"],
    ]
    for item in row["conflicts"]:
        parts.append(item["field"])
        parts.append(item["detail"])
    parts.extend(row["observations"])
    for issue in row["issues"]:
        parts.append(issue["id"])
        parts.append(issue["message"])
    for field in row["fields"]:
        parts.append(field["label"])
        parts.append(field["crm"] or "")
        parts.append(field["calendar"] or "")
    return " ".join(parts).lower()


@app.get("/api/health")
def health():
    return {"ok": True, "meetings": get_report()["summary"]["meetings"]}


@app.get("/api/meetings")
def list_meetings(view: str = "all", q: str = ""):
    if view not in VIEWS:
        raise HTTPException(status_code=400, detail="unknown view")
    report = get_report()
    return {"summary": report["summary"], "meetings": apply_view(report["meetings"], view, q)}


@app.get("/api/meetings/{meeting_id}")
def one_meeting(meeting_id: str):
    for meeting in get_report()["meetings"]:
        if meeting["id"] == meeting_id:
            return meeting
    raise HTTPException(status_code=404, detail="not found")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


# After the API routes, so /api/... is not swallowed by the static mount.
app.mount("/", StaticFiles(directory=WEB), name="web")


def main():
    port = int(os.environ.get("PORT", "8000"))
    get_report()
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
