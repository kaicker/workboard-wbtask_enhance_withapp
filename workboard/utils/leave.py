# Copyright (c) 2026, Nesscale Solutions Pvt Ltd and contributors
# For license information, please see license.txt

"""Leave + weekly-off helpers for WorkBoard task creation.

Design notes
------------
* We read leave state from HRMS's `Leave Application` doctype. We do NOT
  replicate leave data into WorkBoard. If HRMS is not installed the helpers
  degrade gracefully (treat everyone as not-on-leave, fallback paths apply).
* `WorkBoard Calendar Settings` is a singleton created in Phase 1. It owns
  `enable_leave_awareness` (the feature flag), `weekly_off_day`, and optional
  `holiday_list`. Everything downstream must gate on the flag.
* Every skip / delegation / deferral is logged to `WB Leave Skip Log` for
  audit and later reconciliation.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe.utils import add_days, get_datetime, getdate, now_datetime, nowdate


# ---------------------------------------------------------------------------
# Settings + feature flag
# ---------------------------------------------------------------------------

_CALENDAR_SETTINGS_DOCTYPE = "WorkBoard Calendar Settings"


def get_calendar_settings():
	"""Return the singleton. Caller should read `.enable_leave_awareness` first.

	Safe when the singleton hasn't been instantiated yet: returns a fresh doc
	with schema defaults.
	"""
	try:
		return frappe.get_single(_CALENDAR_SETTINGS_DOCTYPE)
	except frappe.DoesNotExistError:
		# Doctype exists but the single row was never created.
		return frappe.new_doc(_CALENDAR_SETTINGS_DOCTYPE)


def leave_awareness_enabled() -> bool:
	"""Global kill-switch. If this returns False, behave exactly as pre-v1.1."""
	try:
		settings = get_calendar_settings()
		return bool(getattr(settings, "enable_leave_awareness", 0))
	except Exception:
		# Never crash task creation because of a settings read error.
		frappe.log_error(
			title="WorkBoard leave_awareness_enabled error",
			message=frappe.get_traceback(),
		)
		return False


def _hrms_available() -> bool:
	"""True iff the Leave Application doctype is present in this site."""
	try:
		return bool(frappe.db.exists("DocType", "Leave Application"))
	except Exception:
		return False


# ---------------------------------------------------------------------------
# Leave detection
# ---------------------------------------------------------------------------


def is_user_on_leave(user: Optional[str], on_date: Optional[str] = None) -> bool:
	"""True iff `user` has an Approved Leave Application that covers `on_date`.

	`on_date` defaults to today. Falls back to False if HRMS isn't installed,
	the user is empty, or a DB error occurs — we'd rather create a task than
	silently drop one.
	"""
	if not user:
		return False
	if not _hrms_available():
		return False

	target = getdate(on_date) if on_date else getdate(nowdate())

	try:
		count = frappe.db.count(
			"Leave Application",
			filters={
				"employee_user": user,
				"status": "Approved",
				"docstatus": 1,
				"from_date": ["<=", target],
				"to_date": [">=", target],
			},
		)
		if count:
			return True

		# Some HRMS setups link leave to `user` directly rather than
		# employee_user; try that as a fallback.
		count = frappe.db.count(
			"Leave Application",
			filters={
				"user": user,
				"status": "Approved",
				"docstatus": 1,
				"from_date": ["<=", target],
				"to_date": [">=", target],
			},
		)
		return bool(count)
	except Exception:
		frappe.log_error(
			title="WorkBoard is_user_on_leave error",
			message=frappe.get_traceback(),
		)
		return False


def get_active_leave(user: Optional[str], on_date: Optional[str] = None):
	"""Return the covering Leave Application dict for (user, on_date), or None.

	Returned dict keys: name, from_date, to_date, leave_type, employee_user.
	"""
	if not user or not _hrms_available():
		return None
	target = getdate(on_date) if on_date else getdate(nowdate())

	try:
		for user_field in ("employee_user", "user"):
			rows = frappe.get_all(
				"Leave Application",
				filters={
					user_field: user,
					"status": "Approved",
					"docstatus": 1,
					"from_date": ["<=", target],
					"to_date": [">=", target],
				},
				fields=["name", "from_date", "to_date", "leave_type"],
				order_by="from_date desc",
				limit=1,
			)
			if rows:
				row = rows[0]
				row["employee_user"] = user
				return row
	except Exception:
		frappe.log_error(
			title="WorkBoard get_active_leave error",
			message=frappe.get_traceback(),
		)
	return None


def users_returning_from_leave(on_date: Optional[str] = None):
	"""Users whose most recent Approved leave ended exactly the day before `on_date`.

	Used by the return-from-leave reconciler. Returns a list of dicts
	{"user": str, "leave_application": str, "to_date": date}.
	"""
	if not _hrms_available():
		return []
	target = getdate(on_date) if on_date else getdate(nowdate())
	ended_on = add_days(target, -1)

	out = []
	try:
		for user_field in ("employee_user", "user"):
			rows = frappe.get_all(
				"Leave Application",
				filters={
					"status": "Approved",
					"docstatus": 1,
					"to_date": ended_on,
				},
				fields=[f"{user_field} as user", "name", "to_date"],
			)
			for r in rows:
				if r.get("user"):
					out.append(r)
	except Exception:
		frappe.log_error(
			title="WorkBoard users_returning_from_leave error",
			message=frappe.get_traceback(),
		)

	# De-dupe by user, prefer first match.
	seen = set()
	deduped = []
	for r in out:
		u = r["user"]
		if u in seen:
			continue
		seen.add(u)
		deduped.append(r)
	return deduped


# ---------------------------------------------------------------------------
# Weekly off / holiday
# ---------------------------------------------------------------------------


_WEEKDAY_BY_NAME = {
	"Monday": 0,
	"Tuesday": 1,
	"Wednesday": 2,
	"Thursday": 3,
	"Friday": 4,
	"Saturday": 5,
	"Sunday": 6,
}


def is_weekly_off(on_date: Optional[str] = None) -> bool:
	"""True iff `on_date` is the team's configured weekly off day.

	Returns False if leave awareness is off (so the scheduler behaves
	pre-v1.1 when the feature flag is flipped off).
	"""
	if not leave_awareness_enabled():
		return False
	settings = get_calendar_settings()
	day_name = getattr(settings, "weekly_off_day", None)
	if not day_name:
		return False
	target = getdate(on_date) if on_date else getdate(nowdate())
	idx = _WEEKDAY_BY_NAME.get(day_name)
	if idx is None:
		return False
	return target.weekday() == idx


def is_holiday(on_date: Optional[str] = None) -> bool:
	"""True iff `on_date` is in the configured Holiday List.

	Optional — if no list is configured we return False.
	"""
	if not leave_awareness_enabled():
		return False
	settings = get_calendar_settings()
	holiday_list = getattr(settings, "holiday_list", None)
	if not holiday_list:
		return False
	target = getdate(on_date) if on_date else getdate(nowdate())
	try:
		return bool(
			frappe.db.exists(
				"Holiday",
				{"parent": holiday_list, "holiday_date": target},
			)
		)
	except Exception:
		return False


# ---------------------------------------------------------------------------
# Assignee resolution for a rule
# ---------------------------------------------------------------------------


def resolve_assignee_for_rule(rule, on_date: Optional[str] = None, is_event: bool = False):
	"""Decide who a task should actually be assigned to given leave state.

	Returns a dict:
	    {
	        "action":        "proceed" | "pause" | "delegate" | "defer",
	        "assign_to":     str or None,     # the user the task should go to
	        "delegated_from": str or None,    # original assignee if delegated
	        "leave_application": str or None, # HRMS Leave Application name
	        "defer_to":      date or None,    # new end date for "defer"
	        "reason":        str,             # short human-readable reason
	    }

	* If the feature flag is off, always returns ("proceed", rule.assign_to).
	* If the assignee isn't on leave, returns ("proceed", rule.assign_to).
	* Otherwise reads `on_leave_behavior` (or `on_leave_event_behavior` for
	  event rules) and builds the right action.
	"""
	base_result = {
		"action": "proceed",
		"assign_to": rule.get("assign_to"),
		"delegated_from": None,
		"leave_application": None,
		"defer_to": None,
		"reason": "",
	}

	if not leave_awareness_enabled():
		return base_result

	assignee = rule.get("assign_to")
	if not assignee:
		return base_result

	leave = get_active_leave(assignee, on_date=on_date)
	if not leave:
		return base_result

	# Pick the policy field: recurring rules use on_leave_behavior,
	# event rules use on_leave_event_behavior.
	policy_field = "on_leave_event_behavior" if is_event else "on_leave_behavior"
	policy = rule.get(policy_field) or ("Delegate to Backup" if is_event else "Pause")

	base_result["leave_application"] = leave.get("name")

	if policy == "Pause":
		base_result["action"] = "pause"
		base_result["assign_to"] = None
		base_result["reason"] = f"Assignee {assignee} on leave {leave['from_date']}→{leave['to_date']}"
		return base_result

	if policy == "Delegate to Backup":
		backup = rule.get("backup_user") or rule.get("assign_from")
		# Avoid bouncing to someone who is themselves on leave.
		if backup and is_user_on_leave(backup, on_date=on_date):
			# Fall back to assign_from if the backup is also out.
			if rule.get("assign_from") and rule.get("assign_from") != backup:
				if not is_user_on_leave(rule["assign_from"], on_date=on_date):
					backup = rule["assign_from"]
				else:
					backup = None
			else:
				backup = None
		if not backup:
			# No viable delegate — fall through to pause so we don't lose the task silently.
			base_result["action"] = "pause"
			base_result["assign_to"] = None
			base_result["reason"] = (
				f"Assignee {assignee} on leave; no available backup — paused"
			)
			return base_result
		base_result["action"] = "delegate"
		base_result["assign_to"] = backup
		base_result["delegated_from"] = assignee
		base_result["reason"] = f"Delegated to {backup} while {assignee} is on leave"
		return base_result

	if policy == "Defer to Return Date":
		defer_to = add_days(leave["to_date"], 1)
		base_result["action"] = "defer"
		base_result["assign_to"] = assignee  # still the original assignee
		base_result["defer_to"] = defer_to
		base_result["reason"] = f"Deferred to {defer_to} ({assignee} on leave until {leave['to_date']})"
		return base_result

	return base_result


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def log_skip(
	rule: str,
	user: str,
	target_date,
	action_taken: str,
	leave_application: Optional[str] = None,
	task: Optional[str] = None,
	resolution: Optional[str] = None,
):
	"""Write a row to WB Leave Skip Log. Best-effort — never raises."""
	try:
		doc = frappe.get_doc(
			{
				"doctype": "WB Leave Skip Log",
				"rule": rule,
				"user": user,
				"target_date": getdate(target_date) if target_date else getdate(nowdate()),
				"action_taken": action_taken,
				"leave_application": leave_application,
				"task": task,
				"resolution": resolution,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		frappe.log_error(
			title="WorkBoard log_skip error",
			message=frappe.get_traceback(),
		)
		return None
