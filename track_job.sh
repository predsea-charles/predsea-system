!#/bin/bash


while true; do
  STATUS=$(aws batch describe-jobs --jobs a26241e3-f001-4171-aae0-bff042adb4c1 --region eu-west-1 --query 'jobs[0].status' --output text)
  echo "$(date +%H:%M:%S) $STATUS"
  [[ "$STATUS" != "SUBMITTED" && "$STATUS" != "PENDING" && "$STATUS" != "RUNNABLE" && "$STATUS" != "STARTING" && "$STATUS" != "RUNNING" ]] && break
  sleep 30
done
