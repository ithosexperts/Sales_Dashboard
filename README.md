# Sales Analysis Dashboard – HoseXperts

An independent, enterprise-grade Sales Analytics Dashboard application for HoseXperts.
Built according to **Sales Dashboard – Functional Specification and Testing Checklists, Version 1.0, dated 07-Nov-2026**.

---

## 1. Technology Stack

| Layer | Technology | Details |
|---|---|---|
| **Backend** | Python 3.11+, FastAPI, HTTPX, Pandas | High-performance REST service, in-memory data analytics, API client |
| **Frontend** | HTML5, CSS3, JavaScript, Bootstrap 5, Chart.js, html2pdf.js | Management-ready responsive business intelligence UI |
| **Application Type** | Standalone & Integrated Web Application | Direct access analytics portal |
| **Data Source** | HoseXperts Company API (`apiv2.php` / `apiv3.php`) | SQL View: `OperationsDB.dbo.VD_Sales_Dashboard` |
| **Deployment** | Render (`render.yaml`) / Linux / Windows Service | Fast ASGI web service |

---

## 2. Architecture & Data Principles

1. **Single Source of Truth**:
   - `OperationsDB.dbo.VD_Sales_Dashboard` (and identical `Test_OperationsDB`).
   - Unique row key: `[Document] + [DocEntry] + [LineNum]`.
   - Data starts 01-Apr-2023. Excluded: cancelled documents and BaseType 67.
2. **Strict Data-Loading Rules (DL1–DL5)**:
   - Queried **only** on open and on explicit **Refresh Data** click.
   - Zero automatic polling, timed reloads, or background queries.
   - All filters, cascading options, counts, granularity switches, measures, breakdowns, and detail table sorting/paging run **in-memory** on the loaded Pandas DataFrame.
   - `Data as of DD-MMM-YYYY HH:MM` in 24-hour Indian Standard Time (IST).
3. **Granularity & Measure Panel (FL1–FL6)**:
   - Periods: Daily, Weekly, Monthly, Yearly (Default: **Monthly**).
   - Measures: Revenue ₹, Quantity, Gross Profit ₹ (Default: **Revenue ₹**).
   - Bar labels: Yearly (`2026`), Monthly (`Sep-2026`), Weekly (`2026-W39`), Daily (`22-Sep-26`).
   - Reset Granularity restores Monthly & Revenue without resetting filters.
4. **Summary KPI Cards (HD4–HD6)**:
   - Filtered Revenue: Compact Cr/Lakh + exact value.
   - Filtered Gross Profit: ₹ value + Margin % `SUM(Gross Profit) / SUM(Revenue) * 100` (1 decimal place). Shows `–` if Revenue is 0.
   - Filtered Rows: Exact matching line items count.
   - Granularity: e.g. `Monthly • Revenue`.
5. **Filters & Two-Way Cascading (FT1–FT11)**:
   - 8 collapsible sections with Active Filters badge count.
   - Period levels adapt to selected period (FT2).
   - Multi-select across all filters, AND across filters, OR within filter.
   - Dropdown options calculated from data filtered by all other active filters excluding its own selection (FT5).
   - Stale values retained with greyed-out `(0)` badge (FT7).
   - Calendar-only date pickers (typing disabled, dates without data disabled, FT8).
   - `(Blank)` and `NA` strictly separated (FT9).
6. **Main Analytics Chart (CH1–CH3)**:
   - Large dominant vertical bar chart.
   - Quantity mode: grouped side-by-side bars per UoM with mandatory value labels.
   - Gross Profit mode: Gross Profit bars on primary axis + Margin % line on secondary axis.
7. **Fifteen Breakdown Charts (CH4–CH13)**:
   - Horizontal bars sorted largest to smallest.
   - Negative values drawn to left of zero and sorted below positive bars.
   - All categories shown with every bar labelled (no thinning/skipping).
   - Exactly 15 breakdown charts in order:
     1. Domestic vs Export
     2. Region
     3. Ship-To State
     4. Sales From Location
     5. Item Group
     6. Sub Group 1
     7. Sub Group 2
     8. Brand
     9. Row Sales Employee
     10. BP Sales Employee
     11. Credit vs Advance
     12. Top N Customers (number box in header 2–50, default 50 + `Others (n customers)`)
     13. Customer Group
     14. Industry
     15. BP Project
   - Reconciliation rule (CH12): Breakdown chart totals reconcile to main chart total.
8. **Detail Table (TB1–TB5)**:
   - Exactly 12 columns in order: `#`, `DocNum`, `Document`, `Document Type`, `Doc Date` (DD-MMM-YYYY), `BP Name`, `Item Code`, `Quantity`, `UoM`, `Row Total (After Doc Disc)`, `Row Sales Employee`, `BP Sales Employee`.
   - Gross profit is hidden.
   - Global column header sorting (all pages).
   - Paging: 50 rows per page with `Rows x–y of N`.
9. **PDF Export (HD3)**:
   - Client-side export via `html2pdf.bundle.min.js`.
   - Generates high-resolution PDF with Dashboard title, Data as of stamp, and exactly 16 charts (main + 15 breakdowns).
   - Excludes filter panel and detail table. Does not query database.

---

## 3. Directory Layout

```text
Sales Analysis/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application entrypoint
│   ├── config.py                   # Pydantic settings & .env loader
│   ├── templates_config.py         # Jinja2 environment setup
│   ├── api/
│   │   ├── __init__.py
│   │   └── client.py               # Company API gateway client (apiv2.php / apiv3.php)
│   ├── auth/
│   │   ├── __init__.py
│   │   └── request_context.py      # ContextVar storage for auth & target database
│   ├── routers/
│   │   ├── __init__.py
│   │   └── dashboard.py            # Sales Dashboard routes and query JSON API
│   ├── services/
│   │   ├── __init__.py
│   │   └── sales_service.py        # Core analytics service: in-memory store, filtering, charts, table
│   ├── static/
│   │   ├── css/
│   │   │   └── styles.css          # Executive corporate theme & responsive styling
│   │   ├── images/
│   │   │   └── hosexperts-logo.png # Company logo
│   │   └── js/
│   │       ├── sales_app.js        # Dashboard state management & Chart.js logic
│   │       └── html2pdf.bundle.min.js # PDF export bundle
│   └── templates/
│       ├── base.html               # Shared navbar, header & layout
│       └── sales/
│           └── index.html          # Main sales dashboard view
├── tests/
│   ├── __init__.py
│   ├── test_data_contract.py       # Phase 2 & DS1–DS12 contract tests
│   ├── test_checklist_a.py         # 18-step Checklist A data reconciliation tests
│   ├── test_checklist_b.py         # Complete Checklist B design requirements tests
│   ├── test_app.py                 # FastAPI endpoint & integration tests
│   └── test_e2e_live.py            # Live dataset & performance tests
├── .env                            # Active environment configuration
├── .env.example                    # Template environment configuration
├── requirements.txt                # Python dependencies
├── render.yaml                     # Cloud deployment blueprint
└── README.md                       # Documentation
```

---

## 4. Running the Application

### 4.1 Running with Python / Uvicorn

```bash
# Start FastAPI application
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser to:
- `http://localhost:8000/` or `http://localhost:8000/sales`

### 4.2 Running Tests

```bash
# Run complete test suite (contract, Checklist A, Checklist B, integration, live e2e)
python -m pytest tests -v
```
