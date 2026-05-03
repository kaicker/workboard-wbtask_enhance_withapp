# Copyright (c) 2026, Nesscale Solutions Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class FMSTemplate(Document):
	def validate(self):
		self._validate_steps()
		self._validate_trigger_and_schedule()
		self._validate_scheduled_tasks()

	def _validate_steps(self):
		if not self.steps:
			frappe.throw(_("An FMS Template must define at least one step"))

		seen = set()
		for idx, step in enumerate(self.steps, start=1):
			# Auto-number steps if step_no is missing, then dedupe
			if not step.step_no:
				step.step_no = idx
			if step.step_no in seen:
				frappe.throw(_("Duplicate Step No {0}").format(step.step_no))
			seen.add(step.step_no)

		# Keep steps ordered in the child table so spawn order is stable
		self.steps.sort(key=lambda s: s.step_no)

	def _validate_trigger_and_schedule(self):
		if self.trigger_type == "Event" and not self.reference_doctype:
			frappe.throw(_("Reference Doctype is required for Event FMS Templates"))

		if (self.scheduled_tasks or []) and not self.reference_doctype:
			frappe.throw(_("Reference Doctype is required when Scheduled Tasks are configured"))

	def _validate_scheduled_tasks(self):
		if not (self.scheduled_tasks or []):
			return

		seen = set()
		for idx, scheduled in enumerate(self.scheduled_tasks, start=1):
			if not scheduled.schedule_no:
				scheduled.schedule_no = idx
			if scheduled.schedule_no in seen:
				frappe.throw(_("Duplicate Schedule No {0}").format(scheduled.schedule_no))
			seen.add(scheduled.schedule_no)

			if not scheduled.reference_date_field:
				frappe.throw(_("Reference Date Field is required for Scheduled Task {0}").format(scheduled.schedule_no))
			if scheduled.offset_days and scheduled.offset_days < 0:
				frappe.throw(_("Offset Days cannot be negative for Scheduled Task {0}").format(scheduled.schedule_no))

			if (
				self.reference_doctype
				and scheduled.reference_date_field
				and frappe.db.exists("DocType", self.reference_doctype)
				and not frappe.db.has_column(self.reference_doctype, scheduled.reference_date_field)
			):
				frappe.throw(
					_("Field {0} does not exist on {1}").format(
						scheduled.reference_date_field, self.reference_doctype
					)
				)

		self.scheduled_tasks.sort(key=lambda s: s.schedule_no)

	@frappe.whitelist()
	def start_run(self, reference_doctype=None, reference_name=None):
		"""Spawn Step 1 of this FMS for the given reference doc (or standalone).

		Subsequent steps are spawned by the chain logic in workboard.fms.chain
		when each prior task transitions to Done.
		"""
		if not self.enabled:
			frappe.throw(_("FMS Template {0} is not enabled").format(self.name))

		ref_doc = None
		if reference_doctype and reference_name:
			ref_doc = frappe.get_doc(reference_doctype, reference_name)

		from workboard.fms.chain import spawn_step, new_run_id

		run_id = new_run_id(self.name)
		task = spawn_step(
			template=self,
			step_no=self.steps[0].step_no,
			run_id=run_id,
			reference_doc=ref_doc,
			prev_done_on=None,
		)
		return {"run_id": run_id, "task": task.name}
