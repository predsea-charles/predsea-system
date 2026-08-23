import sys
from google.cloud import bigquery

def main():
    client = bigquery.Client()
    print("Analyzing geographic coverage of stations...")
    
    # We define boxes for Spain, France, Italy (Med side)
    # Spain Med: Lat [35.0, 44.0], Lon [-10.0, 5.0]
    # France Med: Lat [41.0, 44.0], Lon [3.0, 10.0]
    # Italy Med: Lat [35.0, 46.0], Lon [6.0, 20.0]
    
    query = """
        SELECT 
            CASE 
                WHEN latitude BETWEEN 35.0 AND 44.0 AND longitude BETWEEN -10.0 AND 4.5 THEN 'Spain'
                WHEN latitude BETWEEN 41.0 AND 44.0 AND longitude BETWEEN 4.5 AND 10.0 THEN 'France (Med)'
                WHEN latitude BETWEEN 35.0 AND 46.0 AND longitude BETWEEN 10.0 AND 20.0 THEN 'Italy'
                ELSE 'Other/Atlantic'
            END AS region,
            provider,
            COUNT(*) as station_count
        FROM `predsea-api.predsea_validation.station_metadata`
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        GROUP BY region, provider
        ORDER BY region, station_count DESC
    """
    
    try:
        results = client.query(query).result()
        print("\nStations by Region and Provider:")
        print(f"{'Region':<15} | {'Provider':<25} | {'Count':<10}")
        print("-" * 56)
        for row in results:
            print(f"{row.region:<15} | {row.provider or 'None':<25} | {row.station_count:<10}")
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
