"""
WorkBoard Web Page Context Controller
File: workboard/www/workboard.py  (OR save as context script in Web Page)

This makes the page login-required and passes user info to the template.
"""

import frappe


def get_context(context):
    # Force login – guests will be redirected automatically by Frappe
    if frappe.session.user == "Guest":
        frappe.throw(frappe._("Please login to access WorkBoard"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = False
    # Page meta
    context.title = "WorkBoard – My Tasks"
    context.current_user = frappe.session.user
