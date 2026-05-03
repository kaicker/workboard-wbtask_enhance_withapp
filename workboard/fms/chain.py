# Copyright (c) 2026, Nesscale Solutions Pvt Ltd and contributors
# For license information, please see license.txt

"""FMS chain logic.

Spawns WB Tasks step-by-step as each prior task transitions to Done.

Design recap (from the design doc):
  - Planned (end_datetime) = prev_done_on + step.planned_offset_minutes.
    For Step 1, prev_done_on is the run start (now).
  - Actual is stamped on the task itself as done_on.
  - The step chain is frozen at spawn time (via snapshot on the spawned task).
    Template edits affect future runs only, not in-flight runs.
  - Title is 'Step N: <step.title> \u2014 <rendered title_template>'.
"""

import uuid

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, get_datetime, getdate, now_datetime, nowdate

from workboard.utils import _context


def new_run_id(template_name: str) -> str:
	return f"{template_name}::{uuid.uuid4().hex[:8]}"


def spawn_step(template, step_no: int, run_id: str, reference_doc=None, prev_done_on=None):
	"""Create the WB Task for `step_no` of `template` and return the saved doc.

	`template` is the FMS Template Document (not just the name) so we can
	access the frozen child rows without re-fetching.
	"""
	step = _find_step(template, step_no)
	if not step:
		return None

	# Render base title via Jinja, then prefix with 'Step N:' + step.title
	base_title = _render_title(template.title_template, reference_doc)
	title = f"Step {step.step_no}: {step.title} \u2014 {base_title}" if base_title else f"Step {step.step_no}: {step.title}"

	# Planned = prior step's done_on (or now for step 1) + planned_offset
	anchor = get_datetime(prev_done_on) if prev_done_on else now_datetime()
	end_datetime = add_to_date(anchor, seconds=cint(step.planned_offset_minutes or 0))

	# Description: render the step's own description through Jinja with the ref doc
	ctx = _context(reference_doc) if reference_doc else {"doc": None}
	description = (
		frappe.render_template(step.description, ctx)
		if step.description
		else f"FMS: {template.name} — Step {step.step_no}"
	)

	reference_doctype = reference_doc.doctype if reference_doc else None
	reference_name = reference_doc.name if reference_doc else None

	task_doc = {
		"doctype": "WB Task",
		"title": title,
		"description": description,
		"priority": step.priority,
		"assign_from": "Administrator",
		"assign_to": step.assign_to,
		"status": "Open",
		"task_type": "FMS",
		"has_checklist": cint(step.has_checklist or 0),
		"checklist_template": step.checklist_template,
		"depends_on_time": 1,
		"end_datetime": end_datetime,
		"triggered_on": now_datetime(),
		"reference_doctype": reference_doctype,
		"reference_name": reference_name,
		"source_fms_template": template.name,
		"fms_task_kind": "Sequential",
		"fms_step_no": step.step_no,
		"fms_run_id": run_id,
	}

	# Apply the FMS-specific naming series if the template defines one.
	# We set `name` via frappe.model.naming.make_autoname so Frappe's .#### counter works.
	if template.task_naming_series:
		from frappe.model.naming import make_autoname
		task_doc["name"] = make_autoname(template.task_naming_series, doctype="WB Task")

	doc = frappe.get_doc(task_doc)
	doc.flags.ignore_permissions = True
	doc.fetch_checklist()
	doc.insert(ignore_permissions=True)
	return doc


def advance_on_done(task_doc):
	"""Called from WB Task.validate() when status transitions to Done.

	If this task belongs to an FMS run, spawn the next step (if any).
	"""
	if task_doc.task_type != "FMS" or not task_doc.source_fms_template or not task_doc.fms_run_id:
		return

	template = frappe.get_doc("FMS Template", task_doc.source_fms_template)
	next_step = _find_next_step(template, task_doc.fms_step_no)
	if not next_step:
		return

	# Idempotency: don't spawn again if the next step for this run already exists
	existing = frappe.db.exists(
		"WB Task",
		{
			"source_fms_template": template.name,
			"fms_run_id": task_doc.fms_run_id,
			"fms_step_no": next_step.step_no,
		},
	)
	if existing:
		return

	reference_doc = None
	if task_doc.reference_doctype and task_doc.reference_name:
		try:
			reference_doc = frappe.get_doc(task_doc.reference_doctype, task_doc.reference_name)
		except frappe.DoesNotExistError:
			reference_doc = None

	spawn_step(
		template=template,
		step_no=next_step.step_no,
		run_id=task_doc.fms_run_id,
		reference_doc=reference_doc,
		prev_done_on=task_doc.done_on or now_datetime(),
	)


def trigger_due_scheduled_tasks():
	"""Create due FMS Scheduled Tasks for existing FMS runs.

	Runs are inferred from existing FMS WB Tasks. This intentionally does not
	require the sequential chain to still be open; a scheduled follow-up can be
	created even after the linear FMS steps are complete.
	"""
	try:
		for run in _iter_fms_runs_with_reference():
			_create_due_scheduled_tasks_for_run(run)
	except Exception:
		frappe.log_error(
			title=_("WorkBoard FMS scheduled task error"),
			message=frappe.get_traceback(),
		)


def _iter_fms_runs_with_reference():
	rows = frappe.get_all(
		"WB Task",
		filters=[
			["WB Task", "task_type", "=", "FMS"],
			["WB Task", "source_fms_template", "is", "set"],
			["WB Task", "fms_run_id", "is", "set"],
			["WB Task", "reference_doctype", "is", "set"],
			["WB Task", "reference_name", "is", "set"],
		],
		fields=[
			"source_fms_template",
			"fms_run_id",
			"reference_doctype",
			"reference_name",
		],
		limit_page_length=0,
	)

	seen = set()
	for row in rows:
		key = (
			row.source_fms_template,
			row.fms_run_id,
			row.reference_doctype,
			row.reference_name,
		)
		if key in seen:
			continue
		seen.add(key)
		yield row


def _create_due_scheduled_tasks_for_run(run):
	try:
		template = frappe.get_doc("FMS Template", run.source_fms_template)
	except frappe.DoesNotExistError:
		return

	if not template.enabled or not (template.scheduled_tasks or []):
		return

	if template.reference_doctype and run.reference_doctype != template.reference_doctype:
		return

	try:
		reference_doc = frappe.get_doc(run.reference_doctype, run.reference_name)
	except frappe.DoesNotExistError:
		return

	for scheduled in template.scheduled_tasks or []:
		try:
			if _scheduled_task_exists(template.name, run.fms_run_id, scheduled.schedule_no):
				continue
			if not _scheduled_task_due_today(scheduled, reference_doc):
				continue
			if scheduled.condition and not frappe.safe_eval(
				scheduled.condition, None, _context(reference_doc)
			):
				continue
			spawn_scheduled_task(template, scheduled, run.fms_run_id, reference_doc)
			frappe.db.commit()
		except Exception:
			frappe.log_error(
				title=_("WorkBoard FMS scheduled task row error"),
				message=frappe.get_traceback(),
			)


def spawn_scheduled_task(template, scheduled, run_id: str, reference_doc):
	"""Create a scheduled FMS WB Task for one scheduled row."""
	if not scheduled:
		return None

	ctx = _context(reference_doc)
	base_title = _render_title(template.title_template, reference_doc)
	row_title = (
		frappe.render_template(scheduled.title, ctx)
		if scheduled.title
		else _("Scheduled Task")
	)
	title = f"{row_title} — {base_title}" if base_title else row_title

	description = (
		frappe.render_template(scheduled.description, ctx)
		if scheduled.description
		else f"FMS: {template.name} — Scheduled {scheduled.schedule_no}"
	)

	due_time = scheduled.due_time or "18:00:00"
	end_datetime = get_datetime(f"{nowdate()} {due_time}")

	task_doc = {
		"doctype": "WB Task",
		"title": title,
		"description": description,
		"priority": scheduled.priority,
		"assign_from": "Administrator",
		"assign_to": scheduled.assign_to,
		"status": "Open",
		"task_type": "FMS",
		"has_checklist": cint(scheduled.has_checklist or 0),
		"checklist_template": scheduled.checklist_template,
		"depends_on_time": 1,
		"end_datetime": end_datetime,
		"triggered_on": now_datetime(),
		"reference_doctype": reference_doc.doctype,
		"reference_name": reference_doc.name,
		"source_fms_template": template.name,
		"fms_task_kind": "Scheduled",
		"fms_schedule_no": scheduled.schedule_no,
		"fms_run_id": run_id,
	}

	if template.task_naming_series:
		from frappe.model.naming import make_autoname
		task_doc["name"] = make_autoname(template.task_naming_series, doctype="WB Task")

	doc = frappe.get_doc(task_doc)
	doc.flags.ignore_permissions = True
	doc.fetch_checklist()
	doc.insert(ignore_permissions=True)
	return doc


def _scheduled_task_exists(template_name, run_id, schedule_no):
	return frappe.db.exists(
		"WB Task",
		{
			"source_fms_template": template_name,
			"fms_run_id": run_id,
			"fms_schedule_no": schedule_no,
		},
	)


def _scheduled_task_due_today(scheduled, reference_doc):
	if not scheduled.reference_date_field:
		return False
	reference_value = reference_doc.get(scheduled.reference_date_field)
	if not reference_value:
		return False

	reference_date = getdate(reference_value)
	offset_days = cint(scheduled.offset_days or 0)
	if scheduled.offset_direction == "After":
		trigger_date = add_days(reference_date, offset_days)
	else:
		trigger_date = add_days(reference_date, -offset_days)
	return trigger_date == getdate(nowdate())


def _find_step(template, step_no):
	for s in template.steps or []:
		if cint(s.step_no) == cint(step_no):
			return s
	return None


def _find_next_step(template, current_step_no):
	steps = sorted(template.steps or [], key=lambda s: cint(s.step_no))
	current = cint(current_step_no)
	for s in steps:
		if cint(s.step_no) > current:
			return s
	return None


def _render_title(title_template, reference_doc):
	if not title_template:
		return ""
	try:
		ctx = _context(reference_doc) if reference_doc else {"doc": None}
		return frappe.render_template(title_template, ctx) or ""
	except Exception:
		return reference_doc.name if reference_doc else ""
