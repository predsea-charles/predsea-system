#!/bin/bash

# Check Alboran
gcloud logging read "bf7f7d57" --project=predsea-api --limit=15 --order="desc" --format="value(textPayload, jsonPayload.message)"

# Check Algerian
gcloud logging read "928262c6" --project=predsea-api --limit=15 --order="desc" --format="value(textPayload, jsonPayload.message)"

# Check Tyrrhenian
gcloud logging read "6e198b0a" --project=predsea-api --limit=15 --order="desc" --format="value(textPayload, jsonPayload.message)"
