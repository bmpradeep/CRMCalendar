"""Print the reconciliation. `python -m sync` from the repo root."""

from sync.present import load_report


def main() -> None:
    report = load_report()
    summary = report["summary"]
    print(
        f"{summary['meetings']} meetings from "
        f"{summary['crm_records']} CRM rows and {summary['calendar_records']} calendar rows"
    )
    print(
        f"in both: {summary['in_both']}   crm only: {summary['crm_only']}   "
        f"calendar only: {summary['calendar_only']}"
    )
    print(
        f"with a disagreement: {summary['with_conflicts']}   "
        f"with a data note: {summary['with_issues']}   "
        f"calendar dupes collapsed: {summary['collapsed_duplicates']}"
    )
    print()
    for meeting in report["meetings"]:
        flags = ", ".join(item["field"] for item in meeting["conflicts"]) or "-"
        ids = "+".join(meeting["crm_ids"] + meeting["calendar_ids"])
        print(f"{meeting['when'] or '????-??-??'}  {meeting['time_label']:<28}  {flags:<16}  {ids}")
        print(f"    {meeting['title']}  ·  {meeting['client'] or '—'}  ·  {meeting['owner'] or '—'}")
        for item in meeting["conflicts"]:
            print(f"    ! {item['detail']}")
        for note in meeting["observations"]:
            print(f"    - {note}")
        for issue in meeting["issues"]:
            print(f"    * {issue['id']}: {issue['message']}")
        print()


if __name__ == "__main__":
    main()
