from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from files.route_store import RouteStore as _BaseRouteStore

logger = logging.getLogger(__name__)

try:
    from api.config import DEFAULT_ROUTE_GCS_PREFIX
except ImportError:
    DEFAULT_ROUTE_GCS_PREFIX = "gs://predsea-daily-outputs/routes"

DEFAULT_API_TIMEZONE = "Europe/Madrid"


class RouteStore(_BaseRouteStore):
    def load_from_gcs(self, gcs_prefix: str, date_str: str) -> None:
        super().load_from_gcs(gcs_prefix, date_str)
        self._loaded_date = date_str

    def load_latest_from_gcs(
        self,
        gcs_prefix: str = DEFAULT_ROUTE_GCS_PREFIX,
        preferred_date: Optional[str] = None,
        fallback_days: int = 7,
    ) -> Optional[str]:
        preferred_date = preferred_date or current_local_date()
        candidates = [preferred_date]
        try:
            base = date_type.fromisoformat(preferred_date)
        except ValueError:
            base = None
        if base is not None:
            for offset in range(1, max(1, fallback_days) + 1):
                candidates.append((base - timedelta(days=offset)).isoformat())

        last_error = None
        for candidate in candidates:
            try:
                self.load_from_gcs(gcs_prefix, date_str=candidate)
                return candidate
            except Exception as error:
                last_error = error
                logger.info("RouteStore load failed for %s: %s", candidate, error)

        if last_error is not None:
            logger.warning("Unable to load precomputed routes from %s: %s", gcs_prefix, last_error)
        return None

    def ensure_loaded(
        self,
        gcs_prefix: str = DEFAULT_ROUTE_GCS_PREFIX,
        preferred_date: Optional[str] = None,
        fallback_days: int = 7,
    ) -> Optional[str]:
        preferred_date = preferred_date or current_local_date()
        if self._results and self._loaded_date == preferred_date:
            return self._loaded_date
        return self.load_latest_from_gcs(
            gcs_prefix=gcs_prefix,
            preferred_date=preferred_date,
            fallback_days=fallback_days,
        )


def current_local_date(timezone_name: str = DEFAULT_API_TIMEZONE) -> str:
    try:
        return datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()
