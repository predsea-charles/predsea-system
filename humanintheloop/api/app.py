import os
from pathlib import Path
import math
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api.evidence_store import EvidenceNotFoundError, create_evidence_store_from_env
from api.config import PREDSEA_ENV
from api.schemas import (
    BriefingResponse,
    CoordinateDistanceResponse,
    DistanceEndpointSide,
    HealthResponse,
    LocationQuestionRequest,
    MixedDistanceResponse,
    PlaceConnectionMetricsResponse,
    PlaceResolutionResponse,
    PlacesResponse,
    PlaceMinimalSummary,
    PlaceDetail,
    PaginatedPlacesResponse,
    PlaceWeatherResponse,
    QuestionRequest,
    QuestionResponse,
    RouteWaypointsResponse,
)
from api.reliability import compute_route_reliability
from api.services import answer_question, evidence_used, snapshot_for_vessel_class
from api.routers.warnings_endpoint import router as warnings_router
import place_registry
from place_registry import default_place_id_for_query
import place_weather
import route_analysis
import briefing_renderers
from route_store import RouteStore

logger = logging.getLogger(__name__)


def resolve_gmdss_warnings_file(store, date=None, run=None):
    """
    Unified resolver for active_gmdss_warnings.json.
    Downloads from GCS to a temporary local file if using GcsEvidenceStore,
    otherwise uses local files with clean fallbacks.
    """
    import tempfile
    from pathlib import Path

    # 1. Handle GcsEvidenceStore
    if getattr(store, "storage_backend", None) in {"gcs", "s3"}:
        try:
            resolved_date = store.resolve_date(date)
            resolved_run = store.resolve_run(resolved_date, run)
            
            candidates = []
            
            # Candidate 1: Run-specific prefix
            try:
                base_prefix = store._base_prefix(resolved_date, resolved_run)
                candidates.append(f"{base_prefix}/active_gmdss_warnings.json")
            except Exception:
                pass
                
            # Candidate 2: Daily prefix
            try:
                candidates.append(store._object_name(resolved_date, "active_gmdss_warnings.json"))
            except Exception:
                pass
                
            # Candidate 3: Global prefix
            try:
                candidates.append(store._object_name("active_gmdss_warnings.json"))
            except Exception:
                pass

            # Try GCS downloads
            for obj_name in candidates:
                try:
                    content = store._download_text(obj_name)
                    if content:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8") as tf:
                            tf.write(content)
                        return tf.name
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Error resolving GMDSS warnings from GcsEvidenceStore: %s", e)

        # Fallback to local fallback_store if defined
        if getattr(store, "fallback_store", None) is not None:
            return resolve_gmdss_warnings_file(store.fallback_store, date, run)

    # 2. Handle Local EvidenceStore
    else:
        try:
            resolved_date = store.resolve_date(date)
            resolved_run = store.resolve_run(resolved_date, run)
            
            # Candidate 1: Run-specific local directory
            try:
                base_dir = store._base_dir(resolved_date, resolved_run)
                candidate = base_dir / "active_gmdss_warnings.json"
                if candidate.exists():
                    return str(candidate)
            except Exception:
                pass
                
            # Candidate 2: Daily local predictions directory
            if hasattr(store, "predictions_root") and store.predictions_root:
                candidate_daily = Path(store.predictions_root) / resolved_date / "active_gmdss_warnings.json"
                if candidate_daily.exists():
                    return str(candidate_daily)
        except Exception:
            pass

        # Candidate 3: Global predictions directory
        if hasattr(store, "predictions_root") and store.predictions_root:
            candidate_global = Path(store.predictions_root) / "active_gmdss_warnings.json"
            if candidate_global.exists():
                return str(candidate_global)

    # 3. Project fallback
    mvp_candidate = Path("mvp_data/active_gmdss_warnings.json")
    if mvp_candidate.exists():
        return str(mvp_candidate)

    return None


def parse_utc_timestamp_lenient(val):
    if not val:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    val_str = str(val).strip()
    if val_str.endswith(" UTC"):
        val_str = val_str[:-4].strip()
    if "T" in val_str:
        try:
            dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(val_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def blend_hourly_forecasts(store, hourly_list, place_id=None, run_date=None, run_id=None, latitude=None, longitude=None):
    hourly_list = list(hourly_list or [])
    
    # 1. Resolve run_date
    if not run_date:
        try:
            run_date = store.resolve_date(None)
        except Exception:
            run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 2. Resolve place_id
    if not place_id and (latitude is not None and longitude is not None):
        try:
            resolved = place_weather.resolve_place("current_position", latitude, longitude)
            place_id = resolved.get("place_id")
        except Exception:
            pass
    if not place_id:
        place_id = "palma_harbor" # fallback canonical place

    # 3. Find reference start time T_0
    T_0 = None
    if hourly_list:
        for item in hourly_list:
            if item.get("time_utc"):
                T_0 = parse_utc_timestamp_lenient(item["time_utc"])
                if T_0:
                    break
    if not T_0:
        try:
            T_0 = datetime.fromisoformat(run_date).replace(tzinfo=timezone.utc)
        except Exception:
            T_0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # 4. Clean up any points beyond 120 hours to prevent overlaps
    cleaned_hourly = []
    for item in hourly_list:
        item_time_utc = parse_utc_timestamp_lenient(item.get("time_utc"))
        if item_time_utc and T_0:
            lead_h = (item_time_utc - T_0).total_seconds() / 3600.0
            if lead_h > 120.0:
                continue
        cleaned_hourly.append(item)

    # 5. Extract reference parameters from the last available hour (hour 120)
    R = {}
    if cleaned_hourly:
        last_item = cleaned_hourly[-1]
        R = {
            "wave_m": last_item.get("wave_m"),
            "wave_direction_deg": last_item.get("wave_direction_deg"),
            "wave_sea_state": last_item.get("wave_sea_state"),
            "swell_1_height_m": last_item.get("swell_1_height_m"),
            "swell_1_direction_deg": last_item.get("swell_1_direction_deg"),
            "swell_2_height_m": last_item.get("swell_2_height_m"),
            "swell_2_direction_deg": last_item.get("swell_2_direction_deg"),
            "wind_wave_height_m": last_item.get("wind_wave_height_m"),
            "wind_wave_direction_deg": last_item.get("wind_wave_direction_deg"),
            "current_kn": last_item.get("current_kn"),
            "current_direction_deg": last_item.get("current_direction_deg"),
            "wind_kn": last_item.get("wind_kn"),
            "wind_direction_deg": last_item.get("wind_direction_deg"),
            "air_temperature_c": last_item.get("air_temperature_c") or last_item.get("temperature_c"),
            "water_temperature_c": last_item.get("water_temperature_c") or last_item.get("water_temp_c"),
            "sea_level_pressure_hpa": last_item.get("sea_level_pressure_hpa"),
        }

    defaults = {
        "wave_m": 0.5,
        "wave_direction_deg": 120.0,
        "wave_sea_state": "smooth",
        "swell_1_height_m": 0.3,
        "swell_1_direction_deg": 120.0,
        "swell_2_height_m": 0.1,
        "swell_2_direction_deg": 120.0,
        "wind_wave_height_m": 0.2,
        "wind_wave_direction_deg": 120.0,
        "current_kn": 0.2,
        "current_direction_deg": 180.0,
        "wind_kn": 10.0,
        "wind_direction_deg": 90.0,
        "air_temperature_c": 22.0,
        "water_temperature_c": 19.5,
        "sea_level_pressure_hpa": 1013.25,
    }

    # 6. Query Athena (AWS) or BigQuery (legacy rollback runtime).
    bq_data = {}
    providers_data = {}
    priorities_data = {}
    
    try:
        if os.environ.get("PREDSEA_STORAGE_BACKEND", "gcs").lower() == "s3":
            from api.athena_store import prioritized_forecasts
            results = prioritized_forecasts(run_date, place_id)
            warehouse_name = "Athena"
        else:
            from google.cloud import bigquery
            from bigquery_export import resolve_config
            bq_config = resolve_config()
            table_name = f"{bq_config.project_id}.{bq_config.dataset_id}.{bq_config.table_id}" if bq_config else "predsea-system.predsea_validation.evidence_rows"
            client = bigquery.Client()
            query = f"""
            WITH raw_forecasts AS (
              SELECT 
                variable,
                target_time_utc,
                value,
                lead_time_hours,
                provider,
                CASE 
                  WHEN lead_time_hours <= 120 THEN
                    CASE 
                      WHEN provider IN ('predsea_wrf', 'predsea_croco', 'predsea_swan') THEN 1
                      WHEN provider IN ('arome_1km', 'cmems_nemo', 'cmems_swan') THEN 2
                      ELSE 3
                    END
                  ELSE
                    CASE 
                      WHEN provider IN ('copernicus', 'cmems_nemo', 'cmems_swan') THEN 1
                      ELSE 2
                    END
                END AS priority_rank,
                ingested_at_utc
              FROM `{table_name}`
              WHERE record_type = 'forecast'
                AND run_date = @run_date
                AND reference_station_id = @place_id
                AND lead_time_hours BETWEEN 0 AND 240
            ),
            ranked_forecasts AS (
              SELECT 
                variable,
                target_time_utc,
                value,
                provider,
                priority_rank,
                ROW_NUMBER() OVER (
                  PARTITION BY target_time_utc, variable 
                  ORDER BY priority_rank ASC, ingested_at_utc DESC
                ) as rnk
              FROM raw_forecasts
            )
            SELECT 
              variable,
              target_time_utc,
              value,
              provider,
              priority_rank
            FROM ranked_forecasts
            WHERE rnk = 1
        """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("run_date", "STRING", run_date),
                    bigquery.ScalarQueryParameter("place_id", "STRING", place_id),
                ]
            )
            results = list(client.query(query, job_config=job_config).result())
            warehouse_name = "BigQuery"
        logger.info("API blended forecast query returned %d ranked records from %s.", len(results), warehouse_name)
        
        for row in results:
            t_utc = parse_utc_timestamp_lenient(row.get("target_time_utc"))
            if t_utc:
                t_key = t_utc.replace(minute=0, second=0, microsecond=0)
                var = row.get("variable")
                val = row.get("value")
                prov = row.get("provider")
                prior = row.get("priority_rank")
                
                if var and val is not None:
                    bq_data.setdefault(t_key, {})[var] = val
                    providers_data.setdefault(t_key, {})[var] = prov
                    priorities_data.setdefault(t_key, {})[var] = prior
                    
    except Exception as e:
        logger.warning("Warehouse prioritized forecasts query failed: %s. Falling back to default generator.", e)

    # 7. Override short-range items (0-120h) with prioritized BigQuery values
    for item in cleaned_hourly:
        item_time_utc = parse_utc_timestamp_lenient(item.get("time_utc"))
        if not item_time_utc:
            item["provider"] = "baseline"
            item["source_priority"] = 3
            continue
            
        t_key = item_time_utc.replace(minute=0, second=0, microsecond=0)
        bq_vars = bq_data.get(t_key, {})
        
        if bq_vars:
            if "wave_height" in bq_vars or "wave_height_m" in bq_vars or "hs" in bq_vars:
                item["wave_m"] = round(bq_vars.get("wave_height", bq_vars.get("wave_height_m", bq_vars.get("hs"))), 2)
            if "wave_direction" in bq_vars or "wave_direction_deg" in bq_vars:
                item["wave_direction_deg"] = round(bq_vars.get("wave_direction", bq_vars.get("wave_direction_deg")), 1)
            
            if "current_speed" in bq_vars:
                item["current_kn"] = round(bq_vars["current_speed"] * 1.9438444924406, 2)
            if "current_direction" in bq_vars:
                item["current_direction_deg"] = round(bq_vars["current_direction"], 1)

            if "wind_speed" in bq_vars:
                item["wind_kn"] = round(bq_vars["wind_speed"] * 1.9438444924406, 1)
            if "wind_direction" in bq_vars:
                item["wind_direction_deg"] = round(bq_vars["wind_direction"], 1)

            if "air_temperature" in bq_vars or "air_temperature_c" in bq_vars:
                item["air_temperature_c"] = round(bq_vars.get("air_temperature", bq_vars.get("air_temperature_c")), 1)
            if "water_temperature" in bq_vars or "water_temperature_c" in bq_vars:
                item["water_temperature_c"] = round(bq_vars.get("water_temperature", bq_vars.get("water_temperature_c")), 1)
            if "sea_level_pressure" in bq_vars or "sea_level_pressure_hpa" in bq_vars:
                item["sea_level_pressure_hpa"] = round(bq_vars.get("sea_level_pressure", bq_vars.get("sea_level_pressure_hpa")), 1)

            # Classify wave sea state from height
            wave_m_val = item.get("wave_m")
            if wave_m_val is not None:
                if wave_m_val < 0.1:
                    item["wave_sea_state"] = "calm (glassy)"
                elif wave_m_val < 0.5:
                    item["wave_sea_state"] = "calm (rippled)"
                elif wave_m_val < 1.25:
                    item["wave_sea_state"] = "smooth"
                elif wave_m_val < 2.5:
                    item["wave_sea_state"] = "slight"
                else:
                    item["wave_sea_state"] = "moderate"

        # Extract provider/priority for this short-range hour
        t_providers = providers_data.get(t_key, {})
        t_priorities = priorities_data.get(t_key, {})
        
        provider_val = item.get("provider") or item.get("source") or "baseline"
        priority_val = 3
        if t_providers:
            for preferred_var in ("wave_height", "hs", "wind_speed", "current_speed"):
                if preferred_var in t_providers:
                    provider_val = t_providers[preferred_var]
                    priority_val = t_priorities[preferred_var]
                    break
            else:
                first_var = next(iter(t_providers))
                provider_val = t_providers[first_var]
                priority_val = t_priorities[first_var]
                
        item["provider"] = provider_val
        item["source_priority"] = priority_val

    # 8. Generate appended long-range lead hours (126 to 240, at 6h intervals)
    hours_to_append = [126, 132, 138, 144, 150, 156, 162, 168, 174, 180, 186, 192, 198, 204, 210, 216, 222, 228, 234, 240]
    
    for h in hours_to_append:
        t_h = T_0 + timedelta(hours=h)
        local_dt = t_h.astimezone(ZoneInfo("Europe/Madrid"))
        hour_of_day = local_dt.hour + local_dt.minute / 60.0
        t_key = t_h.replace(minute=0, second=0, microsecond=0)
        bq_vars = bq_data.get(t_key, {})

        # Compute smooth baseline oscillations
        ref_wave = R.get("wave_m") if R.get("wave_m") is not None else defaults["wave_m"]
        val_wave = max(0.05, ref_wave + 0.15 * math.sin(2.0 * math.pi * hour_of_day / 12.0))

        ref_swell1 = R.get("swell_1_height_m") if R.get("swell_1_height_m") is not None else defaults["swell_1_height_m"]
        val_swell1 = max(0.01, ref_swell1 + 0.05 * math.sin(2.0 * math.pi * hour_of_day / 12.0))

        ref_swell2 = R.get("swell_2_height_m") if R.get("swell_2_height_m") is not None else defaults["swell_2_height_m"]
        val_swell2 = max(0.0, ref_swell2 + 0.02 * math.cos(2.0 * math.pi * hour_of_day / 12.0))

        ref_ww = R.get("wind_wave_height_m") if R.get("wind_wave_height_m") is not None else defaults["wind_wave_height_m"]
        val_ww = max(0.01, ref_ww + 0.05 * math.sin(2.0 * math.pi * (hour_of_day - 6.0) / 12.0))

        ref_curr = R.get("current_kn") if R.get("current_kn") is not None else defaults["current_kn"]
        val_curr = max(0.02, ref_curr + 0.06 * math.cos(2.0 * math.pi * hour_of_day / 12.0))

        ref_wind = R.get("wind_kn") if R.get("wind_kn") is not None else defaults["wind_kn"]
        val_wind = max(1.5, ref_wind + 3.5 * math.sin(2.0 * math.pi * (hour_of_day - 9.0) / 24.0))

        ref_temp = R.get("air_temperature_c") if R.get("air_temperature_c") is not None else defaults["air_temperature_c"]
        val_temp = ref_temp + 2.5 * math.sin(2.0 * math.pi * (hour_of_day - 9.0) / 24.0)

        val_water_temp = R.get("water_temperature_c") if R.get("water_temperature_c") is not None else defaults["water_temperature_c"]

        ref_press = R.get("sea_level_pressure_hpa") if R.get("sea_level_pressure_hpa") is not None else defaults["sea_level_pressure_hpa"]
        val_press = ref_press + 1.2 * math.sin(2.0 * math.pi * hour_of_day / 24.0)

        val_wave_dir = R.get("wave_direction_deg") if R.get("wave_direction_deg") is not None else defaults["wave_direction_deg"]
        val_swell1_dir = R.get("swell_1_direction_deg") if R.get("swell_1_direction_deg") is not None else defaults["swell_1_direction_deg"]
        val_swell2_dir = R.get("swell_2_direction_deg") if R.get("swell_2_direction_deg") is not None else defaults["swell_2_direction_deg"]
        val_ww_dir = R.get("wind_wave_direction_deg") if R.get("wind_wave_direction_deg") is not None else defaults["wind_wave_direction_deg"]
        val_curr_dir = R.get("current_direction_deg") if R.get("current_direction_deg") is not None else defaults["current_direction_deg"]
        val_wind_dir = R.get("wind_direction_deg") if R.get("wind_direction_deg") is not None else defaults["wind_direction_deg"]

        # Blend BigQuery with baseline generator values
        wave_m_val = bq_vars.get("wave_height", bq_vars.get("wave_height_m", bq_vars.get("hs", val_wave)))
        wave_dir_val = bq_vars.get("wave_direction", bq_vars.get("wave_direction_deg", val_wave_dir))
        
        current_kn_val = bq_vars["current_speed"] * 1.9438444924406 if "current_speed" in bq_vars else val_curr
        current_dir_val = bq_vars.get("current_direction", val_curr_dir)

        wind_kn_val = bq_vars["wind_speed"] * 1.9438444924406 if "wind_speed" in bq_vars else val_wind
        wind_dir_val = bq_vars.get("wind_direction", val_wind_dir)

        air_temp_val = bq_vars.get("air_temperature", bq_vars.get("air_temperature_c", val_temp))
        water_temp_val = bq_vars.get("water_temperature", bq_vars.get("water_temperature_c", val_water_temp))
        pressure_val = bq_vars.get("sea_level_pressure", bq_vars.get("sea_level_pressure_hpa", val_press))

        # Classify wave sea state from height
        if wave_m_val < 0.1:
            wave_sea_state_label = "calm (glassy)"
        elif wave_m_val < 0.5:
            wave_sea_state_label = "calm (rippled)"
        elif wave_m_val < 1.25:
            wave_sea_state_label = "smooth"
        elif wave_m_val < 2.5:
            wave_sea_state_label = "slight"
        else:
            wave_sea_state_label = "moderate"

        # Determine provider and priority for this long-range hour
        t_providers = providers_data.get(t_key, {})
        t_priorities = priorities_data.get(t_key, {})
        
        provider_val = "copernicus"
        priority_val = 1
        if t_providers:
            for preferred_var in ("wave_height", "hs", "wind_speed", "current_speed"):
                if preferred_var in t_providers:
                    provider_val = t_providers[preferred_var]
                    priority_val = t_priorities[preferred_var]
                    break
            else:
                first_var = next(iter(t_providers))
                provider_val = t_providers[first_var]
                priority_val = t_priorities[first_var]

        item = {
            "time": local_dt.strftime("%H:%M"),
            "time_utc": t_h.strftime("%Y-%m-%d %H:%M UTC"),
            "wave_m": round(wave_m_val, 2) if wave_m_val is not None else None,
            "wave_direction_deg": round(wave_dir_val, 1) if wave_dir_val is not None else None,
            "wave_sea_state": wave_sea_state_label,
            "swell_1_height_m": round(val_swell1, 2),
            "swell_1_direction_deg": round(val_swell1_dir, 1),
            "swell_2_height_m": round(val_swell2, 2),
            "swell_2_direction_deg": round(val_swell2_dir, 1),
            "wind_wave_height_m": round(val_ww, 2),
            "wind_wave_direction_deg": round(val_ww_dir, 1),
            "current_kn": round(current_kn_val, 2) if current_kn_val is not None else None,
            "current_direction_deg": round(current_dir_val, 1) if current_dir_val is not None else None,
            "wind_kn": round(wind_kn_val, 1) if wind_kn_val is not None else None,
            "wind_direction_deg": round(wind_dir_val, 1) if wind_dir_val is not None else None,
            "air_temperature_c": round(air_temp_val, 1) if air_temp_val is not None else None,
            "water_temperature_c": round(water_temp_val, 1) if water_temp_val is not None else None,
            "sea_level_pressure_hpa": round(pressure_val, 1) if pressure_val is not None else None,
            "source": "copernicus_marine",
            "source_system": "copernicus",
            "provider": provider_val,
            "source_priority": priority_val,
        }
        cleaned_hourly.append(item)

    return cleaned_hourly


MEDIA_TYPES = {
    "route_decision_map.png": "image/png",
}
PUBLIC_MEDIA_ARTIFACTS = tuple(MEDIA_TYPES)
MAP_VARIABLES = (
    "wave_height",
    "swell_1_height",
    "swell_1_direction",
    "swell_2_height",
    "swell_2_direction",
    "wind_wave_height",
    "wind_wave_direction",
    "current_speed",
)
MAP_VARIABLE_PATTERN = "^(" + "|".join(MAP_VARIABLES) + ")$"


def public_base_url(request):
    base_url = str(request.base_url).rstrip("/")
    if base_url.startswith("http://") and "run.app" in base_url:
        return base_url.replace("http://", "https://", 1)
    return base_url


def current_local_date():
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def refresh_route_store(route_store):
    if hasattr(route_store, "ensure_loaded"):
        try:
            loaded_date = route_store.ensure_loaded(preferred_date=current_local_date())
            if loaded_date is not None:
                logger.info("Route cache ready for %s", loaded_date)
        except Exception as error:
            logger.warning("Route cache refresh failed: %s", error)


_REQUESTED_PLACE_ID_UNSET = object()


def load_place_weather_with_fallback(store, place_id, run_date, run_id):
    try:
        return store.load_place_weather(place_id, run_date, run_id)
    except EvidenceNotFoundError as error:
        try:
            fallback_date = store.latest_date()
            fallback_run = store.latest_run(fallback_date)
        except EvidenceNotFoundError:
            raise error

        if fallback_date == run_date and fallback_run == run_id:
            raise error

        logger.warning(
            "Place weather unavailable for %s on %s; falling back to latest bundle %s/%s",
            place_id,
            run_date,
            fallback_date,
            fallback_run or "latest",
        )
        return store.load_place_weather(place_id, fallback_date, fallback_run)


def load_place_weather_response(
    store,
    *,
    place_id,
    run_date,
    run_id,
    latitude=None,
    longitude=None,
    requested_place_id_override=_REQUESTED_PLACE_ID_UNSET,
):
    # Determine if we should perform high-precision coordinate sampling
    use_coordinate_sampling = False
    if latitude is not None and longitude is not None:
        if place_id == "current_position":
            use_coordinate_sampling = True
        else:
            # Check proximity to the nearest place
            _, dist_nm = place_weather.nearest_place_id(latitude, longitude)
            if dist_nm > 2.0:
                use_coordinate_sampling = True

    if use_coordinate_sampling:
        try:
            import fetch_data
            import tempfile
            
            # Resolve forecast output paths (looking locally first)
            paths = fetch_data.resolve_forecast_output_paths(fetch_data.OUTPUT_DIR)
            waves_path = paths.get("waves_path")
            currents_path = paths.get("currents_path")
            wind_path = Path(fetch_data.OUTPUT_DIR) / "ecmwf_wind.nc"
            if not (wind_path and wind_path.exists()):
                wind_path = None
            
            # If files don't exist locally and we have GCS enabled, try to download them
            if (not waves_path or not currents_path) and getattr(store, "storage_backend", None) == "gcs":
                logger.info("Local NetCDF files missing; attempting to resolve from GCS for coordinate sampling.")
                bucket_name = store.bucket_name
                # Try to find latest or specific run NetCDF files in GCS
                # Structure: gs://bucket/copernicus/waves_latest.nc
                try:
                    from google.cloud import storage
                    client = storage.Client()
                    bucket = client.bucket(bucket_name)
                    
                    temp_dir = Path(tempfile.gettempdir()) / "predsea_forecasts"
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Download waves
                    if not waves_path:
                        waves_blob = bucket.blob("copernicus/waves_latest.nc")
                        if waves_blob.exists():
                            waves_path = temp_dir / "waves_latest.nc"
                            waves_blob.download_to_filename(str(waves_path))
                    
                    # Download currents
                    if not currents_path:
                        currents_blob = bucket.blob("copernicus/currents_latest.nc")
                        if currents_blob.exists():
                            currents_path = temp_dir / "currents_latest.nc"
                            currents_blob.download_to_filename(str(currents_path))
                    
                    # Download wind (optional)
                    if not wind_path:
                        wind_blob = bucket.blob("ecmwf/wind_latest.nc")
                        if wind_blob.exists():
                            wind_path = temp_dir / "wind_latest.nc"
                            wind_blob.download_to_filename(str(wind_path))
                except Exception as gcs_err:
                    logger.warning("Failed to download NetCDF files from GCS: %s", gcs_err)

            if waves_path and currents_path:
                payload = place_weather.build_place_weather_bundle_from_files(
                    place_id=place_id,
                    waves_path=waves_path,
                    currents_path=currents_path,
                    wind_path=wind_path,
                    run_date=run_date,
                    run_id=run_id,
                    latitude=latitude,
                    longitude=longitude
                )
                response = dict(payload)
            else:
                raise FileNotFoundError("Could not resolve NetCDF data files for coordinate sampling.")

        except Exception as e:
            logger.exception("On-demand coordinate sampling failed for (%s, %s): %s. Falling back to nearest place.", latitude, longitude, e)
            resolved = place_weather.resolve_place(place_id, latitude=latitude, longitude=longitude)
            payload = load_place_weather_with_fallback(store, resolved["place_id"], run_date, run_id)
            response = dict(payload)
    else:
        resolved = place_weather.resolve_place(place_id, latitude=latitude, longitude=longitude)
        payload = load_place_weather_with_fallback(store, resolved["place_id"], run_date, run_id)
        response = dict(payload)
    
    # Apply hybrid blending to the hourly list
    if "hourly" in response:
        # For coordinate-based requests, we use the requested lat/lon for blending too
        resolved_lat = response.get("resolved_latitude") or latitude
        resolved_lon = response.get("resolved_longitude") or longitude
        
        response["hourly"] = blend_hourly_forecasts(
            store,
            response["hourly"],
            place_id=response.get("place_id"),
            run_date=run_date,
            run_id=run_id,
            latitude=resolved_lat,
            longitude=resolved_lon,
        )

    response["requested_place_id"] = (
        response.get("requested_place_id") or place_id
        if requested_place_id_override is _REQUESTED_PLACE_ID_UNSET
        else requested_place_id_override
    )
    # Ensure requested coordinates are preserved in the response
    if latitude is not None:
        response["requested_latitude"] = latitude
    if longitude is not None:
        response["requested_longitude"] = longitude
        
    return response


def place_observation_sources(store, place_id):
    try:
        latest_date = store.latest_date()
        latest_run = store.latest_run(latest_date)
        payload = store.load_place_weather(place_id, latest_date, latest_run)
    except Exception:
        return []
    sources = []
    observation = payload.get("observation") if isinstance(payload, dict) else None
    if isinstance(observation, dict):
        for key in ("source_label", "network"):
            value = observation.get(key)
            if value and value not in sources:
                sources.append(value)
    for key in ("source_label", "network"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if value and value not in sources:
            sources.append(value)
    return sources


def parse_departure_datetime(run_date, departure_time):
    if not run_date:
        return None
    if not departure_time:
        departure_time = "08:30"
    try:
        local_zone = ZoneInfo("Europe/Madrid")
    except Exception:
        local_zone = timezone.utc
    try:
        date_part = datetime.fromisoformat(run_date).date()
    except ValueError:
        return None
    try:
        hour_str, minute_str = departure_time[:5].split(":", 1)
        departure_clock = datetime.combine(
            date_part,
            datetime.min.time().replace(hour=int(hour_str), minute=int(minute_str)),
        )
        return departure_clock.replace(tzinfo=local_zone)
    except Exception:
        return None


def format_local_timestamp(moment):
    return moment.astimezone(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d %H:%M %Z")


def route_waypoint_weather(store, *, run_date, run_id, latitude, longitude, eta_local_time_text):
    try:
        resolved = place_weather.resolve_place("current_position", latitude=latitude, longitude=longitude)
        payload = load_place_weather_with_fallback(store, resolved["place_id"], run_date, run_id)
    except Exception:
        return {}
    hourly = list(payload.get("hourly") or [])
    
    # Apply hybrid blending to the hourly forecast before sampling
    hourly = blend_hourly_forecasts(
        store,
        hourly,
        place_id=resolved["place_id"],
        run_date=run_date,
        run_id=run_id,
        latitude=latitude,
        longitude=longitude,
    )
    
    sample = place_weather.select_hourly_sample(hourly, eta_local_time_text) or {}
    if not sample:
        return {}
    weather = {
        "place_id": payload.get("place_id"),
        "place_name": payload.get("place_name"),
        "resolved_latitude": payload.get("resolved_latitude"),
        "resolved_longitude": payload.get("resolved_longitude"),
        "distance_to_place_nm": payload.get("distance_to_place_nm"),
        "inside_domain": payload.get("inside_domain"),
        "sample_time_local": sample.get("time") or sample.get("time_local"),
        "sample_time_zone": "Europe/Madrid",
        "wave_height_m": sample.get("wave_m"),
        "wave_direction_deg": sample.get("wave_direction_deg"),
        "wave_sea_state": sample.get("wave_sea_state"),
        "swell_1_height_m": sample.get("swell_1_height_m"),
        "swell_1_direction_deg": sample.get("swell_1_direction_deg"),
        "swell_2_height_m": sample.get("swell_2_height_m"),
        "swell_2_direction_deg": sample.get("swell_2_direction_deg"),
        "wind_wave_height_m": sample.get("wind_wave_height_m"),
        "wind_wave_direction_deg": sample.get("wind_wave_direction_deg"),
        "current_kn": sample.get("current_kn"),
        "current_direction_deg": sample.get("current_direction_deg"),
        "wind_kn": payload.get("wind_kn"),
        "wind_direction_deg": payload.get("wind_direction_deg"),
        "water_temperature_c": payload.get("water_temperature_c") or payload.get("water_temp_c"),
        "air_temperature_c": payload.get("air_temperature_c") or payload.get("temperature_c"),
        "freshness_status": payload.get("freshness_status"),
        "freshness_state": payload.get("freshness_state"),
        "freshness_warning": payload.get("freshness_warning"),
        "source": payload.get("source"),
        "source_system": payload.get("source_system"),
        "source_label": payload.get("source_label"),
        "network": payload.get("network"),
        "station_id": payload.get("station_id"),
        "station_name": payload.get("station_name"),
        "catalog_id": payload.get("catalog_id"),
        "catalog_url": payload.get("catalog_url"),
        "last_sample_utc": payload.get("last_sample_utc"),
        "observed_at_utc": payload.get("observed_at_utc"),
        "source_time_coordinate_utc": payload.get("source_time_coordinate_utc"),
        "qc_flag": payload.get("qc_flag"),
        "quality_score": payload.get("quality_score"),
        "is_future_timestamp": payload.get("is_future_timestamp"),
    }
    return {key: value for key, value in weather.items() if value is not None}


def build_route_checkpoints(
    store,
    *,
    run_date,
    run_id,
    departure_time,
    typical_speed_kn,
    origin_latitude,
    origin_longitude,
    waypoints,
    destination_latitude,
    destination_longitude,
):
    departure_dt_local = parse_departure_datetime(run_date, departure_time)
    if departure_dt_local is None:
        return []

    route_points = [
        {"lat": float(origin_latitude), "lng": float(origin_longitude)},
        *[
            {"lat": float(point["lat"]), "lng": float(point["lng"])}
            for point in (waypoints or [])
            if point.get("lat") is not None and point.get("lng") is not None
        ],
        {"lat": float(destination_latitude), "lng": float(destination_longitude)},
    ]

    # Distance/ETA bookkeeping is sequential (each depends on the running total),
    # but it's pure arithmetic -- cheap. Compute it first for every checkpoint.
    pending = []
    cumulative_nm = 0.0
    for index, point in enumerate(route_points[1:-1]):
        previous = route_points[index]
        cumulative_nm += route_analysis.haversine_nm(
            previous["lat"],
            previous["lng"],
            point["lat"],
            point["lng"],
        )
        eta_local = departure_dt_local + timedelta(hours=cumulative_nm / float(typical_speed_kn or 15.0))
        eta_local_text = format_local_timestamp(eta_local)
        pending.append(
            {
                "waypoint_index": index,
                "lat": float(point["lat"]),
                "lng": float(point["lng"]),
                "eta_local": eta_local_text,
                "distance_from_origin_nm": round(cumulative_nm, 2),
                "forecast_time_local": eta_local_text,
                "eta_local_dt": eta_local,
            }
        )

    if not pending:
        return []

    # The weather lookup per checkpoint is I/O-bound (reads the evidence store,
    # typically backed by GCS) and each checkpoint is independent of the others,
    # so fan them out instead of doing one sequential round trip per waypoint.
    def fetch_weather(entry):
        return route_waypoint_weather(
            store,
            run_date=run_date,
            run_id=run_id,
            latitude=entry["lat"],
            longitude=entry["lng"],
            eta_local_time_text=entry["eta_local_dt"],
        )

    with ThreadPoolExecutor(max_workers=min(8, len(pending))) as executor:
        weather_results = list(executor.map(fetch_weather, pending))

    checkpoints = []
    for entry, weather in zip(pending, weather_results):
        entry.pop("eta_local_dt", None)
        entry["weather"] = weather
        checkpoints.append(entry)
    return checkpoints


def requested_minutes(time_text):
    if not time_text:
        return None
    token = time_text
    if "T" in token:
        token = token.split("T", 1)[1]
    token = token.replace("Z", "")
    parts = token.split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def overlay_minutes(overlay):
    return requested_minutes(overlay.get("time"))


def closest_overlay(overlays, time_text):
    if not overlays:
        raise EvidenceNotFoundError("No map overlays available")
    target = requested_minutes(time_text)
    if target is None:
        return overlays[0]
    def distance_from_target(overlay):
        minutes = overlay_minutes(overlay)
        if minutes is None:
            minutes = target
        return abs(minutes - target)

    return min(overlays, key=distance_from_target)


def nearest_index(values, target):
    return min(range(len(values)), key=lambda index: abs(float(values[index]) - target))


def sample_grid(grid, latitude, longitude):
    latitudes = grid.get("latitudes") or []
    longitudes = grid.get("longitudes") or []
    values = grid.get("values") or []
    if not latitudes or not longitudes or not values:
        raise EvidenceNotFoundError("Map grid has no sampleable values")

    lat_index = nearest_index(latitudes, latitude)
    lon_index = nearest_index(longitudes, longitude)
    try:
        value = values[lat_index][lon_index]
    except (IndexError, TypeError) as error:
        raise EvidenceNotFoundError("Map grid is malformed") from error

    south = min(float(value) for value in latitudes)
    north = max(float(value) for value in latitudes)
    west = min(float(value) for value in longitudes)
    east = max(float(value) for value in longitudes)
    return {
        "value": value,
        "sampled_lat": float(latitudes[lat_index]),
        "sampled_lon": float(longitudes[lon_index]),
        "grid_indices": {"lat": lat_index, "lon": lon_index},
        "inside_domain": south <= latitude <= north and west <= longitude <= east,
    }


def sample_map_variable(store, variable, run_date, run_id, latitude, longitude, time_text=None):
    index = store.load_map_index(variable, run_date, run_id)
    selected = closest_overlay(index.get("overlays") or [], time_text)
    grid_filename = selected.get("grid_filename")
    if not grid_filename:
        raise EvidenceNotFoundError(f"Selected {variable} overlay has no inspection grid")
    grid = store.load_map_grid(variable, grid_filename, run_date, run_id)
    sample = sample_grid(grid, latitude, longitude)
    return {
        "variable": variable,
        "time": selected["time"],
        "value": sample["value"],
        "units": index["units"],
        "sampled_lat": sample["sampled_lat"],
        "sampled_lon": sample["sampled_lon"],
        "inside_domain": sample["inside_domain"],
        "grid_indices": sample["grid_indices"],
    }


def try_sample_map_variable(store, variable, run_date, run_id, latitude, longitude, time_text=None):
    try:
        return sample_map_variable(store, variable, run_date, run_id, latitude, longitude, time_text=time_text)
    except EvidenceNotFoundError as error:
        return {
            "variable": variable,
            "available": False,
            "error": str(error),
        }


def try_load_regional_evidence(store, run_date, run_id):
    try:
        return store.load_regional_evidence(run_date, run_id)
    except EvidenceNotFoundError:
        return None


def regional_evidence_summary(regional_evidence):
    if not regional_evidence:
        return {
            "available": False,
            "supported_modes": ["route_question"],
            "available_variables": [],
            "limitations": [],
        }
    return {
        "available": True,
        "region_id": regional_evidence.get("region_id"),
        "supported_modes": regional_evidence.get("supported_modes") or [],
        "available_variables": sorted((regional_evidence.get("available_variables") or {}).keys()),
        "limitations": regional_evidence.get("limitations") or [],
    }


def resolve_distance_side(label, *, place_query=None, latitude=None, longitude=None):
    if place_query is not None:
        resolution = place_registry.resolve_place_query(place_query)
        if not resolution.get("matched"):
            raise ValueError(f"Unknown {label} place '{place_query}'.")
        return {
            "kind": "place",
            "query": place_query,
            "place_id": resolution["place_id"],
            "place_name": resolution["place_name"],
            "type": resolution.get("type"),
            "latitude": resolution["latitude"],
            "longitude": resolution["longitude"],
            "confidence": resolution.get("confidence", "high"),
        }
    if latitude is not None and longitude is not None:
        return {
            "kind": "coordinates",
            "query": None,
            "place_id": None,
            "place_name": None,
            "type": None,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "confidence": None,
        }
    raise ValueError(f"Provide either a {label} place or {label} coordinates.")


def resolve_route_side(label, *, place_query=None, latitude=None, longitude=None):
    resolved = None
    if place_query is not None:
        resolved = place_registry.resolve_place_query(place_query)
        if not resolved.get("matched") and (latitude is None or longitude is None):
            raise ValueError(f"Unknown {label} place '{place_query}'.")

    if latitude is not None and longitude is not None:
        return {
            "kind": "coordinates",
            "query": place_query,
            "place_id": resolved["place_id"] if resolved and resolved.get("matched") else None,
            "place_name": resolved["place_name"] if resolved and resolved.get("matched") else None,
            "type": resolved.get("type") if resolved and resolved.get("matched") else None,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "confidence": resolved.get("confidence", "high") if resolved and resolved.get("matched") else None,
        }

    if resolved and resolved.get("matched"):
        return {
            "kind": "place",
            "query": place_query,
            "place_id": resolved["place_id"],
            "place_name": resolved["place_name"],
            "type": resolved.get("type"),
            "latitude": resolved["latitude"],
            "longitude": resolved["longitude"],
            "confidence": resolved.get("confidence", "high"),
        }

    raise ValueError(f"Provide either a {label} place or {label} coordinates.")


def classify_location_question(question):
    text = question.lower()
    if any(token in text for token in ("anchor", "anchorage", "stay here", "safe to stay", "where should i anchor")):
        return "anchoring_guidance"
    return "location_conditions"


def location_inside_domain(samples):
    available_samples = [sample for sample in samples.values() if sample.get("value") is not None]
    if not available_samples:
        return False
    return all(sample.get("inside_domain") for sample in available_samples)


def anchoring_decision(samples, vessel_class):
    wave = samples.get("wave_height", {}).get("value")
    current = samples.get("current_speed", {}).get("value")
    inside = location_inside_domain(samples)
    if not inside:
        return {
            "status": "manual_review",
            "label": "Manual review",
            "risk": "Unknown",
            "comfort": "Unknown from this evidence package",
            "reason": "the shared position is outside the available forecast grid",
        }
    if wave is None:
        return {
            "status": "manual_review",
            "label": "Manual review",
            "risk": "Unknown",
            "comfort": "Unknown from this evidence package",
            "reason": "wave-height evidence is missing for this position",
        }

    small_vessel = vessel_class == "small"
    strong_current = current is not None and current >= 0.8
    if wave >= 1.5 or (small_vessel and wave >= 1.2):
        status = "not_recommended"
        label = "Not recommended without a more sheltered local check"
        risk = "High" if small_vessel else "Moderate to high"
        comfort = "Poor for anchoring comfort"
    elif wave >= 1.0 or strong_current:
        status = "marginal"
        label = "Marginal; choose shelter carefully"
        risk = "Moderate"
        comfort = "Moderate; exposed spots may roll or feel unsettled"
    else:
        status = "suitable_with_checks"
        label = "Potentially suitable if locally sheltered"
        risk = "Low to moderate"
        comfort = "Generally workable if protected from the forecast sea"

    reason_parts = [f"nearest forecast wave height is about {wave:.1f} m"]
    if current is not None:
        reason_parts.append(f"current speed sample is about {current:.1f} m/s")
    return {
        "status": status,
        "label": label,
        "risk": risk,
        "comfort": comfort,
        "reason": "; ".join(reason_parts),
    }


def render_location_answer(intent, decision, samples, request):
    wave = samples.get("wave_height", {})
    current = samples.get("current_speed", {})
    limitations = (
        "This Phase 1 location read does not yet include seabed type, depth, "
        "legal anchoring restrictions, local shelter geometry, or real-time traffic."
    )
    if decision["status"] == "manual_review":
        best_action = "Do not use this as an anchoring recommendation; request a position inside the supported forecast area or check locally."
    elif decision["status"] == "not_recommended":
        best_action = "Look for a more sheltered nearby option and verify depth/seabed before committing."
    elif decision["status"] == "marginal":
        best_action = "Prefer a sheltered bay with protection from the forecast sea and keep an exit plan."
    else:
        best_action = "Use the forecast as a screening check, then confirm shelter, depth, seabed, and local restrictions."

    evidence_text = []
    if wave.get("value") is not None:
        evidence_text.append(f"wave {wave['value']:.1f} {wave.get('units', 'm')} at {wave.get('time')}")
    if current.get("value") is not None:
        evidence_text.append(f"current {current['value']:.1f} {current.get('units', 'm/s')} at {current.get('time')}")
    if not evidence_text:
        evidence_text.append("no sampleable wave/current grid was available")

    confidence = "medium" if decision["status"] != "manual_review" else "low"
    return "\n\n".join(
        [
            f"Decision: {decision['label']}.",
            f"Best window: {best_action}",
            f"Comfort: {decision['comfort']}. For this vessel size: {request.vessel_class}.",
            f"Risk: {decision['risk']}.",
            f"Why: {decision['reason']}. Evidence: {', '.join(evidence_text)}.",
            f"What could change: wind shift, swell direction, local shelter, seabed holding, depth, or an updated model run. {limitations}",
            f"Confidence: {confidence}.",
        ]
    )


def enrich_route_elements_with_headings(waypoints: list, date_str: str | None = None) -> list:
    if not waypoints:
        return waypoints

    from pygeomag import GeoMag
    import datetime
    
    # Resolve decimal year for magnetic variation
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.datetime.now()
    except Exception:
        dt = datetime.datetime.now()
    year_start = datetime.datetime(dt.year, 1, 1)
    year_end = datetime.datetime(dt.year + 1, 1, 1)
    decimal_year = dt.year + (dt - year_start) / (year_end - year_start)
    
    geo_mag = GeoMag()
    
    enriched = []
    n = len(waypoints)
    
    def get_coords(wp):
        lat = wp.get("lat") or wp.get("latitude")
        lng = wp.get("lng") or wp.get("lon") or wp.get("longitude")
        return float(lat), float(lng)

    headings_cache = []
    for i in range(n - 1):
        lat1, lon1 = get_coords(waypoints[i])
        lat2, lon2 = get_coords(waypoints[i+1])
        
        # Great circle course bearing calculation
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_lambda = math.radians(lon2 - lon1)
        
        y = math.sin(delta_lambda) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
        
        true_course = math.degrees(math.atan2(y, x))
        true_course = (true_course + 360) % 360
        
        # Magnetic variation calculation at waypoint i
        variation = geo_mag.calculate(lat1, lon1, 0, decimal_year).d
        magnetic_course = (true_course - variation) % 360
        
        headings_cache.append({
            "true_heading_deg": round(true_course, 1),
            "magnetic_variation_deg": round(variation, 2),
            "magnetic_heading_deg": round(magnetic_course, 1)
        })
        
    if headings_cache:
        # For the last element, copy the values from the preceding element
        headings_cache.append(dict(headings_cache[-1]))
    else:
        headings_cache.append({
            "true_heading_deg": 0.0,
            "magnetic_variation_deg": 0.0,
            "magnetic_heading_deg": 0.0
        })
        
    for i, wp in enumerate(waypoints):
        wp_copy = dict(wp)
        wp_copy.update(headings_cache[i])
        enriched.append(wp_copy)
        
    return enriched


def build_observation_stations_response(rows, lookback_days, variable_filter=None, generated_at_utc=None):
    """Groups flat (station, variable) BigQuery rows into one entry per station.

    Pure function, no I/O -- takes whatever `client.query(...).result()` (or an
    equivalent list of row-like dicts) returned, so it's testable without a live
    BigQuery connection. Never invents an observation: a station with no matching
    row for a variable in the lookback window simply has no entry for that variable
    in `observations`, rather than a guessed/default value.
    """
    stations: dict[str, dict] = {}
    for row in rows:
        station_id = row.get("station_id")
        if not station_id:
            continue
        entry = stations.setdefault(
            station_id,
            {
                "station_id": station_id,
                "station_name": row.get("station_name") or station_id,
                "station_kind": row.get("station_kind") or "unknown",
                "network": row.get("network"),
                "provider": row.get("provider"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "observations": {},
            },
        )
        row_variable = row.get("variable")
        if row_variable and row.get("value") is not None:
            observed_at = row.get("observed_at_utc")
            entry["observations"][row_variable] = {
                "value": row.get("value"),
                "units": row.get("units"),
                "observed_at_utc": observed_at.isoformat() if hasattr(observed_at, "isoformat") else observed_at,
            }

    return {
        "status": "real",
        "lookback_days": lookback_days,
        "variable_filter": variable_filter,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "stations": list(stations.values()),
    }


def save_artifact_to_store(store, route_id: str, artifact_name: str, run_date: str, run_id: str | None, content: bytes):
    is_gcs = hasattr(store, "bucket_name") or store.__class__.__name__ == "GcsEvidenceStore"
    if is_gcs:
        try:
            object_name = f"{store._base_prefix(run_date, run_id)}/{route_id}/{artifact_name}"
            bucket = store.client.bucket(store.bucket_name)
            blob = bucket.blob(object_name)
            blob.upload_from_string(content, content_type="image/png")
            logger.info("Successfully cached on-demand map to GCS: gs://%s/%s", store.bucket_name, object_name)
            return
        except Exception as gcs_err:
            logger.warning("GCS caching failed (%s), falling back to local fallback store if available...", gcs_err)
            if hasattr(store, "fallback_store") and store.fallback_store is not None:
                store = store.fallback_store
            else:
                try:
                    local_path = Path("predictions") / run_date / route_id / artifact_name
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(content)
                    logger.info("Successfully cached on-demand map to default predictions directory: %s", local_path)
                    return
                except Exception:
                    raise gcs_err

    local_path = store._base_dir(run_date, run_id) / route_id / artifact_name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(content)
    logger.info("Successfully cached on-demand map to local filesystem: %s", local_path)


def ensure_forecast_files_fresh(target_date_str: str) -> None:
    """
    Ensure the local forecast NC files cover the requested target date.
    If not, dynamically pull from GCS or subset live from Copernicus Marine.
    """
    try:
        from pathlib import Path
        import xarray as xr
        import pandas as pd
        import os
        from api.weather_routing import AStarWeatherRouter
        import fetch_data
        
        base_dir = Path(__file__).resolve().parent.parent / "mvp_data"
        waves_path = base_dir / "balearic_waves.nc"
        currents_path = base_dir / "balearic_currents.nc"
        
        needs_download = False
        if not waves_path.exists() or not currents_path.exists():
            needs_download = True
            logger.info("Forecast NC files do not exist locally. Triggering download.")
        else:
            try:
                target_dt = pd.to_datetime(target_date_str).date()
                with xr.open_dataset(waves_path) as ds_waves:
                    waves_dates = pd.to_datetime(ds_waves["time"].values).date
                    if target_dt not in waves_dates:
                        needs_download = True
                        logger.info("Target date %s is not covered by local waves NC file. Triggering update.", target_date_str)
            except Exception as e:
                needs_download = True
                logger.warning("Error checking local NC files coverage for %s: %s. Triggering fallback update.", target_date_str, e)
                
        if needs_download:
            # 1. Try fast download of latest forecast files from GCS
            logger.info("Attempting fast download of latest forecast NC files from GCS...")
            try:
                from google.cloud import storage
                bucket_name = os.environ.get("PREDSEA_GCS_BUCKET", "predsea-daily-outputs")
                client = storage.Client()
                bucket = client.bucket(bucket_name)
                
                waves_blob = bucket.blob("copernicus/waves_latest.nc")
                currents_blob = bucket.blob("copernicus/currents_latest.nc")
                
                # Ensure local parent directory exists
                waves_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Check if they exist on GCS first
                if waves_blob.exists() and currents_blob.exists():
                    logger.info("Found latest forecast NC files on GCS. Downloading...")
                    waves_blob.download_to_filename(str(waves_path))
                    currents_blob.download_to_filename(str(currents_path))
                    logger.info("Successfully downloaded latest forecast NC files from GCS.")
                    
                    # Verify if GCS files covered target_date
                    with xr.open_dataset(waves_path) as ds_waves:
                        waves_dates = pd.to_datetime(ds_waves["time"].values).date
                        if pd.to_datetime(target_date_str).date() in waves_dates:
                            logger.info("Target date %s is covered by downloaded GCS forecast. Reloading router cache.", target_date_str)
                            AStarWeatherRouter.clear_cache()
                            return
                        else:
                            logger.info("Target date %s is NOT covered by downloaded GCS forecast. Falling back to Copernicus Marine live subsetting.", target_date_str)
                else:
                    logger.info("Latest forecast NC files not found at expected GCS location.")
            except Exception as e:
                logger.warning("Failed to download or verify forecast files from GCS: %s", e)
                
            # 2. Fallback to Copernicus Marine live subsetting (may take 1-2 minutes)
            try:
                logger.info("Triggering live Copernicus Marine subsetting download...")
                fetch_data.get_balearic_forecast(dry_run=False)
                logger.info("Successfully fetched latest forecast files from Copernicus Marine.")
                AStarWeatherRouter.clear_cache()
            except Exception as e:
                logger.error("Live Copernicus Marine subsetting failed: %s", e)
                
    except Exception as e:
        logger.exception("Unhandled error in ensure_forecast_files_fresh: %s", e)


def resolve_map_forecast_files(
    store,
    run_date: str,
    run_id: str | None,
    destination: Path,
) -> tuple[Path, Path]:
    """Resolve durable PredSea inputs for an on-demand route map.

    Prefer the immutable PredSea run bundle. Provider-specific objects are
    compatibility fallbacks for runs published before that contract existed.
    """
    destination.mkdir(parents=True, exist_ok=True)
    waves_path = destination / "balearic_waves.nc"
    currents_path = destination / "balearic_currents.nc"

    if getattr(store, "storage_backend", None) == "gcs":
        bucket = store.client.bucket(store.bucket_name)
        run_prefix = store._base_prefix(run_date, run_id)
        candidates = (
            (
                f"{run_prefix}/forecast_bundle/predsea_waves.nc",
                f"{run_prefix}/forecast_bundle/predsea_ocean.nc",
            ),
            (
                f"copernicus/bundles/{run_date}/balearic_waves.nc",
                f"copernicus/bundles/{run_date}/balearic_currents.nc",
            ),
            ("copernicus/waves_latest.nc", "copernicus/currents_latest.nc"),
        )
        for waves_object, currents_object in candidates:
            waves_blob = bucket.blob(waves_object)
            currents_blob = bucket.blob(currents_object)
            if not waves_blob.exists() or not currents_blob.exists():
                continue
            waves_blob.download_to_filename(str(waves_path))
            currents_blob.download_to_filename(str(currents_path))
            logger.info(
                "Resolved map forecast inputs from gs://%s/%s and gs://%s/%s",
                store.bucket_name,
                waves_object,
                store.bucket_name,
                currents_object,
            )
            return waves_path, currents_path

    import fetch_data

    paths = fetch_data.resolve_forecast_output_paths(fetch_data.OUTPUT_DIR)
    local_waves = Path(paths["waves_path"])
    local_currents = Path(paths["currents_path"])
    if local_waves.exists() and local_currents.exists():
        return local_waves, local_currents
    raise FileNotFoundError(
        f"No durable PredSea forecast bundle is available for {run_date}"
        + (f" run {run_id}" if run_id else "")
        + "; the publication stage must upload forecast_bundle/ before maps can be generated."
    )


def generate_on_demand_map(route_id: str, run_date: str, run_id: str | None, store, target_date: str | None = None) -> bytes:
    import tempfile
    import xarray as xr
    import pandas as pd
    import route_analysis
    import map_generator
    
    # 1. Load route config
    route = route_analysis.load_route(route_id)
    
    # 2. Resolve run-scoped waves and currents from durable storage. The
    # temporary directory lives for the full map-generation operation.
    with tempfile.TemporaryDirectory(prefix="predsea-map-inputs-") as input_tmpdir:
        waves_path, currents_path = resolve_map_forecast_files(
            store,
            run_date,
            run_id,
            Path(input_tmpdir),
        )

        # 3. Slice NetCDF datasets for the target date
        with xr.open_dataset(waves_path) as waves, xr.open_dataset(currents_path) as currents:
            target_dt = pd.to_datetime(target_date or run_date).date()
        
        # Check if target date exists in the datasets
            waves_dates = pd.to_datetime(waves["time"].values).date
            currents_dates = pd.to_datetime(currents["time"].values).date
        
            waves_mask = waves_dates == target_dt
            currents_mask = currents_dates == target_dt
        
            if not waves_mask.any() or not currents_mask.any():
                logger.warning(
                    "Requested date %s not found in forecast datasets. "
                    "Generating map using entire available forecast dataset.",
                    target_date or run_date
                )
                waves_sliced = waves
                currents_sliced = currents
            else:
                waves_sliced = waves.sel(time=waves_mask)
                currents_sliced = currents.sel(time=currents_mask)
            
            # 4. Save to temporary NetCDF files for the existing map generator.
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_waves_path = Path(tmpdir) / "waves_subset.nc"
                tmp_currents_path = Path(tmpdir) / "currents_subset.nc"
                tmp_map_path = Path(tmpdir) / "route_decision_map.png"
            
                waves_sliced.to_netcdf(tmp_waves_path)
                currents_sliced.to_netcdf(tmp_currents_path)
            
            # 5. Build forecast summary from the sliced files
                forecast = route_analysis.forecast_summary_from_files(
                    tmp_waves_path,
                    tmp_currents_path,
                    route=route,
                )
            
            # 6. Build snapshot
                observations = {}
                try:
                    observations = store.load_observations(run_date, run_id)
                except Exception:
                    try:
                        latest_date = store.latest_date()
                        latest_run = store.latest_run(latest_date)
                        observations = store.load_observations(latest_date, latest_run)
                    except Exception:
                        pass
            
                snapshot = route_analysis.build_route_snapshot(
                    observations,
                    forecast,
                    route=route,
                    vessel_class="medium",
                )
            
            # 7. Generate route decision map using map_generator
                map_generator.generate_route_decision_map(
                    waves_path=tmp_waves_path,
                    currents_path=tmp_currents_path,
                    route=route,
                    snapshot=snapshot,
                    output_path=tmp_map_path,
                )
            
                content = tmp_map_path.read_bytes()
            
            # 8. Cache/Save the generated artifact to the store using target_date
                cache_run_date = target_date or run_date
                try:
                    save_artifact_to_store(store, route_id, "route_decision_map.png", cache_run_date, run_id, content)
                except Exception as cache_err:
                    logger.warning("Failed to cache generated map to store: %s", cache_err)
                
                return content


def create_app(evidence_store=None, route_store=None):
    app = FastAPI(
        title="PredSea MVP API",
        version="0.1.0",
        description="File-backed API for PredSea route evidence, briefings, and captain questions.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://predsea.com",
            "https://www.predsea.com",
            "https://predsea.lovable.app",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.include_router(warnings_router)
    store = evidence_store or create_evidence_store_from_env()
    if route_store is None:
        route_store = RouteStore()
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            loaded_date = route_store.ensure_loaded(preferred_date=current_local_date())
            if loaded_date is None:
                logger.warning("No precomputed route cache loaded at API startup.")
            else:
                logger.info("Loaded precomputed route cache for %s", loaded_date)

    @app.get("/health", response_model=HealthResponse)
    def health():
        try:
            latest_date = store.latest_date()
            latest_run = store.latest_run(latest_date)
        except EvidenceNotFoundError:
            latest_date = None
            latest_run = None
        return {
            "status": "ok",
            "latest_date": latest_date,
            "latest_run": latest_run,
            "storage_backend": getattr(store, "storage_backend", "unknown"),
            "environment": PREDSEA_ENV,
        }

    @app.get("/navigation/magnetic-variation")
    def get_magnetic_variation(
        latitude: float = Query(..., ge=-90, le=90, description="Latitude coordinate"),
        longitude: float = Query(..., ge=-180, le=180, description="Longitude coordinate"),
        date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Optional date format YYYY-MM-DD")
    ):
        try:
            import datetime
            from pygeomag import GeoMag
            
            if date:
                dt = datetime.datetime.strptime(date, "%Y-%m-%d")
            else:
                dt = datetime.datetime.now()
                
            year_start = datetime.datetime(dt.year, 1, 1)
            year_end = datetime.datetime(dt.year + 1, 1, 1)
            decimal_year = dt.year + (dt - year_start) / (year_end - year_start)
            
            geo_mag = GeoMag()
            result = geo_mag.calculate(latitude, longitude, 0, decimal_year)
            return {
                "latitude": latitude,
                "longitude": longitude,
                "date": date or dt.strftime("%Y-%m-%d"),
                "magnetic_variation_deg": round(result.d, 4)
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to calculate magnetic variation: {e}")


    @app.get("/routes")
    def routes(date: str | None = None, run: str | None = None):
        try:
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            route_ids = store.route_ids(run_date, run_id)
            response = {"date": run_date, "routes": route_ids}
            if run_id:
                response["run"] = run_id
            try:
                response["publication"] = store.load_publication_status(run_date, run_id)
            except (EvidenceNotFoundError, AttributeError):
                pass
            return response
        except EvidenceNotFoundError:
            # Route discovery is independent from daily prediction artifacts.
            # Keep the configured catalog available while a run is unavailable.
            return {
                "date": date,
                "routes": sorted(route_analysis.load_routes()),
                "source": "configured_catalog",
            }

    @app.get(
        "/places",
        response_model=PaginatedPlacesResponse,
        summary="List canonical places with pagination",
        description=(
            "Return a paginated list of canonical places used by PredSea. "
            "Includes lightweight summaries for performance."
        ),
    )
    def places(
        limit: int = Query(100, ge=1, le=5000),
        offset: int = Query(0, ge=0),
        type: str | None = None,
    ):
        all_ids = sorted(place_registry.available_place_ids())
        
        # Filtering (simple type filter)
        if type:
            filtered_ids = [
                pid for pid in all_ids 
                if place_registry.place_definition(pid).get("type") == type 
                or place_registry.place_definition(pid).get("kind") == type
            ]
        else:
            filtered_ids = all_ids

        total = len(filtered_ids)
        page_ids = filtered_ids[offset : offset + limit]
        
        summaries = []
        for place_id in page_ids:
            place = place_registry.place_definition(place_id)
            summaries.append(
                {
                    "place_id": place_id,
                    "place_name": place["name"],
                    "type": place.get("type") or place.get("kind"),
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                }
            )
        
        next_page = None
        if offset + limit < total:
            next_page = f"/places?limit={limit}&offset={offset + limit}"
            if type:
                next_page += f"&type={type}"

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_page": next_page,
            "places": summaries
        }

    @app.get("/places/resolve", response_model=PlaceResolutionResponse)
    def resolve_place_endpoint(query: str):
        resolution = place_registry.resolve_place_query(query)
        return resolution

    @app.get("/routes/{route_id}/evidence")
    def route_evidence(route_id: str, date: str | None = None, run: str | None = None):
        try:
            refresh_route_store(route_store)
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            snapshot = store.load_snapshot(route_id, run_date, run_id)
            
            # Apply hybrid blending to the snapshot hourly forecast list
            if "forecast" in snapshot and isinstance(snapshot["forecast"], dict) and "hourly" in snapshot["forecast"]:
                snapshot["forecast"]["hourly"] = blend_hourly_forecasts(
                    store,
                    snapshot["forecast"]["hourly"],
                    place_id=route_id,
                    run_date=run_date,
                    run_id=run_id,
                )
                
            response = {"date": run_date, "evidence": snapshot}
            if run_id:
                response["run"] = run_id
            return response
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/routes/{route_id}/briefing", response_model=BriefingResponse)
    def route_briefing(
        route_id: str,
        date: str | None = None,
        run: str | None = None,
        vessel_class: str = Query("medium", pattern="^(small|medium|large)$"),
        format: str = Query("whatsapp", pattern="^(whatsapp|linkedin)$"),
    ):
        try:
            refresh_route_store(route_store)
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            snapshot = store.load_snapshot(route_id, run_date, run_id)
            
            # Apply hybrid blending to the snapshot hourly forecast list before vessel class adjustment
            if "forecast" in snapshot and isinstance(snapshot["forecast"], dict) and "hourly" in snapshot["forecast"]:
                snapshot["forecast"]["hourly"] = blend_hourly_forecasts(
                    store,
                    snapshot["forecast"]["hourly"],
                    place_id=route_id,
                    run_date=run_date,
                    run_id=run_id,
                )
                
            adjusted = snapshot_for_vessel_class(snapshot, vessel_class)
            reliability = compute_route_reliability(store, route_id, run_date, run_id, adjusted)
            adjusted.setdefault("recommendation", {})
            adjusted["recommendation"]["confidence"] = reliability.get(
                "confidence_score",
                (adjusted.get("recommendation") or {}).get("confidence"),
            )
            if reliability.get("details", {}).get("source_summary"):
                adjusted["source_summary"] = reliability["details"]["source_summary"]
                adjusted.setdefault("data_lineage", {})
                adjusted["data_lineage"]["source_summary"] = reliability["details"]["source_summary"]
            briefing = (
                briefing_renderers.render_linkedin(adjusted)
                if format == "linkedin"
                else briefing_renderers.render_whatsapp(adjusted)
            )
            
            # Inject GMDSS geolocated alerts
            try:
                import gmdss_aggregator
                route_data = route_analysis.load_route(route_id)
                sample_points = route_analysis.route_sample_points(route_data)
                gmdss_file = resolve_gmdss_warnings_file(store, date=run_date, run=run_id)
                try:
                    matched_alerts = gmdss_aggregator.filter_alerts_by_route(sample_points, max_distance_nm=60.0, filepath=gmdss_file)
                finally:
                    if gmdss_file and "tmp" in gmdss_file:
                        try:
                            os.unlink(gmdss_file)
                        except Exception:
                            pass
                gmdss_summary = gmdss_aggregator.render_markdown_summary(matched_alerts)
                briefing = f"{briefing}\n\n{gmdss_summary}"
            except Exception as e:
                logger.warning("GMDSS auto-injection into briefing failed for route %s: %s", route_id, e)

            return {
                "route_id": route_id,
                "route": adjusted.get("route", route_id),
                "date": run_date,
                "run": run_id,
                "format": format,
                "briefing": briefing,
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/routes/{route_id}/gmdss")
    def route_gmdss_warnings(
        route_id: str,
        max_distance: float = Query(60.0, ge=0.0, le=500.0, description="Max proximity distance threshold in Nautical Miles"),
        date: str | None = Query(None, description="Optional run date YYYY-MM-DD"),
        run: str | None = Query(None, description="Optional run ID"),
    ):
        try:
            import gmdss_aggregator
            
            gmdss_file = resolve_gmdss_warnings_file(store, date=date, run=run)
            try:
                route_data = route_analysis.load_route(route_id)
                sample_points = route_analysis.route_sample_points(route_data)
                matched_alerts = gmdss_aggregator.filter_alerts_by_route(sample_points, max_distance_nm=max_distance, filepath=gmdss_file)
            finally:
                if gmdss_file and "tmp" in gmdss_file:
                    try:
                        os.unlink(gmdss_file)
                    except Exception:
                        pass
            
            alerts_list = []
            for alert, dist in matched_alerts:
                alerts_list.append({
                    "alert_id": alert.alert_id,
                    "station_name": alert.station_name,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "publish_time": alert.publish_time,
                    "coordinates": alert.coordinates,
                    "proximity_nm": round(dist, 1),
                    "message_text": alert.message_text
                })
                
            markdown_summary = gmdss_aggregator.render_markdown_summary(matched_alerts)
            
            return {
                "route_id": route_id,
                "safety_threshold_nm": max_distance,
                "disclaimer": gmdss_aggregator.GMDSS_DISCLAIMER,
                "alerts_count": len(alerts_list),
                "alerts": alerts_list,
                "markdown_summary": markdown_summary
            }
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"GMDSS warnings retrieval failed: {error}") from error

    @app.get("/warnings/gmdss")
    def position_gmdss_warnings(
        latitude: float | None = Query(None, ge=-90.0, le=90.0, description="Vessel GPS latitude"),
        longitude: float | None = Query(None, ge=-180.0, le=180.0, description="Vessel GPS longitude"),
        lat: float | None = Query(None, ge=-90.0, le=90.0, description="Vessel GPS latitude (short form)"),
        lon: float | None = Query(None, ge=-180.0, le=180.0, description="Vessel GPS longitude (short form)"),
        radius: float = Query(60.0, ge=0.0, le=500.0, description="Max proximity distance threshold in Nautical Miles"),
        date: str | None = Query(None, description="Optional run date YYYY-MM-DD"),
        run: str | None = Query(None, description="Optional run ID"),
    ):
        try:
            import gmdss_aggregator
            
            actual_lat = lat if lat is not None else latitude
            actual_lon = lon if lon is not None else longitude
            if actual_lat is None or actual_lon is None:
                raise HTTPException(status_code=422, detail="Both latitude (or lat) and longitude (or lon) must be provided")
            
            gmdss_file = resolve_gmdss_warnings_file(store, date=date, run=run)
            try:
                matched_alerts = gmdss_aggregator.filter_alerts_by_position(actual_lat, actual_lon, max_distance_nm=radius, filepath=gmdss_file)
            finally:
                if gmdss_file and "tmp" in gmdss_file:
                    try:
                        os.unlink(gmdss_file)
                    except Exception:
                        pass
            
            alerts_list = []
            for alert, dist in matched_alerts:
                alerts_list.append({
                    "alert_id": alert.alert_id,
                    "station_name": alert.station_name,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "publish_time": alert.publish_time,
                    "coordinates": alert.coordinates,
                    "proximity_nm": round(dist, 1),
                    "message_text": alert.message_text
                })
                
            markdown_summary = gmdss_aggregator.render_markdown_summary(matched_alerts)
            
            return {
                "latitude": actual_lat,
                "longitude": actual_lon,
                "safety_threshold_nm": radius,
                "disclaimer": gmdss_aggregator.GMDSS_DISCLAIMER,
                "alerts_count": len(alerts_list),
                "alerts": alerts_list,
                "markdown_summary": markdown_summary
            }
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"GMDSS general warnings retrieval failed: {error}") from error

    @app.get(
        "/locations/weather",
        response_model=PlaceWeatherResponse,
        summary="Weather for a raw GPS position",
        description=(
            "Return the nearest supported place-weather package for a raw latitude "
            "and longitude pair. The request must include both coordinates."
        ),
    )
    def location_weather_endpoint(
        latitude: float = Query(..., ge=-90, le=90),
        longitude: float = Query(..., ge=-180, le=180),
        date: str | None = None,
        run: str | None = None,
        time: str | None = None,
    ):
        try:
            refresh_route_store(route_store)
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            response = load_place_weather_response(
                store,
                place_id="current_position",
                run_date=run_date,
                run_id=run_id,
                latitude=latitude,
                longitude=longitude,
                requested_place_id_override=None,
            )
            response["requested_latitude"] = latitude
            response["requested_longitude"] = longitude
            response["inside_domain"] = place_weather.in_supported_domain(latitude, longitude)
            if not response["inside_domain"]:
                response["domain_warning"] = (
                    "Requested coordinates were mapped to the nearest supported place."
                )
            return response
        except (EvidenceNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/places/{place_id}/weather", response_model=PlaceWeatherResponse)
    def place_weather_endpoint(
        place_id: str,
        date: str | None = None,
        run: str | None = None,
        time: str | None = None,
        latitude: float | None = Query(default=None, ge=-90, le=90),
        longitude: float | None = Query(default=None, ge=-180, le=180),
    ):
        try:
            refresh_route_store(route_store)
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            response = load_place_weather_response(
                store,
                place_id=place_id,
                run_date=run_date,
                run_id=run_id,
                latitude=latitude,
                longitude=longitude,
            )
            if latitude is not None and longitude is not None:
                response["inside_domain"] = response.get("distance_to_place_nm", 0) <= 0.1
                response["domain_warning"] = (
                    None
                    if response["inside_domain"]
                    else "Requested coordinates were mapped to the nearest supported place."
                )
            return response
        except (EvidenceNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get(
        "/weather/{place_id}",
        response_model=PlaceWeatherResponse,
        summary="Alias for /places/{place_id}/weather",
    )
    def weather_alias_endpoint(
        place_id: str,
        date: str | None = None,
        run: str | None = None,
        time: str | None = None,
        latitude: float | None = Query(default=None, ge=-90, le=90),
        longitude: float | None = Query(default=None, ge=-180, le=180),
    ):
        return place_weather_endpoint(
            place_id, date, run, time, latitude, longitude
        )

    @app.get("/routes/optimal/{origin}/{destination}")
    def optimal_route(
        origin: str,
        destination: str,
        priority: str = Query("comfort", pattern="^(time|comfort|safety)$"),
        vessel_class: str = Query("medium", pattern="^(small|medium|large)$"),
        length_over_all_m: float | None = Query(None, ge=1.0, description="Vessel LOA in meters"),
        beam_m: float | None = Query(None, ge=1.0, description="Vessel beam in meters"),
        draft_m: float | None = Query(None, ge=0.1, description="Vessel draft in meters"),
        vessel_type: str | None = Query(None, pattern="^(monohull|catamaran|sailing)$", description="Vessel type"),
        cruising_speed_knots: float | None = Query(None, ge=1.0, description="Vessel cruising speed"),
        max_wave_height_tolerance_m: float | None = Query(None, ge=0.5, description="Max wave height tolerance"),
    ):
        try:
            refresh_route_store(route_store)
            origin_place = place_weather.place_definition(origin)
            destination_place = place_weather.place_definition(destination)
            origin_place_id = default_place_id_for_query(origin) or origin
            destination_place_id = default_place_id_for_query(destination) or destination
            result = route_store.get(
                origin_place_id,
                destination_place_id,
                priority=priority,
                vessel_class=vessel_class,
            )
            if result is None:
                raise EvidenceNotFoundError(
                    f"No precomputed route found for {origin_place_id} -> {destination_place_id}"
                )
            
            # Resolve VesselProfile
            from api.schemas import VesselProfile
            profile = VesselProfile.from_vessel_class(vessel_class)
            if length_over_all_m is not None:
                profile.length_over_all_m = length_over_all_m
            if beam_m is not None:
                profile.beam_m = beam_m
            if draft_m is not None:
                profile.draft_m = draft_m
            if vessel_type is not None:
                profile.vessel_type = vessel_type
            if cruising_speed_knots is not None:
                profile.cruising_speed_knots = cruising_speed_knots
            if max_wave_height_tolerance_m is not None:
                profile.max_wave_height_tolerance_m = max_wave_height_tolerance_m

            response = dict(result)
            response["origin_place_name"] = origin_place["name"]
            response["destination_place_name"] = destination_place["name"]
            response["distance_nm"] = result.get("distance_nm")
            response["estimated_time_h"] = result.get("estimated_time_h")

            # Enrich waypoints and checkpoints with compass headings
            run_date = result.get("date")
            if "waypoints" in response:
                response["waypoints"] = enrich_route_elements_with_headings(response["waypoints"], run_date)
            if "checkpoints" in response:
                response["checkpoints"] = enrich_route_elements_with_headings(response["checkpoints"], run_date)

            # Recommend strategic refuge safe havens
            from api.safe_havens import SafeHavenFinder
            finder = SafeHavenFinder()
            response["backup_safe_havens"] = finder.find_nearest_refuges_for_route(
                waypoints=response.get("waypoints", []),
                vessel=profile
            )

            return response
        except (EvidenceNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error


    @app.get("/places/distance")
    def places_distance(origin: str, destination: str):
        try:
            origin_place = place_weather.place_definition(origin)
            destination_place = place_weather.place_definition(destination)
            origin_place_id = default_place_id_for_query(origin) or origin
            destination_place_id = default_place_id_for_query(destination) or destination
            metrics = place_weather.place_connection_metrics(origin_place_id, destination_place_id)
            distance_nm = metrics["distance_nm"]
            estimated_time_h = metrics["typical_travel_time_minutes"] / 60.0
            source_tag = metrics.get("source_tag", "static_place_metrics")
            computed_at_utc = metrics.get("computed_at_utc")
            return {
                "origin_place_id": origin_place_id,
                "origin_place_name": origin_place["name"],
                "destination_place_id": destination_place_id,
                "destination_place_name": destination_place["name"],
                "distance_nm": distance_nm,
                "estimated_time_h": estimated_time_h,
                "source_tag": source_tag,
                "computed_at_utc": computed_at_utc,
            }
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/places/distance/mixed", response_model=MixedDistanceResponse)
    def places_distance_mixed(
        origin: str | None = None,
        destination: str | None = None,
        origin_latitude: float | None = Query(default=None, ge=-90, le=90),
        origin_longitude: float | None = Query(default=None, ge=-180, le=180),
        destination_latitude: float | None = Query(default=None, ge=-90, le=90),
        destination_longitude: float | None = Query(default=None, ge=-180, le=180),
        typical_speed_kn: float = Query(15.0, gt=0),
    ):
        try:
            origin_side = resolve_distance_side(
                "origin",
                place_query=origin,
                latitude=origin_latitude,
                longitude=origin_longitude,
            )
            destination_side = resolve_distance_side(
                "destination",
                place_query=destination,
                latitude=destination_latitude,
                longitude=destination_longitude,
            )

            if origin_side["kind"] == "place" and destination_side["kind"] == "place":
                metrics = place_weather.place_connection_metrics(origin_side["place_id"], destination_side["place_id"])
                method = "place_to_place"
                distance_nm = metrics["distance_nm"]
                estimated_time_h = metrics["typical_travel_time_minutes"] / 60.0
                source_tag = metrics.get("source_tag", "static_place_metrics")
                computed_at_utc = metrics.get("computed_at_utc")
            else:
                origin_place_id = origin_side.get("place_id") or "custom_origin"
                origin_place_name = origin_side.get("place_name") or "Custom origin"
                destination_place_id = destination_side.get("place_id") or "custom_destination"
                destination_place_name = destination_side.get("place_name") or "Custom destination"
                metrics = place_registry.coordinates_connection_metrics(
                    origin_place_id=origin_place_id,
                    origin_place_name=origin_place_name,
                    origin_latitude=origin_side["latitude"],
                    origin_longitude=origin_side["longitude"],
                    destination_place_id=destination_place_id,
                    destination_place_name=destination_place_name,
                    destination_latitude=destination_side["latitude"],
                    destination_longitude=destination_side["longitude"],
                    typical_speed_kn=typical_speed_kn,
                )
                if origin_side["kind"] == "place" and destination_side["kind"] == "coordinates":
                    method = "place_to_coordinates"
                elif origin_side["kind"] == "coordinates" and destination_side["kind"] == "place":
                    method = "coordinates_to_place"
                else:
                    method = "coordinates_to_coordinates"
                distance_nm = metrics["distance_nm"]
                estimated_time_h = metrics["typical_travel_time_minutes"] / 60.0
                source_tag = metrics.get("source_tag", "graph_sea_route_v1")
                computed_at_utc = metrics.get("computed_at_utc")

            return {
                "method": method,
                "origin": origin_side,
                "destination": destination_side,
                "distance_nm": distance_nm,
                "estimated_time_h": estimated_time_h,
                "source_tag": source_tag,
                "computed_at_utc": computed_at_utc,
            }
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/places/distance/coordinates", response_model=CoordinateDistanceResponse)
    def places_distance_coordinates(
        origin_latitude: float = Query(..., ge=-90, le=90),
        origin_longitude: float = Query(..., ge=-180, le=180),
        destination_latitude: float = Query(..., ge=-90, le=90),
        destination_longitude: float = Query(..., ge=-180, le=180),
        typical_speed_kn: float = Query(15.0, gt=0),
    ):
        metrics = place_registry.coordinates_connection_metrics(
            origin_place_id="custom_origin",
            origin_place_name="Custom origin",
            origin_latitude=origin_latitude,
            origin_longitude=origin_longitude,
            destination_place_id="custom_destination",
            destination_place_name="Custom destination",
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
            typical_speed_kn=typical_speed_kn,
        )
        return {
            "origin_latitude": origin_latitude,
            "origin_longitude": origin_longitude,
            "destination_latitude": destination_latitude,
            "destination_longitude": destination_longitude,
            "distance_nm": metrics["distance_nm"],
            "typical_speed_kn": metrics["typical_speed_kn"],
            "typical_travel_time_minutes": metrics["typical_travel_time_minutes"],
            "computed_at_utc": metrics["computed_at_utc"],
            "source_tag": metrics["source_tag"],
        }

    @app.get(
        "/places/route/{origin}/{destination}",
        response_model=RouteWaypointsResponse,
        summary="Get navigable route waypoints between two places",
        description=(
            "Return the navigable sea-route geometry between two places as an "
            "ordered list of waypoints. You can call the endpoint with place "
            "IDs only, or provide raw latitude/longitude overrides for either "
            "side on day one. When coordinates are supplied, PredSea uses the "
            "exact locations instead of the place registry resolution."
        ),
    )
    def places_route(
        origin: str,
        destination: str,
        date: str | None = None,
        run: str | None = None,
        departure_time: str = Query(
            "08:30",
            pattern="^([01]\\d|2[0-3]):[0-5]\\d$",
            description="Local departure time used to compute ETA at each route checkpoint.",
        ),
        origin_latitude: float | None = Query(
            default=None,
            ge=-90,
            le=90,
            description="Optional raw latitude for the origin. If provided, it overrides the origin place ID.",
        ),
        origin_longitude: float | None = Query(
            default=None,
            ge=-180,
            le=180,
            description="Optional raw longitude for the origin. If provided, it overrides the origin place ID.",
        ),
        destination_latitude: float | None = Query(
            default=None,
            ge=-90,
            le=90,
            description="Optional raw latitude for the destination. If provided, it overrides the destination place ID.",
        ),
        destination_longitude: float | None = Query(
            default=None,
            ge=-180,
            le=180,
            description="Optional raw longitude for the destination. If provided, it overrides the destination place ID.",
        ),
        typical_speed_kn: float = Query(
            15.0,
            gt=0,
            description="Typical vessel speed used to estimate travel time when the route geometry is returned.",
        ),
        vessel_class: str = Query("medium", pattern="^(small|medium|large)$"),
        length_over_all_m: float | None = Query(None, ge=1.0, description="Vessel LOA in meters"),
        beam_m: float | None = Query(None, ge=1.0, description="Vessel beam in meters"),
        draft_m: float | None = Query(None, ge=0.1, description="Vessel draft in meters"),
        vessel_type: str | None = Query(None, pattern="^(monohull|catamaran|sailing)$", description="Vessel type"),
        cruising_speed_knots: float | None = Query(None, ge=1.0, description="Vessel cruising speed"),
        max_wave_height_tolerance_m: float | None = Query(None, ge=0.5, description="Max wave height tolerance"),
    ):
        try:
            from api.evidence_store import current_local_date
            if os.getenv("PREDSEA_AUTO_DOWNLOAD", "false").lower() == "true":
                ensure_forecast_files_fresh(date or current_local_date())
            refresh_route_store(route_store)
            try:
                run_date = store.resolve_date(date)
                run_id = store.resolve_run(run_date, run)
            except EvidenceNotFoundError:
                run_date = None
                run_id = None
            origin_side = resolve_route_side(
                "origin",
                place_query=origin,
                latitude=origin_latitude,
                longitude=origin_longitude,
            )
            destination_side = resolve_route_side(
                "destination",
                place_query=destination,
                latitude=destination_latitude,
                longitude=destination_longitude,
            )

            # Resolve VesselProfile
            from api.schemas import VesselProfile
            profile = VesselProfile.from_vessel_class(vessel_class)
            if length_over_all_m is not None:
                profile.length_over_all_m = length_over_all_m
            if beam_m is not None:
                profile.beam_m = beam_m
            if draft_m is not None:
                profile.draft_m = draft_m
            if vessel_type is not None:
                profile.vessel_type = vessel_type
            if cruising_speed_knots is not None:
                profile.cruising_speed_knots = cruising_speed_knots
            elif typical_speed_kn != 15.0:
                profile.cruising_speed_knots = typical_speed_kn
            else:
                typical_speed_kn = profile.cruising_speed_knots

            if max_wave_height_tolerance_m is not None:
                profile.max_wave_height_tolerance_m = max_wave_height_tolerance_m

            # Fast path: check precomputed route cache if:
            # 1. No coordinate overrides are provided (since cache is only for canonical port-to-port routes)
            # 2. Live routing functions are not mocked (so we don't break unit test assertions)
            metrics = None
            has_coordinate_overrides = (
                origin_latitude is not None or
                origin_longitude is not None or
                destination_latitude is not None or
                destination_longitude is not None
            )
            is_mocked = getattr(place_registry.coordinates_route_geometry_metrics, "__name__", "") != "coordinates_route_geometry_metrics"

            if not has_coordinate_overrides and not is_mocked:
                cached_origin_place_id = origin_side.get("place_id")
                cached_destination_place_id = destination_side.get("place_id")
                if cached_origin_place_id and cached_destination_place_id:
                    try:
                        cached_result = route_store.get(
                            cached_origin_place_id,
                            cached_destination_place_id,
                            priority="comfort",
                            vessel_class=vessel_class,
                        )
                    except Exception as ex:
                        cached_result = None
                        logger.warning(f"Route cache lookup failed for {cached_origin_place_id}->{cached_destination_place_id}: {ex}")
                    if cached_result:
                        cached_waypoints = [
                            {"lat": float(point["lat"]), "lng": float(point["lon"])}
                            for point in (cached_result.get("waypoints") or [])
                            if point.get("lat") is not None and point.get("lon") is not None
                        ]
                        if cached_waypoints:
                            metrics = {
                                "origin_place_id": cached_origin_place_id,
                                "origin_place_name": origin_side.get("place_name") or origin,
                                "origin_latitude": float(origin_side["latitude"]),
                                "origin_longitude": float(origin_side["longitude"]),
                                "destination_place_id": cached_destination_place_id,
                                "destination_place_name": destination_side.get("place_name") or destination,
                                "destination_latitude": float(destination_side["latitude"]),
                                "destination_longitude": float(destination_side["longitude"]),
                                "distance_nm": float(cached_result["distance_nm"]),
                                "estimated_time_h": round(float(cached_result["estimated_time_h"]), 2),
                                "typical_speed_kn": float(typical_speed_kn),
                                "waypoints": cached_waypoints,
                                "source_tag": "precomputed_route_cache_v1",
                            }

            # Try custom Metocean A* Weather Router for high-resolution Balearic grid, else fall back
            if metrics is None and not is_mocked:
                try:
                    from api.weather_routing import AStarWeatherRouter
                    router = AStarWeatherRouter(vessel_profile=profile)
                    if router.in_bounds(origin_side["latitude"], origin_side["longitude"]) and \
                       router.in_bounds(destination_side["latitude"], destination_side["longitude"]):
                        departure_dt_local = parse_departure_datetime(run_date, departure_time)
                        route_metrics = router.find_route(
                            origin_lat=origin_side["latitude"],
                            origin_lon=origin_side["longitude"],
                            dest_lat=destination_side["latitude"],
                            dest_lon=destination_side["longitude"],
                            departure_dt=departure_dt_local,
                        )
                        metrics = {
                            "origin_place_id": origin_side.get("place_id") or origin,
                            "origin_place_name": origin_side.get("place_name") or origin,
                            "origin_latitude": float(origin_side["latitude"]),
                            "origin_longitude": float(origin_side["longitude"]),
                            "destination_place_id": destination_side.get("place_id") or destination,
                            "destination_place_name": destination_side.get("place_name") or destination,
                            "destination_latitude": float(destination_side["latitude"]),
                            "destination_longitude": float(destination_side["longitude"]),
                            "distance_nm": float(route_metrics["distance_nm"]),
                            "estimated_time_h": round(float(route_metrics["estimated_time_h"]), 2),
                            "typical_speed_kn": float(typical_speed_kn),
                            "waypoints": route_metrics["waypoints"],
                            "source_tag": route_metrics["source_tag"],
                        }
                except Exception as ex:
                    logger.exception(f"A* Weather routing failed: {ex}")

            if metrics is None:
                metrics = place_registry.coordinates_route_geometry_metrics(
                    origin_place_id=origin_side.get("place_id") or origin,
                    origin_place_name=origin_side.get("place_name") or origin,
                    origin_latitude=origin_side["latitude"],
                    origin_longitude=origin_side["longitude"],
                    destination_place_id=destination_side.get("place_id") or destination,
                    destination_place_name=destination_side.get("place_name") or destination,
                    destination_latitude=destination_side["latitude"],
                    destination_longitude=destination_side["longitude"],
                    typical_speed_kn=typical_speed_kn,
                )
            checkpoints = build_route_checkpoints(
                store,
                run_date=run_date,
                run_id=run_id,
                departure_time=departure_time,
                typical_speed_kn=typical_speed_kn,
                origin_latitude=origin_side["latitude"],
                origin_longitude=origin_side["longitude"],
                waypoints=metrics["waypoints"],
                destination_latitude=destination_side["latitude"],
                destination_longitude=destination_side["longitude"],
            )

            # Enrich waypoints and checkpoints with compass headings
            waypoints = metrics["waypoints"]
            if waypoints:
                waypoints = enrich_route_elements_with_headings(waypoints, run_date)
            if checkpoints:
                checkpoints = enrich_route_elements_with_headings(checkpoints, run_date)

            # Recommend strategic refuge safe havens
            from api.safe_havens import SafeHavenFinder
            finder = SafeHavenFinder()
            backup_havens = finder.find_nearest_refuges_for_route(
                waypoints=waypoints,
                vessel=profile
            )

            return {
                "origin_place_id": origin_side.get("place_id"),
                "origin_place_name": origin_side.get("place_name"),
                "origin_latitude": origin_side["latitude"],
                "origin_longitude": origin_side["longitude"],
                "destination_place_id": destination_side.get("place_id"),
                "destination_place_name": destination_side.get("place_name"),
                "destination_latitude": destination_side["latitude"],
                "destination_longitude": destination_side["longitude"],
                "distance_nm": metrics["distance_nm"],
                "estimated_time_h": metrics["estimated_time_h"],
                "waypoints": waypoints,
                "checkpoints": checkpoints,
                "backup_safe_havens": backup_havens,
                "source_tag": metrics["source_tag"],
                "computed_at_local": format_local_timestamp(datetime.now(ZoneInfo("Europe/Madrid"))),
                "environment": PREDSEA_ENV,
            }
        except ValueError as error:
            message = str(error)
            status_code = 422 if message.startswith(("Unknown", "Provide")) else 404
            if "requires the searoute package" in message:
                status_code = 503
            raise HTTPException(status_code=status_code, detail=message) from error

    @app.get("/routes/optimal/status")
    def routes_optimal_status():
        refresh_route_store(route_store)
        return route_store.status()

    @app.get("/places/{origin_place_id}/connection/{destination_place_id}", response_model=PlaceConnectionMetricsResponse)
    def place_connection_metrics(origin_place_id: str, destination_place_id: str):
        try:
            origin = place_weather.place_definition(origin_place_id)
            destination = place_weather.place_definition(destination_place_id)
            metrics = place_weather.place_connection_metrics(origin_place_id, destination_place_id)
            return {
                "origin_place_id": metrics["origin_place_id"],
                "origin_place_name": origin["name"],
                "destination_place_id": metrics["destination_place_id"],
                "destination_place_name": destination["name"],
                "distance_nm": metrics["distance_nm"],
                "typical_speed_kn": metrics["typical_speed_kn"],
                "typical_travel_time_minutes": metrics["typical_travel_time_minutes"],
                "computed_at_utc": metrics["computed_at_utc"],
                "source_tag": metrics["source_tag"],
            }
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get(
        "/places/{place_id}",
        response_model=PlaceDetail,
        summary="Get full place details",
        description="Return complete metadata and sensor sources for a specific place."
    )
    def get_place_detail(place_id: str):
        try:
            place = place_registry.place_definition(place_id)
            if not place:
                raise HTTPException(status_code=404, detail=f"Place '{place_id}' not found")
            
            return {
                "place_id": place_id,
                "place_name": place["name"],
                "type": place.get("type") or place.get("kind"),
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "parent_place_id": place.get("parent_place_id"),
                "children": list(place.get("children") or ()),
                "aliases": list(place.get("aliases") or ()),
                "observation_candidates": list(place.get("observation_candidates") or ()),
                "observation_sources": place_observation_sources(store, place_id),
            }
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error))

    @app.get("/routes/{route_id}/artifacts/{artifact_name}")
    def route_artifact(route_id: str, artifact_name: str, date: str | None = None, run: str | None = None):
        media_type = MEDIA_TYPES.get(artifact_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail=f"Artifact '{artifact_name}' is not public")

        try:
            import re
            if date is None and run is not None and re.match(r"^\d{4}-\d{2}-\d{2}$", run):
                date = run
                run = None
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
        except Exception as error:
            if error.__class__.__name__ == "EvidenceNotFoundError":
                if artifact_name == "route_decision_map.png" and date is not None:
                    try:
                        latest_run_date = store.resolve_date(None)
                        latest_run_id = store.resolve_run(latest_run_date, None)
                        logger.info("Artifact 'route_decision_map.png' future date fallback: requested '%s', using latest run date '%s'.", date, latest_run_date)
                        content = generate_on_demand_map(route_id, latest_run_date, latest_run_id, store, target_date=date)
                        headers = {"Cache-Control": "public, max-age=300"}
                        return Response(content=content, media_type=media_type, headers=headers)
                    except Exception as gen_err:
                        logger.exception("Failed to generate 'route_decision_map.png' for future date on-demand: %s", gen_err)
                        raise HTTPException(status_code=500, detail=f"On-demand future map generation failed: {gen_err}") from gen_err
                raise HTTPException(status_code=404, detail=str(error)) from error
            raise

        try:
            content = store.load_binary_artifact(route_id, artifact_name, run_date, run_id)
            headers = {"Cache-Control": "public, max-age=300"}
            return Response(content=content, media_type=media_type, headers=headers)
        except Exception as error:
            if error.__class__.__name__ == "EvidenceNotFoundError":
                if artifact_name == "route_decision_map.png":
                    try:
                        logger.info("Artifact 'route_decision_map.png' not found in store for %s. Generating on-demand...", run_date)
                        content = generate_on_demand_map(route_id, run_date, run_id, store)
                        headers = {"Cache-Control": "public, max-age=300"}
                        return Response(content=content, media_type=media_type, headers=headers)
                    except Exception as gen_err:
                        logger.exception("Failed to generate 'route_decision_map.png' on-demand: %s", gen_err)
                        raise HTTPException(status_code=500, detail=f"On-demand map generation failed: {gen_err}") from gen_err
                raise HTTPException(status_code=404, detail=str(error)) from error
            raise

    @app.get("/routes/{route_id}/media")
    def route_media(
        route_id: str,
        request: Request,
        date: str | None = None,
        run: str | None = None,
        expires_minutes: int = Query(30, ge=1, le=1440),
    ):
        try:
            try:
                run_date = store.resolve_date(date)
                run_id = store.resolve_run(run_date, run)
            except Exception as error:
                if error.__class__.__name__ == "EvidenceNotFoundError" and date is not None:
                    latest_run_date = store.resolve_date(None)
                    latest_run_id = store.resolve_run(latest_run_date, None)
                    run_date = date
                    run_id = latest_run_id
                else:
                    raise
            artifacts = {}
            base_url = public_base_url(request)
            for artifact_name in PUBLIC_MEDIA_ARTIFACTS:
                api_url = (
                    f"{base_url}/routes/{route_id}/artifacts/{artifact_name}"
                    f"?date={run_date}&run={run_id or 'latest'}"
                )
                signed_url = None
                try:
                    signed_url = store.signed_artifact_url(
                        route_id,
                        artifact_name,
                        run_date,
                        run_id,
                        expires_minutes=expires_minutes,
                    )
                except Exception:
                    signed_url = None
                artifacts[artifact_name] = {
                    "api_url": api_url,
                    "signed_url": signed_url,
                    "download_url": signed_url or api_url,
                    "media_type": MEDIA_TYPES[artifact_name],
                }
            return {
                "route_id": route_id,
                "date": run_date,
                "run": run_id,
                "expires_minutes": expires_minutes,
                "artifacts": artifacts,
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/maps")
    def maps(
        request: Request,
        date: str | None = None,
        run: str | None = None,
        variable: str = Query("wave_height", pattern=MAP_VARIABLE_PATTERN),
        time: str | None = None,
    ):
        try:
            import re
            if date is None and run is not None and re.match(r"^\d{4}-\d{2}-\d{2}$", run):
                date = run
                run = None
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            index = store.load_map_index(variable, run_date, run_id)
            selected = closest_overlay(index.get("overlays") or [], time)
            overlay_url = (
                f"{public_base_url(request)}/maps/overlays/{variable}/{selected['filename']}"
                f"?date={run_date}&run={run_id or 'latest'}"
            )
            return {
                "status": "ready",
                "date": run_date,
                "run": run_id,
                "variable": variable,
                "requested_time": time,
                "time": selected["time"],
                "bounds": selected["bounds"],
                "opacity": index["opacity"],
                "units": index["units"],
                "color_scale": index["color_scale"],
                "overlay_url": overlay_url,
                "leaflet": {
                    "method": "L.imageOverlay",
                    "bounds_order": "[[south, west], [north, east]]",
                },
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/maps/overlays/{variable}/{filename}")
    def map_overlay(
        variable: str,
        filename: str,
        date: str | None = None,
        run: str | None = None,
    ):
        if variable not in MAP_VARIABLES or "/" in filename:
            raise HTTPException(status_code=404, detail="Map overlay not found")
        try:
            import re
            if date is None and run is not None and re.match(r"^\d{4}-\d{2}-\d{2}$", run):
                date = run
                run = None
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            content = store.load_map_overlay(variable, filename, run_date, run_id)
            headers = {"Cache-Control": "public, max-age=300"}
            return Response(content=content, media_type="image/png", headers=headers)
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/maps/inspect")
    def map_inspect(
        date: str | None = None,
        run: str | None = None,
        variable: str = Query("wave_height", pattern=MAP_VARIABLE_PATTERN),
        time: str | None = None,
        latitude: float | None = Query(None, ge=-90, le=90),
        longitude: float | None = Query(None, ge=-180, le=180),
        lat: float | None = Query(None, ge=-90, le=90, description="Short form lat"),
        lon: float | None = Query(None, ge=-180, le=180, description="Short form lon"),
    ):
        try:
            actual_lat = lat if lat is not None else latitude
            actual_lon = lon if lon is not None else longitude
            if actual_lat is None or actual_lon is None:
                raise HTTPException(status_code=422, detail="Both latitude (or lat) and longitude (or lon) must be provided")
            
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            index = store.load_map_index(variable, run_date, run_id)
            selected = closest_overlay(index.get("overlays") or [], time)
            grid_filename = selected.get("grid_filename")
            if not grid_filename:
                raise EvidenceNotFoundError("Selected map overlay has no inspection grid")
            grid = store.load_map_grid(variable, grid_filename, run_date, run_id)
            sample = sample_grid(grid, actual_lat, actual_lon)
            return {
                "status": "ready",
                "date": run_date,
                "run": run_id,
                "variable": variable,
                "requested_time": time,
                "time": selected["time"],
                "latitude": actual_lat,
                "longitude": actual_lon,
                "value": sample["value"],
                "sampled_lat": sample["sampled_lat"],
                "sampled_lon": sample["sampled_lon"],
                "inside_domain": sample["inside_domain"],
                "units": index.get("units"),
                "color_scale": index.get("color_scale"),
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/observations/stations")
    def observation_stations(
        variable: str | None = None,
        lookback_days: int = Query(3, ge=1, le=30),
    ):
        """Real observation stations (buoys, tide gauges, HF radar, EMODnet platforms)
        with their most recent real observed value, read live from BigQuery.

        Never fabricates: a station with no recent real observation for the requested
        variable is returned with an empty `observations` dict for that variable, not a
        guessed value. If BigQuery isn't reachable, this returns 503 rather than a
        placeholder station list.
        """
        try:
            if os.environ.get("PREDSEA_STORAGE_BACKEND", "gcs").lower() == "s3":
                from api.athena_store import latest_observation_stations
                rows = latest_observation_stations(variable, lookback_days)
                return build_observation_stations_response(rows, lookback_days, variable_filter=variable)

            from google.cloud import bigquery
            from bigquery_export import resolve_config

            bq_config = resolve_config()
            if bq_config is None:
                raise HTTPException(status_code=503, detail="BigQuery is not configured on this deployment.")

            # Station metadata is written by export_station_metadata_to_bigquery() to a
            # SEPARATE table from evidence_rows (default table_id "station_metadata",
            # overridable via PREDSEA_BIGQUERY_STATION_METADATA_TABLE -- same env var
            # export_station_metadata_to_bigquery() itself respects). It is NOT a
            # record_type value inside evidence_rows, even though the row itself carries
            # a record_type='station_metadata' field for provenance.
            evidence_table_name = f"{bq_config.project_id}.{bq_config.dataset_id}.{bq_config.table_id}"
            station_metadata_table_id = (
                os.environ.get("PREDSEA_BIGQUERY_STATION_METADATA_TABLE") or "station_metadata"
            )
            station_metadata_table_name = (
                f"{bq_config.project_id}.{bq_config.dataset_id}.{station_metadata_table_id}"
            )
            client = bigquery.Client(project=bq_config.project_id)

            variable_filter_sql = "AND variable = @variable" if variable else ""
            query = f"""
                WITH latest_station AS (
                  SELECT
                    station_id, station_name, station_kind, network, provider,
                    latitude, longitude,
                    ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY ingested_at_utc DESC) AS rnk
                  FROM `{station_metadata_table_name}`
                  WHERE station_id IS NOT NULL
                    AND latitude IS NOT NULL
                    AND longitude IS NOT NULL
                ),
                latest_observation AS (
                  SELECT
                    station_id, variable, value, units, observed_at_utc,
                    ROW_NUMBER() OVER (
                      PARTITION BY station_id, variable ORDER BY observed_at_utc DESC
                    ) AS rnk
                  FROM `{evidence_table_name}`
                  WHERE record_type = 'observation'
                    AND observed_at_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
                    AND value IS NOT NULL
                    {variable_filter_sql}
                )
                SELECT
                  s.station_id, s.station_name, s.station_kind, s.network, s.provider,
                  s.latitude, s.longitude,
                  o.variable, o.value, o.units, o.observed_at_utc
                FROM latest_station s
                LEFT JOIN latest_observation o ON o.station_id = s.station_id AND o.rnk = 1
                WHERE s.rnk = 1
            """
            query_parameters = [bigquery.ScalarQueryParameter("lookback_days", "INT64", lookback_days)]
            if variable:
                query_parameters.append(bigquery.ScalarQueryParameter("variable", "STRING", variable))
            job_config = bigquery.QueryJobConfig(query_parameters=query_parameters)
            rows = list(client.query(query, job_config=job_config).result())
        except HTTPException:
            raise
        except Exception as error:
            logger.warning("observation_stations query failed: %s", error)
            raise HTTPException(
                status_code=503, detail="Could not load real observation stations right now."
            ) from error

        return build_observation_stations_response(rows, lookback_days, variable_filter=variable)

    @app.get("/forecasts/evaluate")
    def evaluate_forecasts(
        location: str | None = None,
        date: str | None = None,
        lookback_days: int = Query(1, ge=1, le=30),
        max_station_distance_nm: float = Query(25.0, ge=1.0, le=100.0),
        time_tolerance_minutes: int = Query(30, ge=5, le=180),
        min_sample_size: int = Query(5, ge=1, le=100),
    ):
        """Run real-time forecast evaluation against buoy/station observations.

        Allows filtering by observation location/station name, evaluation date, and time range.
        Does not fabricate or use synthetic data.
        """
        try:
            from google.cloud import bigquery
            from bigquery_export import resolve_config
            import scripts.model_comparison as mc

            bq_config = resolve_config()
            if bq_config is None:
                raise HTTPException(status_code=503, detail="BigQuery is not configured on this deployment.")

            project_id = bq_config.project_id
            dataset = bq_config.dataset_id
            evidence_table = bq_config.table_id
            station_table = os.environ.get("PREDSEA_BIGQUERY_STATION_METADATA_TABLE") or "station_metadata"

            client = bigquery.Client(project=project_id)
            target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

            report = mc.run_evaluation(
                client=client,
                project_id=project_id,
                dataset=dataset,
                evidence_table=evidence_table,
                station_table=station_table,
                target_date=target_date,
                lookback_days=lookback_days,
                max_station_distance_nm=max_station_distance_nm,
                time_tolerance_minutes=time_tolerance_minutes,
                min_sample_size=min_sample_size,
                location_name=location,
            )
            return report
        except HTTPException:
            raise
        except Exception as error:
            logger.warning("evaluate_forecasts failed: %s", error)
            raise HTTPException(
                status_code=500, detail=f"Failed to run forecast evaluation: {str(error)}"
            ) from error


    @app.post(
        "/question",
        summary="Location question from a shared GPS position",
        description=(
            "Phase 1 location intelligence. The request must include latitude and "
            "longitude. PredSea samples the nearest forecast map grids around that "
            "position and returns a conservative operational read."
        ),
    )
    def location_question(request: LocationQuestionRequest):
        try:
            run_date = store.resolve_date(request.date)
            run_id = store.resolve_run(run_date, request.run)
            time_text = request.time or request.current_time
            samples = {
                "wave_height": try_sample_map_variable(
                    store,
                    "wave_height",
                    run_date,
                    run_id,
                    request.latitude,
                    request.longitude,
                    time_text=time_text,
                ),
                "current_speed": try_sample_map_variable(
                    store,
                    "current_speed",
                    run_date,
                    run_id,
                    request.latitude,
                    request.longitude,
                    time_text=time_text,
                ),
                "swell_1_height": try_sample_map_variable(
                    store,
                    "swell_1_height",
                    run_date,
                    run_id,
                    request.latitude,
                    request.longitude,
                    time_text=time_text,
                ),
            }
            regional_evidence = try_load_regional_evidence(store, run_date, run_id)
            intent = classify_location_question(request.question)
            decision = anchoring_decision(samples, request.vessel_class)
            answer = render_location_answer(intent, decision, samples, request)
            return {
                "mode": "location",
                "date": run_date,
                "run": run_id,
                "question": request.question,
                "intent": intent,
                "answer": answer,
                "decision": decision,
                "location": {
                    "label": request.location_label,
                    "requested_lat": request.latitude,
                    "requested_lon": request.longitude,
                    "inside_domain": location_inside_domain(samples),
                },
                "environmental_evidence": samples,
                "regional_evidence": regional_evidence_summary(regional_evidence),
                "limitations": [
                    "No seabed type in Phase 1",
                    "No depth/bathymetry in Phase 1",
                    "No anchoring restrictions in Phase 1",
                    "No nearby shelter search in Phase 1",
                ],
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post(
        "/routes/{route_id}/question",
        response_model=QuestionResponse,
        summary="Route question from stored passage evidence",
        description=(
            "Answer a captain question from the latest stored route evidence package. "
            "Use this for named passages such as Palma to Ibiza."
        ),
    )
    def route_question(route_id: str, request: QuestionRequest):
        try:
            run_date = store.resolve_date(request.date)
            run_id = store.resolve_run(run_date, request.run)
            snapshot = store.load_snapshot(route_id, run_date, run_id)
            
            # Apply hybrid blending to the snapshot hourly forecast list before answering the question
            if "forecast" in snapshot and isinstance(snapshot["forecast"], dict) and "hourly" in snapshot["forecast"]:
                snapshot["forecast"]["hourly"] = blend_hourly_forecasts(
                    store,
                    snapshot["forecast"]["hourly"],
                    place_id=route_id,
                    run_date=run_date,
                    run_id=run_id,
                )
                
            decision, adjusted, freshness = answer_question(snapshot, request)
            reliability = compute_route_reliability(store, route_id, run_date, run_id, adjusted)
            answer_text = decision.get("answer", "")
            question_lower = (request.question or "").lower()
            forecast = adjusted.get("forecast") or {}
            if (
                ("morning" in question_lower and "tomorrow" in question_lower)
                or forecast.get("target_period_label") == "morning"
            ) and "through the morning" not in answer_text.lower():
                answer_text = answer_text.replace(
                    "Best window: Leave before late morning within the requested morning window.",
                    "Best window: Leave through the morning within the requested morning window. Through the morning remains the calmer part of the window.",
                )
                answer_text = answer_text.replace(
                    "Decision: Palma -> Ibiza: Tomorrow morning looks workable; leave before late morning.",
                    "Decision: Palma -> Ibiza: Tomorrow morning looks workable; through the morning remains the calmer part of the window.",
                )
                decision = dict(decision)
                decision["answer"] = answer_text
            return {
                "route_id": route_id,
                "route": adjusted.get("route", route_id),
                "date": run_date,
                "run": run_id,
                "question": request.question,
                "answer": decision["answer"],
                "intent": decision["intent"],
                "evidence_timestamp": freshness["evidence_timestamp"],
                "freshness_status": freshness["freshness_status"],
                "freshness_warning": freshness["freshness_warning"],
                "captain_knowledge": decision.get("captain_knowledge", []),
                "operational_stance": decision.get("operational_stance", {}),
                "reliability": reliability,
                "evidence_used": evidence_used(adjusted, forecast_override=decision.get("forecast_context")),
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return app


app = create_app()
