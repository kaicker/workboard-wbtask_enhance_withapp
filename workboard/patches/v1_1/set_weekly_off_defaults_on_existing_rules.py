# Copyright (c) 2026, Nesscale Solutions Pvt Ltd and contributors
# For license information, please see license.txt

"""Set sensible defaults on existing WB Task Rule records for the new leave-handling fields.

Runs once after the schema migration adds the new fields. Idempotent: running twice
produces the same state (it only writes when the current value is falsy).

Defaults applied:
    - respects_weekly_off = 1 for Daily recurring rules (0 otherwise)
    - on_leave_behavior = 'Pause' (already the JSON default, but backfill for safety)
    - on_leave_event_behavior = 'Delegate to Backup'
    - return_policy = 'Leave as backlog'

We deliberately do NOT set backup_user: that is a deliberate per-rule choice and
leaving it blank forces fallback to assign_from, which is the safe default.
"""

import frappe


def execute():
	rules = frappe.get_all(
		"WB Task Rule",
		fields=[
			"name",
			"recurring",
			"frequency",
			"respects_weekly_off",
			"on_leave_behavior",
			"on_leave_event_behavior",
			"return_policy",
		],
	)

	updated = 0
	for rule in rules:
		updates = {}

		# Weekly-off defaults: only Daily recurring rules respect it by default.
		if not rule.respects_weekly_off:
			if rule.recurring and rule.frequency == "Daily":
				updates["respects_weekly_off"] = 1
			else:
				# Explicit 0 (Check fields default to NULL until written)
				updates["respects_weekly_off"] = 0

		if not rule.on_leave_behavior:
			updates["on_leave_behavior"] = "Pause"

		if not rule.on_leave_event_behavior:
			updates["on_leave_event_behavior"] = "Delegate to Backup"

		if not rule.return_policy:
			updates["return_policy"] = "Leave as backlog"

		if updates:
			frappe.db.set_value("WB Task Rule", rule.name, updates, update_modified=False)
			updated += 1

	if updated:
		frappe.db.commit()
		print(f"[workboard] set_weekly_off_defaults_on_existing_rules: updated {updated} rule(s).")
