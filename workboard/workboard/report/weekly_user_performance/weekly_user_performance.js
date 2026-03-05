// Copyright (c) 2026, Nesscale Solutions Pvt Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Weekly User Performance"] = {
	"filters": [
		{
			"fieldname": "month",
			"label": __("Month"),
			"fieldtype": "Select",
			"options": "January\nFebruary\nMarch\nApril\nMay\nJune\nJuly\nAugust\nSeptember\nOctober\nNovember\nDecember",
			"default": moment().format("MMMM"),
			"reqd": 1
		},
		{
			"fieldname": "year",
			"label": __("Year"),
			"fieldtype": "Int",
			"default": moment().year(),
			"reqd": 1
		}
	]
};
