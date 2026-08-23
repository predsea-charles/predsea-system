# PredSea Web Demo

This is a lightweight static demo for the Visual Co-Captain experience.
It is intentionally not route-first: the main view is land context plus real
sea variables.

Run the demo from the repository root:

```bash
python -m http.server 8099 --bind 127.0.0.1
```

Then open:

```text
http://127.0.0.1:8099/web/
```

Regenerate the map layer from local NetCDF wave/current files:

```bash
./.venv311/bin/python scripts/export_ocean_conditions_layer.py \
  --waves humanintheloop/mvp_data/balearic_waves.nc \
  --currents humanintheloop/mvp_data/balearic_currents.nc \
  --output web/data/ocean_conditions.json \
  --time-index 5
```

The current demo page uses that JSON to draw wave height over the sea and
surface-current direction/speed arrows over a real basemap.
