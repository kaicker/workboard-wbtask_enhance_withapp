"""Push notifications to the WorkBoard staff app via Firebase Cloud Messaging (HTTP v1).

Setup (once per site):
  1. Firebase console -> Project settings -> Service accounts -> Generate new private key.
  2. Save the JSON on the server and point the site at it:
       bench --site <site> set-config workboard_fcm_service_account /path/to/firebase.json
     (On Frappe Cloud, paste the whole JSON object as the config value instead.)
  No config = push is off; nothing else changes.

Sends a push when:
  * a task is created for someone (except when they assigned it to themselves)
  * a task is reassigned to someone else (incl. leave delegation)
  * an assigner reopens a Done task (it goes back to Open)
"""

import json

import frappe
import requests
from frappe import _

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
ACCESS_TOKEN_CACHE_KEY = "workboard:fcm_access_token"
ANDROID_CHANNEL_ID = "wb_tasks"


# ── doc event hooks (WB Task) ────────────────────────────────────────────


def on_task_insert(doc, method=None):
	if doc.status in ("Done", "Completed"):
		return
	_queue(doc, _("New task"), "new")


def on_task_update(doc, method=None):
	before = doc.get_doc_before_save()
	if not before:
		return
	if doc.assign_to and doc.assign_to != before.assign_to and doc.status not in ("Done", "Completed"):
		_queue(doc, _("Task assigned to you"), "assigned")
	elif before.status == "Done" and doc.status in ("Open", "Overdue"):
		_queue(doc, _("Task reopened"), "reopened")


def _queue(doc, heading, reason):
	if not doc.assign_to or not _service_account():
		return
	if frappe.flags.in_install or frappe.flags.in_patch or frappe.flags.in_migrate:
		return
	# Don't buzz people for tasks they gave themselves.
	if doc.assign_to == frappe.session.user:
		return
	frappe.enqueue(
		"workboard.notifications.push.send_task_push",
		queue="short",
		enqueue_after_commit=True,
		task=doc.name,
		user=doc.assign_to,
		heading=heading,
		reason=reason,
	)


# ── sending ──────────────────────────────────────────────────────────────


def send_task_push(task, user, heading, reason=None):
	emp = frappe.db.get_value(
		"Employee", {"user_id": user, "status": "Active"}, ["name", "wb_fcm_token"], as_dict=True
	)
	if not emp or not emp.wb_fcm_token:
		return

	title, priority, end_dt, due = frappe.db.get_value(
		"WB Task", task, ["title", "priority", "end_datetime", "due_date"]
	) or (None, None, None, None)
	if not title:
		return

	when = end_dt or due
	body = title
	if when:
		body += " · " + _("due {0}").format(
			frappe.utils.format_datetime(when, "dd MMM, hh:mm a") if end_dt else frappe.utils.formatdate(due)
		)

	_ok, unregistered = send_push(
		emp.wb_fcm_token,
		title=f"{heading}{' (High)' if priority == 'High' else ''}",
		body=body,
		data={"task": task, "reason": reason or ""},
	)
	if unregistered:
		# App uninstalled / token expired: stop trying until the app re-registers.
		frappe.db.set_value("Employee", emp.name, "wb_fcm_token", None, update_modified=False)


def send_push(fcm_token, title, body, data=None):
	"""Send one notification. Returns (ok, token_is_dead)."""
	info = _service_account()
	if not info:
		return False, False
	access_token = _access_token(info)
	if not access_token:
		return False, False

	message = {
		"message": {
			"token": fcm_token,
			"notification": {"title": title, "body": body},
			"data": {k: str(v) for k, v in (data or {}).items()},
			"android": {
				"priority": "high",
				"notification": {"channel_id": ANDROID_CHANNEL_ID, "sound": "default"},
			},
		}
	}
	try:
		r = requests.post(
			f"https://fcm.googleapis.com/v1/projects/{info['project_id']}/messages:send",
			headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
			data=json.dumps(message),
			timeout=15,
		)
	except requests.RequestException:
		frappe.log_error(title="WorkBoard push failed", message=frappe.get_traceback())
		return False, False

	if r.ok:
		return True, False
	dead = (
		r.status_code == 404
		or "UNREGISTERED" in r.text
		or (r.status_code == 400 and "registration token" in r.text.lower())
	)
	if r.status_code == 401:
		frappe.cache.delete_value(ACCESS_TOKEN_CACHE_KEY)
	if not dead:
		frappe.log_error(title="WorkBoard push failed", message=f"{r.status_code}: {r.text[:2000]}")
	return False, dead


def _service_account():
	conf = frappe.conf.get("workboard_fcm_service_account")
	if not conf:
		return None
	if isinstance(conf, dict):
		return conf
	try:
		if str(conf).lstrip().startswith("{"):
			return json.loads(conf)
		with open(conf) as f:
			return json.load(f)
	except Exception:
		frappe.log_error(
			title="WorkBoard push: bad workboard_fcm_service_account", message=frappe.get_traceback()
		)
		return None


def _access_token(info):
	cached = frappe.cache.get_value(ACCESS_TOKEN_CACHE_KEY)
	if cached:
		return cached
	try:
		from google.auth.transport.requests import Request
		from google.oauth2 import service_account

		creds = service_account.Credentials.from_service_account_info(info, scopes=[FCM_SCOPE])
		creds.refresh(Request())
	except Exception:
		frappe.log_error(
			title="WorkBoard push: could not get Firebase access token", message=frappe.get_traceback()
		)
		return None
	# Google tokens last 60 min; keep 50.
	frappe.cache.set_value(ACCESS_TOKEN_CACHE_KEY, creds.token, expires_in_sec=50 * 60)
	return creds.token


@frappe.whitelist()
def send_test_push(employee):
	"""From the console / a button: check push works for one employee."""
	frappe.only_for("System Manager")
	token = frappe.db.get_value("Employee", employee, "wb_fcm_token")
	if not token:
		frappe.throw(_("This employee hasn't opened the app with notifications on yet"))
	ok, dead = send_push(token, _("WorkBoard test"), _("Notifications are working 🎉"))
	if dead:
		frappe.db.set_value("Employee", employee, "wb_fcm_token", None, update_modified=False)
	return {"ok": ok, "token_dead": dead}
