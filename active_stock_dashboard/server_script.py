# =============================================================================
# Frappe Server Script — Active Stock Dashboard
# =============================================================================
# How to install:
#   1. ERPNext > Server Script > New
#   2. Script Type:  API
#   3. API Method:   active_stock_dashboard
#   4. Allow Guest:  No
#   5. Paste EVERYTHING below the dividing line into the "Script" field.
#      (The header above is just a comment — Frappe will accept it but it's
#      cleaner to skip it.)
#   6. Save.
#
# Endpoint: /api/method/active_stock_dashboard
#
# Constraints this script respects (Frappe RestrictedPython sandbox):
#   - no `import` statements
#   - no user-defined `def` functions
#   - no leading-underscore names (`_foo`)
#   - no `frappe.local` (use `frappe.form_dict` directly)
#   - `json` is pre-bound — `json.loads(...)` works without importing
#
# Accepts (all optional):
#   companies          JSON list, e.g. ["Anayam Delhi","Anayam Mumbai"]
#   master_categories  JSON list of Item Group names
#   categories         JSON list of Category names
#   status             defaults to "Active"
#   load_options       if "1", returns filter dropdown options
# -----------------------------------------------------------------------------

# --- Access control: hard-locked to a single user ---------------------------
# Anyone else hitting /api/method/active_stock_dashboard gets a 403, even via
# direct API call. Add more emails to allowed_users to expand later.
allowed_users = ["kaicker@gmail.com"]
if frappe.session.user not in allowed_users:
    frappe.throw("Not permitted", frappe.PermissionError)

raw_companies = frappe.form_dict.get("companies")
raw_master = frappe.form_dict.get("master_categories")
raw_cats = frappe.form_dict.get("categories")
status = frappe.form_dict.get("status") or "Active"
load_options = frappe.form_dict.get("load_options") in ("1", 1, "true", True)

companies = []
master_categories = []
categories = []

# Inline list parser — no `def` allowed in sandbox, so we loop over slots.
for slot, raw in (("c", raw_companies), ("m", raw_master), ("k", raw_cats)):
    parsed = []
    if raw:
        if isinstance(raw, list):
            parsed = [v for v in raw if v]
        else:
            try:
                p = json.loads(raw)
                if isinstance(p, list):
                    parsed = [v for v in p if v]
                else:
                    parsed = [v.strip() for v in str(raw).split(",") if v.strip()]
            except Exception:
                parsed = [v.strip() for v in str(raw).split(",") if v.strip()]
    if slot == "c":
        companies = parsed
    elif slot == "m":
        master_categories = parsed
    else:
        categories = parsed

# Build WHERE clause with parameterised values (safe from injection).
conditions = ["sn.status = %(status)s"]
params = {"status": status}

if companies:
    conditions.append("sn.company IN %(companies)s")
    params["companies"] = tuple(companies)
if master_categories:
    conditions.append("sn.custom_master_category IN %(master_categories)s")
    params["master_categories"] = tuple(master_categories)
if categories:
    conditions.append("sn.custom_category IN %(categories)s")
    params["categories"] = tuple(categories)

where_sql = " AND ".join(conditions)

rows = frappe.db.sql(
    "SELECT sn.custom_category AS category, COUNT(sn.name) AS count, "
    "COALESCE(SUM(CAST(NULLIF(sn.custom_pure_gold, '') AS DECIMAL(18,4))), 0) AS pure_gold, "
    "COALESCE(SUM(CAST(NULLIF(sn.custom_diamond_weightct, '') AS DECIMAL(18,4))), 0) AS diamond_ct, "
    "COALESCE(SUM(CAST(NULLIF(sn.custom_gross_wt, '') AS DECIMAL(18,4))), 0) AS gross_wt "
    "FROM `tabSerial No` sn WHERE " + where_sql + " "
    "GROUP BY sn.custom_category ORDER BY pure_gold DESC, count DESC",
    params,
    as_dict=True,
)

totals_row = frappe.db.sql(
    "SELECT COUNT(sn.name) AS count, "
    "COALESCE(SUM(CAST(NULLIF(sn.custom_pure_gold, '') AS DECIMAL(18,4))), 0) AS pure_gold, "
    "COALESCE(SUM(CAST(NULLIF(sn.custom_diamond_weightct, '') AS DECIMAL(18,4))), 0) AS diamond_ct, "
    "COALESCE(SUM(CAST(NULLIF(sn.custom_gross_wt, '') AS DECIMAL(18,4))), 0) AS gross_wt, "
    "COUNT(DISTINCT sn.custom_category) AS categories "
    "FROM `tabSerial No` sn WHERE " + where_sql,
    params,
    as_dict=True,
)[0]

filter_options = {}
if load_options:
    filter_options["companies"] = [
        r["name"] for r in frappe.get_all("Company", fields=["name"], order_by="name")
    ]
    filter_options["master_categories"] = [
        r["custom_master_category"]
        for r in frappe.db.sql(
            "SELECT DISTINCT custom_master_category FROM `tabSerial No` "
            "WHERE custom_master_category IS NOT NULL AND custom_master_category != '' "
            "ORDER BY custom_master_category",
            as_dict=True,
        )
    ]
    filter_options["categories"] = [
        r["custom_category"]
        for r in frappe.db.sql(
            "SELECT DISTINCT custom_category FROM `tabSerial No` "
            "WHERE custom_category IS NOT NULL AND custom_category != '' "
            "ORDER BY custom_category",
            as_dict=True,
        )
    ]

out_rows = []
for r in rows:
    out_rows.append({
        "category": r["category"] or "(no category)",
        "count": int(r["count"] or 0),
        "pure_gold": float(r["pure_gold"] or 0),
        "diamond_ct": float(r["diamond_ct"] or 0),
        "gross_wt": float(r["gross_wt"] or 0),
    })

frappe.response["message"] = {
    "rows": out_rows,
    "totals": {
        "count": int(totals_row["count"] or 0),
        "pure_gold": float(totals_row["pure_gold"] or 0),
        "diamond_ct": float(totals_row["diamond_ct"] or 0),
        "gross_wt": float(totals_row["gross_wt"] or 0),
        "categories": int(totals_row["categories"] or 0),
    },
    "filter_options": filter_options,
    "applied": {
        "status": status,
        "companies": companies,
        "master_categories": master_categories,
        "categories": categories,
    },
}
