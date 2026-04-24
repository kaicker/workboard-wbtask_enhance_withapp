// Copyright (c) 2025, Nesscale Solutions Pvt Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on('WB Task', {
  refresh(frm) {
    frm.trigger('add_action_buttons');
  },
  add_action_buttons(frm) {
    if (frm.is_new()) return;

    const current_user = frappe.session.user;
    const is_assignee = current_user === frm.doc.assign_to;
    const is_assigner = current_user === frm.doc.assign_from;
    const is_admin = current_user === 'Administrator';

    // Get WorkBoard Settings including admin role
    frappe.call({
      method: 'workboard.utils.get_workboard_settings',
      callback: (r) => {
        const settings = r.message || {};
        const admin_role = settings.workboard_admin_role;
        const has_admin_role = admin_role && frappe.user_roles.includes(admin_role);

        if (frm.doc.task_type === 'Manual') {
          // Manual tasks: strict approval workflow
          // Step 1: Assignee marks Done (Open/Overdue → Done)
          if (['Open', 'Overdue'].includes(frm.doc.status)) {
            if (is_assignee || is_admin || has_admin_role) {
              frm.add_custom_button(__('Mark Done'), () => {
                frm.call({
                  method: 'mark_done',
                  doc: frm.doc,
                  freeze: true,
                  freeze_message: __('Marking as Done...'),
                  callback: () => frm.reload_doc()
                });
              }).addClass('btn-primary');
            }
          }

          // Step 2: Assigner marks Completed OR Reopens (Done → Completed / Open)
          if (frm.doc.status === 'Done') {
            if (is_assigner || is_admin || has_admin_role) {
              frm.add_custom_button(__('Mark Completed'), () => {
                frm.call({
                  method: 'mark_completed',
                  doc: frm.doc,
                  freeze: true,
                  freeze_message: __('Marking as Completed...'),
                  callback: () => frm.reload_doc()
                });
              }).addClass('btn-success');

              frm.add_custom_button(__('Reopen'), () => {
                frm.call({
                  method: 'reopen_task',
                  doc: frm.doc,
                  freeze: true,
                  freeze_message: __('Reopening task...'),
                  callback: () => frm.reload_doc()
                });
              }).addClass('btn-warning');
            }
          }
        } else if (frm.doc.task_type === 'Auto') {
          // Auto tasks: assignee can directly mark Completed
          if (['Open', 'Overdue'].includes(frm.doc.status)) {
            if (is_assignee || is_admin || has_admin_role) {
              frm.add_custom_button(__('Mark Completed'), () => {
                frm.call({
                  method: 'mark_completed',
                  doc: frm.doc,
                  freeze: true,
                  freeze_message: __('Marking as Completed...'),
                  callback: () => frm.reload_doc()
                });
              }).addClass('btn-primary');
            }
          }
        }
      }
    });
  },
  checklist_template(frm){
    frm.trigger('fetch_checklist');
  },
  fetch_checklist(frm) {
    frm.call({
      method: 'fetch_checklist',
      doc: frm.doc,
      freeze: true,
      callback: (r) => {

      }
    });
  }
});
