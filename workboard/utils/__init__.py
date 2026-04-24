# WorkBoard Task Utilities
# Handles task creation from rules (recurring & event-based)

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, get_datetime, getdate, now_datetime, nowdate
from frappe.utils.safe_exec import get_safe_globals


def _create_task_from_rule(rule, context=None, is_event=False):
	"""Create a WB Task from a rule.

	Honors the rule's leave-handling policy when the feature flag is on. Possible
	branches:
	  * proceed   — business as usual
	  * pause     — skip creation, write an audit log row, return None
	  * delegate  — create task for backup_user, stamp Leave Tracking fields
	  * defer     — create task for original assignee but shift end_datetime to
	                the day after the leave ends, stamp Leave Tracking fields

	`is_event` flips the policy field we read: event rules use
	`on_leave_event_behavior`, recurring rules use `on_leave_behavior`.
	"""
	# --- Leave handling (gated by feature flag inside the helper) -------------
	from workboard.utils.leave import (
		leave_awareness_enabled,
		log_skip,
		resolve_assignee_for_rule,
	)

	decision = resolve_assignee_for_rule(rule, is_event=is_event)

	if decision["action"] == "pause":
		# Audit trail only — no task created.
		if leave_awareness_enabled():
			log_skip(
				rule=rule.name,
				user=rule.get("assign_to"),
				target_date=nowdate(),
				action_taken="Paused",
				leave_application=decision.get("leave_application"),
				resolution=decision.get("reason"),
			)
		return None

	effective_assign_to = decision["assign_to"] or rule.get("assign_to")
	# --------------------------------------------------------------------------

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

	# If deferring due to leave, push end_datetime to (return_date + rule's normal due time if any).
	original_end_datetime = None
	if decision["action"] == "defer" and decision.get("defer_to"):
		defer_date = decision["defer_to"]
		original_end_datetime = end_datetime
		if rule.get("custom_task_due_by") and cint(rule.recurring or 0):
			end_datetime = get_datetime(f"{defer_date} {rule.custom_task_due_by}")
		else:
			# Use end-of-day on the return date as a safe default.
			end_datetime = get_datetime(f"{defer_date} 23:59:59")

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

	# Leave Tracking fields populated only when action required it.
	leave_action = None
	delegated_from = None
	leave_application = None
	if decision["action"] == "delegate":
		leave_action = "Delegated"
		delegated_from = decision.get("delegated_from")
		leave_application = decision.get("leave_application")
	elif decision["action"] == "defer":
		leave_action = "Deferred"
		leave_application = decision.get("leave_application")

	doc = frappe.get_doc(
		{
			"doctype": "WB Task",
			"title": title,
			"description": description,
			"priority": rule.priority,
			"assign_from": assign_from,
			"assign_to": effective_assign_to,
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
			# Leave Tracking
			"leave_action": leave_action,
			"delegated_from": delegated_from,
			"leave_application": leave_application,
			"original_end_datetime": original_end_datetime,
		}
	)
	doc.fetch_checklist()
	doc.save(ignore_permissions=True)

	# Audit log for delegate/defer (skip already logged above)
	if decision["action"] in ("delegate", "defer") and leave_awareness_enabled():
		log_skip(
			rule=rule.name,
			user=rule.get("assign_to"),
			target_date=nowdate(),
			action_taken="Delegated" if decision["action"] == "delegate" else "Deferred",
			leave_application=decision.get("leave_application"),
			task=doc.name,
			resolution=decision.get("reason"),
		)

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
