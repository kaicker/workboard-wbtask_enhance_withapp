# Copyright (c) 2025, Nesscale Solutions Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, getdate, now_datetime, nowdate

from workboard.utils import get_workboard_settings


class WBTask(Document):
	def validate(self):
		if self.status not in ("Open", "Done", "Completed", "Overdue"):
			frappe.throw(_("Invalid Status"))

		# Web Form / API may not send assign_from; keep workflow stable by defaulting to current user.
		if not self.assign_from:
			self.assign_from = frappe.session.user or "Administrator"

		# Auto-derive due_date from end_datetime so users only fill one field
		if self.end_datetime:
			self.due_date = getdate(get_datetime(self.end_datetime))

		prev_status = self._get_previous_status()
		self.validate_overdue()
		self.enforce_checklist()
		self._stamp_status_transition(prev_status)
		self.stamp_completion()

		# Stash the transition so on_update can react to it (e.g. FMS chain advance).
		self.flags.wb_prev_status = prev_status

	def on_update(self):
		# FMS chain: when a step transitions into Done, spawn the next step.
		prev_status = getattr(self.flags, "wb_prev_status", None)
		if (
			self.task_type == "FMS"
			and self.status == "Done"
			and prev_status != "Done"
		):
			try:
				from workboard.fms.chain import advance_on_done

				advance_on_done(self)
			except Exception:
				frappe.log_error(title=_("WorkBoard FMS chain error"), message=frappe.get_traceback())

	def _get_previous_status(self):
		doc_before = self.get_doc_before_save()
		return doc_before.status if doc_before else None

	def _stamp_status_transition(self, prev_status):
		"""Stamp Done/Completed datetimes only when the status transitions.

		This avoids back-filling timestamps on historical tasks just because someone edits/saves them.
		"""
		if self.status == prev_status:
			return

		if self.status == "Done":
			self.done_on = self.done_on or now_datetime()

		if self.status == "Completed":
			self.completed_on = self.completed_on or now_datetime()
			self.date_of_completion = self.date_of_completion or getdate(self.completed_on)

	def validate_overdue(self):
		if not self.due_date or self.status in ("Done", "Completed"):
			return

		is_overdue = False
		if self.end_datetime:
			# Time-based: compare exact datetime
			is_overdue = now_datetime() > get_datetime(self.end_datetime)
		else:
			# Fallback to date-based for manual tasks without end_datetime
			is_overdue = getdate(nowdate()) > getdate(self.due_date)

		if self.status in ("Open", "In Progress") and is_overdue:
			self.status = "Overdue"
		if self.status == "Overdue" and not is_overdue:
			self.status = "Open"

	def enforce_checklist(self):
		if not int(self.has_checklist or 0):
			return
		rows = self.get("wb_task_checklist_details") or []
		if not rows:
			frappe.throw(_("Checklist is required"))
		all_done = all(bool(getattr(r, "completed", 0)) for r in rows)
		if self.status in ("Done", "Completed") and not all_done:
			frappe.throw(_("Complete all checklist items before marking as Done or Completed"))
		if all_done and self.status in ("Open", "In Progress", "Overdue"):
			self.status = "Done" if self.task_type == "Manual" else "Completed"

	def stamp_completion(self):
		if self.status == "Completed":
			# Keep existing field for compatibility with existing reports/dashboards.
			if not self.date_of_completion:
				self.date_of_completion = getdate(self.completed_on) if self.completed_on else nowdate()

			# Calculate timeliness
			if self.end_datetime:
				# Compare completion datetime with end_datetime
				completion_datetime = (
					get_datetime(self.completed_on)
					if self.completed_on
					else (now_datetime() if not self.date_of_completion else get_datetime(self.date_of_completion))
				)
				end_dt = get_datetime(self.end_datetime)
				self.timeliness = "Ontime" if completion_datetime <= end_dt else "Late"
			elif self.due_date and self.date_of_completion:
				# Fallback to date-based for manual tasks without end_datetime
				self.timeliness = (
					"Ontime" if getdate(self.date_of_completion) <= getdate(self.due_date) else "Late"
				)
		else:
			self.timeliness = None

	@frappe.whitelist()
	def mark_done(self):
		"""Mark task as Done by the assignee (task doer)"""
		if self.status not in ("Open", "Overdue"):
			frappe.throw(_("Only Open or Overdue tasks can be marked Done"))

		# Check if user has admin role
		settings = get_workboard_settings()
		admin_role = settings.get("workboard_admin_role")
		has_admin_role = admin_role and admin_role in frappe.get_roles(frappe.session.user)

		# Only assignee or admin role can mark done
		if (
			frappe.session.user != self.assign_to
			and frappe.session.user != "Administrator"
			and not has_admin_role
		):
			frappe.throw(_("Only the assigned user can mark this task as Done"))

		self.enforce_checklist()
		self.status = "Done"
		self.done_on = self.done_on or now_datetime()
		self.save(ignore_permissions=True)

	@frappe.whitelist()
	def mark_completed(self):
		"""Mark task as Completed.

		Manual tasks: only the assigner (or admin) can complete, and task must be Done first.
		Auto tasks: the assignee can complete directly from Open/Overdue.
		"""
		settings = get_workboard_settings()
		admin_role = settings.get("workboard_admin_role")
		current_user = frappe.session.user
		is_admin = current_user == "Administrator"
		has_admin_role = admin_role and admin_role in frappe.get_roles(current_user)

		if self.task_type == "Manual":
			if self.status != "Done":
				frappe.throw(_("Manual tasks must be marked as Done first before completion"))

			is_assigner = current_user == self.assign_from
			if not is_assigner and not is_admin and not has_admin_role:
				frappe.throw(_("Only the task assigner can mark this task as Completed"))
		else:
			# Auto tasks: assignee can complete directly
			if self.status not in ("Open", "Overdue"):
				frappe.throw(_("Only Open or Overdue tasks can be marked Completed"))

			is_assignee = current_user == self.assign_to
			if not is_assignee and not is_admin and not has_admin_role:
				frappe.throw(_("Only the assigned user can mark this task as Completed"))

		self.status = "Completed"
		self.completed_on = self.completed_on or now_datetime()
		self.date_of_completion = self.date_of_completion or getdate(self.completed_on)
		self.save(ignore_permissions=True)

	@frappe.whitelist()
	def reopen_task(self):
		"""Reopen a Done task back to Open.

		Only the assigner (or admin) can reopen. This is used when the assigner
		reviews a Done task and decides it isn't actually complete.
		"""
		if self.status != "Done":
			frappe.throw(_("Only tasks with status Done can be reopened"))

		settings = get_workboard_settings()
		admin_role = settings.get("workboard_admin_role")
		current_user = frappe.session.user
		is_admin = current_user == "Administrator"
		has_admin_role = admin_role and admin_role in frappe.get_roles(current_user)
		is_assigner = current_user == self.assign_from

		if not is_assigner and not is_admin and not has_admin_role:
			frappe.throw(_("Only the task assigner can reopen this task"))

		# Reset status and clear done/completion timestamps
		self.status = "Open"
		self.done_on = None
		self.completed_on = None
		self.date_of_completion = None
		self.timeliness = None
		self.save(ignore_permissions=True)

		# Let validate_overdue() handle flipping to Overdue if past deadline

	@frappe.whitelist()
	def fetch_checklist(self):
		self.wb_task_checklist_details = []
		if not self.checklist_template:
			return
		checklist_doc = frappe.get_doc("WB Task Checklist Template", self.checklist_template)
		for row in checklist_doc.wb_task_checklist_template_details:
			self.append("wb_task_checklist_details", {"checklist_item": row.checklist_item})
