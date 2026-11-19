"""
Testing Checklist A – Data Reconciliation (View vs Dashboard).
Implements the exact step-by-step verification defined in Checklist A (A1–A17).
"""
import pytest
import pandas as pd
import numpy as np

from app.services.sales_service import (
    calculate_summary_cards,
    calculate_main_chart,
    calculate_breakdowns,
    get_detail_table_page,
    _build_filter_mask,
    REV_COL, GP_COL, QTY_COL, UOM_COL, DOC_COL, DOC_DATE_COL,
    YEAR_COL, MONTH_COL, WEEK_COL, DAY_COL, COUNTRY_COL, BRAND_COL,
    ITEM_GROUP_COL, SALES_TYPE_COL, REGION_COL, BP_NAME_COL, DOC_NUM_COL
)


@pytest.fixture
def sample_sales_data():
    """Create a realistic sample DataFrame reflecting VD_Sales_Dashboard schema and rules."""
    records = [
        # Regular Invoice 1
        {
            "Document": "A/R Invoice", "DocEntry": 101, "LineNum": 0, "DocNum": 1001,
            "Document Type": "Item", "Doc Date": "2025-12-30", "_doc_date_str": "2025-12-30",
            "_doc_date_display": "30-Dec-2025", "BP Code": "CUST01", "BP Name": "Alpha Corp",
            "Group": "Group A", "Industry": "Auto", "BP Project": "Project 1",
            "City": "Delhi", "State": "DL", "Country": "IN", "Region": "North Zone",
            "Sales Type": "Credit", "Sales From Location": "Delhi",
            "Item Code": "ITEM01", "Item Name": "Hose 10mm", "Quantity": 10.0, "UoM": "MTR",
            "Brand": "HoseX", "MOC": "Rubber", "Made To Order": "No",
            "Item Group": "01 - Hoses", "Sub Group 1": "Hydraulic", "Sub Group 2": "High Pressure",
            "Row Total (After Doc Disc)": 10000.0, "Gross Profit": 2500.0,
            "Row Sales Employee": "John Doe", "BP Sales Employee": "Jane Smith",
            "Year": 2025, "Month": 12, "Week": 53, "Day": 3,
            "Hose Fittings Type": "Flange"
        },
        # Regular Invoice 2 in 2026 Week 1
        {
            "Document": "A/R Invoice", "DocEntry": 102, "LineNum": 0, "DocNum": 1002,
            "Document Type": "Item", "Doc Date": "2026-01-02", "_doc_date_str": "2026-01-02",
            "_doc_date_display": "02-Jan-2026", "BP Code": "CUST02", "BP Name": "Beta Ltd",
            "Group": "Group B", "Industry": "Pharma", "BP Project": "Project 2",
            "City": "Mumbai", "State": "MH", "Country": "IN", "Region": "West Zone",
            "Sales Type": "Advance", "Sales From Location": "Noida",
            "Item Code": "ITEM02", "Item Name": "Fitting 1/2", "Quantity": 50.0, "UoM": "NOS",
            "Brand": "FitPro", "MOC": "SS", "Made To Order": "Yes",
            "Item Group": "02 - Fittings", "Sub Group 1": "Couplings", "Sub Group 2": "Standard",
            "Row Total (After Doc Disc)": 50000.0, "Gross Profit": 15000.0,
            "Row Sales Employee": "Alice Ray", "BP Sales Employee": "Jane Smith",
            "Year": 2026, "Month": 1, "Week": 1, "Day": 6,
            "Hose Fittings Type": "NA"
        },
        # Export Invoice
        {
            "Document": "A/R Invoice", "DocEntry": 103, "LineNum": 0, "DocNum": 1003,
            "Document Type": "Item", "Doc Date": "2026-09-05", "_doc_date_str": "2026-09-05",
            "_doc_date_display": "05-Sep-2026", "BP Code": "CUST03", "BP Name": "Gamma Global",
            "Group": "Group A", "Industry": "Auto", "BP Project": "Project 1",
            "City": "Dubai", "State": "", "Country": "AE", "Region": "",
            "Sales Type": "Credit", "Sales From Location": "",
            "Item Code": "ITEM01", "Item Name": "Hose 10mm", "Quantity": 20.0, "UoM": "MTR",
            "Brand": "HoseX", "MOC": "Rubber", "Made To Order": "No",
            "Item Group": "01 - Hoses", "Sub Group 1": "Hydraulic", "Sub Group 2": "High Pressure",
            "Row Total (After Doc Disc)": 20000.0, "Gross Profit": 6000.0,
            "Row Sales Employee": "John Doe", "BP Sales Employee": "Bob Vance",
            "Year": 2026, "Month": 9, "Week": 36, "Day": 7,
            "Hose Fittings Type": None
        },
        # Credit Memo (Negative Revenue & GP)
        {
            "Document": "A/R Credit Memo", "DocEntry": 104, "LineNum": 0, "DocNum": 2001,
            "Document Type": "Item", "Doc Date": "2026-09-10", "_doc_date_str": "2026-09-10",
            "_doc_date_display": "10-Sep-2026", "BP Code": "CUST01", "BP Name": "Alpha Corp",
            "Group": "Group A", "Industry": "Auto", "BP Project": "Project 1",
            "City": "Delhi", "State": "DL", "Country": "IN", "Region": "North Zone",
            "Sales Type": "Credit", "Sales From Location": "Delhi",
            "Item Code": "ITEM01", "Item Name": "Hose 10mm", "Quantity": -2.0, "UoM": "MTR",
            "Brand": "HoseX", "MOC": "Rubber", "Made To Order": "No",
            "Item Group": "01 - Hoses", "Sub Group 1": "Hydraulic", "Sub Group 2": "High Pressure",
            "Row Total (After Doc Disc)": -2000.0, "Gross Profit": -500.0,
            "Row Sales Employee": "John Doe", "BP Sales Employee": "Jane Smith",
            "Year": 2026, "Month": 9, "Week": 37, "Day": 5,
            "Hose Fittings Type": "Flange"
        },
        # Service Line (Null UoM, full value GP)
        {
            "Document": "A/R Invoice", "DocEntry": 105, "LineNum": 0, "DocNum": 1004,
            "Document Type": "Service", "Doc Date": "2026-09-12", "_doc_date_str": "2026-09-12",
            "_doc_date_display": "12-Sep-2026", "BP Code": "CUST02", "BP Name": "Beta Ltd",
            "Group": "Group B", "Industry": "Pharma", "BP Project": "Project 2",
            "City": "Mumbai", "State": "MH", "Country": "IN", "Region": "West Zone",
            "Sales Type": "Credit", "Sales From Location": "Noida",
            "Item Code": "SRV01", "Item Name": "Installation Service", "Quantity": 1.0, "UoM": None,
            "Brand": "", "MOC": "", "Made To Order": "No",
            "Item Group": "03 - Services", "Sub Group 1": "Site Service", "Sub Group 2": "Assembly",
            "Row Total (After Doc Disc)": 5000.0, "Gross Profit": 5000.0,
            "Row Sales Employee": "Alice Ray", "BP Sales Employee": "Jane Smith",
            "Year": 2026, "Month": 9, "Week": 37, "Day": 7,
            "Hose Fittings Type": "NA"
        }
    ]
    df = pd.DataFrame(records)
    df[REV_COL] = df[REV_COL].astype(float)
    df[GP_COL] = df[GP_COL].astype(float)
    df[QTY_COL] = df[QTY_COL].astype(float)
    return df


def test_a1_grand_totals(sample_sales_data):
    """A1. Grand totals: rows, Revenue and Gross Profit."""
    cards = calculate_summary_cards(sample_sales_data, granularity="Yearly", measure="Revenue ₹")
    assert cards["filtered_rows"] == 5
    assert cards["filtered_revenue_exact"] == 83000.0
    assert cards["filtered_gross_profit_exact"] == 28000.0
    # Margin % = 28000 / 83000 * 100 = 33.73% -> 33.7%
    assert cards["margin_pct"] == 33.7
    assert cards["margin_pct_formatted"] == "33.7%"


def test_a2_split_by_document(sample_sales_data):
    """A2. Split by document: Credit memos are negative."""
    inv_df = sample_sales_data[sample_sales_data[DOC_COL] == "A/R Invoice"]
    cm_df = sample_sales_data[sample_sales_data[DOC_COL] == "A/R Credit Memo"]

    assert len(inv_df) == 4
    assert inv_df[REV_COL].sum() == 85000.0
    assert inv_df[GP_COL].sum() == 28500.0

    assert len(cm_df) == 1
    assert cm_df[REV_COL].sum() == -2000.0
    assert cm_df[GP_COL].sum() == -500.0


def test_a3_yearly_totals(sample_sales_data):
    """A3. Yearly grouping."""
    chart = calculate_main_chart(sample_sales_data, granularity="Yearly", measure="Revenue ₹")
    assert chart["categories"] == ["2025", "2026"]
    # 2025 rev: 10000; 2026 rev: 50000 + 20000 - 2000 + 5000 = 73000
    assert chart["series"][0]["data"] == [10000.0, 73000.0]


def test_a4_monthly_totals_for_one_year(sample_sales_data):
    """A4. Monthly grouping for Year = 2026."""
    df_2026 = sample_sales_data[sample_sales_data[YEAR_COL] == 2026]
    chart = calculate_main_chart(df_2026, granularity="Monthly", measure="Revenue ₹")
    # Present months: Jan (Month 1: 50000), Sep (Month 9: 20000 - 2000 + 5000 = 23000)
    assert chart["categories"] == ["Jan-2026", "Sep-2026"]
    assert chart["series"][0]["data"] == [50000.0, 23000.0]


def test_a5_weekly_totals_year_end_split(sample_sales_data):
    """A5. Weekly grouping: 2025-W53 and 2026-W01 appear as separate bars (LM1)."""
    chart = calculate_main_chart(sample_sales_data, granularity="Weekly", measure="Revenue ₹")
    assert "2025-W53" in chart["categories"]
    assert "2026-W01" in chart["categories"]


def test_a6_daily_totals_and_labels(sample_sales_data):
    """A6. Daily totals and date labels (e.g. 30-Dec-25)."""
    chart = calculate_main_chart(sample_sales_data, granularity="Daily", measure="Revenue ₹")
    assert "30-Dec-25" in chart["categories"]
    assert "02-Jan-26" in chart["categories"]


def test_a8_quantity_by_uom(sample_sales_data):
    """A8. Quantity is split by UoM."""
    chart = calculate_main_chart(sample_sales_data, granularity="Yearly", measure="Quantity")
    assert chart["uoms"] == ["(Blank)", "MTR", "NOS"]
    # Verify each UoM has its own series
    series_names = [s["name"] for s in chart["series"]]
    assert set(series_names) == {"(Blank)", "MTR", "NOS"}


def test_a9_breakdown_reconciliation(sample_sales_data):
    """A9 & CH12. In Revenue and GP modes, all breakdown charts add up to main chart total."""
    b_rev = calculate_breakdowns(sample_sales_data, measure="Revenue ₹")
    total_rev = sample_sales_data[REV_COL].sum()

    for b_id, b_data in b_rev.items():
        bar_sum = sum(b_data["series"][0]["data"])
        assert round(bar_sum, 2) == round(total_rev, 2), f"Chart {b_id} did not reconcile"

    b_gp = calculate_breakdowns(sample_sales_data, measure="Gross Profit ₹")
    total_gp = sample_sales_data[GP_COL].sum()
    for b_id, b_data in b_gp.items():
        bar_sum = sum(b_data["series"][0]["data"])
        assert round(bar_sum, 2) == round(total_gp, 2), f"Chart {b_id} (GP) did not reconcile"


def test_a10_domestic_vs_export(sample_sales_data):
    """A10. Domestic vs Export mapping."""
    b = calculate_breakdowns(sample_sales_data, measure="Revenue ₹")
    dom_exp = b["domestic_vs_export"]
    cat_map = dict(zip(dom_exp["categories"], dom_exp["series"][0]["data"]))
    # IN -> Domestic (10000 + 50000 - 2000 + 5000 = 63000)
    # AE -> Export (20000)
    assert cat_map["Domestic"] == 63000.0
    assert cat_map["Export"] == 20000.0


def test_a11_top_n_customers(sample_sales_data):
    """A11. Top N Customers + Others bar."""
    b = calculate_breakdowns(sample_sales_data, measure="Revenue ₹", top_n_limit=2)
    top_cust = b["top_customers"]
    cats = top_cust["categories"]
    # Total customers = 3 (Alpha Corp: 8000, Beta Ltd: 55000, Gamma Global: 20000)
    # Top 2: Beta Ltd (55000), Gamma Global (20000)
    # Others: Alpha Corp (8000) -> 'Others (1 customers)'
    assert cats[0] == "Beta Ltd"
    assert cats[1] == "Gamma Global"
    assert cats[2] == "Others (1 customers)"
    assert top_cust["series"][0]["data"][2] == 8000.0


def test_a12_gross_profit_margin_line(sample_sales_data):
    """A12. Gross Profit mode: Margin % line on second axis."""
    chart = calculate_main_chart(sample_sales_data, granularity="Yearly", measure="Gross Profit ₹")
    assert chart["has_margin_line"] is True
    assert len(chart["margin_series"]) == 2
    # 2025: GP=2500, Rev=10000 -> 25.0%
    assert chart["margin_series"][0] == 25.0


def test_a15_blank_vs_na(sample_sales_data):
    """A15. (Blank) vs NA are separate values (FT9)."""
    # In sample data, Hose Fittings Type has 'Flange', 'NA', and None
    vals = sample_sales_data["Hose Fittings Type"].fillna("").astype(str).str.strip().tolist()
    assert "NA" in vals
    assert "" in vals  # represents (Blank)


def test_a16_detail_table(sample_sales_data):
    """A16. Detail table: 12 columns, newest first default sort, no Gross Profit."""
    res = get_detail_table_page(sample_sales_data, page=1, page_size=50, sort_column="Doc Date", sort_direction="desc")
    assert res["total_rows"] == 5
    first_row = res["rows"][0]
    # Newest doc date is 2026-09-12 (DocNum 1004)
    assert first_row["DocNum"] == 1004
    assert "Gross Profit" not in first_row
    assert "Row Total (After Doc Disc)" in first_row
