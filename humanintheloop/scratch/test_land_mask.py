import os
import xarray as xr
import numpy as np

base_dir = "/Users/charles.santana/PredSea/predsea-system/humanintheloop"
waves_path = os.path.join(base_dir, "mvp_data", "balearic_waves.nc")

print("Loading dataset from:", waves_path)
ds = xr.open_dataset(waves_path)

lats = ds.latitude.values
lons = ds.longitude.values
wave_height_matrix = ds.VHM0.values

def _find_nearest_lat_idx(lat: float) -> int:
    return int(np.abs(lats - lat).argmin())

def _find_nearest_lon_idx(lon: float) -> int:
    return int(np.abs(lons - lon).argmin())

def _snap_to_water(lat: float, lon: float) -> tuple[int, int]:
    start_lat_idx = _find_nearest_lat_idx(lat)
    start_lon_idx = _find_nearest_lon_idx(lon)
    
    num_lats, num_lons = wave_height_matrix.shape[1], wave_height_matrix.shape[2]
    
    # Check if the direct mapping is already water
    if not np.isnan(wave_height_matrix[0, start_lat_idx, start_lon_idx]):
        return start_lat_idx, start_lon_idx
        
    # BFS
    queue = [(start_lat_idx, start_lon_idx)]
    visited = {(start_lat_idx, start_lon_idx)}
    
    while queue:
        curr_lat, curr_lon = queue.pop(0)
        
        # Check neighbors
        for d_lat, d_lon in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
            n_lat = curr_lat + d_lat
            n_lon = curr_lon + d_lon
            
            if 0 <= n_lat < num_lats and 0 <= n_lon < num_lons:
                if (n_lat, n_lon) not in visited:
                    visited.add((n_lat, n_lon))
                    if not np.isnan(wave_height_matrix[0, n_lat, n_lon]):
                        return n_lat, n_lon
                    queue.append((n_lat, n_lon))
                    
    return start_lat_idx, start_lon_idx

# Test Palma
p_lat, p_lon = _snap_to_water(39.52, 2.58)
print(f"Palma snapped: lat_idx={p_lat} (val={lats[p_lat]}), lon_idx={p_lon} (val={lons[p_lon]}), wave value={wave_height_matrix[0, p_lat, p_lon]}")

# Test Alcudia
a_lat, p_lon = _snap_to_water(39.84, 3.14)
print(f"Alcudia snapped: lat_idx={a_lat} (val={lats[a_lat]}), lon_idx={p_lon} (val={lons[p_lon]}), wave value={wave_height_matrix[0, a_lat, p_lon]}")
