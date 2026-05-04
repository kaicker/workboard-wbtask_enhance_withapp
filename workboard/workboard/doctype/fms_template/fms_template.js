// Copyright (c) 2026, Nesscale Solutions Pvt Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on('FMS Template', {
	onload(frm) {
		frm.set_query('reference_doctype', function () {
			return {
				filters: {
					istable: 0,
					issingle: 0
				}
			};
		});
	},
	refresh(frm) {
		frm.trigger('setup_reference_date_field_options');
	},
	reference_doctype(frm) {
		frm.trigger('setup_reference_date_field_options');
	},
	scheduled_tasks_add(frm) {
		frm.trigger('setup_reference_date_field_options');
	},
	setup_reference_date_field_options(frm) {
		if (!frm.doc.reference_doctype) {
			set_scheduled_date_field_options(frm, []);
			return;
		}

		frappe.model.with_doctype(frm.doc.reference_doctype, function () {
			const meta = frappe.get_doc('DocType', frm.doc.reference_doctype);
			const date_options = (meta.fields || [])
				.filter((df) => ['Date', 'Datetime'].includes(df.fieldtype))
				.map((df) => df.fieldname);

			date_options.push('creation', 'modified');
			set_scheduled_date_field_options(frm, date_options);
		});
	}
});

function set_scheduled_date_field_options(frm, options) {
	const df = frappe.meta.get_docfield(
		'FMS Scheduled Task',
		'reference_date_field',
		frm.doc.name
	);
	if (!df) return;

	df.options = [''].concat(options).join('\n');
	frm.refresh_field('scheduled_tasks');
}
