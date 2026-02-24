import frappe
from frappe.tests.utils import FrappeTestCase


class TestWBTaskPermissions(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._prev_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user(self._prev_user)
		frappe.db.rollback()
		super().tearDown()

	def _make_user(self):
		email = "workboard_user@example.com"
		if not frappe.db.exists("User", email):
			u = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Workboard",
					"enabled": 1,
					"send_welcome_email": 0,
					"user_type": "System User",
				}
			)
			u.insert(ignore_permissions=True)
		return email

	def test_permission_query_conditions_toggle(self):
		from workboard.permissions.wb_task import get_permission_query_conditions

		user = self._make_user()

		frappe.db.set_single_value("WorkBoard Settings", "restrict_task_visibility", 0)
		self.assertEqual(get_permission_query_conditions(user), "")

		frappe.db.set_single_value("WorkBoard Settings", "restrict_task_visibility", 1)
		cond = get_permission_query_conditions(user)
		self.assertIn("tabWB Task", cond)
		self.assertIn("assign_to", cond)
		self.assertIn(user, cond)

