# Copyright (c) 2026, Nesscale Solutions Pvt Ltd and contributors
# For license information, please see license.txt

"""Tests for the recurring-rule scheduler.

Covers two correctness fixes shipped in 2026-04-25:
  * Patch 1 — disabled-assignee preflight: rules whose `assign_to` is a
    disabled User must skip task creation and log to `WB Leave Skip Log`
    instead of failing silently in Error Log.
  * Patch 2 — month-end clamp: Monthly/Quarterly/Yearly rules with
    `date_of_month` ∈ {29, 30, 31} must fire on the last day of months
    that don't have those days, instead of silently skipping the cycle.
"""

import datetime

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from workboard.background_jobs import _run_recurring_rules, _target_dom


class TestTargetDom(FrappeTestCase):
	"""Pure unit tests for the date_of_month clamp helper."""

	def test_dom_clamps_31_to_april_30(self):
		# Apr 2026 has 30 days
		self.assertEqual(_target_dom(31, datetime.date(2026, 4, 15)), 30)

	def test_dom_clamps_31_to_feb_28_non_leap(self):
		self.assertEqual(_target_dom(31, datetime.date(2027, 2, 10)), 28)

	def test_dom_clamps_31_to_feb_29_leap(self):
		self.assertEqual(_target_dom(31, datetime.date(2028, 2, 10)), 29)

	def test_dom_clamps_30_to_feb_28_non_leap(self):
		self.assertEqual(_target_dom(30, datetime.date(2027, 2, 10)), 28)

	def test_dom_29_unchanged_in_april(self):
		# Apr has 30 days, so 29 stays 29
		self.assertEqual(_target_dom(29, datetime.date(2026, 4, 15)), 29)

	def test_dom_15_unchanged(self):
		self.assertEqual(_target_dom(15, datetime.date(2026, 4, 15)), 15)

	def test_dom_31_unchanged_in_january(self):
		self.assertEqual(_target_dom(31, datetime.date(2026, 1, 15)), 31)

	def test_dom_zero_returns_zero(self):
		# A rule with no date_of_month set should never match.
		self.assertEqual(_target_dom(0, datetime.date(2026, 4, 15)), 0)
		self.assertEqual(_target_dom(None, datetime.date(2026, 4, 15)), 0)
		self.assertEqual(_target_dom("", datetime.date(2026, 4, 15)), 0)


class TestDisabledAssigneePreflight(FrappeTestCase):
	"""Patch 1 — rules pointing at a disabled User must skip + log."""

	def setUp(self):
		super().setUp()
		self._prev_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user(self._prev_user)
		frappe.db.rollback()
		super().tearDown()

	def _make_user(self, email: str, enabled: int):
		if frappe.db.exists("User", email):
			frappe.db.set_value("User", email, "enabled", enabled)
			return frappe.get_doc("User", email)
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Test",
				"send_welcome_email": 0,
				"enabled": enabled,
			}
		).insert(ignore_permissions=True)
		return u

	def _make_daily_rule(self, assignee: str) -> str:
		# A Daily recurring rule fires every day, so we don't have to
		# coordinate with today's calendar to exercise the preflight.
		rule = frappe.get_doc(
			{
				"doctype": "WB Task Rule",
				"title": f"TEST Daily {assignee}",
				"description": "preflight test",
				"priority": "Low",
				"assign_to": assignee,
				"enabled": 1,
				"recurring": 1,
				"frequency": "Daily",
				"respects_weekly_off": 0,
			}
		).insert(ignore_permissions=True)
		return rule.name

	def test_disabled_assignee_skips_and_logs(self):
		disabled = self._make_user("preflight-disabled@example.test", enabled=0)
		rule_name = self._make_daily_rule(disabled.name)

		tasks_before = set(
			frappe.get_all("WB Task", filters={"source_rule": rule_name}, pluck="name")
		)
		logs_before = set(
			frappe.get_all(
				"WB Leave Skip Log",
				filters={"rule": rule_name, "action_taken": "Skipped"},
				pluck="name",
			)
		)

		_run_recurring_rules()

		tasks_after = set(
			frappe.get_all("WB Task", filters={"source_rule": rule_name}, pluck="name")
		)
		logs_after = set(
			frappe.get_all(
				"WB Leave Skip Log",
				filters={"rule": rule_name, "action_taken": "Skipped"},
				pluck="name",
			)
		)

		# No task created…
		self.assertEqual(tasks_after, tasks_before, "Disabled-assignee rule must not create a task")
		# …and exactly one new Skipped log row.
		new_logs = logs_after - logs_before
		self.assertEqual(len(new_logs), 1, "Expected exactly one Skipped log row")
		log = frappe.get_doc("WB Leave Skip Log", next(iter(new_logs)))
		self.assertEqual(log.user, disabled.name)
		self.assertIn("disabled", (log.resolution or "").lower())

	def test_enabled_assignee_proceeds(self):
		# Sanity: an enabled assignee still creates a task.
		enabled = self._make_user("preflight-enabled@example.test", enabled=1)
		rule_name = self._make_daily_rule(enabled.name)

		tasks_before = frappe.db.count("WB Task", filters={"source_rule": rule_name})
		_run_recurring_rules()
		tasks_after = frappe.db.count("WB Task", filters={"source_rule": rule_name})
		self.assertEqual(
			tasks_after - tasks_before, 1, "Enabled assignee must produce one task per run"
		)


class TestMonthEndClamp(FrappeTestCase):
	"""Patch 2 — date_of_month=31 fires on the last day of short months.

	We exercise the clamp via the helper and via _run_recurring_rules with
	monkey-patched date helpers, since FrappeTestCase doesn't ship a clock.
	"""

	def setUp(self):
		super().setUp()
		self._prev_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user(self._prev_user)
		frappe.db.rollback()
		super().tearDown()

	def _make_monthly_rule(self, assignee: str, dom: str) -> str:
		rule = frappe.get_doc(
			{
				"doctype": "WB Task Rule",
				"title": f"TEST Monthly dom={dom}",
				"description": "month-end clamp test",
				"priority": "Low",
				"assign_to": assignee,
				"enabled": 1,
				"recurring": 1,
				"frequency": "Monthly",
				"date_of_month": dom,
			}
		).insert(ignore_permissions=True)
		return rule.name

	def test_dom_31_fires_on_last_day_of_april(self):
		import workboard.background_jobs as bj

		# Use Administrator as the assignee — always enabled in test fixtures.
		rule_name = self._make_monthly_rule("Administrator", "31")

		# Force the scheduler to think today is Apr 30, 2026 (a 30-day month).
		fake_today = datetime.date(2026, 4, 30)
		orig_today = bj.today
		orig_getdate = bj.getdate
		try:
			bj.today = lambda: fake_today.isoformat()
			bj.getdate = lambda *a, **kw: fake_today if not a else orig_getdate(*a, **kw)

			tasks_before = frappe.db.count("WB Task", filters={"source_rule": rule_name})
			_run_recurring_rules()
			tasks_after = frappe.db.count("WB Task", filters={"source_rule": rule_name})
		finally:
			bj.today = orig_today
			bj.getdate = orig_getdate

		self.assertEqual(
			tasks_after - tasks_before,
			1,
			"dom=31 rule must fire on Apr 30",
		)

	def test_dom_30_does_not_fire_on_april_29(self):
		import workboard.background_jobs as bj

		rule_name = self._make_monthly_rule("Administrator", "30")
		fake_today = datetime.date(2026, 4, 29)
		orig_today = bj.today
		orig_getdate = bj.getdate
		try:
			bj.today = lambda: fake_today.isoformat()
			bj.getdate = lambda *a, **kw: fake_today if not a else orig_getdate(*a, **kw)

			tasks_before = frappe.db.count("WB Task", filters={"source_rule": rule_name})
			_run_recurring_rules()
			tasks_after = frappe.db.count("WB Task", filters={"source_rule": rule_name})
		finally:
			bj.today = orig_today
			bj.getdate = orig_getdate

		self.assertEqual(
			tasks_after - tasks_before,
			0,
			"dom=30 rule must not fire on Apr 29 (April still has Apr 30 ahead)",
		)
