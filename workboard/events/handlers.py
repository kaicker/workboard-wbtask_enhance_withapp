import frappe
from frappe import _
from frappe.utils import parse_val

from workboard.utils import _context, _create_task_from_rule


def create_task_for_event(doc, method):
	try:
		if (
			(frappe.flags.in_import and frappe.flags.mute_emails)
			or frappe.flags.in_patch
			or frappe.flags.in_install
		):
			return
		event = _map_method_to_based_on(doc, method)
		if not event:
			return

		# Skip self-referential events: WB Task changes shouldn't trigger WB Task rules/FMS.
		if doc.doctype in ("WB Task", "WB Task Rule", "FMS Template", "FMS Step"):
			return

		ctx = _context(doc)

		# 1) WB Task Rule (existing behavior)
		rules = frappe.get_all(
			"WB Task Rule",
			filters={
				"enabled": 1,
				"event": 1,
				"based_on": event,
				"reference_doctype": doc.doctype,
			},
			fields=["*"],
		)
		for r in rules:
			if event == "Value Change":
				if not r.value_changed or not frappe.db.has_column(doc.doctype, r.value_changed):
					continue
				doc_before_save = doc.get_doc_before_save()
				field_value_before_save = doc_before_save.get(r.value_changed) if doc_before_save else None
				field_value_before_save = parse_val(field_value_before_save)
				if doc.get(r.value_changed) == field_value_before_save:
					continue
			if r.condition and not frappe.safe_eval(r.condition, None, ctx):
				continue
			_create_task_from_rule(r, context=ctx)

		# 2) FMS Template (event-triggered flows)
		_trigger_event_fms_templates(doc, event, ctx)
	except Exception:
		frappe.log_error(title=_("WorkBoard Error"), message=frappe.get_traceback())


def _trigger_event_fms_templates(doc, event, ctx):
	templates = frappe.get_all(
		"FMS Template",
		filters={
			"enabled": 1,
			"trigger_type": "Event",
			"based_on": event,
			"reference_doctype": doc.doctype,
		},
		pluck="name",
	)
	if not templates:
		return
	for tpl_name in templates:
		try:
			tpl = frappe.get_doc("FMS Template", tpl_name)

			if event == "Value Change":
				if not tpl.value_changed or not frappe.db.has_column(doc.doctype, tpl.value_changed):
					continue
				doc_before_save = doc.get_doc_before_save()
				before = doc_before_save.get(tpl.value_changed) if doc_before_save else None
				before = parse_val(before)
				if doc.get(tpl.value_changed) == before:
					continue

			if tpl.condition and not frappe.safe_eval(tpl.condition, None, ctx):
				continue

			tpl.start_run(reference_doctype=doc.doctype, reference_name=doc.name)
		except Exception:
			frappe.log_error(title=_("WorkBoard FMS Trigger Error"), message=frappe.get_traceback())


def _map_method_to_based_on(doc, method):
	m = {"after_insert": "New", "after_save": "Save", "on_submit": "Submit", "on_cancel": "Cancel"}
	if not doc.flags.in_insert:
		m["on_change"] = "Value Change"
	return m.get(method)
