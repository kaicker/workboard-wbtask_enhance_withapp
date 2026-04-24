# WorkBoard

A task management app built on Frappe Framework 15. Used internally for assigning,
tracking, and measuring team task performance.

## Stack

- Frappe Framework 15 (Python + JavaScript)
- MySQL/InnoDB database
- Jinja2 templates for dynamic content

## Key Doctypes

- WB Task — main task document (assign, track, complete)
- WB Task Rule — automation rules (recurring + event-triggered task creation)
- WB Task Checklist Template — reusable checklists for tasks
- WB Task Checklist Details — child table for checklist items
- WorkBoard Settings — global config (permissions, visibility, admin role)

## Important Files

- workboard/hooks.py — Frappe hooks (scheduler, doc events, permissions). Be careful editing this.
- workboard/workboard/doctype/wb_task/wb_task.py — main task logic (~200 lines)
- workboard/background_jobs/__init__.py — scheduled jobs (recurring rules, overdue status)
- workboard/utils/__init__.py — task creation from rules, helper functions
- workboard/events/handlers.py — event-based task creation
- workboard/permissions/wb_task.py — permission query conditions
- workboard/www/workboard.html — custom web app page (1140 lines)

## Commands

- bench start — run the dev server
- bench run-tests --app workboard — run tests
- bench migrate — apply database changes after modifying doctypes

## Notes

- Two-step approval: assignee marks "Done," assigner confirms "Completed"
- Tasks auto-marked Overdue by hourly scheduler job
- Timeliness tracked on every task (Ontime/Late) for performance reports
- Permission system restricts visibility to owner/assign_to/assign_from
