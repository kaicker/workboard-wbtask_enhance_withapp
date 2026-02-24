import frappe
from frappe.utils import cint

from workboard.utils import get_workboard_settings


def _is_exempt_user(user: str) -> bool:
	if not user or user == "Guest":
		return True
	if user in ("Administrator",):
		return True

	roles = frappe.get_roles(user)
	if "System Manager" in roles:
		return True

	settings = get_workboard_settings()
	admin_role = settings.get("workboard_admin_role")
	return bool(admin_role and admin_role in roles)


def _is_visibility_restricted() -> bool:
	settings = get_workboard_settings()
	return bool(cint(settings.get("restrict_task_visibility") or 0))


def get_permission_query_conditions(user: str) -> str:
	"""Limit visible tasks to ones the user is involved in.

	This is an optional extra restriction. Base DocType permissions still apply.
	"""
	if _is_exempt_user(user) or not _is_visibility_restricted():
		return ""

	u = frappe.db.escape(user)
	return (
		f"(`tabWB Task`.`owner`={u} OR `tabWB Task`.`assign_to`={u} OR `tabWB Task`.`assign_from`={u})"
	)


def has_permission(doc, ptype=None, user: str | None = None) -> bool:
	"""Doc-level permission check consistent with query conditions."""
	user = user or frappe.session.user
	if _is_exempt_user(user) or not _is_visibility_restricted():
		return True

	return bool(doc and (doc.owner == user or doc.assign_to == user or doc.assign_from == user))

