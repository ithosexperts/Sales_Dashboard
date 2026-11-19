"""
Testing Checklist B – Design Requirements Verification.
Validates all requirement IDs from section 12 of the functional specification.
"""
import pytest
import pandas as pd
from datetime import datetime

from app.services.sales_service import (
    calculate_summary_cards,
    calculate_main_chart,
    calculate_breakdowns,
    get_detail_table_page,
    _build_filter_mask,
    _get_distinct_options_with_counts,
    SalesDataStore,
    DETAIL_COLUMNS_CONFIG,
    BREAKDOWN_SPECS,
    REV_COL, GP_COL, QTY_COL, DOC_COL, YEAR_COL, MONTH_COL
)


@pytest.fixture
def base_df():
    records = [
        {
            "Document": "A/R Invoice", "DocEntry": 1, "LineNum": 0, "DocNum": 101,
            "Document Type": "Item", "Doc Date": "2026-05-10", "_doc_date_str": "2026-05-10",
            "_doc_date_display": "10-May-2026", "BP Code": "BP01", "BP Name": "Customer A",
            "Group": "Group 1", "Industry": "Engineering", "BP Project": "Project Alpha",
            "City": "Noida", "State": "UP", "Country": "IN", "Region": "North Zone",
            "Sales Type": "Credit", "Sales From Location": "Noida",
            "Item Code": "ITM01", "Item Name": "Hose Type 1", "Quantity": 100.0, "UoM": "MTR",
            "Brand": "HoseX", "MOC": "Steel", "Made To Order": "No",
            "Item Group": "01 - Hoses", "Sub Group 1": "Hydraulic", "Sub Group 2": "High Pressure",
            "Row Total (After Doc Disc)": 200000.0, "Gross Profit": 50000.0,
            "Row Sales Employee": "John", "BP Sales Employee": "Jane",
            "Year": 2026, "Month": 5, "Week": 19, "Day": 1,
            "Hose Fittings Type": "Flange"
        },
        {
            "Document": "A/R Invoice", "DocEntry": 2, "LineNum": 0, "DocNum": 102,
            "Document Type": "Item", "Doc Date": "2026-06-15", "_doc_date_str": "2026-06-15",
            "_doc_date_display": "15-Jun-2026", "BP Code": "BP02", "BP Name": "Customer B",
            "Group": "Group 2", "Industry": "Textile", "BP Project": "Project Beta",
            "City": "Mumbai", "State": "MH", "Country": "IN", "Region": "West Zone",
            "Sales Type": "Advance", "Sales From Location": "Delhi",
            "Item Code": "ITM02", "Item Name": "Fitting SS", "Quantity": 200.0, "UoM": "NOS",
            "Brand": "FitPro", "MOC": "SS", "Made To Order": "Yes",
            "Item Group": "02 - Fittings", "Sub Group 1": "Couplings", "Sub Group 2": "Standard",
            "Row Total (After Doc Disc)": 300000.0, "Gross Profit": -10000.0, # Loss-making line (LM6)
            "Row Sales Employee": "Alice", "BP Sales Employee": "Jane",
            "Year": 2026, "Month": 6, "Week": 24, "Day": 2,
            "Hose Fittings Type": "NA"
        },
        {
            "Document": "A/R Credit Memo", "DocEntry": 3, "LineNum": 0, "DocNum": 201,
            "Document Type": "Item", "Doc Date": "2026-06-20", "_doc_date_str": "2026-06-20",
            "_doc_date_display": "20-Jun-2026", "BP Code": "BP01", "BP Name": "Customer A",
            "Group": "Group 1", "Industry": "Engineering", "BP Project": "Project Alpha",
            "City": "Noida", "State": "UP", "Country": "IN", "Region": "North Zone",
            "Sales Type": "Credit", "Sales From Location": "Noida",
            "Item Code": "ITM01", "Item Name": "Hose Type 1", "Quantity": -10.0, "UoM": "MTR",
            "Brand": "HoseX", "MOC": "Steel", "Made To Order": "No",
            "Item Group": "01 - Hoses", "Sub Group 1": "Hydraulic", "Sub Group 2": "High Pressure",
            "Row Total (After Doc Disc)": -20000.0, "Gross Profit": -5000.0,
            "Row Sales Employee": "John", "BP Sales Employee": "Jane",
            "Year": 2026, "Month": 6, "Week": 25, "Day": 7,
            "Hose Fittings Type": "Flange"
        }
    ]
    df = pd.DataFrame(records)
    df[REV_COL] = df[REV_COL].astype(float)
    df[GP_COL] = df[GP_COL].astype(float)
    df[QTY_COL] = df[QTY_COL].astype(float)
    return df


def test_ds3_revenue_inr_credit_memos_negative(base_df):
    """DS3: Revenue is in INR and credit memos are negative."""
    cm = base_df[base_df[DOC_COL] == "A/R Credit Memo"]
    assert (cm[REV_COL] < 0).all()
    assert (cm[GP_COL] < 0).all()


def test_fl1_fl2_granularity_defaults(base_df):
    """FL1 & FL2: Default granularity is Monthly and Revenue ₹."""
    chart = calculate_main_chart(base_df, granularity="Monthly", measure="Revenue ₹")
    assert chart["granularity"] == "Monthly"
    assert chart["measure"] == "Revenue ₹"
    assert "May-2026" in chart["categories"]
    assert "Jun-2026" in chart["categories"]


def test_hd4_hd6_summary_cards(base_df):
    """HD4 & HD6: Summary cards and title is 'Granularity'."""
    cards = calculate_summary_cards(base_df, granularity="Monthly", measure="Revenue ₹")
    assert cards["filtered_rows"] == 3
    # Net Rev = 200000 + 300000 - 20000 = 480000 -> 4.80 L
    assert "4.80 Lakh" in cards["filtered_revenue_compact"]
    # Net GP = 50000 - 10000 - 5000 = 35000
    assert cards["filtered_gross_profit_exact"] == 35000.0
    # Margin % = 35000 / 480000 * 100 = 7.29% -> 7.3%
    assert cards["margin_pct"] == 7.3
    assert cards["granularity_label"] == "Monthly • Revenue"


def test_ft3_ft4_combined_filters(base_df):
    """FT3 & FT4: AND across filters, OR within filter, multi-select."""
    # Filter Region IN ('North Zone') AND Brand IN ('HoseX', 'FitPro')
    filters = {
        "region": ["North Zone"],
        "brand": ["HoseX", "FitPro"]
    }
    mask = _build_filter_mask(base_df, filters)
    filtered = base_df[mask]
    # Rows 1 and 3 match (North Zone, HoseX). Row 2 is West Zone so excluded.
    assert len(filtered) == 2
    assert set(filtered["DocNum"].tolist()) == {101, 201}


def test_ft5_cascading_and_stale(base_df):
    """FT5 & FT7: Faceted cascading and stale detection."""
    # Active mask where Brand = 'FitPro' (Row 2 only)
    mask = _build_filter_mask(base_df, {"brand": ["FitPro"]})
    # Compute Item Group options
    opts = _get_distinct_options_with_counts(base_df, "Item Group", mask, selected_values=["01 - Hoses"])
    opt_map = {o["value"]: o for o in opts}

    # '02 - Fittings' has count 1
    assert opt_map["02 - Fittings"]["count"] == 1
    # '01 - Hoses' was selected but has count 0 under Brand='FitPro', so stale=True (FT7)
    assert opt_map["01 - Hoses"]["count"] == 0
    assert opt_map["01 - Hoses"]["stale"] is True


def test_ch4_exact_15_breakdown_charts(base_df):
    """CH4: Exactly 15 breakdown charts in specified order."""
    breakdowns = calculate_breakdowns(base_df, measure="Revenue ₹")
    assert len(breakdowns) == 15
    expected_ids = [s["id"] for s in BREAKDOWN_SPECS]
    assert list(breakdowns.keys()) == expected_ids


def test_ch6_horizontal_sorted_negatives(base_df):
    """CH6: Horizontal bars sorted largest to smallest, negatives below positives in GP mode."""
    b = calculate_breakdowns(base_df, measure="Gross Profit ₹")
    # In Brand breakdown: HoseX has GP 50000 - 5000 = 45000. FitPro has GP -10000.
    brand_chart = b["brand"]
    cats = brand_chart["categories"]
    vals = brand_chart["series"][0]["data"]
    assert cats == ["HoseX", "FitPro"]
    assert vals == [45000.0, -10000.0]


def test_tb3_tb4_detail_table(base_df):
    """TB3 & TB4: 12 columns in exact order, no Gross Profit, default sort Doc Date desc."""
    tbl = get_detail_table_page(base_df, page=1, page_size=50, sort_column="Doc Date", sort_direction="desc")
    assert len(tbl["columns"]) == 12
    col_labels = [c["label"] for c in tbl["columns"]]
    expected_labels = [
        "#", "DocNum", "Document", "Document Type", "Doc Date",
        "BP Name", "Item Code", "Quantity", "UoM",
        "Row Total (After Doc Disc)", "Row Sales Employee", "BP Sales Employee"
    ]
    assert col_labels == expected_labels
    assert "Gross Profit" not in col_labels

    # Sort check: 2026-06-20 (DocNum 201) newest, then 2026-06-15 (DocNum 102), then 2026-05-10 (DocNum 101)
    doc_nums = [r["DocNum"] for r in tbl["rows"]]
    assert doc_nums == [201, 102, 101]
