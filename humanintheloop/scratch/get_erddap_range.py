import requests
import pandas as pd
import io

url = (
    "https://data-erddap.emodnet-physics.eu/erddap/tabledap/ERD_EP_TS_WDIR_WSPD_NRT.csv"
    "?PLATFORMCODE,time,latitude,longitude,WSPD,WSPD_QC,WDIR,WDIR_QC"
    "&orderByMax(%22PLATFORMCODE,time%22)"
    "&latitude>=30.0&latitude<=46.0&longitude>=-10.0&longitude<=30.0"
)
print(f"Querying URL: {url}")
try:
    response = requests.get(url, timeout=30)
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        df = pd.read_csv(io.StringIO(response.text), skiprows=[1])
        print(f"Retrieved {len(df)} rows.")
        print(df.head(20))
        print("Time range:")
        print(df["time"].min(), "to", df["time"].max())
    else:
        print(f"Error Response: {response.text}")
except Exception as e:
    print(f"Failed to fetch: {e}")
