# Copyright (c) 2026, Nesscale Solutions Pvt Ltd and contributors
# For license information, please see license.txt

import calendar
from datetime import date, timedelta

import frappe
from frappe import _


MONTH_MAP = {
	"January": 1, "February": 2, "March": 3, "April": 4,
	"May": 5, "June": 6, "July": 7, "August": 8,
	"September": 9, "October": 10, "November": 11, "December": 12,
}


def execute(filters=None):
	filters = filters or {}
	month = MONTH_MAP.get(filters.get("month"), date.today().month)
	year = int(filters.get("year") or date.today().year)

	weeks = _get_weeks(year, month)
	month_start = date(year, month, 1)
	month_end = date(year, month, calendar.monthrange(year, month)[1])

	# Get all users who have tasks in this month
	users = frappe.get_all(
		"WB Task",
		filters=[
			["WB Task", "due_date", ">=", month_start.strftime("%Y-%m-%d")],
			["WB Task", "due_date", "<=", month_end.strftime("%Y-%m-%d")],
		],
		fields=["assign_to"],
		distinct=True,
		pluck="assign_to",
	)

	if not users:
		return _build_columns(weeks), [], None, None

	# Get full names for users
	user_names = {}
	for u in users:
		user_names[u] = frappe.db.get_value("User", u, "full_name") or u

	# Collect stats per user per week
	user_week_stats = {}
	for user in users:
		user_week_stats[user] = {}
		for idx, (w_start, w_end) in enumerate(weeks):
			user_week_stats[user][idx] = _get_week_stats(user, w_start, w_end)

	# Build data rows — 3 rows per user
	data = []
	for user in sorted(users, key=lambda u: user_names.get(u, u)):
		full_name = user_names[user]
		weekly_stats = user_week_stats[user]

		# Row 1: All work should be done — % work not done
		# P = total tasks, A = tasks not completed, A% = ((A - P) / P) * 100
		row1 = {"person": full_name, "kra": "All work should be done", "kpi": "% work not done"}
		total_p, total_a = 0, 0
		for idx in range(len(weeks)):
			s = weekly_stats[idx]
			p = s["total"]
			a = p - s["completed"]  # not done count
			a_pct = round(((a - p) / p) * 100, 2) if p else 0
			row1[f"w{idx}_p"] = p
			row1[f"w{idx}_a"] = a
			row1[f"w{idx}_apct"] = a_pct
			total_p += p
			total_a += a

		row1["month_p"] = total_p
		row1["month_a"] = total_a
		row1["month_apct"] = round(((total_a - total_p) / total_p) * 100, 2) if total_p else 0
		data.append(row1)

		# Row 2: All work should be done on time — % work not done on time
		# P = completed tasks, A = tasks not on time, A% = ((A - P) / P) * 100
		row2 = {"person": full_name, "kra": "All work should be done on time", "kpi": "% work not done on time"}
		total_p2, total_a2 = 0, 0
		for idx in range(len(weeks)):
			s = weekly_stats[idx]
			p = s["completed"]  # base = completed tasks
			a = p - s["ontime"]  # not on time count
			a_pct = round(((a - p) / p) * 100, 2) if p else 0
			row2[f"w{idx}_p"] = p
			row2[f"w{idx}_a"] = a
			row2[f"w{idx}_apct"] = a_pct
			total_p2 += p
			total_a2 += a

		row2["month_p"] = total_p2
		row2["month_a"] = total_a2
		row2["month_apct"] = round(((total_a2 - total_p2) / total_p2) * 100, 2) if total_p2 else 0
		data.append(row2)

		# Row 3: Pending Task — Delayed Task count
		row3 = {"person": full_name, "kra": "Pending Task", "kpi": "Delayed Task"}
		total_pending_p, total_pending_a = 0, 0
		for idx in range(len(weeks)):
			s = weekly_stats[idx]
			p = s["total"]
			a = s["delayed"]
			row3[f"w{idx}_p"] = p
			row3[f"w{idx}_a"] = a
			row3[f"w{idx}_apct"] = ""
			total_pending_p += p
			total_pending_a += a

		row3["month_p"] = total_pending_p
		row3["month_a"] = total_pending_a
		row3["month_apct"] = ""
		data.append(row3)

	columns = _build_columns(weeks)

	# Chart: month-end % work not done per user
	chart_labels = []
	chart_values = []
	for user in sorted(users, key=lambda u: user_names.get(u, u)):
		chart_labels.append(user_names[user])
		# Find the row1 (% work not done) for this user
		for row in data:
			if row["person"] == user_names[user] and row["kpi"] == "% work not done":
				chart_values.append(row["month_a"])
				break

	chart = {
		"data": {
			"labels": chart_labels,
			"datasets": [{"name": _("% Work Not Done"), "values": chart_values}],
		},
		"type": "bar",
		"height": 250,
	}

	return columns, data, None, chart


def _get_weeks(year, month):
	"""Return list of (start_date, end_date) tuples for each week in the month.

	Weeks run Monday–Sunday. Partial weeks at month boundaries are included
	but clamped to the month start/end.
	"""
	month_start = date(year, month, 1)
	month_end = date(year, month, calendar.monthrange(year, month)[1])

	weeks = []
	# Start from the Monday of the week containing month_start
	current = month_start
	while current <= month_end:
		# Week start = current (or month_start if mid-week)
		w_start = current
		# Week end = next Sunday or month_end, whichever comes first
		days_until_sunday = 6 - current.weekday()  # 0=Mon -> 6 days to Sun
		w_end = min(current + timedelta(days=days_until_sunday), month_end)
		weeks.append((w_start, w_end))
		current = w_end + timedelta(days=1)

	return weeks


def _get_week_stats(user, w_start, w_end):
	"""Get task statistics for a user in a given week."""
	start_str = w_start.strftime("%Y-%m-%d")
	end_str = w_end.strftime("%Y-%m-%d")

	base_filters = [
		["WB Task", "assign_to", "=", user],
		["WB Task", "due_date", ">=", start_str],
		["WB Task", "due_date", "<=", end_str],
	]

	total = frappe.db.count("WB Task", filters=base_filters)

	completed = frappe.db.count(
		"WB Task",
		filters=base_filters + [["WB Task", "status", "=", "Completed"]],
	)

	ontime = frappe.db.count(
		"WB Task",
		filters=base_filters + [
			["WB Task", "status", "=", "Completed"],
			["WB Task", "timeliness", "=", "Ontime"],
		],
	)

	delayed = frappe.db.count(
		"WB Task",
		filters=base_filters + [
			["WB Task", "status", "in", ["Open", "Overdue"]],
		],
	)

	return {"total": total, "completed": completed, "ontime": ontime, "delayed": delayed}


def _build_columns(weeks):
	"""Build dynamic column list based on weeks."""
	columns = [
		{"label": _("Team / Person"), "fieldname": "person", "fieldtype": "Data", "width": 160},
		{"label": _("KRA"), "fieldname": "kra", "fieldtype": "Data", "width": 200},
		{"label": _("KPI"), "fieldname": "kpi", "fieldtype": "Data", "width": 160},
	]

	for idx, (w_start, w_end) in enumerate(weeks):
		week_label = f"{w_start.strftime('%d-%b')} to {w_end.strftime('%d-%b')}"
		week_num = idx + 1
		columns.extend([
			{
				"label": _(f"Week {week_num} P"),
				"fieldname": f"w{idx}_p",
				"fieldtype": "Int",
				"width": 70,
				"description": week_label,
			},
			{
				"label": _(f"Week {week_num} A"),
				"fieldname": f"w{idx}_a",
				"fieldtype": "Float",
				"width": 70,
				"description": week_label,
			},
			{
				"label": _(f"Week {week_num} A%"),
				"fieldname": f"w{idx}_apct",
				"fieldtype": "Float",
				"width": 80,
				"description": week_label,
			},
		])

	# Month End Score columns
	columns.extend([
		{"label": _("Month P"), "fieldname": "month_p", "fieldtype": "Int", "width": 80},
		{"label": _("Month A"), "fieldname": "month_a", "fieldtype": "Float", "width": 80},
		{"label": _("Month A%"), "fieldname": "month_apct", "fieldtype": "Float", "width": 90},
	])

	return columns
