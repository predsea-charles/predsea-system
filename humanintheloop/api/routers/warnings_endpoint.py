from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Query

from api.schemas import WarningsResponse, WarningItem
from api.warnings_service import build_warnings_response


router = APIRouter(tags=["warnings"])

# In-memory cache for pre-calculated active warnings pushed by the anomaly checker
_PUSHED_WARNINGS: list[WarningItem] = []


@router.post(
    "/warnings/active",
    response_model=dict,
    summary="Register pre-calculated active anomaly or official warnings",
    description="Allows ingestion pipelines or scripts to push pre-calculated active warning items directly to the API.",
)
def post_warnings_active_endpoint(
    warnings: list[WarningItem],
):
    global _PUSHED_WARNINGS
    _PUSHED_WARNINGS = list(warnings)
    return {
        "status": "success",
        "count": len(_PUSHED_WARNINGS),
        "message": f"Successfully registered {len(_PUSHED_WARNINGS)} active warnings.",
    }


@router.get(
    "/warnings/active",
    response_model=WarningsResponse,
    summary="Operational warnings from official alerts and anomaly detection",
    description=(
        "Combine AEMET official CAP alerts with PredSea anomaly warnings "
        "computed from the latest evidence rows and climatology baseline."
    ),
)
def warnings_active_endpoint(
    route: str | None = Query(default=None, description="Optional route id, e.g. ibiza_palma"),
    place: str | None = Query(default=None, description="Optional place id, e.g. palma"),
    date: str | None = Query(default=None, description="Optional ISO date YYYY-MM-DD"),
    z_threshold: float = Query(default=1.5, ge=0.0),
    lookback_hours: int = Query(default=240, ge=1),
    min_window_hours: int = Query(default=240, ge=1),
    min_sample_count: int = Query(default=10, ge=1),
    include_aemet: bool = Query(default=True),
    include_anomaly: bool = Query(default=True),
):
    global _PUSHED_WARNINGS
    if _PUSHED_WARNINGS:
        warnings_list = list(_PUSHED_WARNINGS)
        
        # Filter warnings by route or place if requested
        if route or place:
            from api.warnings_service import build_scope_terms
            terms = [t.lower() for t in build_scope_terms(route=route, place=place)]
            filtered_warnings = []
            for w in warnings_list:
                # Check route match
                if route and w.route and w.route.lower() == route.lower():
                    filtered_warnings.append(w)
                    continue
                # Check terms overlap
                w_text = f"{w.station_id or ''} {w.station_name or ''} {w.label or ''} {w.description or ''}".lower()
                if any(term in w_text for term in terms):
                    filtered_warnings.append(w)
            warnings_list = filtered_warnings

        from api.warnings_service import warnings_summary, dedupe_and_sort_warnings, _unique_warning_variables
        warnings_list = dedupe_and_sort_warnings(warnings_list)
        summary = warnings_summary(warnings_list)
        
        sources_available = []
        if any(w.source == "predsea_anomaly" for w in warnings_list):
            sources_available.append("predsea_anomaly")
        if any(w.source == "aemet_official" for w in warnings_list):
            sources_available.append("aemet_official")
        summary["sources_available"] = sources_available

        if not warnings_list and not sources_available:
            stance = "Warning sources temporarily unavailable. Check conditions manually."
        elif summary["severe"]:
            severe_variables = ", ".join(_unique_warning_variables(warnings_list, severity="severe"))
            stance = f"SEVERE conditions detected ({severe_variables}). Review warnings before departure."
        elif summary["moderate"]:
            moderate_variables = ", ".join(_unique_warning_variables(warnings_list, severity="moderate"))
            stance = f"Moderate anomalies detected ({moderate_variables}). Monitor conditions closely."
        elif not warnings_list:
            stance = "No active warnings. Conditions appear within normal parameters."
        else:
            stance = "Minor informational alerts active. No immediate action required."

        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "context": {
                "route": route,
                "place": place,
                "date": date,
                "lookback_hours": lookback_hours,
                "min_window_hours": min_window_hours,
                "min_sample_count": min_sample_count,
                "z_threshold": z_threshold,
            },
            "summary": summary,
            "operational_stance": stance,
            "warnings": warnings_list,
            "sources_available": sources_available,
        }

    return build_warnings_response(
        route=route,
        place=place,
        date=date,
        z_threshold=z_threshold,
        lookback_hours=lookback_hours,
        min_window_hours=min_window_hours,
        min_sample_count=min_sample_count,
        include_aemet=include_aemet,
        include_anomaly=include_anomaly,
    )


@router.get(
    "/warnings",
    response_model=WarningsResponse,
    include_in_schema=False,
)
def warnings_endpoint(
    route: str | None = Query(default=None),
    place: str | None = Query(default=None),
    date: str | None = Query(default=None),
    z_threshold: float = Query(default=1.5, ge=0.0),
    lookback_hours: int = Query(default=240, ge=1),
    min_window_hours: int = Query(default=240, ge=1),
    min_sample_count: int = Query(default=10, ge=1),
    include_aemet: bool = Query(default=True),
    include_anomaly: bool = Query(default=True),
):
    return warnings_active_endpoint(
        route=route,
        place=place,
        date=date,
        z_threshold=z_threshold,
        lookback_hours=lookback_hours,
        min_window_hours=min_window_hours,
        min_sample_count=min_sample_count,
        include_aemet=include_aemet,
        include_anomaly=include_anomaly,
    )
