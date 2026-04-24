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
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

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
