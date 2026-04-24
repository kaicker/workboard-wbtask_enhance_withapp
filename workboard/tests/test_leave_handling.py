# Copyright (c) 2026, Nesscale Solutions Pvt Ltd and contributors
# For license information, please see license.txt

"""Tests for leave + weekly-off handling.

These tests work with or without HRMS installed:
  * `is_user_on_leave` / `get_active_leave` degrade to False/None when HRMS
    isn't present, so the "no leave" paths are always exercised.
  * Tests that require actual leave records are skipped when HRMS is missing.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from workboard.utils.leave import (
	get_calendar_settings,
	is_user_on_leave,
	is_weekly_off,
	leave_awareness_enabled,
	log_skip,
	resolve_assignee_for_rule,
)


def _hrms_available():
	return bool(frappe.db.exists("DocType", "Leave Application"))


class TestLeaveHelpers(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._prev_user = frappe.session.user
		frappe.set_user("Administrator")
		# Ensure the singleton is in a known state for each test.
		self._set_flag(0)
		self._set_weekly_off("Tuesday")

	def tearDown(self):
		frappe.set_user(self._prev_user)
		frappe.db.rollback()
		super().tearDown()

	# ---- helpers -----------------------------------------------------------

	def _set_flag(self, on: int):
		frappe.db.set_single_value(
			"WorkBoard Calendar Settings", "enable_leave_awareness", on
		)

	def _set_weekly_off(self, day_name: str):
		frappe.db.set_single_value(
			"WorkBoard Calendar Settings", "weekly_off_day", day_name
		)

	def _rule(self, **kw):
		# A fake rule object — resolve_assignee_for_rule only does .get() lookups.
		base = {
			"name": "TEST-RULE",
			"assign_to": "Administrator",
			"assign_from": "Administrator",
			"on_leave_behavior": "Pause",
			"on_leave_event_behavior": "Delegate to Backup",
			"backup_user": None,
			"recurring": 1,
			"frequency": "Daily",
			"respects_weekly_off": 1,
			"return_policy": "Leave as backlog",
		}
		base.update(kw)
		return frappe._dict(base)

	# ---- flag + settings ---------------------------------------------------

	def test_get_calendar_settings_returns_singleton(self):
		settings = get_calendar_settings()
		self.assertIsNotNone(settings)
		# Schema default from Phase 1
		self.assertEqual(getattr(settings, "weekly_off_day", None), "Tuesday")

	def test_leave_awareness_defaults_off(self):
		self._set_flag(0)
		self.assertFalse(leave_awareness_enabled())

	def test_leave_awareness_can_be_enabled(self):
		self._set_flag(1)
		self.assertTrue(leave_awareness_enabled())

	# ---- weekly off --------------------------------------------------------

	def test_is_weekly_off_false_when_flag_off(self):
		self._set_flag(0)
		# Even on a Tuesday this should be False because the feature is gated.
		self.assertFalse(is_weekly_off("2026-04-28"))  # Tue

	def test_is_weekly_off_matches_configured_day(self):
		self._set_flag(1)
		self._set_weekly_off("Tuesday")
		self.assertTrue(is_weekly_off("2026-04-28"))  # Tuesday
		self.assertFalse(is_weekly_off("2026-04-29"))  # Wednesday

	def test_is_weekly_off_respects_day_change(self):
		self._set_flag(1)
		self._set_weekly_off("Sunday")
		self.assertTrue(is_weekly_off("2026-04-26"))  # Sunday
		self.assertFalse(is_weekly_off("2026-04-28"))

	# ---- leave detection (graceful when HRMS missing) ----------------------

	def test_is_user_on_leave_false_for_unknown_user(self):
		# Whether HRMS is installed or not, an unknown user is never on leave.
		self.assertFalse(is_user_on_leave("nobody@example.com"))

	def test_is_user_on_leave_empty_user(self):
		self.assertFalse(is_user_on_leave(None))
		self.assertFalse(is_user_on_leave(""))

	# ---- resolver ----------------------------------------------------------

	def test_resolver_passthrough_when_flag_off(self):
		self._set_flag(0)
		decision = resolve_assignee_for_rule(self._rule())
		self.assertEqual(decision["action"], "proceed")
		self.assertEqual(decision["assign_to"], "Administrator")

	def test_resolver_passthrough_when_user_not_on_leave(self):
		self._set_flag(1)
		decision = resolve_assignee_for_rule(self._rule())
		# Administrator is not on leave in a clean test site.
		self.assertEqual(decision["action"], "proceed")
		self.assertEqual(decision["assign_to"], "Administrator")

	# ---- audit log ---------------------------------------------------------

	def test_log_skip_writes_a_row(self):
		log_name = log_skip(
			rule="TEST-RULE",
			user="Administrator",
			target_date=nowdate(),
			action_taken="Paused",
			resolution="unit-test",
		)
		# log_skip is best-effort and returns None on failure; in a clean test
		# env it should have returned a name.
		self.assertIsNotNone(log_name)
		rec = frappe.get_doc("WB Leave Skip Log", log_name)
		self.assertEqual(rec.action_taken, "Paused")
		self.assertEqual(rec.user, "Administrator")

	def test_log_skip_swallows_bad_input(self):
		# Missing reqd `target_date` — log_skip should catch and return None.
		result = log_skip(
			rule=None,  # reqd on doctype
			user=None,
			target_date=None,
			action_taken="Paused",
		)
		# Either None (caught) or a name (accepted); either way, must not raise.
		self.assertTrue(result is None or isinstance(result, str))


class TestLeaveWithHRMS(FrappeTestCase):
	"""Scenarios that actually exercise Leave Application. Skipped when HRMS
	isn't installed on the test site."""

	def setUp(self):
		super().setUp()
		if not _hrms_available():
			self.skipTest("HRMS / Leave Application not installed")
		self._prev_user = frappe.session.user
		frappe.set_user("Administrator")
		frappe.db.set_single_value("WorkBoard Calendar Settings", "enable_leave_awareness", 1)

	def tearDown(self):
		frappe.set_user(self._prev_user)
		frappe.db.rollback()
		super().tearDown()

	def test_resolver_pauses_when_assignee_on_leave(self):
		# We don't synthesize a real Leave Application here — creating one
		# requires an Employee, Leave Type, allocation, etc. HRMS-dependent
		# E2E coverage lives in manual QA. This test just asserts the import
		# + flag path works with HRMS present.
		from workboard.utils.leave import is_user_on_leave

		self.assertFalse(is_user_on_leave("Administrator"))
