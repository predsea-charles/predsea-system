from __future__ import annotations

from predsea.connectors.puertos_del_estado.common import (
    is_future_timestamp,
    normalize_text,
    parse_utc_timestamp,
    station_id_from_label,
    strip_accents,
    timestamp_text,
    to_float,
)


SOURCE_SYSTEM = "emodnet_physics"
SOURCE_LABEL = "EMODNET_PHYSICS"

