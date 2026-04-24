import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, get_datetime, getdate, now_datetime, nowdate, today

from workboard.utils import _context, _create_task_from_rule


def trigger_daily_rules():
	try:
		_run_recurring_rules()
		_run_offset_rules()
	except Exception:
		frappe.log_error(title=_("WorkBoard Error"), message=frappe.get_traceback())


def _run_recurring_rules():
	rules = frappe.get_all("WB Task Rule", filters={"enabled": 1, "recurring": 1}, fields=["*"])
	if not rules:
		return
	today_dt = getdate(today())

	# Weekly off check — cheap, done once per scheduler run.
	from workboard.utils.leave import is_weekly_off, is_holiday, log_skip

	weekly_off_today = is_weekly_off()
	holiday_today = is_holiday()

	selected = []
	for r in rules:
		if r.frequency == "Daily":
			# Weekly off only applies to Daily rules, and only when the
			# rule opts in via respects_weekly_off.
			if weekly_off_today and cint(r.get("respects_weekly_off") or 0):
				log_skip(
					rule=r.name,
					user=r.get("assign_to"),
					target_date=today_dt,
					action_taken="Paused",
					resolution=f"Weekly off ({today_dt.strftime('%A')})",
				)
				continue
			# Holiday list: if configured, treat like weekly off for Daily rules.
			if holiday_today and cint(r.get("respects_weekly_off") or 0):
				log_skip(
					rule=r.name,
					user=r.get("assign_to"),
					target_date=today_dt,
					action_taken="Paused",
					resolution="Holiday",
				)
				continue
			selected.append(r)
		elif r.frequency == "Weekly" and today_dt.strftime("%A") == r.day_of_week:
			selected.append(r)
		elif r.frequency == "Fortnightly" and today_dt.strftime("%A") == r.day_of_week:
			# Check if it's a fortnightly occurrence (every 14 days)
			# We use a simple check: if the day number is in the first or third week of the month
			day_of_month = today_dt.day
			if (day_of_month <= 7) or (15 <= day_of_month <= 21):
				selected.append(r)
		elif r.frequency == "Monthly" and cint(today_dt.day) == cint(r.date_of_month):
			selected.append(r)
		elif r.frequency == "Quarterly" and cint(today_dt.day) == cint(r.date_of_month):
			# Quarterly: every 3 months (January, April, July, October)
			if today_dt.month in [1, 4, 7, 10]:
				selected.append(r)
		elif (
			r.frequency == "Yearly"
			and cint(today_dt.day) == cint(r.date_of_month)
			and cint(today_dt.month) == cint(r.month_of_year)
		):
			selected.append(r)
	for r in selected:
		try:
			_create_task_from_rule(r)
			frappe.db.commit()
		except Exception:
			frappe.log_error(title=_("WorkBoard Error"), message=frappe.get_traceback())


def _run_offset_rules():
	rules = frappe.get_all(
		"WB Task Rule",
		filters={
			"enabled": 1,
			"event": 1,
			"based_on": ["in", ["Days Before", "Days After"]],
		},
		fields=["*"],
	)
	for r in rules:
		for ref_doc in _docs_matching_offset_window(r):
			try:
				ctx = _context(ref_doc)
				if r.condition and not frappe.safe_eval(r.condition, None, ctx):
					continue
				# Offset rules fire from scheduler but conceptually resemble events —
				# use the event-leave policy so they honor `on_leave_event_behavior`.
				_create_task_from_rule(r, context=ctx, is_event=True)
			except Exception:
				frappe.log_error(title=_("WorkBoard Error"), message=frappe.get_traceback())


def _docs_matching_offset_window(rule):
	out = []
	if not rule.reference_doctype or not rule.reference_date:
		return out
	if not frappe.db.has_column(rule.reference_doctype, rule.reference_date):
		return out
	diff = cint(rule.days_before_or_after or 0)
	if rule.based_on == "Days After":
		diff = -diff
	ref_date = add_to_date(nowdate(), days=diff)
	start = f"{ref_date} 00:00:00.000000"
	end = f"{ref_date} 23:59:59.000000"
	names = frappe.get_all(
		rule.reference_doctype,
		fields=["name"],
		filters=[
			[rule.reference_doctype, rule.reference_date, ">=", start],
			[rule.reference_doctype, rule.reference_date, "<=", end],
		],
	)
	for n in names:
		out.append(frappe.get_doc(rule.reference_doctype, n.name))
	return out


def update_task_status():
	names = frappe.get_all("WB Task", filters={"status": ["not in", ["Completed"]]}, pluck="name")
	for name in names:
		try:
			d = frappe.get_doc("WB Task", name)
			prev = d.status
			d.validate()
			if d.status != prev:
				d.save(ignore_permissions=True)
		except Exception:
			frappe.log_error(title=_("WorkBoard Status update error"), message=frappe.get_traceback())


# ---------------------------------------------------------------------------
# Return-from-leave reconciliation
# ---------------------------------------------------------------------------


def reconcile_returning_users():
	"""Apply each rule's return_policy to Open/Overdue tasks of users who
	returned from leave yesterday.

	Policies:
	  * "Auto-reschedule to return date" — shift end_datetime to today 23:59,
	    stamp `backlog_reason`.
	  * "Leave as backlog" — no mutation, just stamp `backlog_reason` so the
	    UI can surface it on a Backlog tab.
	  * "Notify assigner" — stamp reason + add a comment pinging assign_from.

	The scheduler calls this daily. Safe to run multiple times; idempotent
	via the `backlog_reason` field.
	"""
	try:
		if not _leave_feature_on():
			return

		from workboard.utils.leave import users_returning_from_leave

		returning = users_returning_from_leave()
		if not returning:
			return

		today_dt = getdate(today())

		for entry in returning:
			user = entry["user"]
			leave_name = entry.get("name")

			tasks = frappe.get_all(
				"WB Task",
				filters={
					"assign_to": user,
					"status": ["in", ["Open", "Overdue"]],
				},
				fields=["name", "source_rule", "end_datetime", "backlog_reason"],
			)
			for t in tasks:
				if t.backlog_reason:
					# Already reconciled on a prior run.
					continue

				return_policy = None
				if t.source_rule:
					return_policy = frappe.db.get_value(
						"WB Task Rule", t.source_rule, "return_policy"
					)
				return_policy = return_policy or "Leave as backlog"

				try:
					_apply_return_policy(t.name, return_policy, user, leave_name, today_dt)
					frappe.db.commit()
				except Exception:
					frappe.log_error(
						title=_("WorkBoard reconcile_returning_users task error"),
						message=frappe.get_traceback(),
					)
	except Exception:
		frappe.log_error(
			title=_("WorkBoard reconcile_returning_users error"),
			message=frappe.get_traceback(),
		)


def _leave_feature_on() -> bool:
	try:
		from workboard.utils.leave import leave_awareness_enabled

		return leave_awareness_enabled()
	except Exception:
		return False


def _apply_return_policy(task_name: str, policy: str, user: str, leave_name, today_dt):
	"""Mutate a single WB Task per its rule's return_policy."""
	task = frappe.get_doc("WB Task", task_name)
	reason = f"Carried over from leave ending {add_days(today_dt, -1)}"

	if policy == "Auto-reschedule to return date":
		task.original_end_datetime = task.original_end_datetime or task.end_datetime
		task.end_datetime = get_datetime(f"{today_dt} 23:59:59")
		task.backlog_reason = reason + " — auto-rescheduled to today"
		if leave_name:
			task.leave_application = task.leave_application or leave_name
		task.save(ignore_permissions=True)
		return

	if policy == "Notify assigner":
		task.backlog_reason = reason + " — assigner notified"
		if leave_name:
			task.leave_application = task.leave_application or leave_name
		task.save(ignore_permissions=True)
		if task.assign_from:
			try:
				task.add_comment(
					comment_type="Comment",
					text=(
						f"{user} is back from leave. This task remained in {task.status} "
						f"during the leave. Please decide whether to reschedule, reassign, "
						f"or cancel."
					),
				)
			except Exception:
				# Comment failures shouldn't block the save above.
				frappe.log_error(
					title="WorkBoard reconcile add_comment error",
					message=frappe.get_traceback(),
				)
		return

	# Default: "Leave as backlog" — just tag it.
	task.backlog_reason = reason
	if leave_name:
		task.leave_application = task.leave_application or leave_name
	task.save(ignore_permissions=True)
