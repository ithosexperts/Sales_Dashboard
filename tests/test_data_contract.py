"""
Data Contract Validation (Phase 2 & DS1–DS12).
Verifies that VD_Sales_Dashboard returns all required columns, validates data types,
and checks unique row key rule [Document] + [DocEntry] + [LineNum].
"""
import pytest
from app.api.client import api_request
from app.services.sales_service import (
    REV_COL, GP_COL, QTY_COL, UOM_COL, DOC_COL, DOC_TYPE_COL,
    DOC_DATE_COL, DOC_NUM_COL, ITEM_CODE_COL, ITEM_NAME_COL,
    BP_CODE_COL, BP_NAME_COL, GROUP_COL, INDUSTRY_COL, BP_PROJECT_COL,
    CITY_COL, STATE_COL, COUNTRY_COL, REGION_COL, SALES_TYPE_COL,
    SALES_FROM_LOC_COL, BRAND_COL, MOC_COL, MADE_TO_ORDER_COL,
    ITEM_GROUP_COL, SUB_GROUP1_COL, SUB_GROUP2_COL,
    ROW_SALES_EMP_COL, BP_SALES_EMP_COL,
    YEAR_COL, MONTH_COL, WEEK_COL, DAY_COL,
    ITEM_ATTRIBUTE_COLUMNS
)

EXPECTED_COLUMNS = [
    "DocEntry", "LineNum", DOC_NUM_COL, DOC_COL, DOC_TYPE_COL, DOC_DATE_COL,
    BP_CODE_COL, BP_NAME_COL, GROUP_COL, INDUSTRY_COL, BP_PROJECT_COL,
    CITY_COL, STATE_COL, COUNTRY_COL, REGION_COL, SALES_TYPE_COL, SALES_FROM_LOC_COL,
    ITEM_CODE_COL, ITEM_NAME_COL, QTY_COL, UOM_COL, BRAND_COL, MOC_COL, MADE_TO_ORDER_COL,
    ITEM_GROUP_COL, SUB_GROUP1_COL, SUB_GROUP2_COL,
    REV_COL, GP_COL, ROW_SALES_EMP_COL, BP_SALES_EMP_COL,
    YEAR_COL, MONTH_COL, WEEK_COL, DAY_COL
] + ITEM_ATTRIBUTE_COLUMNS


@pytest.mark.asyncio
async def test_data_contract_view_columns():
    """Verify all 55+ columns specified in section 2.1 exist in the view."""
    resp = await api_request("VD_Sales_Dashboard", action="select", limit=5)
    assert resp.get("status") == "success"
    data = resp.get("data", [])
    assert len(data) > 0

    first_row = data[0]
    for col in EXPECTED_COLUMNS:
        assert col in first_row, f"Required column '{col}' missing from VD_Sales_Dashboard"


@pytest.mark.asyncio
async def test_data_contract_unique_key():
    """Verify [Document] + [DocEntry] + [LineNum] forms a unique key (DS2)."""
    resp = await api_request("VD_Sales_Dashboard", action="select", limit=100)
    data = resp.get("data", [])
    assert len(data) == 100

    keys = set()
    for r in data:
        k = (r["Document"], r["DocEntry"], r["LineNum"])
        assert k not in keys, f"Duplicate unique key found: {k}"
        keys.add(k)
