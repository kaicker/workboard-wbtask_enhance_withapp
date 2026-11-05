"""API for the WorkBoard staff mobile app (no ERPNext login needed).

Flow:
  1. App calls `register(staff_no, pin)` once -> gets a device token.
  2. Every later call sends that token in the `X-WB-Staff-Token` header
     (not `Authorization`, which Frappe reserves for its own auth).
  3. Actions run as the employee's linked User, so all WB Task rules
     (checklists, timeliness, two-step approval, FMS chain) still apply.

Base URL: /api/method/workboard.api.staff.<function>

Only one phone per employee: registering again replaces the old token.
"""

import secrets

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import now_datetime, sha256_hash
from frappe.utils.password import get_decrypted_password

TOKEN_HEADER = "X-WB-Staff-Token"
TASK_FIELDS = [
	"name",
	"title",
	"status",
	"priority",
	"task_type",
	"due_date",
	"end_datetime",
	"description",
	"assign_from",
	"has_checklist",
]


# ── helpers ──────────────────────────────────────────────────────────────


def _get_token(token=None):
	token = frappe.get_request_header(TOKEN_HEADER) or token
	if not token:
		frappe.throw(_("Not registered on this phone"), frappe.AuthenticationError)
	return token


def _employee_for_token(token=None):
	"""Return the Employee row for a device token, or raise AuthenticationError."""
	token = _get_token(token)
	emp = frappe.db.get_value(
		"Employee",
		{"wb_app_token": sha256_hash(token), "status": "Active"},
		["name", "employee_name", "user_id"],
		as_dict=True,
	)
	if not emp or not emp.user_id or not frappe.db.get_value("User", emp.user_id, "enabled"):
		frappe.throw(
			_("This phone is no longer registered. Please set up again."), frappe.AuthenticationError
		)
	return emp


def _act_as(token=None):
	"""Switch the request to the employee's User and return the Employee row."""
	emp = _employee_for_token(token)
	frappe.set_user(emp.user_id)
	return emp


def _get_own_task(task, user):
	doc = frappe.get_doc("WB Task", task)
	if doc.assign_to != user:
		frappe.throw(_("This task is not assigned to you"), frappe.PermissionError)
	return doc


def _full_name(user):
	return frappe.db.get_value("User", user, "full_name") or user


# ── endpoints ────────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=10 * 60)
def register(staff_no, pin, fcm_token=None):
	"""Set up the app on a phone. Returns a device token to store on the phone."""
	staff_no = (staff_no or "").strip()
	pin = (pin or "").strip()
	bad = _("Wrong Staff No or PIN")
	if not staff_no or not pin:
		frappe.throw(bad, frappe.AuthenticationError)

	emp = frappe.db.get_value(
		"Employee",
		{"wb_staff_no": staff_no, "status": "Active"},
		["name", "employee_name", "user_id"],
		as_dict=True,
	)
	if not emp:
		frappe.throw(bad, frappe.AuthenticationError)

	saved_pin = get_decrypted_password("Employee", emp.name, "wb_pin", raise_exception=False)
	if not saved_pin or not secrets.compare_digest(saved_pin, pin):
		frappe.throw(bad, frappe.AuthenticationError)

	if not emp.user_id:
		frappe.throw(_("Your employee record has no user linked. Please ask the admin."))

	token = secrets.token_urlsafe(32)
	values = {"wb_app_token": sha256_hash(token), "wb_app_last_seen": now_datetime()}
	if fcm_token:
		values["wb_fcm_token"] = fcm_token
	frappe.db.set_value("Employee", emp.name, values, update_modified=False)

	return {"token": token, "employee_name": emp.employee_name, "user": emp.user_id}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def set_push_token(fcm_token, token=None):
	"""Save / refresh the phone's Firebase push token (call on every app start)."""
	emp = _employee_for_token(token)
	frappe.db.set_value(
		"Employee",
		emp.name,
		{"wb_fcm_token": fcm_token or None, "wb_app_last_seen": now_datetime()},
		update_modified=False,
	)
	return {"ok": True}


@frappe.whitelist(allow_guest=True)
def me(token=None):
	emp = _act_as(token)
	return {"employee_name": emp.employee_name, "user": emp.user_id}


@frappe.whitelist(allow_guest=True)
def my_tasks(token=None):
	"""Open, Overdue and Done (waiting for approval) tasks assigned to this employee."""
	emp = _act_as(token)
	tasks = frappe.get_all(
		"WB Task",
		filters={"assign_to": emp.user_id, "status": ["in", ["Open", "Overdue", "Done"]]},
		fields=TASK_FIELDS,
		order_by="due_date asc, end_datetime asc",
		limit_page_length=300,
	)
	names = {}
	for t in tasks:
		if t.assign_from not in names:
			names[t.assign_from] = _full_name(t.assign_from)
		t.assign_from_name = names[t.assign_from]
		# What the app should offer for this task
		if t.status in ("Open", "Overdue"):
			t.action = "mark_done" if t.task_type == "Manual" else "mark_completed"
		else:
			t.action = None  # Done: waiting for the assigner to approve
	return tasks


@frappe.whitelist(allow_guest=True)
def task_detail(task, token=None):
	emp = _act_as(token)
	doc = _get_own_task(task, emp.user_id)
	data = {f: doc.get(f) for f in TASK_FIELDS}
	data["assign_from_name"] = _full_name(doc.assign_from)
	data["checklist"] = [
		{"row": r.name, "item": r.checklist_item, "notes": r.notes, "completed": int(r.completed or 0)}
		for r in (doc.get("wb_task_checklist_details") or [])
	]
	return data


@frappe.whitelist(allow_guest=True, methods=["POST"])
def set_checklist_item(task, row, completed, token=None):
	"""Tick / untick one checklist row. Ticking the last row auto-finishes the task (existing rule)."""
	emp = _act_as(token)
	doc = _get_own_task(task, emp.user_id)
	if doc.status not in ("Open", "Overdue"):
		frappe.throw(_("This task is already {0}").format(doc.status))
	for r in doc.get("wb_task_checklist_details") or []:
		if r.name == row:
			r.completed = 1 if frappe.utils.cint(completed) else 0
			break
	else:
		frappe.throw(_("Checklist item not found"))
	doc.save(ignore_permissions=True)
	return {"status": doc.status}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def finish(task, token=None):
	"""The app's single "Done" button.

	Manual tasks -> Done (assigner still approves). Auto / Event / FMS -> Completed.
	"""
	emp = _act_as(token)
	doc = _get_own_task(task, emp.user_id)
	if doc.task_type == "Manual":
		doc.mark_done()
	else:
		doc.mark_completed()
	return {"status": doc.status}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def unregister(token=None):
	"""Log this phone out (stops notifications too)."""
	emp = _employee_for_token(token)
	frappe.db.set_value(
		"Employee", emp.name, {"wb_app_token": None, "wb_fcm_token": None}, update_modified=False
	)
	return {"ok": True}
