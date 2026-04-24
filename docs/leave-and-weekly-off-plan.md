# WorkBoard: Leave & Weekly Off Handling — Plan

**Status:** Draft
**Owner:** @pranavkaicker
**Last updated:** 2026-04-24

---

## 1. Problem

WorkBoard creates tasks from two sources: recurring rules (Daily / Weekly / Fortnightly / Monthly / Quarterly / Yearly) and document events. Today, the system has no concept of a person being unavailable — so:

- A user on vacation returns to a pile of overdue tasks that were never actionable.
- Tasks assigned to an out-of-office user aren't re-routed, so work stalls silently.
- Daily tasks fire on the team's weekly off day (Tuesdays), generating noise.
- Managers have no visibility into the backlog caused by leave, and no controls over how each type of task should behave when the assignee is away.

We need a system that lets each rule decide — per task type — whether to **pause**, **delegate**, or **defer** during leave, and how to reconcile the backlog on return. Weekly off behavior needs to be rule-aware: Daily tasks skip Tuesdays, but Weekly / Monthly / Quarterly / Yearly tasks still fire even if the target date lands on a Tuesday.

---

## 2. Goals

1. Honor a team-wide **weekly off day** (Tuesday) for Daily recurring tasks only.
2. Read approved leave from the existing **Frappe HRMS `Leave Application`** doctype — don't duplicate leave data.
3. Let each `WB Task Rule` pick its own **on-leave behavior**: Pause, Delegate to Backup, or Defer to Return Date.
4. Let each `WB Task Rule` pick its own **return-from-leave policy**: Auto-reschedule, Leave as backlog, or Notify assigner.
5. Surface a clear **Backlog view** in the web UI so returning users and their managers can triage post-leave work.
6. Keep it resilient: if HRMS isn't installed, WorkBoard should degrade gracefully (no leave awareness, but nothing breaks).

## 3. Non-goals (for this iteration)

- Half-day / partial-day leave granularity — treat any approved leave day as a full off day.
- Public holidays (beyond the optional `Holiday List` link — not a primary focus).
- Automatic leave approval workflows — we only consume approved applications.
- Multi-backup chains (backup of a backup) — out of scope; we fall back to assigner if the primary backup is also on leave.

---

## 4. Behavior specification

### 4.1 Weekly off (team-wide)

Configured via a new `WorkBoard Calendar Settings` singleton:

- `weekly_off_day` (Select, default: Tuesday)
- `holiday_list` (Link to Frappe `Holiday List`, optional)

Rule for Daily rules only: **skip task creation if today is the weekly off day** (and `rule.respects_weekly_off = 1`).

Weekly / Fortnightly / Monthly / Quarterly / Yearly rules are **unaffected** by weekly off — if a Monthly task is due on a Tuesday, it still fires. This matches the user's intent: "tuesdays are our weekly offs but if some annual, monthly, weekly tasks fall on tuesday they should still be there, just daily should not be on tuesday."

Event-triggered rules (`after_insert`, `on_submit`, etc.) are unaffected by weekly off entirely — business events don't wait.

### 4.2 Leave detection

Source: approved Frappe HRMS `Leave Application` records.

Query pattern:

```
SELECT name, employee, from_date, to_date, leave_approver
FROM `tabLeave Application`
WHERE status = 'Approved'
  AND docstatus = 1
  AND employee.user_id = <task assignee>
  AND <target_date> BETWEEN from_date AND to_date
```

Employee → User mapping is via `Employee.user_id`.

### 4.3 On-leave behavior (per rule)

New field on `WB Task Rule`: `on_leave_behavior` — Select:

| Value | Behavior |
|---|---|
| `Pause` | Do not create the task. Log a skip entry for audit. |
| `Delegate to Backup` | Create the task, but set `assign_to = backup_user`. Stamp `delegated_from` on the task for audit. |
| `Defer to Return Date` | Create the task with `end_datetime` pushed to the day after the user's `to_date`. |

The `backup_user` field (Link to User) on `WB Task Rule` is only meaningful when `on_leave_behavior = Delegate to Backup`.

For **event rules**, we add a parallel field `on_leave_event_behavior` with the same choices, since event-triggered work has different urgency. Default: `Delegate to Backup`.

### 4.4 Return-from-leave policy (per rule)

New field on `WB Task Rule`: `return_policy` — Select:

| Value | Behavior |
|---|---|
| `Auto-reschedule to return date` | On return day, reschedule the user's Open/Overdue tasks in the leave window to a fresh `end_datetime`. |
| `Leave as backlog` | Do nothing to the task; it stays with its original dates. Shows up in the Backlog view. |
| `Notify assigner` | On return day, add a Comment + Frappe Notification on each task; assigner decides. |

Ad-hoc (non-rule-generated) manual tasks default to **Leave as backlog**.

### 4.5 Backup-chain fallback

If `on_leave_behavior = Delegate to Backup` and the `backup_user` is **also** on leave:

1. Fall back to `assign_from` (the original assigner).
2. If `assign_from` is also on leave, fall back to `Pause` behavior (don't create) and log a warning.

This is deliberately simple — we can add multi-hop backup chains later if a real need emerges.

---

## 5. Data model changes

### 5.1 New: `WorkBoard Calendar Settings` (Single doctype)

| Field | Type | Notes |
|---|---|---|
| `weekly_off_day` | Select (Mon–Sun) | Default: Tuesday |
| `holiday_list` | Link (Holiday List) | Optional layer on top of weekly off |
| `enable_leave_awareness` | Check | Master toggle; off = WorkBoard ignores leave entirely |

### 5.2 New fields on `WB Task Rule`

| Field | Type | Default | Notes |
|---|---|---|---|
| `respects_weekly_off` | Check | `1` when frequency = Daily, else `0` | Only honored for Daily |
| `on_leave_behavior` | Select | `Pause` | `Pause` / `Delegate to Backup` / `Defer to Return Date` |
| `on_leave_event_behavior` | Select | `Delegate to Backup` | Same choices; applies to event-triggered rules |
| `backup_user` | Link (User) | — | Required when behavior = Delegate |
| `return_policy` | Select | `Leave as backlog` | `Auto-reschedule to return date` / `Leave as backlog` / `Notify assigner` |

### 5.3 New fields on `WB Task`

| Field | Type | Notes |
|---|---|---|
| `delegated_from` | Link (User) | Original intended assignee; set when rule delegated due to leave |
| `original_end_datetime` | Datetime | Original date before leave-based deferral (audit) |
| `backlog_reason` | Small Text | E.g. "Post-leave backlog" — used by Backlog view |
| `leave_application` | Link (Leave Application) | Back-reference when creation was affected by a specific leave |

### 5.4 New doctype (optional, for auditing): `WB Leave Skip Log`

Lightweight log of rule-task creations that were paused / delegated / deferred due to leave. One row per skip.

| Field | Type |
|---|---|
| `rule` | Link (WB Task Rule) |
| `user` | Link (User) |
| `leave_application` | Link (Leave Application) |
| `action_taken` | Select (Paused / Delegated / Deferred) |
| `target_date` | Date |
| `resolution` | Small Text |

Useful for debugging and for a "what didn't happen while I was out" digest.

---

## 6. Job & hook changes

### 6.1 Daily job: `trigger_daily_rules` (existing — patch)

New logic at the start:

```python
settings = frappe.get_cached_doc("WorkBoard Calendar Settings")
today_is_weekly_off = today().weekday() == WEEKDAY_MAP[settings.weekly_off_day]
```

Inside the loop, before creating a task:

```python
if today_is_weekly_off and rule.frequency == "Daily" and rule.respects_weekly_off:
    log_skip(rule, reason="weekly_off")
    continue

leave = get_active_leave(rule.assign_to, target_date)
if leave and settings.enable_leave_awareness:
    create_task_with_leave_policy(rule, target_date, leave)
else:
    create_task_normal(rule, target_date)
```

### 6.2 New daily job: `reconcile_returning_users`

Runs once per day (after `trigger_daily_rules`):

1. Find Leave Applications where `to_date = yesterday`.
2. For each returning user, find their `WB Task` records where `status in ('Open', 'Overdue')` and `end_datetime` falls inside the leave window.
3. Apply the originating rule's `return_policy`:
   - `Auto-reschedule` → set `end_datetime = today + rule.duration_offset`
   - `Leave as backlog` → set `backlog_reason = "Post-leave backlog"`
   - `Notify assigner` → `frappe.get_doc(...).add_comment()` + `frappe.publish_realtime` + Notification

### 6.3 Event handlers (existing — patch)

`workboard/events/handlers.py` — before calling `create_task_from_rule`, apply the same leave-policy branching as 6.1, but use `rule.on_leave_event_behavior`.

### 6.4 New helper module: `workboard/utils/leave.py`

Public functions:

- `is_user_on_leave(user, on_date) -> bool`
- `get_active_leave(user, on_date) -> Leave Application | None`
- `resolve_assignee(rule, target_date) -> (user, action_taken, original_user)`
- `get_weekday_map() -> dict`
- `is_weekly_off(on_date) -> bool`
- `log_skip(rule, **kwargs) -> None`

Graceful fallback: if `frappe.db.exists("DocType", "Leave Application")` is False (HRMS not installed), all functions return "not on leave" and the system behaves as today.

---

## 7. UI additions (`workboard/www/workboard.html`)

- **New tab: Backlog** — filters tasks where `backlog_reason` is set or `status = Overdue` and created inside a known leave window for the current user.
- **Delegated chip** — on any task where `delegated_from` is set, show a small "Delegated from X" label.
- **Leave banner** — if the current user has a `Leave Application` starting in the next 7 days, show a banner listing rule-generated tasks that will be affected, with the per-rule policy preview. Encourages upfront setup.
- **Number card:** `tasks_returned_from_leave_today` — for reporting and as a nudge.

---

## 8. Permissions & edge cases

- When a task is delegated, the backup user's normal permission logic applies (they become the `assign_to`). The `assign_from` stays as the original assigner for audit and for the two-step approval flow.
- If HRMS isn't installed, `enable_leave_awareness` is forced off and WorkBoard behaves exactly as today.
- If an event rule's target user is on leave and the policy is `Pause`, we still log a skip — events can't "come back" the way recurring tasks can, so the assigner should be notified explicitly. (Worth considering: always notify assigner on event-rule pause.)
- If the `backup_user` on a rule is not set but behavior is `Delegate to Backup`, fall back to `assign_from` and log.
- Leave applications edited after approval: we re-query on each run, so edits take effect on the next daily pass.

---

## 9. Rollout & migration

- All new fields are additive, so `bench migrate` is safe.
- Existing rules default to `on_leave_behavior = Pause`, `return_policy = Leave as backlog`, `respects_weekly_off` computed from frequency — matches the most conservative "don't change observable behavior" choice except for the weekly-off skip, which is the actual desired change.
- Feature flag: `WorkBoard Calendar Settings.enable_leave_awareness` (default off in production initially). Turn on after a week of observation.

---

# Implementation Plan

## High-level phases

The build is split into six phases. Phases 1–2 are foundational; 3–4 are the core behavior; 5–6 are UX and polish.

| # | Phase | Scope | Dep | Rough size |
|---|---|---|---|---|
| 1 | **Foundation — schema & settings** | New singleton, new fields on Rule + Task, migrations, feature flag | — | Small |
| 2 | **Leave detection helper** | `utils/leave.py` with HRMS integration, unit tests, graceful fallback | 1 | Small |
| 3 | **Weekly off — Daily rule skip** | Patch `trigger_daily_rules` to honor weekly off day | 1, 2 | XS |
| 4 | **On-leave creation behavior** | Pause / Delegate / Defer in daily + event paths; skip log | 1, 2 | Medium |
| 5 | **Return-from-leave reconciliation** | New daily job; reschedule / backlog / notify | 1, 2, 4 | Medium |
| 6 | **UI & reporting** | Backlog tab, delegated chip, leave banner, number card | 1, 4, 5 | Medium |

Ship phases 1–3 together as a first deployable unit (weekly off alone is already a real improvement). Phases 4–5 ship together since they're two halves of the leave lifecycle. Phase 6 can follow independently.

---

## Phase-by-phase detail

### Phase 1 — Foundation: schema & settings

**Goal:** add all new doctype fields and the settings singleton. No behavior change yet.

**Files to add:**

- `workboard/workboard/doctype/workboard_calendar_settings/workboard_calendar_settings.json`
- `workboard/workboard/doctype/workboard_calendar_settings/workboard_calendar_settings.py`
- `workboard/workboard/doctype/wb_leave_skip_log/wb_leave_skip_log.json`
- `workboard/workboard/doctype/wb_leave_skip_log/wb_leave_skip_log.py`

**Files to modify:**

- `workboard/workboard/doctype/wb_task_rule/wb_task_rule.json` — add `respects_weekly_off`, `on_leave_behavior`, `on_leave_event_behavior`, `backup_user`, `return_policy`
- `workboard/workboard/doctype/wb_task/wb_task.json` — add `delegated_from`, `original_end_datetime`, `backlog_reason`, `leave_application`
- `workboard/patches.txt` — new patch entry for default values on existing records
- `workboard/patches/v1_0/set_weekly_off_defaults_on_existing_rules.py` — backfill `respects_weekly_off` = 1 for Daily rules, 0 for others

**Acceptance criteria:**

- `bench migrate` runs cleanly against a fresh DB and a DB with existing data.
- New fields are visible in the WB Task Rule and WB Task form.
- `WorkBoard Calendar Settings` singleton is accessible and saves `weekly_off_day` = Tuesday by default.
- No behavior change observable in task creation.

---

### Phase 2 — Leave detection helper

**Goal:** a single, tested helper module that answers "is this user on leave on this date" — with HRMS installed or not.

**Files to add:**

- `workboard/utils/leave.py`
- `workboard/tests/test_leave.py`

**Key functions:**

```python
def is_hrms_installed() -> bool: ...
def is_user_on_leave(user: str, on_date: date) -> bool: ...
def get_active_leave(user: str, on_date: date) -> dict | None: ...
def resolve_assignee(rule, target_date: date) -> tuple[str, str, str | None]:
    """Returns (final_assignee, action_taken, delegated_from)."""
def is_weekly_off(on_date: date) -> bool: ...
def log_skip(rule, user, leave_application, action, target_date, resolution) -> None: ...
```

**Acceptance criteria:**

- Unit tests cover: user on leave, user not on leave, HRMS missing, backup on leave fallback to assigner, both on leave → pause.
- `is_user_on_leave("test@x.com", date(2026, 5, 1))` returns False cleanly when HRMS is absent.
- No queries against `tabLeave Application` happen if HRMS is absent (guarded by `is_hrms_installed`).

---

### Phase 3 — Weekly off for Daily rules

**Goal:** Daily rules skip on Tuesdays (or whatever `weekly_off_day` is set to). All other frequencies unaffected.

**Files to modify:**

- `workboard/background_jobs/__init__.py` — in `trigger_daily_rules`, add the weekly-off skip check for Daily frequency rules
- `workboard/tests/test_recurring_rules.py` — add test cases for Daily-on-Tuesday skip, Weekly-on-Tuesday no skip, Monthly-on-Tuesday no skip

**Acceptance criteria:**

- With `weekly_off_day = Tuesday`, a Daily rule with `respects_weekly_off = 1` creates **zero** tasks on a Tuesday.
- A Weekly rule scheduled for Tuesday creates its task on Tuesday.
- A Monthly rule whose date-of-month falls on a Tuesday creates its task.
- A Daily rule with `respects_weekly_off = 0` still creates tasks on Tuesday (escape hatch).
- Test: run `trigger_daily_rules` under a mocked Tuesday `today()` and assert counts.

---

### Phase 4 — On-leave creation behavior

**Goal:** when the intended assignee is on leave, each rule's `on_leave_behavior` decides what happens.

**Files to modify:**

- `workboard/utils/__init__.py` (or wherever `create_task_from_rule` lives) — wrap the existing creation call with leave-policy branching
- `workboard/background_jobs/__init__.py` — call the wrapped function from `trigger_daily_rules`
- `workboard/events/handlers.py` — call the wrapped function but with `rule.on_leave_event_behavior`
- `workboard/tests/test_leave_policies.py` — test each of the three behaviors end-to-end

**New logic:**

```python
def create_task_with_leave_policy(rule, target_date, event_context=None):
    behavior = rule.on_leave_event_behavior if event_context else rule.on_leave_behavior
    leave = get_active_leave(rule.assign_to, target_date)
    if not leave:
        return create_task_normal(rule, target_date)

    if behavior == "Pause":
        log_skip(rule, rule.assign_to, leave, "Paused", target_date, "assignee on leave")
        return None

    if behavior == "Delegate to Backup":
        assignee, action, delegated_from = resolve_assignee(rule, target_date)
        if assignee is None:
            log_skip(rule, rule.assign_to, leave, "Paused", target_date, "backup also on leave")
            return None
        task = create_task_normal(rule, target_date, override_assign_to=assignee)
        task.delegated_from = delegated_from
        task.leave_application = leave.name
        task.save(ignore_permissions=True)
        return task

    if behavior == "Defer to Return Date":
        deferred_date = leave.to_date + timedelta(days=1)
        task = create_task_normal(rule, target_date, override_end_datetime=deferred_date)
        task.original_end_datetime = original_end
        task.leave_application = leave.name
        task.save(ignore_permissions=True)
        return task
```

**Acceptance criteria:**

- Pause: no WB Task created, one WB Leave Skip Log row written.
- Delegate: WB Task created with `assign_to = backup_user` and `delegated_from` set.
- Defer: WB Task created with `end_datetime` = (leave.to_date + 1 day), `original_end_datetime` preserved.
- Backup-on-leave fallback: assigner used; if assigner also on leave, Paused and logged.
- Event-rule path uses `on_leave_event_behavior` (not `on_leave_behavior`).
- HRMS-not-installed path: behaves exactly as today — all tasks created normally.

---

### Phase 5 — Return-from-leave reconciliation

**Goal:** when someone returns, apply their rules' `return_policy` to tasks that were open during their leave window.

**Files to add:**

- `workboard/background_jobs/reconcile_leave.py` (or a new function in the existing background_jobs module)

**Files to modify:**

- `workboard/hooks.py` — register the new daily job after `trigger_daily_rules`
- `workboard/tests/test_return_policies.py` — one test per policy

**Core logic:**

```python
def reconcile_returning_users():
    yesterday = add_days(today(), -1)
    returning = frappe.get_all(
        "Leave Application",
        filters={"status": "Approved", "docstatus": 1, "to_date": yesterday},
        fields=["name", "employee", "from_date", "to_date"],
    )
    for leave in returning:
        user = get_user_for_employee(leave.employee)
        open_tasks = get_open_tasks_for_user_in_window(user, leave.from_date, leave.to_date)
        for task in open_tasks:
            apply_return_policy(task, leave, user)
```

**Acceptance criteria:**

- Auto-reschedule: `end_datetime` updated to `today() + rule.offset`, `status` flips Overdue → Open.
- Leave as backlog: task unchanged, `backlog_reason = "Post-leave backlog"` set.
- Notify assigner: Comment appended to task, Frappe Notification sent to `assign_from`.
- Non-rule tasks default to `Leave as backlog`.
- Idempotent: re-running the job on the same day doesn't duplicate notifications or re-stamp `backlog_reason`.

---

### Phase 6 — UI & reporting

**Goal:** make the new states visible to users and managers.

**Files to modify:**

- `workboard/www/workboard.html` — add Backlog tab, delegated chip, leave banner
- `workboard/workboard/number_card/tasks_returned_from_leave_today/…` — new number card
- `workboard/workboard/report/post_leave_backlog/…` — new report listing tasks with `backlog_reason` set

**UI spec:**

- **Backlog tab:** lists tasks where `backlog_reason` is set OR (`status = Overdue` AND assignee has a leave application covering the task's creation date).
- **Delegated chip:** small pill "Delegated from {delegated_from}" on task cards where the field is set.
- **Leave banner:** if the current user has an approved Leave Application starting in the next 7 days, banner reads: "You have leave from {from_date} to {to_date}. N recurring tasks will be affected: [view policies]". Links to a modal showing per-rule policy.
- **Number card:** `tasks_returned_from_leave_today` — count of tasks the reconciliation job touched today.

**Acceptance criteria:**

- Backlog tab shows correct tasks for the logged-in user.
- Delegated chip renders only when `delegated_from` is set.
- Leave banner appears only when an approved, upcoming (<=7 days) Leave Application exists.
- Number card updates after the reconciliation job runs.

---

## Testing strategy

- **Unit tests** for every helper in `utils/leave.py` — this is where the logic lives.
- **Integration tests** for each rule policy combination, run against a mocked HRMS `Leave Application` set.
- **Feature-flag test**: with `enable_leave_awareness = 0`, system behaves exactly as pre-change. This is the rollback insurance.
- **HRMS-absent test**: run the full test suite with HRMS mocked as uninstalled.
- **Smoke test script**: `scripts/smoke_leave.py` — creates a fake leave, runs the jobs, prints what happened. Useful for QA on a staging bench.

## Open questions to resolve before Phase 4

1. For **event rules** with `Pause` policy, do we notify the assigner? (Recommendation: yes — events don't retry.)
2. For **Defer to Return Date**, if the return date is already past (leave edited retroactively), do we create immediately or skip?
3. Should the **weekly off day** be per-team or strictly global? (Current plan: global. Revisit if multi-team rollout.)
4. Does half-day leave (HRMS `half_day = 1`) count as a full off day? (Current plan: yes — simplification.)

## Appendix: rollout checklist

- [ ] Phase 1 merged and migrated on staging
- [ ] Phase 2 helper shipped with tests green
- [ ] Phase 3 live on staging for one week, monitoring skip count
- [ ] Phase 4 + 5 merged together; feature flag off in prod
- [ ] Create a "pilot" rule set with a real user's leave booked
- [ ] Turn on `enable_leave_awareness` for a small user group
- [ ] Observe a full leave cycle (before / during / after) in prod
- [ ] Phase 6 UI ships
- [ ] Enable for all users
