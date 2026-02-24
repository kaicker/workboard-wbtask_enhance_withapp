# Copyright (c) 2025, Nesscale Solutions Pvt Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from workboard.background_jobs import trigger_daily_rules


class TestWBTask(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._prev_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user(self._prev_user)
		frappe.db.rollback()
		super().tearDown()

	def _make_task(self, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "WB Task",
				"title": overrides.get("title") or "Test Task",
				"description": overrides.get("description") or "Test Description",
				"priority": overrides.get("priority") or "High",
				"assign_from": overrides.get("assign_from") or "Administrator",
				"assign_to": overrides.get("assign_to") or "Administrator",
				"due_date": overrides.get("due_date") or frappe.utils.nowdate(),
				"status": overrides.get("status") or "Open",
				"task_type": overrides.get("task_type") or "Manual",
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_mark_done_stamps_done_on(self):
		task = self._make_task()
		self.assertIsNone(task.get("done_on"))

		task.mark_done()
		task.reload()

		self.assertEqual(task.status, "Done")
		self.assertIsNotNone(task.done_on)

	def test_mark_completed_stamps_completed_on_and_date(self):
		task = self._make_task(task_type="Auto")
		self.assertIsNone(task.get("completed_on"))
		self.assertIsNone(task.get("date_of_completion"))

		task.mark_completed()
		task.reload()

		self.assertEqual(task.status, "Completed")
		self.assertIsNotNone(task.completed_on)
		self.assertIsNotNone(task.date_of_completion)

	def test_rule_created_task_stamps_reference_and_triggered_on(self):
		from workboard.utils import _context, _create_task_from_rule

		ref = frappe.get_doc({"doctype": "ToDo", "description": "Ref"})
		ref.insert(ignore_permissions=True)

		rule = frappe.get_doc(
			{
				"doctype": "WB Task Rule",
				"title": "Rule Task",
				"description": "Hello {{ doc.name }}",
				"priority": "High",
				"assign_to": "Administrator",
				"due_days": 0,
				"enabled": 1,
				"event": 1,
				"based_on": "Save",
				"reference_doctype": "ToDo",
			}
		)
		rule.insert(ignore_permissions=True)

		task = _create_task_from_rule(rule, context=_context(ref))
		task.reload()

		self.assertIsNotNone(task.triggered_on)
		self.assertEqual(task.source_rule, rule.name)
		self.assertEqual(task.reference_doctype, ref.doctype)
		self.assertEqual(task.reference_name, ref.name)

	def test_recurring_rule_creates_task_via_scheduler(self):
		rule = frappe.get_doc(
			{
				"doctype": "WB Task Rule",
				"title": "Daily Recurring Rule",
				"description": "Recurring task",
				"priority": "High",
				"assign_to": "Administrator",
				"due_days": 0,
				"enabled": 1,
				"recurring": 1,
				"frequency": "Daily",
			}
		)
		rule.insert(ignore_permissions=True)

		existing = set(
			frappe.get_all("WB Task", filters={"source_rule": rule.name}, pluck="name")
		)

		trigger_daily_rules()

		after = set(
			frappe.get_all("WB Task", filters={"source_rule": rule.name}, pluck="name")
		)

		self.assertGreater(len(after - existing), 0)
