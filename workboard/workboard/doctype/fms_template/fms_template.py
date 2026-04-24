# Copyright (c) 2026, Nesscale Solutions Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class FMSTemplate(Document):
	def validate(self):
		self._validate_steps()

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
