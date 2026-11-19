"""
Dashboard router – Sales Dashboard landing page and JSON APIs.
"""
from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, Body, Query, Request, Response
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.sales_service import (
    data_store,
    get_sales_initial_summary,
    query_sales_data,
)
from app.templates_config import templates

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sales_dashboard"])


@router.get("/")
@router.get("/sales")
@router.head("/")
@router.head("/sales")
async def index(request: Request):
    """Render the main Sales Dashboard landing page."""
    if request.method == "HEAD":
        return Response(status_code=200, media_type="text/html")

    if data_store.is_loaded:
        try:
            summary = await get_sales_initial_summary()
        except Exception as exc:
            logger.warning("Error getting sales summary on index: %s", exc)
            summary = {
                "record_count": 0,
                "total_revenue": 0.0,
                "total_revenue_formatted": "₹0.00",
                "total_revenue_compact": "₹0.00",
                "total_gross_profit": 0.0,
                "total_gross_profit_formatted": "₹0.00",
                "margin_pct_formatted": "–",
                "data_as_of_formatted": "--",
                "database": settings.api_database,
                "error": str(exc),
            }
    else:
        summary = {
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

    return templates.TemplateResponse(
        request,
        "sales/index.html",
        {
            "user": None,
            "record_count": summary["record_count"],
            "total_revenue": summary["total_revenue"],
            "total_revenue_formatted": summary["total_revenue_formatted"],
            "total_revenue_compact": summary.get("total_revenue_compact", "₹0.00"),
            "total_gross_profit": summary["total_gross_profit"],
            "total_gross_profit_formatted": summary["total_gross_profit_formatted"],
            "margin_pct_formatted": summary["margin_pct_formatted"],
            "data_as_of": f"Data as of {summary['data_as_of_formatted']}" if (summary.get("data_as_of_formatted") and summary["data_as_of_formatted"] != "--") else "Data as of --",
            "database": summary["database"],
            "error": summary["error"],
        },
    )


@router.get("/api/sales/summary")
async def sales_summary_api(request: Request):
    """JSON API endpoint returning real-time sales summary metrics."""
    summary = await get_sales_initial_summary()
    return JSONResponse(summary)


@router.get("/api/sales/dataset")
async def sales_dataset_api(
    request: Request,
    refresh: bool = Query(False, description="Force refresh from upstream API"),
):
    """
    Check or trigger in-memory dataset load (Rules DL1–DL4).
    Non-blocking: returns status immediately.
    """
    if refresh:
        data_store.start_background_load(force_refresh=True)
        return JSONResponse({
            "status": "loading",
            "progress": "Refreshing sales dataset from OperationsDB...",
            "record_count": 0,
            "data_as_of": "",
            "data_as_of_formatted": "--",
            "database": settings.api_database,
        })

    if data_store.is_loading:
        return JSONResponse({
            "status": "loading",
            "progress": data_store.load_progress,
            "record_count": data_store.loaded_so_far,
            "data_as_of": "",
            "data_as_of_formatted": "--",
            "database": settings.api_database,
        })

    if data_store.load_error:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": data_store.load_error,
                "record_count": 0,
                "data_as_of": "",
                "data_as_of_formatted": "--",
                "database": settings.api_database,
            },
        )

    if data_store.is_loaded:
        return JSONResponse({
            "status": "success",
            "record_count": data_store.total_records,
            "data_as_of": data_store.data_as_of.isoformat() if data_store.data_as_of else "",
            "data_as_of_formatted": data_store.data_as_of_formatted,
            "database": data_store._database,
        })

    data_store.start_background_load(force_refresh=False)
    return JSONResponse({
        "status": "loading",
        "progress": data_store.load_progress,
        "record_count": data_store.loaded_so_far,
        "data_as_of": "",
        "data_as_of_formatted": "--",
        "database": settings.api_database,
    })


@router.post("/api/sales/query")
async def sales_query_api(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    """
    Query the in-memory dataset with active filters, granularity and measure.
    Returns:
    - Summary 4 KPI cards (HD4, HD5, HD6)
    - 2-way cascading filter options with row counts (FT5, FT6, FT7)
    - Main chart period bars (CH1, CH2, CH3, FL4, FL5, FL6)
    - 15 horizontal breakdown charts (CH4–CH13)
    - 12-column detail table page (TB1–TB5)
    """
    if not data_store.is_loaded:
        return JSONResponse(
            status_code=503,
            content={"status": "loading", "message": "Dataset is currently loading."},
        )

    granularity = payload.get("granularity", "Monthly")
    measure = payload.get("measure", "Revenue ₹")
    filters = payload.get("filters", {})
    page = int(payload.get("page", 1))
    page_size = int(payload.get("page_size", 50))
    sort_column = payload.get("sort_column", "Doc Date")
    sort_direction = payload.get("sort_direction", "desc")
    intent = payload.get("intent", "all")
    top_customers_limit = int(payload.get("top_customers_limit", 50))

    result = await query_sales_data(
        granularity=granularity,
        measure=measure,
        filters=filters,
        page=page,
        page_size=page_size,
        sort_column=sort_column,
        sort_direction=sort_direction,
        top_customers_limit=top_customers_limit,
        intent=intent,
    )

    return JSONResponse(result)
