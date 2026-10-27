// Loads /api/meetings and shows CRM vs calendar for the row you click.

const rowsEl = document.getElementById("rows");
const detailEl = document.getElementById("detail");
const summaryEl = document.getElementById("summary");
const conflictsOnly = document.getElementById("conflicts-only");

let meetings = [];
let selectedId = null;

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function cell(value) {
  return value ? esc(value) : "—";
}

function sources(row) {
  const names = [];
  if (row.crm_ids.length) names.push("CRM");
  if (row.calendar_ids.length) names.push("Calendar");
  return names.join(", ");
}

async function load() {
  const view = conflictsOnly.checked ? "conflicts" : "all";
  const response = await fetch("/api/meetings?view=" + view);
  if (!response.ok) {
    summaryEl.textContent = "Could not load meetings.";
    return;
  }
  const payload = await response.json();
  meetings = payload.meetings;
  const summary = payload.summary;
  summaryEl.textContent =
    summary.meetings + " meetings. " +
    summary.in_both + " in both sources. " +
    summary.with_conflicts + " with a conflict.";
  if (selectedId && !meetings.some((row) => row.id === selectedId)) {
    selectedId = null;
  }
  drawList();
  drawDetail();
}

function drawList() {
  if (!meetings.length) {
    rowsEl.innerHTML = '<tr><td colspan="4">Nothing in this view.</td></tr>';
    return;
  }
  rowsEl.innerHTML = meetings.map((row) => {
    const flags = row.conflicts.map((item) => item.field).join(", ");
    const who = [row.client, row.company].filter(Boolean).join(" · ");
    const cls = (row.conflicts.length ? "flagged " : "") + (row.id === selectedId ? "on" : "");
    return (
      '<tr class="' + cls + '" data-id="' + esc(row.id) + '">' +
      "<td>" + esc(row.when || "—") + "<br><span class=\"sub\">" + esc(row.time_label) + "</span></td>" +
      "<td><strong>" + esc(row.title) + "</strong><br><span class=\"sub\">" + esc(who) + "</span></td>" +
      "<td>" + esc(sources(row)) + "</td>" +
      "<td>" + esc(flags) + "</td>" +
      "</tr>"
    );
  }).join("");
}

function drawDetail() {
  const row = meetings.find((item) => item.id === selectedId);
  if (!row) {
    detailEl.innerHTML = "<p>Click a meeting. Each field shows the CRM value and the calendar value. A highlighted row is a disagreement.</p>";
    return;
  }

  let html = "<h2>" + esc(row.title) + "</h2>";
  html += "<p class=\"sub\">" + esc(row.crm_ids.concat(row.calendar_ids).join("  ")) + "</p>";

  row.conflicts.forEach((item) => {
    html += "<p><strong>" + esc(item.field) + ".</strong> " + esc(item.detail) + "</p>";
  });
  row.issues.forEach((issue) => {
    html += "<p class=\"issue\">" + esc(issue.id) + ": " + esc(issue.message) + "</p>";
  });

  html += "<table class=\"fields\"><thead><tr><th>Field</th><th>CRM</th><th>Calendar</th></tr></thead><tbody>";
  row.fields.forEach((field) => {
    html += '<tr class="' + (field.conflict ? "bad" : "") + '">' +
      "<td>" + esc(field.label) + "</td>" +
      "<td>" + cell(field.crm) + "</td>" +
      "<td>" + cell(field.calendar) + "</td></tr>";
  });
  html += "</tbody></table>";
  detailEl.innerHTML = html;
}

rowsEl.addEventListener("click", (event) => {
  const tr = event.target.closest("tr");
  if (!tr || !tr.dataset.id) return;
  selectedId = tr.dataset.id;
  drawList();
  drawDetail();
});

conflictsOnly.addEventListener("change", load);
load();
