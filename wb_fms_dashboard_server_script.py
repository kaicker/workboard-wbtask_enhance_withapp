user = frappe.session.user
if user == "Guest":
    frappe.throw("Login required", frappe.PermissionError)


def as_int(value, default=0):
    try:
        return int(value or default)
    except Exception:
        return default


def as_text(value):
    return str(value or "").strip()


def dt_text(value):
    return str(value) if value else None


def lookup_user_names(emails):
    emails = list({e for e in emails if e})
    if not emails:
        return {}
    rows = frappe.get_all(
        "User",
        filters=[["name", "in", emails]],
        fields=["name", "full_name"],
        limit_page_length=0,
    )
    return {r.name: (r.full_name or r.name) for r in rows}


def lookup_reference_titles(pairs):
    """Batch-fetch title-field values for (doctype, name) pairs."""
    grouped = {}
    for dt, name in pairs:
        if dt and name:
            grouped.setdefault(dt, set()).add(name)

    titles = {}
    for dt, names in grouped.items():
        try:
            title_field = frappe.get_meta(dt).title_field
        except Exception:
            continue
        if not title_field:
            continue
        try:
            rows = frappe.get_all(
                dt,
                filters=[["name", "in", list(names)]],
                fields=["name", title_field],
                limit_page_length=0,
            )
        except Exception:
            continue
        for row in rows:
            value = row.get(title_field) or row.get("name")
            titles[(dt, row.get("name"))] = value
    return titles


def compute_delay_minutes(task):
    if not task.get("end_datetime"):
        return None

    planned = frappe.utils.get_datetime(task.get("end_datetime"))
    actual_value = task.get("completed_on") or task.get("done_on")

    if actual_value:
        actual = frappe.utils.get_datetime(actual_value)
    elif task.get("status") in ("Open", "Overdue"):
        actual = frappe.utils.now_datetime()
    else:
        return None

    return int((actual - planned).total_seconds() / 60)


def format_delay_label(minutes):
    if minutes is None:
        return ""
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    hours = minutes // 60
    mins = minutes % 60
    if hours:
        return "{0}{1}h {2}m".format(sign, hours, mins)
    return "{0}{1}m".format(sign, mins)


def compute_status_bucket(task):
    status = task.get("status")
    delay = task.get("delay_minutes")
    if status == "Completed":
        return "late" if delay and delay > 0 else "completed"
    if status == "Done":
        return "done"
    if status == "Overdue":
        return "late"
    return "open"


def build_template_catalog(template_docs, user_names):
    catalog = {}
    for template_name, doc in template_docs.items():
        steps = []
        for row in doc.get("steps") or []:
            assignee = row.assign_to or ""
            steps.append({
                "key": "S{0}".format(row.step_no or 0),
                "kind": "Sequential",
                "no": row.step_no or 0,
                "title": row.title or "Step {0}".format(row.step_no or ""),
                "who": user_names.get(assignee, assignee),
                "how": frappe.utils.strip_html(row.description or "")[:160],
                "when": "After previous step" if (row.step_no or 0) > 1 else "Run start",
                "offset_minutes": row.planned_offset_minutes or 0,
            })

        scheduled = []
        for row in doc.get("scheduled_tasks") or []:
            direction = row.offset_direction or "Before"
            offset_days = row.offset_days or 0
            ref_field = row.reference_date_field or ""
            due_time = row.due_time or ""
            assignee = row.assign_to or ""
            scheduled.append({
                "key": "T{0}".format(row.schedule_no or 0),
                "kind": "Scheduled",
                "no": row.schedule_no or 0,
                "title": row.title or "Scheduled Task",
                "who": user_names.get(assignee, assignee),
                "how": frappe.utils.strip_html(row.description or "")[:160],
                "when": "{0} {1} day(s) {2} {3}".format(
                    offset_days,
                    "before" if direction == "Before" else "after",
                    ref_field,
                    due_time,
                ).strip(),
                "reference_date_field": ref_field,
                "offset_direction": direction,
                "offset_days": offset_days,
                "due_time": due_time,
            })

        catalog[template_name] = {
            "name": doc.name,
            "title": doc.name,
            "reference_doctype": doc.reference_doctype,
            "steps": steps,
            "scheduled": scheduled,
            "columns": steps + scheduled,
        }
    return catalog


fms_template = as_text(frappe.form_dict.get("fms_template"))
reference_doctype = as_text(frappe.form_dict.get("reference_doctype"))
reference_name = as_text(frappe.form_dict.get("reference_name"))
status_filter = as_text(frappe.form_dict.get("status"))
search = as_text(frappe.form_dict.get("search")).lower()
assigned_to = as_text(frappe.form_dict.get("assigned_to"))
limit = min(max(as_int(frappe.form_dict.get("limit_page_length"), 300), 50), 1000)
start = max(as_int(frappe.form_dict.get("limit_start"), 0), 0)

filters = [
    ["task_type", "=", "FMS"],
    ["source_fms_template", "is", "set"],
    ["fms_run_id", "is", "set"],
]

if fms_template:
    filters.append(["source_fms_template", "=", fms_template])
if reference_doctype:
    filters.append(["reference_doctype", "=", reference_doctype])
if reference_name:
    filters.append(["reference_name", "=", reference_name])
if status_filter and status_filter != "all":
    filters.append(["status", "=", status_filter])
if assigned_to:
    filters.append(["assign_to", "=", assigned_to])

fields = [
    "name", "title", "priority", "status", "due_date", "end_datetime",
    "assign_from", "assign_to", "task_type", "description", "timeliness",
    "creation", "done_on", "completed_on", "triggered_on",
    "reference_doctype", "reference_name",
    "source_fms_template", "fms_task_kind", "fms_step_no", "fms_schedule_no", "fms_run_id",
]

raw_tasks = frappe.get_all(
    "WB Task",
    fields=fields,
    filters=filters,
    order_by="modified desc",
    limit_start=start,
    limit_page_length=limit,
)

if search:
    filtered = []
    for task in raw_tasks:
        haystack = " ".join([
            task.get("name") or "",
            task.get("title") or "",
            task.get("reference_doctype") or "",
            task.get("reference_name") or "",
            task.get("assign_to") or "",
            task.get("assign_from") or "",
            task.get("source_fms_template") or "",
            task.get("status") or "",
        ]).lower()
        if search in haystack:
            filtered.append(task)
    raw_tasks = filtered

# Preload templates referenced by the result set so we can both build the
# catalog and collect template-side assignee emails in one pass.
template_names = list({t.get("source_fms_template") for t in raw_tasks if t.get("source_fms_template")})
template_docs = {}
for tn in template_names:
    try:
        template_docs[tn] = frappe.get_doc("FMS Template", tn)
    except Exception:
        continue

# Collect every email we need to resolve to a full name (tasks + template rows).
emails = []
for task in raw_tasks:
    emails.append(task.get("assign_to"))
    emails.append(task.get("assign_from"))
for doc in template_docs.values():
    for row in (doc.get("steps") or []):
        emails.append(row.assign_to)
    for row in (doc.get("scheduled_tasks") or []):
        emails.append(row.assign_to)
user_names = lookup_user_names(emails)

templates = build_template_catalog(template_docs, user_names)

# Batch reference-doc title lookups instead of one get_meta + db.get_value per task.
ref_pairs = list({
    (t.get("reference_doctype"), t.get("reference_name"))
    for t in raw_tasks
    if t.get("reference_doctype") and t.get("reference_name")
})
ref_titles = lookup_reference_titles(ref_pairs)

runs_map = {}
for task in raw_tasks:
    key = "|".join([
        task.get("source_fms_template") or "",
        task.get("fms_run_id") or "",
        task.get("reference_doctype") or "",
        task.get("reference_name") or "",
    ])

    if key not in runs_map:
        ref_dt = task.get("reference_doctype")
        ref_name = task.get("reference_name")
        runs_map[key] = {
            "key": key,
            "source_fms_template": task.get("source_fms_template"),
            "fms_run_id": task.get("fms_run_id"),
            "reference_doctype": ref_dt,
            "reference_name": ref_name,
            "reference_title": ref_titles.get((ref_dt, ref_name), ref_name or ""),
            "tasks": [],
            "tasks_by_key": {},
            "status_counts": {"Open": 0, "Overdue": 0, "Done": 0, "Completed": 0},
            "first_planned": None,
            "last_actual": None,
            "max_delay_minutes": None,
        }

    task["assign_to_name"] = user_names.get(task.get("assign_to"), task.get("assign_to"))
    task["assign_from_name"] = user_names.get(task.get("assign_from"), task.get("assign_from"))
    task["planned"] = dt_text(task.get("end_datetime"))
    task["actual_done"] = dt_text(task.get("done_on"))
    task["actual_completed"] = dt_text(task.get("completed_on"))
    task["delay_minutes"] = compute_delay_minutes(task)
    task["delay_label"] = format_delay_label(task.get("delay_minutes"))
    task["bucket"] = compute_status_bucket(task)

    if task.get("fms_task_kind") == "Scheduled":
        task_key = "T{0}".format(task.get("fms_schedule_no") or 0)
    else:
        task_key = "S{0}".format(task.get("fms_step_no") or 0)
    task["column_key"] = task_key

    run = runs_map[key]
    run["tasks"].append(task)
    run["tasks_by_key"][task_key] = task

    status_value = task.get("status")
    if status_value in run["status_counts"]:
        run["status_counts"][status_value] = run["status_counts"][status_value] + 1

    if task.get("end_datetime") and (not run["first_planned"] or str(task.get("end_datetime")) < run["first_planned"]):
        run["first_planned"] = str(task.get("end_datetime"))
    actual_value = task.get("completed_on") or task.get("done_on")
    if actual_value and (not run["last_actual"] or str(actual_value) > run["last_actual"]):
        run["last_actual"] = str(actual_value)
    if task.get("delay_minutes") is not None:
        if run["max_delay_minutes"] is None or task.get("delay_minutes") > run["max_delay_minutes"]:
            run["max_delay_minutes"] = task.get("delay_minutes")

runs = list(runs_map.values())
runs.sort(
    key=lambda r: (
        r["status_counts"].get("Overdue", 0),
        r["max_delay_minutes"] or 0,
        r["first_planned"] or "",
    ),
    reverse=True,
)

total_tasks = len(raw_tasks)
open_tasks = len([t for t in raw_tasks if t.get("status") == "Open"])
overdue_tasks = len([t for t in raw_tasks if t.get("status") == "Overdue"])
done_tasks = len([t for t in raw_tasks if t.get("status") == "Done"])
completed_tasks = len([t for t in raw_tasks if t.get("status") == "Completed"])
late_tasks = len([
    t for t in raw_tasks
    if (t.get("delay_minutes") or 0) > 0 and t.get("status") in ("Done", "Completed", "Overdue")
])
delay_values = [
    t.get("delay_minutes") for t in raw_tasks
    if t.get("delay_minutes") is not None and t.get("delay_minutes") > 0
]
avg_delay = int(sum(delay_values) / len(delay_values)) if delay_values else 0

template_options = frappe.get_all(
    "FMS Template",
    filters={"enabled": 1},
    fields=["name", "reference_doctype"],
    order_by="name asc",
    limit_page_length=0,
)

frappe.response["message"] = {
    "ok": True,
    "user": user,
    "generated_at": frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
    "filters": {
        "fms_template": fms_template,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "status": status_filter,
        "search": search,
        "assigned_to": assigned_to,
    },
    "kpis": {
        "runs": len(runs),
        "total_tasks": total_tasks,
        "open_tasks": open_tasks,
        "overdue_tasks": overdue_tasks,
        "done_tasks": done_tasks,
        "completed_tasks": completed_tasks,
        "late_tasks": late_tasks,
        "avg_delay_minutes": avg_delay,
        "avg_delay_label": format_delay_label(avg_delay),
    },
    "templates": templates,
    "runs": runs,
    "options": {
        "templates": template_options,
        "statuses": ["all", "Open", "Overdue", "Done", "Completed"],
    },
}
