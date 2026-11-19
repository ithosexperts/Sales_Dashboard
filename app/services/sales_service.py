"""
Sales Analytics Data Service.

Implements all specification requirements:
- In-memory dataset caching and thread-safe loading (DL1–DL5)
- Revenue [Row Total (After Doc Disc)] (DS3), Quantity by UoM (DS4), Gross Profit (DS5)
- Multi-granularity period grouping using SQL Server columns (DS6, DS7, FL1–FL6)
- Multi-select, two-way cascading (faceted) filters across 8 sections (FT1–FT11)
- Main chart with vertical bars and dual-axis Margin % line in GP mode (CH1–CH3)
- 15 breakdown charts with largest-to-smallest sorting, negative handling, and Top N Customers (CH4–CH13)
- 12-column detail table with global sorting and 50-row pagination (TB1–TB5)
- Preserves accepted limitations (LM1–LM6) and data quality characteristics (DQ1–DQ6)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta, date
import gc
import logging
import math
import time
from typing import Any

import numpy as np
import pandas as pd

from app.api.client import api_request, ApiError
from app.auth.request_context import get_current_database_target
from app.config import settings

logger = logging.getLogger(__name__)

# Column names from SQL View VD_Sales_Dashboard
REV_COL = "Row Total (After Doc Disc)"
GP_COL = "Gross Profit"
QTY_COL = "Quantity"
UOM_COL = "UoM"
DOC_COL = "Document"
DOC_TYPE_COL = "Document Type"
DOC_DATE_COL = "Doc Date"
DOC_NUM_COL = "DocNum"
ITEM_CODE_COL = "Item Code"
ITEM_NAME_COL = "Item Name"
BP_CODE_COL = "BP Code"
BP_NAME_COL = "BP Name"
GROUP_COL = "Group"
INDUSTRY_COL = "Industry"
BP_PROJECT_COL = "BP Project"
CITY_COL = "City"
STATE_COL = "State"
COUNTRY_COL = "Country"
REGION_COL = "Region"
SALES_TYPE_COL = "Sales Type"
SALES_FROM_LOC_COL = "Sales From Location"
BRAND_COL = "Brand"
MOC_COL = "MOC"
MADE_TO_ORDER_COL = "Made To Order"
ITEM_GROUP_COL = "Item Group"
SUB_GROUP1_COL = "Sub Group 1"
SUB_GROUP2_COL = "Sub Group 2"
ROW_SALES_EMP_COL = "Row Sales Employee"
BP_SALES_EMP_COL = "BP Sales Employee"
YEAR_COL = "Year"
MONTH_COL = "Month"
WEEK_COL = "Week"
DAY_COL = "Day"

# All 20 Item Attributes
ITEM_ATTRIBUTE_COLUMNS = [
    "Clamps Min Range mm",
    "Clamps Max Range mm",
    "Hose Assy EC1",
    "Hose Assy EC2",
    "Hose Assy Hose",
    "Hose Assy Hose Guard",
    "Hose Coupling Dash Size",
    "Hose Coupling WP",
    "Hose Fittings Dash Size",
    "Hose Fittings Type",
    "Hose Guard ID mm",
    "Hose Size (mm)",
    "Hose WP (Bar)",
    "Rub Exp Joints ID (mm)",
    "Rub Exp Joints WP (Bar)",
    "Rub Exp Joints Falnge Type",
    "Hose Reel Type",
    "Hose Reel Size",
    "Hose Reel Arms",
    "Hose Reel Hose Type",
]

MONTH_ABBRS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# Query calculation caches (cleared on dataset refresh)
_facet_cache: dict[tuple, dict[str, Any]] = {}
_breakdown_cache: dict[tuple, dict[str, Any]] = {}
_table_cache: dict[tuple, tuple[pd.DataFrame, int]] = {}
_mask_cache: dict[tuple, pd.Series] = {}


def clear_query_caches() -> None:
    """Clear all in-memory calculation caches on dataset reload/refresh."""
    _facet_cache.clear()
    _breakdown_cache.clear()
    _table_cache.clear()
    _mask_cache.clear()


def _hash_filters(filters: dict[str, Any] | None) -> tuple:
    """Produce a deterministic, hashable representation of active filters."""
    if not filters:
        return ()
    items = []
    for k in sorted(filters.keys()):
        v = filters[k]
        if not v:
            continue
        if k == "itemAttributes" and isinstance(v, dict):
            sub_items = tuple(
                (sub_k, tuple(sorted(str(x) for x in sub_v)))
                for sub_k, sub_v in sorted(v.items())
                if sub_v
            )
            if sub_items:
                items.append((k, sub_items))
        elif isinstance(v, list):
            valid_vals = tuple(sorted(str(x) for x in v if x is not None and str(x) != ""))
            if valid_vals:
                items.append((k, valid_vals))
        elif v is not None and str(v) != "":
            items.append((k, str(v)))
    return tuple(items)


def format_indian_currency(val: float, compact: bool = False) -> str:
    """Format currency in Indian Lakh/Crore numbering."""
    if math.isnan(val):
        return "₹0.00"
    is_neg = val < 0
    abs_val = abs(val)
    prefix = "-₹" if is_neg else "₹"
    if compact:
        if abs_val >= 10000000:
            cr = abs_val / 10000000
            return f"{prefix}{cr:.2f} Cr"
        elif abs_val >= 100000:
            lakh = abs_val / 100000
            return f"{prefix}{lakh:.2f} Lakh"
        else:
            return f"{prefix}{abs_val:,.2f}"
    return f"{prefix}{abs_val:,.2f}"


class SalesDataStore:
    """
    In-memory singleton dataset store for VD_Sales_Dashboard.
    Queries the database ONLY on open or explicit refresh (DL1, DL2, DL3).
    """

    _instance: SalesDataStore | None = None

    def __init__(self) -> None:
        self._df: pd.DataFrame | None = None
        self._data_as_of: datetime | None = None
        self._total_records: int = 0
        self._database: str = settings.api_database
        self._lock = asyncio.Lock()
        self._is_loading: bool = False
        self._load_error: str | None = None
        self._load_progress: str = "Ready"
        self._loaded_so_far: int = 0
        self._load_task: asyncio.Task | None = None

    @classmethod
    def get_instance(cls) -> SalesDataStore:
        if cls._instance is None:
            cls._instance = SalesDataStore()
        return cls._instance

    @property
    def is_loaded(self) -> bool:
        return self._df is not None and not self._df.empty and not self._is_loading

    @property
    def is_loading(self) -> bool:
        return self._is_loading

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def load_progress(self) -> str:
        return self._load_progress

    @property
    def loaded_so_far(self) -> int:
        return self._loaded_so_far

    @property
    def total_records(self) -> int:
        return self._total_records

    @property
    def data_as_of(self) -> datetime | None:
        return self._data_as_of

    @property
    def data_as_of_formatted(self) -> str:
        """Data as of DD-MMM-YYYY HH:MM in 24-hour IST (DL4)."""
        if not self._data_as_of:
            return "--"
        dt = self._data_as_of
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ist = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
        return ist.strftime("%d-%b-%Y %H:%M")

    def start_background_load(self, force_refresh: bool = False) -> None:
        """Initiate background data load without blocking HTTP response."""
        if self._df is not None and not self._df.empty and not force_refresh and not self._is_loading:
            return
        if self._is_loading or (self._load_task and not self._load_task.done()):
            return
        self._is_loading = True
        self._load_error = None
        self._load_progress = "Connecting to database..."
        self._loaded_so_far = 0
        if force_refresh:
            clear_query_caches()
        try:
            loop = asyncio.get_running_loop()
            self._load_task = loop.create_task(self._do_background_load(force_refresh=force_refresh))
        except RuntimeError:
            try:
                self._load_task = asyncio.create_task(self._do_background_load(force_refresh=force_refresh))
            except RuntimeError:
                pass

    async def _do_background_load(self, force_refresh: bool = False) -> None:
        async with self._lock:
            if self._df is not None and not self._df.empty and not force_refresh:
                self._is_loading = False
                return
            try:
                await self._load_data()
                self._load_progress = "Ready"
            except Exception as exc:
                logger.exception("Failed to load sales dataset: %s", exc)
                self._load_error = str(exc)
                self._load_progress = f"Error: {exc}"
            finally:
                self._is_loading = False

    async def get_dataframe(self, force_refresh: bool = False) -> pd.DataFrame:
        """Return the loaded DataFrame, loading or refreshing if required."""
        if self._df is not None and not force_refresh and not self._is_loading:
            return self._df

        async with self._lock:
            if self._df is not None and not force_refresh and not self._is_loading:
                return self._df
            self._is_loading = True
            self._load_error = None
            try:
                await self._load_data()
            except Exception as exc:
                self._load_error = str(exc)
                raise
            finally:
                self._is_loading = False
            return self._df

    async def _load_data(self) -> None:
        """Fetch the full view from OperationsDB into in-memory pandas DataFrame with strict memory controls for 512MB RAM."""
        target_db = get_current_database_target() or settings.api_database or "OperationsDB"
        logger.info("Initiating low-memory dataset load from VD_Sales_Dashboard (%s)", target_db)
        self._load_progress = "Fetching initial batch..."

        batch_size = 10000
        stable_order = "Document, DocEntry, LineNum"

        categorical_cols = [
            DOC_COL, DOC_TYPE_COL, SALES_TYPE_COL, SALES_FROM_LOC_COL,
            BP_CODE_COL, BP_NAME_COL, GROUP_COL, INDUSTRY_COL, BP_PROJECT_COL,
            CITY_COL, STATE_COL, COUNTRY_COL, REGION_COL,
            ITEM_GROUP_COL, SUB_GROUP1_COL, SUB_GROUP2_COL,
            ITEM_CODE_COL, ITEM_NAME_COL, BRAND_COL, MOC_COL, MADE_TO_ORDER_COL, UOM_COL,
            ROW_SALES_EMP_COL, BP_SALES_EMP_COL,
        ] + ITEM_ATTRIBUTE_COLUMNS

        def _optimize_chunk(chunk_df: pd.DataFrame) -> pd.DataFrame:
            if REV_COL in chunk_df.columns:
                chunk_df[REV_COL] = pd.to_numeric(chunk_df[REV_COL], errors="coerce").fillna(0.0).astype("float64")
            if GP_COL in chunk_df.columns:
                chunk_df[GP_COL] = pd.to_numeric(chunk_df[GP_COL], errors="coerce").fillna(0.0).astype("float64")
            if QTY_COL in chunk_df.columns:
                chunk_df[QTY_COL] = pd.to_numeric(chunk_df[QTY_COL], errors="coerce").fillna(0.0).astype("float32")

            for p_col in (YEAR_COL, MONTH_COL, WEEK_COL, DAY_COL):
                if p_col in chunk_df.columns:
                    chunk_df[p_col] = pd.to_numeric(chunk_df[p_col], errors="coerce").fillna(0).astype("int16")

            if DOC_DATE_COL in chunk_df.columns:
                doc_dates = pd.to_datetime(chunk_df[DOC_DATE_COL], errors="coerce")
                chunk_df["_doc_date_str"] = doc_dates.dt.strftime("%Y-%m-%d").fillna("")
                chunk_df["_doc_date_display"] = doc_dates.dt.strftime("%d-%b-%Y").fillna("")

            for c in categorical_cols:
                if c in chunk_df.columns:
                    s = chunk_df[c].fillna("(Blank)").astype(str).str.strip()
                    chunk_df[c] = s.replace({"": "(Blank)", "None": "(Blank)", "nan": "(Blank)", "Null": "(Blank)", "null": "(Blank)"})
            return chunk_df

        # Fetch page 1 to get total pages
        first_resp = await api_request(
            table="VD_Sales_Dashboard",
            action="select",
            columns="*",
            order_by=stable_order,
            page=1,
            limit=batch_size,
            database=target_db,
        )

        total_rows = int(first_resp.get("totalRows", 0) or 0)
        total_pages = int(first_resp.get("totalPages", 1) or ((total_rows + batch_size - 1) // batch_size))
        page_frames: list[pd.DataFrame] = []

        first_rows = first_resp.get("data") or []
        if first_rows:
            chunk1 = _optimize_chunk(pd.DataFrame(first_rows))
            page_frames.append(chunk1)
            self._loaded_so_far = len(chunk1)
            self._load_progress = f"Loaded {self._loaded_so_far:,} of {total_rows:,} records (batch 1/{total_pages})..."
        del first_rows, first_resp
        gc.collect()

        if total_pages > 1:
            sem = asyncio.Semaphore(3)

            async def _fetch_page(page_num: int) -> pd.DataFrame:
                async with sem:
                    resp = await api_request(
                        table="VD_Sales_Dashboard",
                        action="select",
                        columns="*",
                        order_by=stable_order,
                        page=page_num,
                        limit=batch_size,
                        database=target_db,
                    )
                    rows = resp.get("data") or []
                    if rows:
                        chunk = _optimize_chunk(pd.DataFrame(rows))
                    else:
                        chunk = pd.DataFrame()
                    del resp, rows
                    gc.collect()
                    self._loaded_so_far += len(chunk)
                    self._load_progress = f"Loaded {min(self._loaded_so_far, total_rows):,} of {total_rows:,} records (batch {page_num}/{total_pages})..."
                    logger.info("Loaded batch %d/%d (%d rows, progress: %s)", page_num, total_pages, len(chunk), self._load_progress)
                    return chunk

            tasks = [_fetch_page(p) for p in range(2, total_pages + 1)]
            remaining_frames = await asyncio.gather(*tasks)
            page_frames.extend([f for f in remaining_frames if not f.empty])
            del remaining_frames
            gc.collect()

        df = pd.concat(page_frames, ignore_index=True)
        del page_frames
        gc.collect()

        # Convert categorical text columns to category dtype for ultra-fast aggregation & low RAM
        for col in categorical_cols:
            if col in df.columns:
                df[col] = df[col].astype("category")

        gc.collect()

        self._df = df
        self._total_records = len(df)
        self._data_as_of = datetime.now(timezone.utc)
        self._database = target_db
        clear_query_caches()
        mem_mb = float(df.memory_usage(deep=True).sum()) / (1024 * 1024)
        logger.info("Successfully loaded %d records from VD_Sales_Dashboard (RAM: %.1f MB)",
                    self._total_records, mem_mb)


data_store = SalesDataStore.get_instance()


# ─── FILTERING AND CASCADING HELPERS ──────────────────────────────────────────

FILTER_FIELD_MAP = {
    "year": YEAR_COL,
    "month": MONTH_COL,
    "week": WEEK_COL,
    "day": DAY_COL,
    "document": DOC_COL,
    "documentType": DOC_TYPE_COL,
    "salesType": SALES_TYPE_COL,
    "salesFromLocation": SALES_FROM_LOC_COL,
    "bpCode": BP_CODE_COL,
    "bpName": BP_NAME_COL,
    "group": GROUP_COL,
    "industry": INDUSTRY_COL,
    "bpProject": BP_PROJECT_COL,
    "rowSalesEmployee": ROW_SALES_EMP_COL,
    "bpSalesEmployee": BP_SALES_EMP_COL,
    "region": REGION_COL,
    "state": STATE_COL,
    "city": CITY_COL,
    "country": COUNTRY_COL,
    "itemGroup": ITEM_GROUP_COL,
    "subGroup1": SUB_GROUP1_COL,
    "subGroup2": SUB_GROUP2_COL,
    "itemCode": ITEM_CODE_COL,
    "brand": BRAND_COL,
    "moc": MOC_COL,
    "madeToOrder": MADE_TO_ORDER_COL,
    "uom": UOM_COL,
}

ITEM_ATTR_FIELD_MAP = {
    "clampsMinRange": "Clamps Min Range mm",
    "clampsMaxRange": "Clamps Max Range mm",
    "hoseAssyEc1": "Hose Assy EC1",
    "hoseAssyEc2": "Hose Assy EC2",
    "hoseAssyHose": "Hose Assy Hose",
    "hoseAssyHoseGuard": "Hose Assy Hose Guard",
    "hoseCouplingDashSize": "Hose Coupling Dash Size",
    "hoseCouplingWp": "Hose Coupling WP",
    "hoseFittingsDashSize": "Hose Fittings Dash Size",
    "hoseFittingsType": "Hose Fittings Type",
    "hoseGuardIdMm": "Hose Guard ID mm",
    "hoseSizeMm": "Hose Size (mm)",
    "hoseWpBar": "Hose WP (Bar)",
    "rubExpJointsIdMm": "Rub Exp Joints ID (mm)",
    "rubExpJointsWpBar": "Rub Exp Joints WP (Bar)",
    "rubExpJointsFalngeType": "Rub Exp Joints Falnge Type",
    "hoseReelType": "Hose Reel Type",
    "hoseReelSize": "Hose Reel Size",
    "hoseReelArms": "Hose Reel Arms",
    "hoseReelHoseType": "Hose Reel Hose Type",
}


def _build_filter_mask(
    df: pd.DataFrame,
    filters: dict[str, Any] | None,
    exclude_key: str | None = None,
    exclude_attr: str | None = None,
) -> pd.Series:
    """Build a boolean filter mask across all active filters, optionally excluding one."""
    if not filters:
        return pd.Series(True, index=df.index)

    mask = None

    # 1. From Date & To Date (calendar range filtering on Doc Date)
    if exclude_key != "dateRange":
        from_date = filters.get("fromDate")
        to_date = filters.get("toDate")
        if from_date and "_doc_date_str" in df.columns:
            c = (df["_doc_date_str"] >= str(from_date))
            mask = c if mask is None else (mask & c)
        if to_date and "_doc_date_str" in df.columns:
            c = (df["_doc_date_str"] <= str(to_date))
            mask = c if mask is None else (mask & c)

    # 2. Standard field filters
    for filter_key, col_name in FILTER_FIELD_MAP.items():
        if exclude_key == filter_key:
            continue
        selected_values = filters.get(filter_key)
        if not selected_values:
            continue
        if not isinstance(selected_values, list):
            selected_values = [selected_values]
        if not selected_values:
            continue

        col_series = df[col_name]
        if pd.api.types.is_numeric_dtype(col_series):
            int_vals = [int(v) for v in selected_values if str(v).isdigit()]
            cond = col_series.isin(int_vals) if int_vals else pd.Series(False, index=df.index)
        else:
            cond = col_series.isin(selected_values)

        mask = cond if mask is None else (mask & cond)

    # 3. Item Attributes filters
    item_attrs = filters.get("itemAttributes") or {}
    for attr_key, attr_col in ITEM_ATTR_FIELD_MAP.items():
        if exclude_key == "itemAttributes" and exclude_attr == attr_key:
            continue
        selected_values = item_attrs.get(attr_key)
        if not selected_values:
            continue
        if not isinstance(selected_values, list):
            selected_values = [selected_values]
        if not selected_values:
            continue

        cond = df[attr_col].isin(selected_values)
        mask = cond if mask is None else (mask & cond)

    if mask is None:
        return pd.Series(True, index=df.index)
    return mask


def _get_distinct_options_with_counts(
    df: pd.DataFrame,
    col_name: str,
    active_mask: pd.Series | None,
    selected_values: list[Any] | None = None,
    is_numeric: bool = False,
) -> list[dict[str, Any]]:
    """
    Compute faceted options with matching row counts (FT5, FT6, FT7).
    Runs on pre-categorized series for ultra-fast response.
    """
    selected_set = set(str(v) for v in (selected_values or []))
    col_series = df[col_name] if active_mask is None else df.loc[active_mask, col_name]

    counts_dict: dict[str, int] = {}

    if is_numeric:
        valid_series = col_series.dropna().astype(int)
        vc = valid_series.value_counts()
        for k, count in vc.items():
            counts_dict[str(k)] = int(count)
    else:
        # col_series is pre-categorized with '(Blank)'
        vc = col_series.value_counts()
        for k, count in vc.items():
            counts_dict[str(k)] = int(count)

    options = []
    all_keys = set(counts_dict.keys()) | selected_set
    sorted_keys = sorted(all_keys, key=lambda x: (x == "(Blank)", -counts_dict.get(x, 0), str(x)))

    for k in sorted_keys:
        cnt = counts_dict.get(k, 0)
        is_selected = k in selected_set
        is_stale = is_selected and cnt == 0
        options.append({
            "value": k,
            "label": f"{k} ({cnt:,})",
            "count": cnt,
            "selected": is_selected,
            "stale": is_stale,
        })

    return options


# ─── SUMMARY KPI CARDS CALCULATION (HD4, HD5, HD6) ───────────────────────────

def calculate_summary_cards(
    filtered_df: pd.DataFrame,
    granularity: str = "Monthly",
    measure: str = "Revenue ₹",
) -> dict[str, Any]:
    """Calculate the 4 required summary cards."""
    row_count = len(filtered_df)
    if row_count == 0:
        return {
            "filtered_revenue_exact": 0.0,
            "filtered_revenue_formatted": "₹0.00",
            "filtered_revenue_compact": "₹0.00",
            "filtered_gross_profit_exact": 0.0,
            "filtered_gross_profit_formatted": "₹0.00",
            "margin_pct": None,
            "margin_pct_formatted": "–",
            "filtered_rows": 0,
            "filtered_rows_formatted": "0",
            "granularity_label": f"{granularity} • {measure.replace('₹', '').strip()}",
        }

    total_revenue = float(filtered_df[REV_COL].sum())
    total_gp = float(filtered_df[GP_COL].sum())

    if total_revenue != 0.0:
        margin = round((total_gp / total_revenue) * 100.0, 1)
        margin_str = f"{margin:.1f}%"
    else:
        margin = None
        margin_str = "–"

    compact_rev = format_indian_currency(total_revenue, compact=True)
    exact_rev = format_indian_currency(total_revenue, compact=False)
    exact_gp = format_indian_currency(total_gp, compact=False)

    measure_clean = "Revenue" if "Revenue" in measure else ("Gross Profit" if "Profit" in measure else "Quantity")

    return {
        "filtered_revenue_exact": round(total_revenue, 2),
        "filtered_revenue_formatted": exact_rev,
        "filtered_revenue_compact": compact_rev,
        "filtered_gross_profit_exact": round(total_gp, 2),
        "filtered_gross_profit_formatted": exact_gp,
        "margin_pct": margin,
        "margin_pct_formatted": margin_str,
        "filtered_rows": row_count,
        "filtered_rows_formatted": f"{row_count:,}",
        "granularity_label": f"{granularity} • {measure_clean}",
    }


# ─── MAIN SALES ANALYSIS CHART (CH1, CH2, CH3, FL4, FL5, FL6) ─────────────────

def calculate_main_chart(
    filtered_df: pd.DataFrame,
    granularity: str = "Monthly",
    measure: str = "Revenue ₹",
) -> dict[str, Any]:
    """
    Main chart vertical bars by selected Period (FL4, FL5, FL6, CH1, CH2, CH3).
    """
    if filtered_df.empty:
        return {
            "categories": [],
            "series": [],
            "has_margin_line": False,
            "margin_series": [],
            "uoms": [],
            "measure": measure,
            "granularity": granularity,
        }

    is_gp_mode = "Profit" in measure or measure == "Gross Profit ₹"
    is_qty_mode = "Quantity" in measure

    if granularity == "Yearly":
        group_cols = [YEAR_COL]
        order_key = [YEAR_COL]

        def get_label(row):
            return str(int(row[YEAR_COL]))

    elif granularity == "Monthly":
        group_cols = [YEAR_COL, MONTH_COL]
        order_key = [YEAR_COL, MONTH_COL]

        def get_label(row):
            y = int(row[YEAR_COL])
            m = int(row[MONTH_COL])
            m_abbr = MONTH_ABBRS[m - 1] if 1 <= m <= 12 else f"M{m}"
            return f"{m_abbr}-{y}"

    elif granularity == "Weekly":
        group_cols = [YEAR_COL, WEEK_COL]
        order_key = [YEAR_COL, WEEK_COL]

        def get_label(row):
            y = int(row[YEAR_COL])
            w = int(row[WEEK_COL])
            return f"{y}-W{w:02d}"

    else:  # Daily
        group_cols = ["_doc_date_str"]
        order_key = ["_doc_date_str"]

        def get_label(row):
            d_str = str(row["_doc_date_str"])
            try:
                dt = datetime.strptime(d_str, "%Y-%m-%d")
                return dt.strftime("%d-%b-%y")
            except Exception:
                return d_str

    if is_qty_mode:
        df_qty = filtered_df.copy()
        uom_clean = df_qty[UOM_COL].fillna("(Blank)").astype(str).str.strip()
        uom_clean = uom_clean.replace({"": "(Blank)", "nan": "(Blank)", "None": "(Blank)"})
        df_qty[UOM_COL] = uom_clean

        uom_group_cols = group_cols + [UOM_COL]
        agg_df = df_qty.groupby(uom_group_cols, as_index=False, observed=True)[QTY_COL].sum()

        unique_periods = df_qty[group_cols].drop_duplicates().sort_values(order_key)
        labels = [get_label(r) for _, r in unique_periods.iterrows()]
        period_keys = [tuple(r[c] for c in group_cols) for _, r in unique_periods.iterrows()]

        unique_uoms = sorted(str(u) for u in agg_df[UOM_COL].unique())
        series = []

        agg_map = {}
        for _, row in agg_df.iterrows():
            p_key = tuple(row[c] for c in group_cols)
            u = str(row[UOM_COL])
            agg_map[(p_key, u)] = float(row[QTY_COL])

        for u in unique_uoms:
            data_vals = [round(agg_map.get((pk, u), 0.0), 2) for pk in period_keys]
            series.append({
                "name": u,
                "data": data_vals,
            })

        return {
            "categories": labels,
            "series": series,
            "has_margin_line": False,
            "margin_series": [],
            "uoms": unique_uoms,
            "measure": measure,
            "granularity": granularity,
        }

    # Revenue or Gross Profit mode
    agg_dict = {REV_COL: "sum", GP_COL: "sum"}
    agg_df = filtered_df.groupby(group_cols, as_index=False, observed=True).agg(agg_dict)
    agg_df = agg_df.sort_values(order_key)

    labels = [get_label(r) for _, r in agg_df.iterrows()]
    rev_vals = [round(float(v), 2) for v in agg_df[REV_COL]]
    gp_vals = [round(float(v), 2) for v in agg_df[GP_COL]]

    if is_gp_mode:
        margin_line = []
        for r, g in zip(rev_vals, gp_vals):
            if r != 0.0:
                m_pct = round((g / r) * 100.0, 1)
                margin_line.append(m_pct)
            else:
                margin_line.append(None)

        series = [{
            "name": "Gross Profit ₹",
            "data": gp_vals,
        }]
        return {
            "categories": labels,
            "series": series,
            "has_margin_line": True,
            "margin_series": margin_line,
            "uoms": [],
            "measure": measure,
            "granularity": granularity,
        }

    series = [{
        "name": "Revenue ₹",
        "data": rev_vals,
    }]
    return {
        "categories": labels,
        "series": series,
        "has_margin_line": False,
        "margin_series": [],
        "uoms": [],
        "measure": measure,
        "granularity": granularity,
    }


# ─── 15 BREAKDOWN CHARTS (CH4–CH13) ──────────────────────────────────────────

BREAKDOWN_SPECS = [
    {"id": "domestic_vs_export", "title": "Domestic vs Export", "col": "Country", "custom": "country"},
    {"id": "region", "title": "Region", "col": "Region"},
    {"id": "state", "title": "Ship-To State", "col": "State"},
    {"id": "sales_from_location", "title": "Sales From Location", "col": "Sales From Location"},
    {"id": "item_group", "title": "Item Group", "col": "Item Group"},
    {"id": "sub_group1", "title": "Sub Group 1", "col": "Sub Group 1"},
    {"id": "sub_group2", "title": "Sub Group 2", "col": "Sub Group 2"},
    {"id": "brand", "title": "Brand", "col": "Brand"},
    {"id": "row_sales_employee", "title": "Row Sales Employee", "col": "Row Sales Employee"},
    {"id": "bp_sales_employee", "title": "BP Sales Employee", "col": "BP Sales Employee"},
    {"id": "sales_type", "title": "Credit vs Advance", "col": "Sales Type"},
    {"id": "top_customers", "title": "Top N Customers", "col": "BP Name", "custom": "top_n"},
    {"id": "customer_group", "title": "Customer Group", "col": "Group"},
    {"id": "industry", "title": "Industry", "col": "Industry"},
    {"id": "bp_project", "title": "BP Project", "col": "BP Project"},
]


def calculate_breakdowns(
    filtered_df: pd.DataFrame,
    measure: str = "Revenue ₹",
    top_n_limit: int = 50,
) -> dict[str, Any]:
    """Calculate all 15 breakdown charts (CH4–CH13)."""
    if filtered_df.empty:
        return {b["id"]: {"id": b["id"], "title": b["title"], "categories": [], "series": [], "is_qty": False} for b in BREAKDOWN_SPECS}

    is_gp_mode = "Profit" in measure or measure == "Gross Profit ₹"
    is_qty_mode = "Quantity" in measure
    val_col = GP_COL if is_gp_mode else (QTY_COL if is_qty_mode else REV_COL)

    results = {}

    for spec in BREAKDOWN_SPECS:
        b_id = spec["id"]
        title = spec["title"]
        col = spec["col"]
        custom = spec.get("custom")

        if custom == "country":
            country_clean = filtered_df[COUNTRY_COL].astype(str).str.upper()
            cat_series = pd.Series("(Blank)", index=filtered_df.index)
            cat_series[country_clean == "IN"] = "Domestic"
            cat_series[(country_clean != "IN") & (country_clean != "(BLANK)") & (country_clean != "")] = "Export"
        else:
            cat_series = filtered_df[col]

        if is_qty_mode:
            uom_series = filtered_df[UOM_COL]
            df_temp = pd.DataFrame({
                "cat": cat_series,
                "uom": uom_series,
                "qty": filtered_df[QTY_COL],
                "rev": filtered_df[REV_COL],
            })

            if custom == "top_n":
                n_val = max(2, min(50, int(top_n_limit)))
                bp_rev = df_temp.groupby("cat", observed=True)["rev"].sum().sort_values(ascending=False)
                total_cust = len(bp_rev)
                top_cats = bp_rev.head(n_val).index.tolist()
                others_count = max(0, total_cust - len(top_cats))

                cat_mapped = df_temp["cat"].apply(lambda c: c if c in top_cats else f"Others ({others_count} customers)")
                df_temp["cat"] = cat_mapped

                grouped = df_temp.groupby(["cat", "uom"], as_index=False, observed=True)["qty"].sum()
                all_uoms = sorted(str(u) for u in df_temp["uom"].unique())
                categories = [str(c) for c in top_cats] + ([f"Others ({others_count} customers)"] if others_count > 0 else [])
            else:
                cat_totals = df_temp.groupby("cat", observed=True)["qty"].sum().sort_values(ascending=False)
                categories = [str(c) for c in cat_totals.index.tolist()]
                grouped = df_temp.groupby(["cat", "uom"], as_index=False, observed=True)["qty"].sum()
                all_uoms = sorted(str(u) for u in df_temp["uom"].unique())

            val_map = {(str(r["cat"]), str(r["uom"])): round(float(r["qty"]), 2) for _, r in grouped.iterrows()}
            series = []
            for u in all_uoms:
                s_data = [val_map.get((c, u), 0.0) for c in categories]
                series.append({"name": u, "data": s_data})

            results[b_id] = {
                "id": b_id,
                "title": title,
                "categories": categories,
                "series": series,
                "is_qty": True,
                "uoms": all_uoms,
            }

        elif custom == "top_n":
            n_val = max(2, min(50, int(top_n_limit)))
            df_temp = pd.DataFrame({
                "cat": cat_series,
                "val": filtered_df[val_col],
            })
            grouped_cust = df_temp.groupby("cat", observed=True)["val"].sum()

            if is_gp_mode:
                pos = grouped_cust[grouped_cust >= 0].sort_values(ascending=False)
                neg = grouped_cust[grouped_cust < 0].sort_values(ascending=False)
                sorted_cust = pd.concat([pos, neg])
            else:
                sorted_cust = grouped_cust.sort_values(ascending=False)

            total_cust = len(sorted_cust)
            top_part = sorted_cust.head(n_val)
            rem_part = sorted_cust.iloc[n_val:]
            others_count = max(0, total_cust - len(top_part))

            categories = [str(c) for c in top_part.index]
            data_vals = [round(float(v), 2) for v in top_part.values]

            if others_count > 0:
                others_label = f"Others ({others_count} customers)"
                others_val = round(float(rem_part.sum()), 2)
                categories.append(others_label)
                data_vals.append(others_val)

            results[b_id] = {
                "id": b_id,
                "title": title,
                "categories": categories,
                "series": [{"name": measure, "data": data_vals}],
                "is_qty": False,
                "top_n": n_val,
            }

        else:
            df_temp = pd.DataFrame({
                "cat": cat_series,
                "val": filtered_df[val_col],
            })
            grouped = df_temp.groupby("cat", observed=True)["val"].sum()

            if is_gp_mode:
                pos = grouped[grouped >= 0].sort_values(ascending=False)
                neg = grouped[grouped < 0].sort_values(ascending=False)
                sorted_grouped = pd.concat([pos, neg])
            else:
                sorted_grouped = grouped.sort_values(ascending=False)

            categories = [str(c) for c in sorted_grouped.index]
            data_vals = [round(float(v), 2) for v in sorted_grouped.values]

            results[b_id] = {
                "id": b_id,
                "title": title,
                "categories": categories,
                "series": [{"name": measure, "data": data_vals}],
                "is_qty": False,
            }

    return results


# ─── DETAIL TABLE WITH GLOBAL SORTING & PAGINATION (TB1–TB5) ──────────────────

DETAIL_COLUMNS_CONFIG = [
    {"key": "index", "label": "#", "numeric": True},
    {"key": "DocNum", "label": "DocNum", "numeric": True},
    {"key": "Document", "label": "Document", "numeric": False},
    {"key": "Document Type", "label": "Document Type", "numeric": False},
    {"key": "Doc Date", "label": "Doc Date", "numeric": False},
    {"key": "BP Name", "label": "BP Name", "numeric": False},
    {"key": "Item Code", "label": "Item Code", "numeric": False},
    {"key": "Quantity", "label": "Quantity", "numeric": True},
    {"key": "UoM", "label": "UoM", "numeric": False},
    {"key": "Row Total (After Doc Disc)", "label": "Row Total (After Doc Disc)", "numeric": True},
    {"key": "Row Sales Employee", "label": "Row Sales Employee", "numeric": False},
    {"key": "BP Sales Employee", "label": "BP Sales Employee", "numeric": False},
]


def get_detail_table_page(
    filtered_df: pd.DataFrame,
    page: int = 1,
    page_size: int = 50,
    sort_column: str = "Doc Date",
    sort_direction: str = "desc",
) -> dict[str, Any]:
    """Get sorted, paged detail table records (TB1–TB5)."""
    total_rows = len(filtered_df)
    if total_rows == 0:
        return {
            "columns": DETAIL_COLUMNS_CONFIG,
            "rows": [],
            "total_rows": 0,
            "page": 1,
            "page_size": page_size,
            "total_pages": 0,
            "range_label": "Rows 0 of 0",
        }

    ascending = (sort_direction.lower() == "asc")
    sort_col = sort_column

    if sort_col == "Doc Date":
        target_sort = "_doc_date_str" if "_doc_date_str" in filtered_df.columns else DOC_DATE_COL
    elif sort_col in filtered_df.columns:
        target_sort = sort_col
    else:
        target_sort = "_doc_date_str" if "_doc_date_str" in filtered_df.columns else DOC_DATE_COL

    sorted_df = filtered_df.sort_values(by=target_sort, ascending=ascending)

    total_pages = max(1, math.ceil(total_rows / page_size))
    current_page = max(1, min(page, total_pages))
    start_idx = (current_page - 1) * page_size
    end_idx = min(start_idx + page_size, total_rows)

    page_slice = sorted_df.iloc[start_idx:end_idx]

    rows = []
    for i, (_, row) in enumerate(page_slice.iterrows(), start=start_idx + 1):
        doc_date_disp = row.get("_doc_date_display") or str(row.get(DOC_DATE_COL, ""))[:10]
        qty_val = float(row.get(QTY_COL, 0.0))
        rev_val = float(row.get(REV_COL, 0.0))

        uom_val = str(row.get(UOM_COL, ""))
        if uom_val == "(Blank)":
            uom_val = ""

        rows.append({
            "index": i,
            "DocNum": row.get(DOC_NUM_COL, ""),
            "Document": str(row.get(DOC_COL, "")) or "",
            "Document Type": str(row.get(DOC_TYPE_COL, "")) or "",
            "Doc Date": doc_date_disp,
            "BP Name": str(row.get(BP_NAME_COL, "")) or "",
            "Item Code": str(row.get(ITEM_CODE_COL, "")) or "",
            "Quantity": f"{qty_val:,.2f}",
            "UoM": uom_val,
            "Row Total (After Doc Disc)": f"₹{rev_val:,.2f}",
            "Row Sales Employee": str(row.get(ROW_SALES_EMP_COL, "")) or "",
            "BP Sales Employee": str(row.get(BP_SALES_EMP_COL, "")) or "",
        })

    range_label = f"Rows {start_idx + 1}–{end_idx} of {total_rows:,}"

    return {
        "columns": DETAIL_COLUMNS_CONFIG,
        "rows": rows,
        "total_rows": total_rows,
        "page": current_page,
        "page_size": page_size,
        "total_pages": total_pages,
        "range_label": range_label,
    }


# ─── PRIMARY QUERY DISPATCHER ────────────────────────────────────────────────

async def query_sales_data(
    granularity: str = "Monthly",
    measure: str = "Revenue ₹",
    filters: dict[str, Any] | None = None,
    page: int = 1,
    page_size: int = 50,
    sort_column: str = "Doc Date",
    sort_direction: str = "desc",
    top_customers_limit: int = 50,
    intent: str = "all",  # "all" | "top_n" | "table"
) -> dict[str, Any]:
    """Execute in-memory query across all filters and aggregate components."""
    df = await data_store.get_dataframe()
    if df.empty:
        return {
            "status": "empty",
            "message": "Dataset not loaded.",
            "summary": calculate_summary_cards(df, granularity, measure),
            "facets": {},
            "main_chart": calculate_main_chart(df, granularity, measure),
            "breakdowns": calculate_breakdowns(df, measure, top_customers_limit),
            "table": get_detail_table_page(df, page, page_size, sort_column, sort_direction),
        }

    # 1. Compute active filtered DataFrame
    active_mask = _build_filter_mask(df, filters)
    filtered_df = df if active_mask is None else df[active_mask]

    # Fast path: Top N Customers update only (CH9)
    if intent == "top_n":
        breakdowns = calculate_breakdowns(filtered_df, measure, top_customers_limit)
        return {
            "status": "success",
            "top_customers": breakdowns.get("top_customers"),
        }

    # Fast path: Table paging or sorting only
    if intent == "table":
        table_page = get_detail_table_page(filtered_df, page, page_size, sort_column, sort_direction)
        return {
            "status": "success",
            "table": table_page,
        }

    # Full query
    summary = calculate_summary_cards(filtered_df, granularity, measure)

    if filtered_df.empty:
        facets = _compute_all_facets(df, filters)
        return {
            "status": "no_data",
            "message": "No data for selected filters",
            "summary": summary,
            "facets": facets,
            "main_chart": calculate_main_chart(filtered_df, granularity, measure),
            "breakdowns": {},
            "table": get_detail_table_page(filtered_df, page, page_size, sort_column, sort_direction),
        }

    main_chart = calculate_main_chart(filtered_df, granularity, measure)
    breakdowns = calculate_breakdowns(filtered_df, measure, top_customers_limit)
    table_page = get_detail_table_page(filtered_df, page, page_size, sort_column, sort_direction)
    facets = _compute_all_facets(df, filters)

    return {
        "status": "success",
        "summary": summary,
        "facets": facets,
        "main_chart": main_chart,
        "breakdowns": breakdowns,
        "table": table_page,
        "data_as_of": data_store.data_as_of_formatted,
        "database": data_store._database,
    }


def _compute_all_facets(df: pd.DataFrame, filters: dict[str, Any] | None) -> dict[str, Any]:
    """Compute 2-way cascading facets for all filter dropdowns (FT5, FT6, FT7)."""
    f_hash = _hash_filters(filters)
    cache_key = (id(df), f_hash)
    if cache_key in _facet_cache:
        return _facet_cache[cache_key]

    f_dict = filters or {}

    # Identify which filters are actually active
    active_keys = set()
    if f_dict.get("fromDate") or f_dict.get("toDate"):
        active_keys.add("dateRange")
    for k in FILTER_FIELD_MAP.keys():
        if f_dict.get(k):
            active_keys.add(k)
    item_attrs = f_dict.get("itemAttributes") or {}
    for attr_k in ITEM_ATTR_FIELD_MAP.keys():
        if item_attrs.get(attr_k):
            active_keys.add(f"attr_{attr_k}")

    # Compute base active mask ONCE for all non-active filters (massive optimization)
    base_mask = _build_filter_mask(df, f_dict) if active_keys else None

    # Compute excluded masks ONLY for filters that are currently active
    excluded_masks = {}
    for k in active_keys:
        if k.startswith("attr_"):
            attr_real_k = k[5:]
            excluded_masks[k] = _build_filter_mask(df, f_dict, exclude_key="itemAttributes", exclude_attr=attr_real_k)
        else:
            excluded_masks[k] = _build_filter_mask(df, f_dict, exclude_key=k)

    facets = {}

    # 1. Standard field filters
    for key, col in FILTER_FIELD_MAP.items():
        mask_to_use = excluded_masks.get(key, base_mask)
        selected_vals = f_dict.get(key)
        is_num = col in [YEAR_COL, MONTH_COL, WEEK_COL, DAY_COL]
        facets[key] = _get_distinct_options_with_counts(
            df, col, mask_to_use, selected_values=selected_vals, is_numeric=is_num
        )

    # 2. Item Attributes facets
    attr_facets = {}
    for attr_key, attr_col in ITEM_ATTR_FIELD_MAP.items():
        comp_key = f"attr_{attr_key}"
        mask_to_use = excluded_masks.get(comp_key, base_mask)
        selected_vals = item_attrs.get(attr_key)
        attr_facets[attr_key] = _get_distinct_options_with_counts(
            df, attr_col, mask_to_use, selected_values=selected_vals, is_numeric=False
        )
    facets["itemAttributes"] = attr_facets

    # 3. Valid date boundaries for Date Picker (FT8b)
    date_mask = excluded_masks.get("dateRange", base_mask)
    date_col_series = df["_doc_date_str"] if date_mask is None else df.loc[date_mask, "_doc_date_str"]
    date_active = date_col_series.dropna().unique()
    valid_dates = sorted([d for d in date_active if d and d != "(Blank)"])
    facets["activeDates"] = valid_dates
    facets["minDate"] = valid_dates[0] if valid_dates else "2023-04-01"
    facets["maxDate"] = valid_dates[-1] if valid_dates else str(date.today())

    _facet_cache[cache_key] = facets
    return facets


async def get_sales_initial_summary() -> dict[str, Any]:
    """Summary metrics and sample data for the initial page load."""
    df = await data_store.get_dataframe()
    if df.empty:
        return {
            "record_count": 0,
            "total_revenue": 0.0,
            "total_revenue_formatted": "₹0.00",
            "total_revenue_compact": "₹0.00",
            "total_gross_profit": 0.0,
            "total_gross_profit_formatted": "₹0.00",
            "margin_pct_formatted": "–",
            "data_as_of_formatted": "--",
            "database": settings.api_database,
            "error": None,
        }

    total_revenue = float(df[REV_COL].sum())
    total_gp = float(df[GP_COL].sum())
    margin = round((total_gp / total_revenue) * 100.0, 1) if total_revenue != 0 else 0.0

    return {
        "record_count": len(df),
        "total_revenue": total_revenue,
        "total_revenue_formatted": format_indian_currency(total_revenue, compact=False),
        "total_revenue_compact": format_indian_currency(total_revenue, compact=True),
        "total_gross_profit": total_gp,
        "total_gross_profit_formatted": format_indian_currency(total_gp, compact=False),
        "margin_pct_formatted": f"{margin:.1f}%" if total_revenue != 0 else "–",
        "data_as_of_formatted": data_store.data_as_of_formatted,
        "database": data_store._database,
        "error": None,
    }
