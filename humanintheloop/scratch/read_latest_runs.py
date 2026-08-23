from google.cloud import storage
import json
import datetime

client = storage.Client()
bucket_name = "predsea-daily-outputs"
bucket = client.bucket(bucket_name)

# Let's scan from 2026-06-25 to 2026-07-06
start_date = datetime.date(2026, 6, 25)
end_date = datetime.date(2026, 7, 6)

delta = datetime.timedelta(days=1)
curr = start_date
while curr <= end_date:
    date_str = curr.strftime("%Y-%m-%d")
    blob = bucket.blob(f"predictions/{date_str}/latest_run.json")
    if blob.exists():
        try:
            content = blob.download_as_text()
            data = json.loads(content)
            validation = data.get("validation", {})
            print(f"Date: {date_str} | Run ID: {data.get('run_id')} | Obs: {validation.get('observation_rows')} | Fore: {validation.get('forecast_rows')} | Matched: {validation.get('matched_rows')}")
            print(f"  Variables: {data.get('regional_evidence', {}).get('available_variables')}")
        except Exception as e:
            print(f"Date: {date_str} | Error parsing: {e}")
    else:
        print(f"Date: {date_str} | No latest_run.json")
    curr += delta
