// Copyright (c) 2025, Nesscale Solutions Pvt Ltd and contributors
// For license information, please see license.txt

frappe.listview_settings["WB Task"] = {
	get_indicator: function (doc) {
		// Status indicators
		if (doc.status === "Open") {
			return [__("Open"), "blue", "status,=,Open"];
		} else if (doc.status === "Done") {
			return [__("Done"), "purple", "status,=,Done"];
		} else if (doc.status === "Completed") {
			return [__("Completed"), "green", "status,=,Completed"];
		} else if (doc.status === "Overdue") {
			return [__("Overdue"), "red", "status,=,Overdue"];
		}
	},

	formatters: {
		task_type: function (value) {
			if (value === "Auto") {
				return `<span class="indicator-pill orange filterable" data-filter="task_type,=,Auto">
					<span class="ellipsis">${__("Auto")}</span>
				</span>`;
			} else if (value === "Manual") {
				return `<span class="indicator-pill blue filterable" data-filter="task_type,=,Manual">
					<span class="ellipsis">${__("Manual")}</span>
				</span>`;
			}
			return value;
		},

		timeliness: function (value) {
			if (value === "Ontime") {
				return `<span class="indicator-pill green filterable" data-filter="timeliness,=,Ontime">
					<span class="ellipsis">${__("Ontime")}</span>
				</span>`;
			} else if (value === "Late") {
				return `<span class="indicator-pill red filterable" data-filter="timeliness,=,Late">
					<span class="ellipsis">${__("Late")}</span>
				</span>`;
			}
			return value;
		},
	},
};
