# Silent Rule Failures — Patch Plan

**Status:** Implemented 2026-04-25 (Patches 1 + 2). Patch 3 deferred.
**Audited:** 2026-04-25
**Affected file:** `workboard/background_jobs/__init__.py`
**Severity:** HIGH (statutory tax payments are silently skipped)
**Estimated work:** ~2 hours code + 1 hour tests

---

## TL;DR for the implementer

Three independent bugs in `_run_recurring_rules()` cause WB Task Rules to silently produce zero tasks:

1. **Disabled assignees** — when a rule's `assign_to` user is `enabled=0`, the rule fires but task creation throws an exception that is swallowed and logged to `Error Log` (which has ~15-day retention). The rule looks "broken" but produces no signal anywhere users can see. **9 rules currently affected**, including statutory ESIC and EPF payments.
2. **Month-end clamp missing** — `Monthly` rules with `date_of_month ∈ {29, 30, 31}` skip months that don't have those days (Feb/Apr/Jun/Sep/Nov for `dom=31`). **12 rules currently affected.** Same bug applies to `Quarterly` and `Yearly`.
3. **Quarterly hardcoded calendar** — the Quarterly branch only fires when `today.month in [1, 4, 7, 10]`, hardcoding the year's quarters to start in January. Not currently biting any rule, but wrong in principle.

Fix in this order: **(1) → (2) → (3)**. Each fix is independent — ship them as separate PRs if you prefer small diffs.

---

## Diagnosis: where each bug lives

### Bug 1 — disabled-user task creation fails silently

**File:** `workboard/background_jobs/__init__.py`, lines 73–78:

```python
for r in selected:
    try:
        _create_task_from_rule(r)
        frappe.db.commit()
    except Exception:
        frappe.log_error(title=_("WorkBoard Error"), message=frappe.get_traceback())
```

When `r.assign_to` points to a User with `enabled=0`, `_create_task_from_rule()` calls `doc.save(ignore_permissions=True)` on a WB Task whose `assign_to` Link field references a disabled user. Frappe's link validator raises `LinkValidationError` (or in some Frappe versions, `frappe.exceptions.ValidationError`). The bare `except Exception` swallows it, writes to `Error Log` titled "WorkBoard Error", and the loop continues.

The user has no way to know the rule failed:
- No row in `WB Task` (so the dashboard shows nothing).
- No row in `WB Leave Skip Log` (only the leave-handling code writes there, and only when `enable_leave_awareness=1`, which is currently `0` on the production site).
- The `Error Log` entry expires within ~15 days (verified: oldest entry on the live site is Apr 10; today is Apr 25).

**Live evidence (verified Apr 25, 2026 against the production site):**

- 9 enabled recurring rules have a disabled `assign_to`. Full list:

| Rule | Title | Frequency | Disabled User |
|---|---|---|---|
| Task-Rule-0286 | Advance Tax Payment - Income Tax | Quarterly | `rishh6980@gmail.com` |
| Task-Rule-0268 | ESIC Payment | Monthly | `email.rahulkumar689@gmail.com` |
| Task-Rule-0269 | EPF Payment | Monthly | `email.rahulkumar689@gmail.com` |
| Task-Rule-0208 | Car Insurance - DL-08-CAT-5065 (INNOVA TOYOTA) | Yearly | `gaur65162@gmail.com` |
| Task-Rule-0209 | Car Insurance - DL34D8867 (TATA TIAGO) | Yearly | `gaur65162@gmail.com` |
| Task-Rule-0210 | Car Insurance - CH01CN6528 (BMW-6) | Yearly | `gaur65162@gmail.com` |
| Task-Rule-0211 | Car Insurance - CH01CH2546 (MERCEDES - Benz) | Yearly | `gaur65162@gmail.com` |
| Task-Rule-0213 | Car Insurance- (PORSCHE) | Yearly | `gaur65162@gmail.com` |
| Task-Rule-0214 | Car Insurance - UP16EL3388 (INNOVA TOYOTA) | Yearly | `gaur65162@gmail.com` |

- Smoking-gun pair: Task-Rule-0285 and Task-Rule-0286 are sibling rules (both Quarterly, both `date_of_month=5`, both created Mar 26 within 10 minutes, identical config except `assign_to`). Task-Rule-0285 (active user) fired on Apr 5 and produced a task. Task-Rule-0286 (disabled user) did not. No Error Log entry remains because of retention.

### Bug 2 — month-end clamp missing

**File:** `workboard/background_jobs/__init__.py`, lines 61–72:

```python
elif r.frequency == "Monthly" and cint(today_dt.day) == cint(r.date_of_month):
    selected.append(r)
elif r.frequency == "Quarterly" and cint(today_dt.day) == cint(r.date_of_month):
    if today_dt.month in [1, 4, 7, 10]:
        selected.append(r)
elif (
    r.frequency == "Yearly"
    and cint(today_dt.day) == cint(r.date_of_month)
    and cint(today_dt.month) == cint(r.month_of_year)
):
    selected.append(r)
```

A Monthly rule with `date_of_month=31` matches the condition only on months that have a 31st — Jan, Mar, May, Jul, Aug, Oct, Dec. It silently skips Feb (28/29), Apr (30), Jun (30), Sep (30), Nov (30). `dom=30` skips Feb. `dom=29` skips Feb in non-leap years.

There is no catch-up. The next firing window is the next valid month, so a `dom=31` rule loses 5 of 12 monthly cycles per year.

**Live evidence:** 12 Monthly rules with `dom=31`, all created Apr 17, 2026 in the same batch. Examples:

- Task-Rule-0536 "Anup Sir All personal accounts related bill payment"
- Task-Rule-0537 "Anup Sir's Personal accounts transaction booked in Tally & ERP"
- Task-Rule-0540 "Poonam Mam All personal accounts related bill payment"
- Task-Rule-0546 "Capital Goods Bill Checking"
- Task-Rule-0547 "Fixed Assests Sale and Purchase Entry in Tally"
- (7 more, same batch)

These rules will not fire on Apr 30 (today is Apr 25, scheduler runs nightly at 00:00). They will fire on May 31, then skip June (no June 31), etc.

### Bug 3 — Quarterly hardcoded to Jan/Apr/Jul/Oct

Lines 63–66:

```python
elif r.frequency == "Quarterly" and cint(today_dt.day) == cint(r.date_of_month):
    if today_dt.month in [1, 4, 7, 10]:
        selected.append(r)
```

This forces every Quarterly rule's quarter to start in January. A user who creates a Quarterly rule on Mar 26 expecting "every 3 months from now" (i.e., Jun 26, Sep 26, Dec 26, Mar 26) instead gets it firing only on Apr 26, Jul 26, Oct 26, Jan 26 — a different cadence than they intended, and no UI clue this is happening.

**Live evidence:** the only enabled Quarterly rule with zero tasks is Task-Rule-0286, and it's blocked by Bug 1, not by this hardcode (Apr is in the allowed list). So this fix is theoretical at present, but will become an issue the moment a user creates a Quarterly rule expecting a non-Jan-start cadence.

---

## Patch plan

### Patch 1 — skip and log rules whose assignee is disabled

**Goal:** when `r.assign_to` is disabled, do not attempt to create the task. Log the skip somewhere user-visible.

**File:** `workboard/background_jobs/__init__.py`

**Approach:** add a pre-flight check inside the `for r in selected:` loop. Reuse the existing `WB Leave Skip Log` doctype with a new `action_taken` value, `"Skipped — disabled assignee"`. This avoids creating a new doctype and gives admins one place to look.

**Pseudo-diff** (do not commit verbatim — confirm `WB Leave Skip Log` accepts the new `action_taken` value first; if it's a Select field with a fixed option list, extend the JSON):

```python
# ~line 73, replace the for-loop with:
for r in selected:
    # Pre-flight: skip rules whose assignee was disabled.
    # Frappe's link validator would raise on save anyway, but we'd
    # rather log a clear reason to WB Leave Skip Log than rely on Error Log
    # (15-day retention, error message is a noisy traceback).
    if r.get("assign_to"):
        if not frappe.db.get_value("User", r["assign_to"], "enabled"):
            try:
                from workboard.utils.leave import log_skip
                log_skip(
                    rule=r.name,
                    user=r.get("assign_to"),
                    target_date=today_dt,
                    action_taken="Skipped — disabled assignee",
                    resolution=(
                        f"Assignee {r['assign_to']} is disabled. "
                        f"Re-enable the user or reassign the rule."
                    ),
                )
            except Exception:
                frappe.log_error(
                    title=_("WorkBoard log_skip error"),
                    message=frappe.get_traceback(),
                )
            continue

    try:
        _create_task_from_rule(r)
        frappe.db.commit()
    except Exception:
        frappe.log_error(title=_("WorkBoard Error"), message=frappe.get_traceback())
```

**Important:** check the `WB Leave Skip Log` JSON before adding the new `action_taken` value. If `action_taken` is a `Select` field with a closed option list, you must extend the options in `wb_leave_skip_log.json`. If it's `Data`, no schema change needed.

```bash
grep -n action_taken workboard/workboard/doctype/wb_leave_skip_log/wb_leave_skip_log.json
```

**Tests to add** (`workboard/tests/test_background_jobs.py` or new file):

```python
def test_disabled_assignee_skips_rule_and_logs(self):
    # Create a disabled user, an enabled recurring rule that would fire today,
    # run trigger_daily_rules, assert:
    # - no WB Task was created with source_rule = rule.name
    # - exactly one WB Leave Skip Log row exists with rule = rule.name
    #   and action_taken = "Skipped — disabled assignee"
```

**Operational follow-up (not code, but worth doing same day):**

- Backfill the 9 affected rules: either re-enable the 3 disabled users (`rishh6980@gmail.com`, `email.rahulkumar689@gmail.com`, `gaur65162@gmail.com`) **or** edit each rule's `assign_to` to a current owner.
- For ESIC (Task-Rule-0268) and EPF (Task-Rule-0269): these have statutory deadlines on the 15th of each month. Check whether April's payments were made out-of-band by accounts; if not, escalate.

### Patch 2 — clamp `date_of_month` to last-day-of-month

**Goal:** a Monthly/Quarterly/Yearly rule with `date_of_month=31` should fire on the last day of months with fewer than 31 days. Same for `dom=30` in February.

**File:** `workboard/background_jobs/__init__.py`

**Approach:** compute the "effective trigger day" once per rule by clamping `r.date_of_month` to `min(date_of_month, last_day_of_current_month)`.

**Pseudo-diff:**

```python
import calendar  # at top of file

# inside _run_recurring_rules, after `today_dt = getdate(today())`:
last_day_of_month = calendar.monthrange(today_dt.year, today_dt.month)[1]

# replace the Monthly branch:
elif r.frequency == "Monthly":
    target_dom = min(cint(r.date_of_month), last_day_of_month)
    if cint(today_dt.day) == target_dom:
        selected.append(r)

# replace the Quarterly branch (and address Bug 3 here too — see Patch 3):
elif r.frequency == "Quarterly":
    target_dom = min(cint(r.date_of_month), last_day_of_month)
    if cint(today_dt.day) == target_dom and today_dt.month in [1, 4, 7, 10]:
        selected.append(r)

# replace the Yearly branch:
elif r.frequency == "Yearly" and cint(today_dt.month) == cint(r.month_of_year):
    target_dom = min(cint(r.date_of_month), last_day_of_month)
    if cint(today_dt.day) == target_dom:
        selected.append(r)
```

**Edge case to verify in tests:**

- Feb 28, 2027 (non-leap): a rule with `dom=29`, `dom=30`, or `dom=31` all fire on Feb 28.
- Feb 29, 2028 (leap): a rule with `dom=29` fires on Feb 29; `dom=30` and `dom=31` also fire on Feb 29 (the last day).
- Apr 30, 2026: a rule with `dom=30` or `dom=31` fires on Apr 30; a rule with `dom=29` fires on Apr 29 (not Apr 30 — the rule's intent is "the 29th", which exists in April).

**Idempotency caveat:** the clamp creates a new risk. If a user has *both* a `dom=30` rule and a `dom=31` rule for the same task, in April both will fire on Apr 30 — duplicate task. Probably acceptable given how rare this combo is, but document it. If you want to be strict, add an idempotency guard: before creating, check whether a WB Task with this `source_rule` already has `triggered_on >= today_dt 00:00`.

**Tests to add:**

```python
def test_monthly_dom_31_fires_on_apr_30(self):
    # mock today = 2026-04-30, Monthly rule with date_of_month=31, expect 1 task created

def test_monthly_dom_30_does_not_fire_on_apr_29(self):
    # mock today = 2026-04-29, Monthly rule with date_of_month=30, expect 0 tasks

def test_yearly_dom_31_clamps_to_feb_28_in_non_leap(self):
    # mock today = 2027-02-28, Yearly rule with month_of_year=2, date_of_month=31
```

### Patch 3 — make Quarterly start-month configurable (optional)

**Goal:** allow a Quarterly rule to fire on its own quarter cadence, not the hardcoded Jan/Apr/Jul/Oct.

**Two options:**

**Option A (low effort, low correctness):** drop the month restriction entirely. Quarterly with `date_of_month=15` would then fire every month on the 15th — which is wrong (that's Monthly). Reject this option.

**Option B (correct):** add a `quarter_start_month` field to `WB Task Rule` (Select 1–3, defaulting to 1 = Jan-Apr-Jul-Oct). The branch becomes:

```python
elif r.frequency == "Quarterly":
    target_dom = min(cint(r.date_of_month), last_day_of_month)
    qsm = cint(r.get("quarter_start_month") or 1)  # 1, 2, or 3
    if cint(today_dt.day) == target_dom and ((today_dt.month - qsm) % 3 == 0):
        selected.append(r)
```

Schema change required:

```json
// workboard/workboard/doctype/wb_task_rule/wb_task_rule.json
// add inside "fields", near date_of_month:
{
  "depends_on": "eval:doc.frequency == \"Quarterly\"",
  "default": "1",
  "fieldname": "quarter_start_month",
  "fieldtype": "Select",
  "label": "Quarter Starts In",
  "options": "1\n2\n3",
  "description": "1 = Jan/Apr/Jul/Oct, 2 = Feb/May/Aug/Nov, 3 = Mar/Jun/Sep/Dec"
}
```

Plus a patch in `workboard/patches/v1_2/` to backfill `quarter_start_month=1` on all existing Quarterly rules (preserves current behavior).

**Defer this patch** unless a user files a request. No live rule is currently broken by it.

---

## What to leave alone

The audit's §4 conclusions hold against the live data — there are no rules with `frequency=NULL`, no rules with `month_of_year=NULL` for Yearly, and Weekly/Fortnightly/Daily are firing correctly. The 80 Yearly + 76 of the 85 Monthly rules in the "0 tasks" bucket are legitimate (waiting for their cycle, or recently created with this month's day-of-month already past).

Specifically, do **not** touch:
- The Daily branch — the audit's Tuesday-outage fix (already landed Apr 21) is correct.
- The `respects_weekly_off` flag — only applies to Daily, by design.
- The leave-handling logic in `_create_task_from_rule` — orthogonal to this bug.

---

## Operational items (not code)

These are independent of the patches above and should be done regardless:

1. **Re-enable or reassign the 9 disabled-assignee rules** before Patch 1 ships, otherwise Patch 1 will start logging skips for them daily (correct behavior, but noisy). After Patch 1, the skip log tells you exactly which to fix.
2. **Investigate ESIC/EPF April payments.** Statutory deadline on the 15th. Confirm with accounts whether they were paid out-of-band.
3. **Extend `Error Log` retention.** Default is short. Bench config:
   ```python
   # frappe-bench/sites/{site}/site_config.json
   "logging": 1,
   "log_clearing_doctypes": {
       "Error Log": 90  // days
   }
   ```
   Without this, future bugs of the same shape will hit the same diagnostic wall.
4. **Add a list-view indicator on `/app/wb-task-rule`** showing "last fired on" and "tasks generated (90d)". Frappe's listview supports custom indicator functions. This is the audit's §3 recommendation 2.

---

## Verification plan after deploy

After Patch 1 ships, on the day after deploy:

```python
# bench --site {site} console
import frappe
# Should be 9 (or however many disabled-assignee rules exist)
frappe.db.count("WB Leave Skip Log", filters={
    "action_taken": "Skipped — disabled assignee",
    "target_date": frappe.utils.today(),
})
# Should match the rules listed above
frappe.db.get_all("WB Leave Skip Log", filters={
    "action_taken": "Skipped — disabled assignee",
    "target_date": frappe.utils.today(),
}, fields=["rule", "user", "resolution"])
```

After Patch 2 ships, on Apr 30, 2026 (next month-end with <31 days):

```python
# Count WB Tasks created today from rules with date_of_month=31
# Expected: 12 (the dom=31 batch from Apr 17)
frappe.db.sql("""
    SELECT COUNT(*) FROM `tabWB Task` t
    JOIN `tabWB Task Rule` r ON r.name = t.source_rule
    WHERE r.frequency = 'Monthly' AND r.date_of_month = '31'
      AND DATE(t.creation) = CURDATE()
""")
```

---

## Open questions for the implementer

1. ~~**`WB Leave Skip Log.action_taken` field type**~~ — **Resolved.** It's a `Select` with options `Paused / Delegated / Deferred`. Extended to add `Skipped` in `wb_leave_skip_log.json`. The doctype's `modified` timestamp was bumped so `bench migrate` picks up the option change on deploy.
2. **Should the disabled-assignee skip log roll up?** Logging once per rule per day is noisy if you have a daily digest. Consider a "log once, then suppress for N days" mode if you build a daily digest email.
3. **Does the team want auto-reassignment?** If a rule's assignee is disabled and the rule has `assign_from` set, you could auto-reassign to `assign_from` instead of skipping. This is a policy decision, not a code one — flag it for the WorkBoard product owner before implementing.

---

## What shipped (2026-04-25)

**Files changed:**

- `workboard/background_jobs/__init__.py`
  - Added `import calendar`.
  - Added `_target_dom(date_of_month, today_dt)` helper that clamps to the last day of the current month (returns 0 for falsy/invalid input so the caller can treat it as "never matches").
  - Updated Monthly / Quarterly / Yearly branches to use the clamp.
  - Added a disabled-assignee preflight inside the per-rule create loop, calling `log_skip(... action_taken="Skipped" ...)` and `continue`-ing.
- `workboard/workboard/doctype/wb_leave_skip_log/wb_leave_skip_log.json`
  - Added `Skipped` to `action_taken` options.
  - Bumped `modified` timestamp.
- `workboard/tests/test_background_jobs.py` *(new)*
  - `TestTargetDom`: 8 unit tests for the clamp helper, including leap-year, non-leap-year, and zero-input cases.
  - `TestDisabledAssigneePreflight`: end-to-end test that a Daily rule with a disabled assignee creates 0 tasks and 1 `WB Leave Skip Log` row with `action_taken="Skipped"`. Plus a sanity test that an enabled assignee still produces a task.
  - `TestMonthEndClamp`: end-to-end tests that monkey-patch `today` / `getdate` to confirm a `dom=31` rule fires on Apr 30 and a `dom=30` rule does not fire on Apr 29.

**Deploy steps on the production site:**

1. `bench migrate` — picks up the `action_taken` option extension.
2. `bench restart` — picks up the Python changes.
3. (Operational, not code) Either re-enable the 3 disabled users or reassign the 9 affected rules. Without this, Patch 1 will log 9 `Skipped` entries per cycle until the rules are fixed — which is the intended user-visible signal, not a problem.
4. Verify with the `bench --site {site} console` snippets in the "Verification plan after deploy" section above.
