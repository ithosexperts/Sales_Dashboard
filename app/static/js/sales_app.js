/**
 * Sales Dashboard – Client-Side Application Logic.
 *
 * Implements all functional specification & testing checklist requirements:
 * - DL1–DL5: Data loading & in-memory querying
 * - FL1–FL6: Granularity Panel (Period, Measure, grouping, labels)
 * - HD1–HD6: Header, buttons (Reset Filters, Refresh Data, Export PDF), 4 KPI cards
 * - FT1–FT11: 8 filter sections, 2-way cascading, multi-select, calendar-only, stale (0), empty state
 * - CH1–CH14: Main chart (bars + GP margin line), 15 breakdown charts, Top N Customers
 * - TB1–TB5: 12-column detail table with global sorting and 50-row pagination
 */

(function () {
    "use strict";

    // Application State
    const AppState = {
        granularity: "Monthly",   // "Daily" | "Weekly" | "Monthly" | "Yearly" (FL2)
        measure: "Revenue ₹",     // "Revenue ₹" | "Quantity" | "Gross Profit ₹" (FL2)

        isLoaded: false,
        isLoading: false,
        dataAsOf: null,
        database: "OperationsDB",

        // Active Filter Selections (FT1–FT4)
        filters: {
            fromDate: null,
            toDate: null,
            year: [],
            month: [],
            week: [],
            day: [],
            document: [],
            documentType: [],
            salesType: [],
            salesFromLocation: [],
            bpCode: [],
            bpName: [],
            group: [],
            industry: [],
            bpProject: [],
            rowSalesEmployee: [],
            bpSalesEmployee: [],
            region: [],
            state: [],
            city: [],
            country: [],
            itemGroup: [],
            subGroup1: [],
            subGroup2: [],
            itemCode: [],
            brand: [],
            moc: [],
            madeToOrder: [],
            uom: [],
            itemAttributes: {} // attr_name -> array of selected values
        },

        topCustomersLimit: 50, // default 50 (CH9)

        tableSort: {
            column: "Doc Date",
            direction: "desc"
        },
        tablePage: 1,
        tablePageSize: 50,

        // Cached facet metadata
        facets: {},
        activeDates: []
    };

    // Chart.js Instances Registry (Main chart + 15 breakdown charts = exactly 16 charts)
    const ChartInstances = {
        main: null,
        domestic_vs_export: null,
        region: null,
        state: null,
        sales_from_location: null,
        item_group: null,
        sub_group1: null,
        sub_group2: null,
        brand: null,
        row_sales_employee: null,
        bp_sales_employee: null,
        sales_type: null,
        top_customers: null,
        customer_group: null,
        industry: null,
        bp_project: null
    };

    // Palette tokens
    const COLORS = {
        sapphire: "#0F3B6C",
        sapphireLight: "#165BAA",
        cyan: "#0284C7",
        emerald: "#0D9488",
        amber: "#D97706",
        purple: "#7C3AED",
        pink: "#DB2777",
        red: "#DC2626",
        gray: "#94A3B8",
        border: "#E2E8F0"
    };

    const UOM_PALETTE = [
        "#0F3B6C", "#0D9488", "#0284C7", "#D97706",
        "#7C3AED", "#DB2777", "#4F46E5", "#059669",
        "#B45309", "#9333EA", "#BE123C", "#0369A1"
    ];

    /**
     * Compact Indian Currency Formatter for Axis & Tooltips.
     */
    function formatCompactINR(val) {
        if (val === null || val === undefined || isNaN(val)) return "₹0";
        const isNeg = val < 0;
        const abs = Math.abs(val);
        const prefix = isNeg ? "-₹" : "₹";
        if (abs >= 10000000) {
            return prefix + (abs / 10000000).toFixed(2) + " Cr";
        } else if (abs >= 100000) {
            return prefix + (abs / 100000).toFixed(2) + " L";
        } else if (abs >= 1000) {
            return prefix + (abs / 1000).toFixed(1) + " K";
        }
        return prefix + abs.toLocaleString("en-IN", { maximumFractionDigits: 0 });
    }

    function formatFullINR(val) {
        if (val === null || val === undefined || isNaN(val)) return "₹0.00";
        const isNeg = val < 0;
        const abs = Math.abs(val);
        const prefix = isNeg ? "-₹" : "₹";
        return prefix + abs.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // ─── DOM ELEMENTS ────────────────────────────────────────────────────────
    const DOM = {
        loadingOverlay: document.getElementById("loadingOverlay"),
        loadingText: document.getElementById("loadingText"),
        loadingSubText: document.getElementById("loadingSubText"),
        dataAsOfText: document.getElementById("dataAsOfText"),
        btnToggleFilters: document.getElementById("btnToggleFilters"),
        btnResetFilters: document.getElementById("btnResetFilters"),
        btnRefreshData: document.getElementById("btnRefreshData"),
        btnExportPdf: document.getElementById("btnExportPdf"),
        btnResetGranularity: document.getElementById("btnResetGranularity"),
        granularityRadios: document.querySelectorAll("input[name='granularity']"),
        measureRadios: document.querySelectorAll("input[name='measure']"),
        topNInput: document.getElementById("topNInput"),
        filterSidebarCol: document.getElementById("filterSidebarCol"),
        analyticsContentCol: document.getElementById("analyticsContentCol"),
        noDataContainer: document.getElementById("noDataContainer"),
        analyticsChartsAndTable: document.getElementById("analyticsChartsAndTable"),
        activeFilterBadge: document.getElementById("activeFilterBadge"),
        filterFromDate: document.getElementById("filterFromDate"),
        filterToDate: document.getElementById("filterToDate"),
        cardFilteredRevenueCompact: document.getElementById("cardFilteredRevenueCompact"),
        cardFilteredRevenueExact: document.getElementById("cardFilteredRevenueExact"),
        cardFilteredGrossProfit: document.getElementById("cardFilteredGrossProfit"),
        cardMarginPct: document.getElementById("cardMarginPct"),
        cardFilteredRows: document.getElementById("cardFilteredRows"),
        cardGranularity: document.getElementById("cardGranularity"),
        mainChartTitle: document.getElementById("mainChartTitle"),
        mainChartSubtitle: document.getElementById("mainChartSubtitle"),
        mainSalesChartCanvas: document.getElementById("mainSalesChart"),
        detailTableBody: document.getElementById("detailTableBody"),
        tableRangeLabel: document.getElementById("tableRangeLabel"),
        btnTablePrev: document.getElementById("btnTablePrev"),
        btnTableNext: document.getElementById("btnTableNext"),
        tableHeaderRow: document.getElementById("tableHeaderRow"),
        pdfReportHeader: document.getElementById("pdfReportHeader"),
        pdfReportGranularity: document.getElementById("pdfReportGranularity"),
        pdfReportDate: document.getElementById("pdfReportDate"),
    };

    // ─── INITIALIZATION ──────────────────────────────────────────────────────
    async function init() {
        bindEvents();
        updatePeriodFilterVisibility();
        await pollDatasetLoad();
    }

    function showLoading(text, subtext) {
        if (DOM.loadingOverlay) {
            DOM.loadingOverlay.classList.add("active");
            if (text) DOM.loadingText.textContent = text;
            if (subtext) DOM.loadingSubText.textContent = subtext;
        }
    }

    function hideLoading() {
        if (DOM.loadingOverlay) {
            DOM.loadingOverlay.classList.remove("active");
        }
    }

    async function pollDatasetLoad() {
        showLoading("Loading Sales Data...", "Checking in-memory dataset");
        try {
            const resp = await fetch("/api/sales/dataset");
            const data = await resp.json();

            if (data.status === "success") {
                AppState.isLoaded = true;
                AppState.dataAsOf = data.data_as_of_formatted;
                AppState.database = data.database;
                if (DOM.dataAsOfText) DOM.dataAsOfText.textContent = `Data as of ${data.data_as_of_formatted}`;
                await executeQuery();
            } else if (data.status === "loading") {
                if (DOM.loadingSubText) DOM.loadingSubText.textContent = data.progress || "Loading records...";
                setTimeout(pollDatasetLoad, 1000);
            } else {
                hideLoading();
                alert("Failed to load dataset: " + (data.error || "Unknown error"));
            }
        } catch (err) {
            hideLoading();
            console.error("Dataset check failed:", err);
        }
    }

    // ─── EVENT BINDINGS ──────────────────────────────────────────────────────
    function bindEvents() {
        // Toggle Sidebar
        if (DOM.btnToggleFilters) {
            DOM.btnToggleFilters.addEventListener("click", () => {
                const isHidden = DOM.filterSidebarCol.classList.contains("d-none");
                if (isHidden) {
                    DOM.filterSidebarCol.classList.remove("d-none");
                    DOM.analyticsContentCol.className = "col-12 col-lg-9";
                    document.getElementById("textToggleSidebar").textContent = "Hide Filters";
                } else {
                    DOM.filterSidebarCol.classList.add("d-none");
                    DOM.analyticsContentCol.className = "col-12";
                    document.getElementById("textToggleSidebar").textContent = "Show Filters";
                }
            });
        }

        // Granularity Radios (Period)
        DOM.granularityRadios.forEach(radio => {
            radio.addEventListener("change", (e) => {
                AppState.granularity = e.target.value;
                updatePeriodFilterVisibility();
                executeQuery();
            });
        });

        // Measure Radios
        DOM.measureRadios.forEach(radio => {
            radio.addEventListener("change", (e) => {
                AppState.measure = e.target.value;
                executeQuery();
            });
        });

        // Reset Granularity (FL3)
        if (DOM.btnResetGranularity) {
            DOM.btnResetGranularity.addEventListener("click", () => {
                AppState.granularity = "Monthly";
                AppState.measure = "Revenue ₹";
                document.getElementById("granMonthly").checked = true;
                document.getElementById("measRevenue").checked = true;
                updatePeriodFilterVisibility();
                executeQuery();
            });
        }

        // Reset Filters (DL5, FT10)
        if (DOM.btnResetFilters) {
            DOM.btnResetFilters.addEventListener("click", () => {
                resetFilters();
            });
        }

        // Refresh Data (DL1, DL5)
        if (DOM.btnRefreshData) {
            DOM.btnRefreshData.addEventListener("click", () => {
                refreshData();
            });
        }

        // Export PDF (HD3)
        if (DOM.btnExportPdf) {
            DOM.btnExportPdf.addEventListener("click", () => {
                exportPdf();
            });
        }

        // Top N Input (CH9)
        if (DOM.topNInput) {
            DOM.topNInput.addEventListener("change", (e) => {
                let n = parseInt(e.target.value, 10);
                if (isNaN(n) || n < 2) n = 2;
                if (n > 50) n = 50;
                e.target.value = n;
                AppState.topCustomersLimit = n;
                updateTopNCustomersOnly();
            });
        }

        // Calendar From/To Date Pickers (FT8)
        if (DOM.filterFromDate) {
            DOM.filterFromDate.addEventListener("change", (e) => {
                AppState.filters.fromDate = e.target.value || null;
                executeQuery();
            });
        }
        if (DOM.filterToDate) {
            DOM.filterToDate.addEventListener("change", (e) => {
                AppState.filters.toDate = e.target.value || null;
                executeQuery();
            });
        }

        // Detail Table Pagination
        if (DOM.btnTablePrev) {
            DOM.btnTablePrev.addEventListener("click", () => {
                if (AppState.tablePage > 1) {
                    AppState.tablePage--;
                    updateTableOnly();
                }
            });
        }
        if (DOM.btnTableNext) {
            DOM.btnTableNext.addEventListener("click", () => {
                AppState.tablePage++;
                updateTableOnly();
            });
        }

        // Detail Table Sorting (TB4)
        if (DOM.tableHeaderRow) {
            DOM.tableHeaderRow.addEventListener("click", (e) => {
                const th = e.target.closest("th");
                if (!th) return;
                const colKey = th.getAttribute("data-col");
                if (!colKey || colKey === "index") return;

                if (AppState.tableSort.column === colKey) {
                    AppState.tableSort.direction = (AppState.tableSort.direction === "asc") ? "desc" : "asc";
                } else {
                    AppState.tableSort.column = colKey;
                    AppState.tableSort.direction = "desc";
                }
                updateSortIcons();
                updateTableOnly();
            });
        }
    }

    // ─── PERIOD VISIBILITY GATING (FT2) ──────────────────────────────────────
    function updatePeriodFilterVisibility() {
        const gran = AppState.granularity;
        const grpYear = document.getElementById("filterGroupYear");
        const grpMonth = document.getElementById("filterGroupMonth");
        const grpWeek = document.getElementById("filterGroupWeek");
        const grpDay = document.getElementById("filterGroupDay");

        if (grpYear) grpYear.classList.toggle("d-none", false); // Year is always visible
        if (grpMonth) grpMonth.classList.toggle("d-none", gran === "Yearly");
        if (grpWeek) grpWeek.classList.toggle("d-none", gran === "Yearly" || gran === "Monthly");
        if (grpDay) grpDay.classList.toggle("d-none", gran !== "Daily");
    }

    // ─── QUERY EXECUTION (In-Memory, DL3) ────────────────────────────────────
    async function executeQuery() {
        showLoading("Calculating Analytics...", "Updating in-memory charts and filters");
        try {
            const payload = {
                granularity: AppState.granularity,
                measure: AppState.measure,
                filters: AppState.filters,
                page: AppState.tablePage,
                page_size: AppState.tablePageSize,
                sort_column: AppState.tableSort.column,
                sort_direction: AppState.tableSort.direction,
                top_customers_limit: AppState.topCustomersLimit,
                intent: "all"
            };

            const resp = await fetch("/api/sales/query", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            const result = await resp.json();

            if (result.status === "no_data") {
                renderNoDataState(result);
            } else if (result.status === "success") {
                renderFullDashboard(result);
            } else {
                console.error("Query failed:", result);
            }
        } catch (err) {
            console.error("Error executing sales query:", err);
        } finally {
            hideLoading();
        }
    }

    // Fast path: Top N Customers update only (CH9)
    async function updateTopNCustomersOnly() {
        try {
            const payload = {
                granularity: AppState.granularity,
                measure: AppState.measure,
                filters: AppState.filters,
                top_customers_limit: AppState.topCustomersLimit,
                intent: "top_n"
            };
            const resp = await fetch("/api/sales/query", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const result = await resp.json();
            if (result.status === "success" && result.top_customers) {
                renderHorizontalBarChart("chart_top_customers", "top_customers", result.top_customers);
            }
        } catch (err) {
            console.error("Error updating Top N:", err);
        }
    }

    // Fast path: Detail Table update only (TB4, TB5)
    async function updateTableOnly() {
        try {
            const payload = {
                granularity: AppState.granularity,
                measure: AppState.measure,
                filters: AppState.filters,
                page: AppState.tablePage,
                page_size: AppState.tablePageSize,
                sort_column: AppState.tableSort.column,
                sort_direction: AppState.tableSort.direction,
                intent: "table"
            };
            const resp = await fetch("/api/sales/query", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const result = await resp.json();
            if (result.status === "success" && result.table) {
                renderDetailTable(result.table);
            }
        } catch (err) {
            console.error("Error updating table:", err);
        }
    }

    // ─── RENDERING FUNCTIONS ─────────────────────────────────────────────────
    function renderNoDataState(result) {
        if (DOM.noDataContainer) DOM.noDataContainer.classList.remove("d-none");
        if (DOM.analyticsChartsAndTable) DOM.analyticsChartsAndTable.classList.add("d-none");

        // Render summary cards with 0 values (HD5)
        renderSummaryCards(result.summary);
        renderFacets(result.facets);
        updateActiveFilterBadge();
    }

    function renderFullDashboard(result) {
        if (DOM.noDataContainer) DOM.noDataContainer.classList.add("d-none");
        if (DOM.analyticsChartsAndTable) DOM.analyticsChartsAndTable.classList.remove("d-none");

        renderSummaryCards(result.summary);
        renderFacets(result.facets);
        renderMainChart(result.main_chart);
        renderAllBreakdownCharts(result.breakdowns);
        renderDetailTable(result.table);
        updateActiveFilterBadge();
    }

    // 4 Summary KPI Cards (HD4, HD5, HD6)
    function renderSummaryCards(summary) {
        if (!summary) return;
        if (DOM.cardFilteredRevenueCompact) DOM.cardFilteredRevenueCompact.textContent = summary.filtered_revenue_compact;
        if (DOM.cardFilteredRevenueExact) DOM.cardFilteredRevenueExact.textContent = `Exact: ${summary.filtered_revenue_formatted}`;
        if (DOM.cardFilteredGrossProfit) DOM.cardFilteredGrossProfit.textContent = summary.filtered_gross_profit_formatted;
        if (DOM.cardMarginPct) DOM.cardMarginPct.textContent = summary.margin_pct_formatted;
        if (DOM.cardFilteredRows) DOM.cardFilteredRows.textContent = summary.filtered_rows_formatted;
        if (DOM.cardGranularity) DOM.cardGranularity.textContent = summary.granularity_label;
    }

    // Main Chart (CH1, CH2, CH3)
    function renderMainChart(chartData) {
        if (!DOM.mainSalesChartCanvas) return;
        const ctx = DOM.mainSalesChartCanvas.getContext("2d");

        if (ChartInstances.main) {
            ChartInstances.main.destroy();
            ChartInstances.main = null;
        }

        if (!chartData || !chartData.categories || chartData.categories.length === 0) {
            return;
        }

        // Subtitle
        if (DOM.mainChartSubtitle) {
            DOM.mainChartSubtitle.textContent = `${chartData.granularity} • ${chartData.measure}`;
        }

        const isGPMode = chartData.has_margin_line;
        const isQtyMode = (chartData.uoms && chartData.uoms.length > 0);

        let datasets = [];

        if (isQtyMode) {
            // Grouped bars per UoM (CH2)
            datasets = chartData.series.map((s, idx) => ({
                label: s.name,
                data: s.data,
                backgroundColor: UOM_PALETTE[idx % UOM_PALETTE.length],
                borderColor: UOM_PALETTE[idx % UOM_PALETTE.length],
                borderWidth: 1,
                yAxisID: "y"
            }));
        } else if (isGPMode) {
            // Gross Profit vertical bars on left axis (y) + Margin % line on right axis (y1) (CH3)
            datasets.push({
                type: "bar",
                label: "Gross Profit ₹",
                data: chartData.series[0].data,
                backgroundColor: chartData.series[0].data.map(v => v < 0 ? COLORS.red : COLORS.emerald),
                borderColor: chartData.series[0].data.map(v => v < 0 ? COLORS.red : COLORS.emerald),
                borderWidth: 1,
                yAxisID: "y"
            });

            datasets.push({
                type: "line",
                label: "Margin %",
                data: chartData.margin_series,
                borderColor: COLORS.sapphireLight,
                backgroundColor: COLORS.sapphireLight,
                borderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6,
                fill: false,
                tension: 0.1,
                yAxisID: "y1"
            });
        } else {
            // Revenue vertical bars
            datasets.push({
                type: "bar",
                label: "Revenue ₹",
                data: chartData.series[0].data,
                backgroundColor: chartData.series[0].data.map(v => v < 0 ? COLORS.red : COLORS.sapphire),
                borderColor: chartData.series[0].data.map(v => v < 0 ? COLORS.red : COLORS.sapphire),
                borderWidth: 1,
                yAxisID: "y"
            });
        }

        const scalesConfig = {
            x: {
                grid: { display: false },
                ticks: {
                    color: "#475569",
                    font: { size: 11, family: "Plus Jakarta Sans" }
                }
            },
            y: {
                type: "linear",
                position: "left",
                grid: { color: "#F1F5F9" },
                ticks: {
                    callback: function (val) {
                        return isQtyMode ? val.toLocaleString() : formatCompactINR(val);
                    },
                    color: "#475569",
                    font: { size: 11, family: "Plus Jakarta Sans" }
                }
            }
        };

        if (isGPMode) {
            scalesConfig.y1 = {
                type: "linear",
                position: "right",
                grid: { drawOnChartArea: false },
                ticks: {
                    callback: function (val) {
                        return val.toFixed(1) + "%";
                    },
                    color: COLORS.sapphireLight,
                    font: { size: 11, family: "Plus Jakarta Sans", weight: "bold" }
                }
            };
        }

        ChartInstances.main = new Chart(ctx, {
            type: "bar",
            data: {
                labels: chartData.categories,
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: {
                        display: isQtyMode || isGPMode,
                        position: "top",
                        labels: { font: { size: 11, family: "Plus Jakarta Sans" } }
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                if (context.dataset.yAxisID === "y1") {
                                    return `Margin: ${context.parsed.y !== null ? context.parsed.y.toFixed(1) + "%" : "–"}`;
                                }
                                if (isQtyMode) {
                                    return `${context.dataset.label}: ${context.parsed.y.toLocaleString()} ${context.dataset.label}`;
                                }
                                return `${context.dataset.label}: ${formatFullINR(context.parsed.y)}`;
                            }
                        }
                    }
                },
                scales: scalesConfig
            }
        });
    }

    // 15 Breakdown Charts (CH4–CH13)
    function renderAllBreakdownCharts(breakdowns) {
        if (!breakdowns) return;
        const chartKeys = [
            "domestic_vs_export", "region", "state", "sales_from_location",
            "item_group", "sub_group1", "sub_group2", "brand",
            "row_sales_employee", "bp_sales_employee", "sales_type",
            "top_customers", "customer_group", "industry", "bp_project"
        ];

        chartKeys.forEach(k => {
            const data = breakdowns[k];
            if (data) {
                renderHorizontalBarChart(`chart_${k}`, k, data);
            }
        });
    }

    function renderHorizontalBarChart(canvasId, chartKey, data) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext("2d");

        if (ChartInstances[chartKey]) {
            ChartInstances[chartKey].destroy();
            ChartInstances[chartKey] = null;
        }

        if (!data || !data.categories || data.categories.length === 0) {
            return;
        }

        // Adjust canvas height dynamically based on category count so labels don't get squished (CH7)
        const barHeight = 24;
        const calculatedHeight = Math.max(240, data.categories.length * barHeight + 40);
        canvas.style.height = `${calculatedHeight}px`;
        canvas.parentElement.style.height = `${calculatedHeight}px`;

        const isQty = data.is_qty;
        let datasets = [];

        if (isQty) {
            datasets = data.series.map((s, idx) => ({
                label: s.name,
                data: s.data,
                backgroundColor: UOM_PALETTE[idx % UOM_PALETTE.length],
                borderColor: UOM_PALETTE[idx % UOM_PALETTE.length],
                borderWidth: 1
            }));
        } else {
            const sData = data.series[0].data;
            datasets.push({
                label: data.series[0].name,
                data: sData,
                backgroundColor: sData.map(v => v < 0 ? COLORS.red : COLORS.sapphire),
                borderColor: sData.map(v => v < 0 ? COLORS.red : COLORS.sapphire),
                borderWidth: 1
            });
        }

        ChartInstances[chartKey] = new Chart(ctx, {
            type: "bar",
            data: {
                labels: data.categories,
                datasets: datasets
            },
            options: {
                indexAxis: "y", // Horizontal bars (CH6)
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: isQty,
                        position: "top",
                        labels: { font: { size: 10, family: "Plus Jakarta Sans" } }
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                if (isQty) {
                                    return `${context.dataset.label}: ${context.parsed.x.toLocaleString()} ${context.dataset.label}`;
                                }
                                return `${context.dataset.label}: ${formatFullINR(context.parsed.x)}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: "#F1F5F9" },
                        ticks: {
                            callback: function (val) {
                                return isQty ? val.toLocaleString() : formatCompactINR(val);
                            },
                            color: "#64748B",
                            font: { size: 10, family: "Plus Jakarta Sans" }
                        }
                    },
                    y: {
                        grid: { display: false },
                        ticks: {
                            autoSkip: false, // All categories shown, none skipped (CH7)
                            color: "#1E293B",
                            font: { size: 10, family: "Plus Jakarta Sans", weight: "500" }
                        }
                    }
                }
            }
        });
    }

    // Detail Table (TB1–TB5)
    function renderDetailTable(tableData) {
        if (!DOM.detailTableBody || !tableData) return;
        DOM.detailTableBody.innerHTML = "";

        if (!tableData.rows || tableData.rows.length === 0) {
            DOM.detailTableBody.innerHTML = `<tr><td colspan="12" class="text-center text-muted py-4">No records to display</td></tr>`;
            if (DOM.tableRangeLabel) DOM.tableRangeLabel.textContent = "Rows 0 of 0";
            if (DOM.btnTablePrev) DOM.btnTablePrev.disabled = true;
            if (DOM.btnTableNext) DOM.btnTableNext.disabled = true;
            return;
        }

        tableData.rows.forEach(r => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td class="text-center text-muted small">${r.index}</td>
                <td class="text-end font-monospace small">${r.DocNum}</td>
                <td><span class="badge ${r.Document === 'A/R Invoice' ? 'bg-primary-subtle text-primary' : 'bg-danger-subtle text-danger'}">${r.Document}</span></td>
                <td><span class="badge bg-light text-dark border">${r["Document Type"]}</span></td>
                <td class="small font-monospace">${r["Doc Date"]}</td>
                <td class="fw-medium">${r["BP Name"]}</td>
                <td class="font-monospace small">${r["Item Code"]}</td>
                <td class="text-end font-monospace">${r.Quantity}</td>
                <td class="small">${r.UoM || '–'}</td>
                <td class="text-end font-monospace fw-semibold ${parseFloat(String(r['Row Total (After Doc Disc)']).replace(/[^0-9.-]+/g, '')) < 0 ? 'text-danger' : 'text-dark'}">${r["Row Total (After Doc Disc)"]}</td>
                <td class="small text-muted">${r["Row Sales Employee"]}</td>
                <td class="small text-muted">${r["BP Sales Employee"]}</td>
            `;
            DOM.detailTableBody.appendChild(tr);
        });

        if (DOM.tableRangeLabel) DOM.tableRangeLabel.textContent = tableData.range_label;
        if (DOM.btnTablePrev) DOM.btnTablePrev.disabled = (tableData.page <= 1);
        if (DOM.btnTableNext) DOM.btnTableNext.disabled = (tableData.page >= tableData.total_pages);
    }

    function updateSortIcons() {
        const headers = DOM.tableHeaderRow.querySelectorAll("th");
        headers.forEach(th => {
            const col = th.getAttribute("data-col");
            if (!col || col === "index") return;
            let icon = th.querySelector("i");
            if (col === AppState.tableSort.column) {
                if (!icon) {
                    icon = document.createElement("i");
                    th.appendChild(icon);
                }
                icon.className = (AppState.tableSort.direction === "asc") ? "bi bi-sort-up text-primary ms-1" : "bi bi-sort-down text-primary ms-1";
            } else if (icon) {
                icon.className = "bi bi-arrow-down-up small text-muted ms-1";
            }
        });
    }

    // ─── FACETED MULTI-SELECT DROPDOWNS (FT5, FT6, FT7) ──────────────────────
    function renderFacets(facets) {
        if (!facets) return;
        AppState.facets = facets;

        // Render date boundaries (FT8b)
        if (facets.minDate && DOM.filterFromDate) DOM.filterFromDate.min = facets.minDate;
        if (facets.maxDate && DOM.filterFromDate) DOM.filterFromDate.max = facets.maxDate;
        if (facets.minDate && DOM.filterToDate) DOM.filterToDate.min = facets.minDate;
        if (facets.maxDate && DOM.filterToDate) DOM.filterToDate.max = facets.maxDate;

        // Render standard dropdowns
        document.querySelectorAll(".custom-multi-select[data-filter]").forEach(container => {
            const filterKey = container.getAttribute("data-filter");
            const options = facets[filterKey] || [];
            renderCustomMultiSelect(container, filterKey, options, false);
        });

        // Render Item Attribute dropdowns
        const attrFacets = facets.itemAttributes || {};
        document.querySelectorAll(".custom-multi-select[data-attr-filter]").forEach(container => {
            const attrKey = container.getAttribute("data-attr-filter");
            const options = attrFacets[attrKey] || [];
            renderCustomMultiSelect(container, attrKey, options, true);
        });
    }

    function renderCustomMultiSelect(container, key, options, isAttr) {
        container.innerHTML = "";

        const selectedVals = isAttr ? (AppState.filters.itemAttributes[key] || []) : (AppState.filters[key] || []);
        const selectedCount = selectedVals.length;

        // Toggle button
        const toggleBtn = document.createElement("div");
        toggleBtn.className = "multi-select-toggle";
        const labelText = selectedCount === 0 ? "All" : `${selectedCount} selected`;
        toggleBtn.innerHTML = `<span>${labelText}</span><i class="bi bi-chevron-down small text-muted"></i>`;

        // Menu
        const menu = document.createElement("div");
        menu.className = "multi-select-menu";

        // Search box
        const searchBox = document.createElement("div");
        searchBox.className = "multi-select-search";
        const searchInput = document.createElement("input");
        searchInput.type = "text";
        searchInput.placeholder = "Search...";
        searchBox.appendChild(searchInput);
        menu.appendChild(searchBox);

        // Options container
        const optionsList = document.createElement("div");
        optionsList.className = "multi-select-options";

        options.forEach(opt => {
            const optRow = document.createElement("div");
            optRow.className = `multi-select-option ${opt.stale ? 'stale' : ''}`;

            const chk = document.createElement("input");
            chk.type = "checkbox";
            chk.className = "form-check-input me-2";
            chk.checked = opt.selected;
            chk.value = opt.value;

            const lbl = document.createElement("span");
            lbl.className = "flex-grow-1 text-truncate";
            lbl.textContent = opt.label;

            optRow.appendChild(chk);
            optRow.appendChild(lbl);

            optRow.addEventListener("click", (e) => {
                if (e.target !== chk) {
                    chk.checked = !chk.checked;
                }
                handleOptionToggle(key, opt.value, chk.checked, isAttr);
            });

            optionsList.appendChild(optRow);
        });

        menu.appendChild(optionsList);
        container.appendChild(toggleBtn);
        container.appendChild(menu);

        // Toggle dropdown open/close
        toggleBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            // Close other open menus
            document.querySelectorAll(".multi-select-menu.show").forEach(m => {
                if (m !== menu) m.classList.remove("show");
            });
            menu.classList.toggle("show");
            if (menu.classList.contains("show")) {
                searchInput.focus();
            }
        });

        // Filter search input
        searchInput.addEventListener("input", () => {
            const q = searchInput.value.toLowerCase();
            optionsList.querySelectorAll(".multi-select-option").forEach(row => {
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(q) ? "" : "none";
            });
        });

        // Close on click outside
        document.addEventListener("click", (e) => {
            if (!container.contains(e.target)) {
                menu.classList.remove("show");
            }
        });
    }

    function handleOptionToggle(key, value, isChecked, isAttr) {
        if (isAttr) {
            if (!AppState.filters.itemAttributes[key]) {
                AppState.filters.itemAttributes[key] = [];
            }
            if (isChecked) {
                if (!AppState.filters.itemAttributes[key].includes(value)) {
                    AppState.filters.itemAttributes[key].push(value);
                }
            } else {
                AppState.filters.itemAttributes[key] = AppState.filters.itemAttributes[key].filter(v => v !== value);
            }
        } else {
            if (!AppState.filters[key]) {
                AppState.filters[key] = [];
            }
            if (isChecked) {
                if (!AppState.filters[key].includes(value)) {
                    AppState.filters[key].push(value);
                }
            } else {
                AppState.filters[key] = AppState.filters[key].filter(v => v !== value);
            }
        }
        executeQuery();
    }

    function updateActiveFilterBadge() {
        let count = 0;
        if (AppState.filters.fromDate) count++;
        if (AppState.filters.toDate) count++;

        Object.keys(AppState.filters).forEach(k => {
            if (k === "fromDate" || k === "toDate" || k === "itemAttributes") return;
            const vals = AppState.filters[k];
            if (Array.isArray(vals) && vals.length > 0) count += vals.length;
        });

        const attrs = AppState.filters.itemAttributes || {};
        Object.keys(attrs).forEach(k => {
            const vals = attrs[k];
            if (Array.isArray(vals) && vals.length > 0) count += vals.length;
        });

        if (DOM.activeFilterBadge) {
            DOM.activeFilterBadge.textContent = `Active Filters: ${count}`;
        }
    }

    function resetFilters() {
        // FT10: Reset all filters to nothing selected. Does not reload data, does not change Period/Measure or Top N.
        AppState.filters = {
            fromDate: null,
            toDate: null,
            year: [],
            month: [],
            week: [],
            day: [],
            document: [],
            documentType: [],
            salesType: [],
            salesFromLocation: [],
            bpCode: [],
            bpName: [],
            group: [],
            industry: [],
            bpProject: [],
            rowSalesEmployee: [],
            bpSalesEmployee: [],
            region: [],
            state: [],
            city: [],
            country: [],
            itemGroup: [],
            subGroup1: [],
            subGroup2: [],
            itemCode: [],
            brand: [],
            moc: [],
            madeToOrder: [],
            uom: [],
            itemAttributes: {}
        };
        if (DOM.filterFromDate) DOM.filterFromDate.value = "";
        if (DOM.filterToDate) DOM.filterToDate.value = "";
        AppState.tablePage = 1;
        executeQuery();
    }

    async function refreshData() {
        showLoading("Refreshing Sales Data...", "Reloading live SAP data through API gateway");
        try {
            const resp = await fetch("/api/sales/dataset?refresh=true");
            const data = await resp.json();
            if (data.status === "loading") {
                setTimeout(pollDatasetLoad, 1000);
            }
        } catch (err) {
            hideLoading();
            alert("Error refreshing dataset: " + err);
        }
    }

    // ─── PDF EXPORT (HD3) ────────────────────────────────────────────────────
    function exportPdf() {
        if (!window.html2pdf) {
            alert("PDF export library is still loading. Please try again in a moment.");
            return;
        }

        // HD3: Produces PDF containing Title, Data as of stamp, and exactly 16 charts (main + 15 breakdowns)
        // Does not include filter panel or detail table. Does not reload data.
        showLoading("Generating PDF...", "Rendering all 16 charts to document");

        // Prepare print header
        if (DOM.pdfReportHeader) {
            DOM.pdfReportHeader.classList.remove("d-none");
            if (DOM.pdfReportGranularity) {
                DOM.pdfReportGranularity.textContent = `${AppState.granularity} • ${AppState.measure}`;
            }
            if (DOM.pdfReportDate) {
                DOM.pdfReportDate.textContent = `Data as of ${AppState.dataAsOf || '--'}`;
            }
        }

        const element = document.createElement("div");
        element.style.padding = "20px";
        element.style.backgroundColor = "#FFFFFF";

        // 1. Header
        element.appendChild(DOM.pdfReportHeader.cloneNode(true));

        // 2. Main Chart
        const mainCardClone = document.getElementById("mainChartCard").cloneNode(true);
        // Replace canvas with image from active chart
        const mainCanvas = document.getElementById("mainSalesChart");
        const mainImg = document.createElement("img");
        mainImg.src = mainCanvas.toDataURL("image/png");
        mainImg.style.width = "100%";
        mainImg.style.height = "auto";
        const mainCanvasContainer = mainCardClone.querySelector("canvas").parentElement;
        mainCanvasContainer.innerHTML = "";
        mainCanvasContainer.style.height = "auto";
        mainCanvasContainer.appendChild(mainImg);
        element.appendChild(mainCardClone);

        // 3. All 15 Breakdown Charts
        const breakdownGrid = document.createElement("div");
        breakdownGrid.className = "row g-3";

        const chartItems = document.querySelectorAll("#breakdownChartsGrid .chart-item");
        chartItems.forEach(item => {
            const chartId = item.getAttribute("data-chart-id");
            const clone = item.cloneNode(true);
            const origCanvas = document.getElementById(`chart_${chartId}`);
            if (origCanvas) {
                const img = document.createElement("img");
                img.src = origCanvas.toDataURL("image/png");
                img.style.width = "100%";
                img.style.height = "auto";
                const scrollContainer = clone.querySelector(".breakdown-scroll-container");
                if (scrollContainer) {
                    scrollContainer.innerHTML = "";
                    scrollContainer.style.height = "auto";
                    scrollContainer.style.overflow = "visible";
                    scrollContainer.appendChild(img);
                }
            }
            breakdownGrid.appendChild(clone);
        });

        element.appendChild(breakdownGrid);

        const opt = {
            margin: [10, 10, 10, 10],
            filename: `HoseXperts_Sales_Dashboard_${new Date().toISOString().slice(0, 10)}.pdf`,
            image: { type: "jpeg", quality: 0.98 },
            html2canvas: { scale: 2, useCORS: true, logging: false },
            jsPDF: { unit: "mm", format: "a4", orientation: "landscape" }
        };

        window.html2pdf().from(element).set(opt).save().then(() => {
            if (DOM.pdfReportHeader) DOM.pdfReportHeader.classList.add("d-none");
            hideLoading();
        }).catch(err => {
            console.error("PDF generation failed:", err);
            if (DOM.pdfReportHeader) DOM.pdfReportHeader.classList.add("d-none");
            hideLoading();
            alert("PDF generation failed. Please see console.");
        });
    }

    // Boot
    document.addEventListener("DOMContentLoaded", init);
})();
