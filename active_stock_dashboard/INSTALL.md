# Active Stock Dashboard — Install Guide

A Frappe Web Page that shows a live count + pure gold sum per category for
all Active Serial Nos, with multi-select filters for Company, Master Category
and Category.

Three pieces — install in this order.

---

## 1. Server Script — `server_script.py`

This exposes `/api/method/active_stock_dashboard`.

1. Go to **Server Script > New** in your ERPNext desk.
2. Set:
   - **Script Type:** API
   - **API Method:** `active_stock_dashboard`
   - **Allow Guest:** No
3. Paste the body of `server_script.py` (everything from `import json` onward
   — skip the comment header).
4. Save.

Test it from the browser bar (you should get a JSON blob back):

```
https://lakshmidiamonds.in/api/method/active_stock_dashboard?load_options=1
```

---

## 2. Web Page — `web_page.html` + `client_script.js`

1. Go to **Web Page > New**.
2. Title: `Active Stock Dashboard`
3. Route: `active-stock-dashboard`
4. Tick **Published**.
5. **Content Type:** HTML
6. Paste the contents of `web_page.html` into **Main Section (HTML)**.
7. Paste the contents of `client_script.js` into the **Javascript** field.
8. Save.

---

## 3. Use it

Open: `https://lakshmidiamonds.in/active-stock-dashboard`

- Filters apply instantly (Company, Master Category, Category — all multi-select with search + Select all / Clear).
- Default sort is **Pure gold (g) descending**; click any column header to re-sort.
- KPI cards show total active items, total pure gold (g), and category count, all reflecting the active filters.

---

## How the pure gold sum is computed

`SUM(CAST(NULLIF(custom_pure_gold,'') AS DECIMAL(18,4)))` — the field is stored
as `Data` rather than `Float`, so we coerce to decimal and treat blanks as 0.
Rows with `custom_category IS NULL` are reported under the "(no category)" label.

## Notes / extensions

- Permissions: the endpoint runs in the calling user's context, so a user who
  cannot see a given Company's serials simply won't get those rows back.
- Want a CSV export? Easy add — `client_script.js` already has the rows in
  memory; just wire a button that calls `URL.createObjectURL(new Blob([...]))`.
- Want a bar chart on top? Plug `state.rows` into Chart.js or Frappe Charts.
