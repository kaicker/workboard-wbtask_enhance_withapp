// =============================================================================
// Active Stock Dashboard — Alpine.js component (Ribbons theme)
// =============================================================================
// Paste into the Web Page's "Javascript" field (below the HTML).
// The HTML loads Alpine v3 from CDN; this file just registers the component.
// Server contract unchanged: GET /api/method/active_stock_dashboard
// =============================================================================

window.activeStockDashboard = function () {
  const ENDPOINT = "/api/method/active_stock_dashboard";

  const fmtInt = new Intl.NumberFormat("en-IN");
  const fmtNum = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  return {
    // ---- reactive state ----
    state: { companies: [], master_categories: [], categories: [] },
    options: { companies: [], master_categories: [], categories: [] },
    search: { companies: "", master_categories: "", categories: "" },
    rows: [],
    totals: { count: 0, pure_gold: 0, diamond_ct: 0, gross_wt: 0, categories: 0 },
    defaultTotals() { return { count: 0, pure_gold: 0, diamond_ct: 0, gross_wt: 0, categories: 0 }; },
    sort: { key: "pure_gold", dir: "desc" },
    openKey: null,
    loading: true,
    meta: "—",

    filterDefs: [
      { key: "companies", label: "Company", allLabel: "All companies" },
      { key: "master_categories", label: "Master category", allLabel: "All master categories" },
      { key: "categories", label: "Category", allLabel: "All categories" },
    ],

    columns: [
      { key: "category", label: "Category", num: false },
      { key: "count", label: "Count", num: true },
      { key: "pure_gold", label: "Pure gold (g)", num: true },
      { key: "gross_wt", label: "Gross wt (g)", num: true },
      { key: "diamond_ct", label: "Diamond (ct)", num: true },
      { key: "avg", label: "Avg / item", num: true },
    ],

    // ---- lifecycle ----
    init() {
      this.refresh(true);
    },

    // ---- derived ----
    get avgPerItem() {
      return this.totals.count ? this.totals.pure_gold / this.totals.count : 0;
    },

    get sortedRows() {
      const { key, dir } = this.sort;
      const mul = dir === "asc" ? 1 : -1;
      return this.rows.slice().sort((a, b) => {
        const av = key === "avg" ? (a.count ? a.pure_gold / a.count : 0) : a[key];
        const bv = key === "avg" ? (b.count ? b.pure_gold / b.count : 0) : b[key];
        if (typeof av === "string") return av.localeCompare(bv) * mul;
        return ((av || 0) - (bv || 0)) * mul;
      });
    },

    rowAvg(r) {
      return r.count ? r.pure_gold / r.count : 0;
    },

    // ---- formatting helpers ----
    kpi(value, opts) {
      opts = opts || {};
      const v = Number(value || 0);
      if (!v && !opts.alwaysShow) return "—";
      return opts.int ? fmtInt.format(v) : fmtNum.format(v);
    },

    numCellText(value, opts) {
      opts = opts || {};
      const v = Number(value || 0);
      if (!v) return "—";
      return opts.int ? fmtInt.format(v) : fmtNum.format(v);
    },

    numCellClass(value, opts) {
      opts = opts || {};
      const v = Number(value || 0);
      const base = opts.bold ? "asd-num bold" : "asd-num";
      return v ? base : base + " asd-zero";
    },

    // ---- multi-select behaviour ----
    triggerLabel(key) {
      const def = this.filterDefs.find((f) => f.key === key);
      const sel = this.state[key];
      const total = (this.options[key] || []).length;
      if (!sel.length || sel.length === total) return def.allLabel;
      if (sel.length === 1) return sel[0];
      return `${sel.length} selected`;
    },

    filteredOptions(key) {
      const q = (this.search[key] || "").toLowerCase();
      return (this.options[key] || []).filter((o) => o.toLowerCase().includes(q));
    },

    toggleOpen(key) {
      this.openKey = this.openKey === key ? null : key;
      if (this.openKey === key) this.search[key] = "";
    },
    closeAll() { this.openKey = null; },

    selectAll(key) {
      this.state[key] = [...(this.options[key] || [])];
      this.refresh();
    },

    clear(key) {
      this.state[key] = [];
      this.refresh();
    },

    reset() {
      this.state.companies = [];
      this.state.master_categories = [];
      this.state.categories = [];
      this.refresh();
    },

    setSort(key) {
      if (this.sort.key === key) {
        this.sort.dir = this.sort.dir === "asc" ? "desc" : "asc";
      } else {
        this.sort.key = key;
        this.sort.dir = key === "category" ? "asc" : "desc";
      }
    },

    // ---- network ----
    refreshTimer: null,
    refresh(loadOptions) {
      this.loading = true;
      this.meta = "Loading…";
      clearTimeout(this.refreshTimer);
      this.refreshTimer = setTimeout(() => {
        const params = new URLSearchParams();
        params.append("status", "Active");
        params.append("companies", JSON.stringify(this.state.companies));
        params.append("master_categories", JSON.stringify(this.state.master_categories));
        params.append("categories", JSON.stringify(this.state.categories));
        if (loadOptions) params.append("load_options", "1");

        fetch(ENDPOINT + "?" + params.toString(), {
          method: "GET",
          credentials: "include",
          headers: { "X-Frappe-CSRF-Token": (window.frappe && frappe.csrf_token) || "" },
        })
          .then((r) => r.json())
          .then((j) => {
            const res = j.message || {};
            this.rows = res.rows || [];
            this.totals = res.totals || this.defaultTotals();
            if (res.filter_options && Object.keys(res.filter_options).length) {
              this.options = res.filter_options;
            }
            this.meta = "Updated " + new Date().toLocaleTimeString();
            this.loading = false;
          })
          .catch((err) => {
            console.error(err);
            this.meta = "Error loading data";
            this.loading = false;
          });
      }, 80);
    },
  };
};
