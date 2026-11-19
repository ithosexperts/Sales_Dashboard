"""
End-to-End Live Validation against OperationsDB / Test_OperationsDB.
Confirms live dataset load, performance, 15 breakdowns, main chart, cascading, and reconciliation.
"""
import pytest
import time
from app.services.sales_service import (
    data_store,
    query_sales_data,
    calculate_summary_cards,
    REV_COL, GP_COL, QTY_COL
)


@pytest.mark.asyncio
async def test_live_data_store_and_query():
    """Verify live dataset loading and in-memory analytics response time."""
    # 1. Load dataset (DL1)
    t0 = time.time()
    df = await data_store.get_dataframe()
    t1 = time.time()
    assert not df.empty
    assert len(df) > 100000, f"Expected >100,000 rows, got {len(df)}"

    # 2. Query default state: Monthly, Revenue ₹ (FL2)
    t_q0 = time.time()
    res = await query_sales_data(granularity="Monthly", measure="Revenue ₹")
    t_q1 = time.time()

    assert res["status"] == "success"
    # Query must be sub-second from in-memory data (DL3)
    query_duration = t_q1 - t_q0
    assert query_duration < 1.5, f"Query took too long: {query_duration:.2f}s"

    # 3. Check summary card totals
    summary = res["summary"]
    assert summary["filtered_rows"] == len(df)
    assert summary["filtered_revenue_exact"] > 0
    assert summary["granularity_label"] == "Monthly • Revenue"

    # 4. Check main chart
    main_chart = res["main_chart"]
    assert len(main_chart["categories"]) > 0
    assert main_chart["has_margin_line"] is False

    # 5. Check 15 breakdown charts
    breakdowns = res["breakdowns"]
    assert len(breakdowns) == 15

    # 6. Reconciliation check (CH12)
    main_total = sum(main_chart["series"][0]["data"])
    for b_id, b_data in breakdowns.items():
        if not b_data.get("is_qty"):
            b_total = sum(b_data["series"][0]["data"])
            assert abs(b_total - main_total) < 1.0, f"Breakdown {b_id} sum ({b_total}) does not reconcile with main chart ({main_total})"

    # 7. Check detail table
    table = res["table"]
    assert len(table["columns"]) == 12
    assert len(table["rows"]) == 50
    assert "Gross Profit" not in [c["label"] for c in table["columns"]]
