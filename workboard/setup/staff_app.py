"""Custom fields on Employee for the WorkBoard staff mobile app.

Staff open the Android app, type their Staff App No + PIN once, and the app
keeps a device token. Admins fill the two fields below on each Employee.

Applied on `bench migrate` (after_migrate) and on install, so it is safe to
re-run: existing fields are updated in place, nothing is duplicated.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

STAFF_APP_FIELDS = {
	"Employee": [
		{
			"fieldname": "wb_staff_app_tab",
			"fieldtype": "Tab Break",
			"label": "Staff App",
		},
		{
			"fieldname": "wb_staff_no",
			"fieldtype": "Data",
			"label": "Staff App No",
			"insert_after": "wb_staff_app_tab",
			"unique": 1,
			"in_standard_filter": 1,
			"description": "The number this employee types into the WorkBoard app. Must be unique.",
		},
		{
			"fieldname": "wb_pin",
			"fieldtype": "Password",
			"label": "Staff App PIN",
			"insert_after": "wb_staff_no",
			"length": 12,
			"description": "4-6 digit PIN, asked once when the app is set up on a phone.",
		},
		{
			"fieldname": "wb_staff_app_cb",
			"fieldtype": "Column Break",
			"insert_after": "wb_pin",
		},
		{
			"fieldname": "wb_app_last_seen",
			"fieldtype": "Datetime",
			"label": "App Last Seen",
			"insert_after": "wb_staff_app_cb",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "wb_app_token",
			"fieldtype": "Data",
			"label": "App Device Token (hashed)",
			"insert_after": "wb_app_last_seen",
			"read_only": 1,
			"hidden": 1,
			"no_copy": 1,
			"search_index": 1,
		},
		{
			"fieldname": "wb_fcm_token",
			"fieldtype": "Small Text",
			"label": "Push Notification Token",
			"insert_after": "wb_app_token",
			"read_only": 1,
			"hidden": 1,
			"no_copy": 1,
		},
	]
}


def create_staff_app_fields():
	# Employee comes from ERPNext/HRMS; skip quietly on sites without it.
	if not frappe.db.exists("DocType", "Employee"):
		return
	create_custom_fields(STAFF_APP_FIELDS, update=True)
