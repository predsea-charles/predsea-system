#!/usr/bin/env python3
# Helper script to update BigQuery dataset access list for PredSea SAs
# Uses the local authenticated 'bq' CLI to fetch and update dataset access list.
# This avoids Python SDK credential conflicts and uses the active gcloud identity.

import sys
import json
import subprocess
import os

def run_cmd(cmd: list[str]) -> str:
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command {' '.join(cmd)} failed:\n{result.stderr}")
    return result.stdout.strip()

def grant_access(dataset_id: str, email: str, role: str):
    print(f"👉 [INFO] Granting {role} on dataset {dataset_id} to service account: {email}")
    
    # 1. Fetch current dataset JSON metadata using bq CLI
    dataset_json_str = run_cmd(["bq", "show", "--format=prettyjson", dataset_id])
    dataset_data = json.loads(dataset_json_str)
    
    # 2. Extract access array
    access_list = dataset_data.get("access", [])
    
    # Ensure role is UPPERCASE ('READER' or 'WRITER')
    gcp_role = role.upper()
    if gcp_role not in ("READER", "WRITER", "OWNER"):
        raise ValueError(f"Invalid role: {role}")
        
    # Check if entry already exists
    exists = False
    for existing in access_list:
        if existing.get("userByEmail") == email:
            existing_role = existing.get("role")
            if existing_role == gcp_role or (gcp_role == "READER" and existing_role in ("WRITER", "OWNER")):
                print(f"   [SKIP] Access for {email} already exists with role {existing_role}.")
                exists = True
                break

    if not exists:
        # Create new access entry
        new_entry = {
            "role": gcp_role,
            "userByEmail": email
        }
        access_list.append(new_entry)
        dataset_data["access"] = access_list
        
        # 3. Write modified JSON to a temporary file
        temp_file = f"temp_{dataset_id.replace(':', '_').replace('.', '_')}.json"
        with open(temp_file, "w") as f:
            json.dump(dataset_data, f, indent=2)
            
        try:
            # 4. Update dataset using bq update --source
            print(f"   [INFO] Updating access with bq update --source...")
            run_cmd(["bq", "update", f"--source={temp_file}", dataset_id])
            print(f"   [SUCCESS] Successfully granted {gcp_role} access!")
        finally:
            # Clean up temp file
            if os.path.exists(temp_file):
                os.remove(temp_file)

def main():
    if len(sys.argv) != 4:
        print("Usage: python update_bq_access.py [dataset_id] [sa_email] [READER|WRITER]")
        sys.exit(1)
        
    dataset_id = sys.argv[1]
    email = sys.argv[2]
    role = sys.argv[3]
    
    try:
        grant_access(dataset_id, email, role)
    except Exception as e:
        print(f"❌ Error updating access: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
