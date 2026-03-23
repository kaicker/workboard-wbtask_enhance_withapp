import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, get_datetime, getdate, now_datetime, nowdate
from frappe.utils.safe_exec import get_safe_globals


def _create_task_from_rule(rule, context=None):
	title = rule.title or _("Task")
	# Append due date (dd/mm) to title for recurring tasks so each day's task is identifiable
	if cint(rule.recurring or 0):
		title = f"{title} {getdate(nowdate()).strftime('%d/%m')}"
	description = (
		frappe.render_template(rule.description, context)
		if (rule.description and context)
		else (rule.description or "")
	)

	# All tasks are time-based. Calculate end_datetime from:
	# - custom_task_due_by (fixed time of day) for recurring tasks
	# - time_limit_in_minutes (Duration in seconds, relative from now) for event tasks
	end_datetime = None
	if rule.get("custom_task_due_by") and cint(rule.recurring or 0):
		end_datetime = get_datetime(f"{nowdate()} {rule.custom_task_due_by}")
	elif rule.time_limit_in_minutes:
		# Duration field stores value in seconds
		end_datetime = add_to_date(now_datetime(), seconds=cint(rule.time_limit_in_minutes))

	# Use Administrator as default assign_from for recurring/event tasks if not specified
	assign_from = rule.assign_from
	if not assign_from and (cint(rule.recurring or 0) or cint(rule.event or 0)):
		assign_from = "Administrator"

	# Metadata for traceability: when/why the task was created
	triggered_on = now_datetime()
	reference_doctype = None
	reference_name = None
	if context and context.get("doc"):
		reference_doctype = context["doc"].doctype
		reference_name = context["doc"].name

	doc = frappe.get_doc(
		{
			"doctype": "WB Task",
			"title": title,
			"description": description,
			"priority": rule.priority,
			"assign_from": assign_from,
			"assign_to": rule.assign_to,
			"status": "Open",
			"task_type": "Auto",
			"has_checklist": cint(rule.has_checklist or 0),
			"checklist_template": rule.checklist_template,
			"depends_on_time": 1,
			"end_datetime": end_datetime,
			"triggered_on": triggered_on,
			"source_rule": rule.name,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		}
	)
	doc.fetch_checklist()
	doc.save(ignore_permissions=True)
	return doc


def _context(doc):
	return {
		"doc": doc,
		"nowdate": nowdate,
		"frappe": frappe._dict(utils=get_safe_globals().get("frappe").get("utils")),
	}


@frappe.whitelist()
def get_workboard_settings():
	"""Get WorkBoard Settings without permission checks"""
	return frappe.get_doc("WorkBoard Settings", "WorkBoard Settings")


def seed_demo_data():
	"""Create demo WB Tasks and rules on the current site.

	This is intended for local/manual verification and is safe to run multiple times.
	"""
	from workboard.background_jobs import trigger_daily_rules, update_task_status

	frappe.set_user("Administrator")

	open_task = frappe.get_doc(
		{
			"doctype": "WB Task",
			"title": "Demo Open Task",
			"description": "Open task for WorkBoard demo",
			"priority": "High",
			"assign_from": "Administrator",
			"assign_to": "Administrator",
			"due_date": nowdate(),
			"status": "Open",
			"task_type": "Manual",
		}
	).insert(ignore_permissions=True)

	overdue_task = frappe.get_doc(
		{
			"doctype": "WB Task",
			"title": "Demo Overdue Task",
			"description": "Overdue task for WorkBoard demo",
			"priority": "Medium",
			"assign_from": "Administrator",
			"assign_to": "Administrator",
			"due_date": add_days(nowdate(), -3),
			"status": "Open",
			"task_type": "Manual",
		}
	).insert(ignore_permissions=True)

	update_task_status()
	overdue_task.reload()

	completed_task = frappe.get_doc(
		{
			"doctype": "WB Task",
			"title": "Demo Completed Task",
			"description": "Completed task for WorkBoard demo",
			"priority": "Low",
			"assign_from": "Administrator",
			"assign_to": "Administrator",
			"due_date": add_days(nowdate(), -1),
			"status": "Open",
			"task_type": "Auto",
		}
	).insert(ignore_permissions=True)
	completed_task.mark_completed()
	completed_task.reload()

	event_rule = frappe.get_doc(
		{
			"doctype": "WB Task Rule",
			"title": "Demo Event Rule",
			"description": "Task for ToDo {{ doc.name }}",
			"priority": "High",
			"assign_to": "Administrator",
			"due_days": 0,
			"enabled": 1,
			"event": 1,
			"based_on": "New",
			"reference_doctype": "ToDo",
		}
	).insert(ignore_permissions=True)

	ref_todo = frappe.get_doc(
		{"doctype": "ToDo", "description": "Demo ToDo for WorkBoard event rule"}
	).insert(ignore_permissions=True)

	event_tasks = frappe.get_all(
		"WB Task", filters={"source_rule": event_rule.name}, pluck="name"
	)

	recurring_rule = frappe.get_doc(
		{
			"doctype": "WB Task Rule",
			"title": "Demo Daily Recurring Rule",
			"description": "Recurring demo task",
			"priority": "High",
			"assign_to": "Administrator",
			"due_days": 0,
			"enabled": 1,
			"recurring": 1,
			"frequency": "Daily",
		}
	).insert(ignore_permissions=True)

	before = set(
		frappe.get_all("WB Task", filters={"source_rule": recurring_rule.name}, pluck="name")
	)
	trigger_daily_rules()
	after = set(
		frappe.get_all("WB Task", filters={"source_rule": recurring_rule.name}, pluck="name")
	)

	recurring_tasks = list(after - before)

	frappe.db.commit()

	return {
		"open_task": open_task.name,
		"overdue_task": overdue_task.name,
		"overdue_status": overdue_task.status,
		"completed_task": completed_task.name,
		"completed_status": completed_task.status,
		"event_rule": event_rule.name,
		"event_ref_todo": ref_todo.name,
		"event_tasks": event_tasks,
		"recurring_rule": recurring_rule.name,
		"recurring_tasks": recurring_tasks,
	}

