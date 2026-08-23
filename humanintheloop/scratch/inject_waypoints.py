import json
from pathlib import Path

def main():
    project_root = Path(__file__).resolve().parent.parent
    routes_path = project_root / "routes.json"
    
    with open(routes_path, "r", encoding="utf-8") as f:
        routes = json.load(f)
        
    # Coast-hugging waypoints from Marseille -> Sète -> Barcelona -> Palma
    # we use standard dict structure {"latitude": lat, "longitude": lng}
    waypoints = [
        {"latitude": 43.30, "longitude": 5.37, "name": "Marseille"},
        {"latitude": 43.3224, "longitude": 5.3141},
        {"latitude": 43.1864, "longitude": 5.2125},
        {"latitude": 43.1443, "longitude": 5.0394},
        {"latitude": 43.3504, "longitude": 4.2869},
        {"latitude": 43.51, "longitude": 4.0589, "name": "Sète"},
        {"latitude": 43.3504, "longitude": 3.7499},
        {"latitude": 42.7696, "longitude": 3.4277, "name": "Perpignan Approach"},
        {"latitude": 42.4537, "longitude": 3.4948, "name": "Cap de Creus"},
        {"latitude": 41.7972, "longitude": 3.3104, "name": "Costa Brava"},
        {"latitude": 41.30, "longitude": 2.50},
        {"latitude": 41.3122, "longitude": 2.2094, "name": "Barcelona"},
        {"latitude": 41.1761, "longitude": 2.3141},
        {"latitude": 40.9676, "longitude": 2.4744},
        {"latitude": 40.6715, "longitude": 2.4517},
        {"latitude": 40.5312, "longitude": 2.4409},
        {"latitude": 40.3979, "longitude": 2.4306},
        {"latitude": 40.3077, "longitude": 2.4237},
        {"latitude": 40.00, "longitude": 2.40},
        {"latitude": 39.4254, "longitude": 2.2681, "name": "Mallorca West"},
        {"latitude": 39.5696, "longitude": 2.6502, "name": "Palma"}
    ]
    
    routes["marseille_palma"]["waypoints"] = waypoints
    
    with open(routes_path, "w", encoding="utf-8") as f:
        json.dump(routes, f, indent=2, ensure_ascii=False)
        
    print("Successfully updated routes.json with marseille_palma coast-hugging waypoints!")

if __name__ == "__main__":
    main()
