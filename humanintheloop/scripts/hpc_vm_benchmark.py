#!/usr/bin/env python3
"""
scripts/hpc_vm_benchmark.py
Benchmarking script for PredSea HPC VMs. Spins up spot instances, runs sysbench CPU/Memory
and MPI PingPong, retrieves timing/cost data, and uploads reports to GCS.
"""

import os
import sys
import json
import time
import subprocess
from google.cloud import storage

ZONE = "europe-west1-b"
BUCKET_NAME = "predsea-hpc-outputs"

VM_CONFIGS = {
    "c2d-standard-16": {"vcpus": 16, "price_per_hour": 0.19, "ram_gb": 64},
    "c2d-standard-32": {"vcpus": 32, "price_per_hour": 0.38, "ram_gb": 128},
    "c2d-standard-56": {"vcpus": 56, "price_per_hour": 0.665, "ram_gb": 224},
    "c3-highcpu-44": {"vcpus": 44, "price_per_hour": 0.55, "ram_gb": 88}
}

STARTUP_SCRIPT_TEMPLATE = """#!/bin/bash
set -euo pipefail

# Export environment variables for the benchmark run
VM_TYPE="{vm_type}"
NUM_CPUS={vcpus}
BUCKET_NAME="{bucket_name}"

echo "Starting benchmark for $VM_TYPE with $NUM_CPUS vCPUs..."

# Update and install benchmark suite
apt-get update
apt-get install -y sysbench mpich intel-mpi-benchmarks curl wget git

START_TIME=$(date +%s)

# Run CPU benchmark (representative of Fortran MPI workload)
sysbench cpu --cpu-max-prime=50000 --threads=$NUM_CPUS run > sysbench_cpu.log

# Run Memory bandwidth benchmark
sysbench memory --memory-total-size=10G --threads=$NUM_CPUS run > sysbench_mem.log

# Run MPI point-to-point latency
IMB_PATH=$(find /usr -name "IMB-MPI1" | head -n 1 || true)
if [ -z "$IMB_PATH" ]; then
    # Compile a simple C-based PingPong program if packages don't provide it
    cat << 'EOF' > pingpong.c
#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char** argv) {
    MPI_Init(&argc, &argv);
    int rank, size;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    int val = 0;
    double start = MPI_Wtime();
    for (int i = 0; i < 10000; i++) {
        if (rank == 0) {
            MPI_Send(&val, 1, MPI_INT, 1, 0, MPI_COMM_WORLD);
            MPI_Recv(&val, 1, MPI_INT, 1, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
        } else if (rank == 1) {
            MPI_Recv(&val, 1, MPI_INT, 0, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
            MPI_Send(&val, 1, MPI_INT, 0, 0, MPI_COMM_WORLD);
        }
    }
    double end = MPI_Wtime();
    if (rank == 0) {
        printf("MPI PingPong 10000 round-trips: %f sec (Average latency: %f us)\\n", end - start, (end - start) / 20000.0 * 1e6);
    }
    MPI_Finalize();
    return 0;
}
EOF
    mpicc -O3 pingpong.c -o pingpong
    mpirun -np 2 ./pingpong > mpi_pingpong.log
else
    mpirun -np 2 "$IMB_PATH" PingPong > mpi_pingpong.log
fi

END_TIME=$(date +%s)
WALLCLOCK_MINUTES=$(( (END_TIME - START_TIME + 59) / 60 ))

# Extract key metrics safely
CPU_TIME=$(grep "total time:" sysbench_cpu.log | awk '{{print $3}}' | tr -d 's' || echo "0")
MEM_SPEED=$(grep "transferred" sysbench_mem.log | head -n 1 | awk '{{print $4}}' | tr -d '()' || echo "0")
MPI_LATENCY=$(grep -E "(Average latency|PingPong)" mpi_pingpong.log | grep -E -o "([0-9]+\\.[0-9]+)" | tail -n 1 || echo "0")

# Package into results JSON
cat <<EOF > benchmark_results.json
{{
  "vm_type": "$VM_TYPE",
  "vcpus": $NUM_CPUS,
  "sysbench_cpu_time_sec": $CPU_TIME,
  "sysbench_mem_speed_mbs": "$MEM_SPEED",
  "mpi_latency_us": "$MPI_LATENCY",
  "benchmark_wallclock_minutes": $WALLCLOCK_MINUTES
}}
EOF

# Upload logs and result to GCS
gsutil cp benchmark_results.json "gs://$BUCKET_NAME/benchmarks/$VM_TYPE/results.json"
gsutil cp sysbench_cpu.log "gs://$BUCKET_NAME/benchmarks/$VM_TYPE/sysbench_cpu.log"
gsutil cp sysbench_mem.log "gs://$BUCKET_NAME/benchmarks/$VM_TYPE/sysbench_mem.log"
gsutil cp mpi_pingpong.log "gs://$BUCKET_NAME/benchmarks/$VM_TYPE/mpi_pingpong.log"

echo "Benchmark for $VM_TYPE finished."
"""

def create_vm(vm_type, config):
    instance_name = f"predsea-hpc-benchmark-{vm_type}"
    vcpus = config["vcpus"]
    print(f"Creating VM: {instance_name}...")
    
    # Save the custom startup script to a local temp file
    startup_file = f"/tmp/startup_{vm_type}.sh"
    with open(startup_file, "w") as f:
        f.write(STARTUP_SCRIPT_TEMPLATE.format(
            vm_type=vm_type,
            vcpus=vcpus,
            bucket_name=BUCKET_NAME
        ))
        
    cmd = [
        "gcloud", "compute", "instances", "create", instance_name,
        f"--zone={ZONE}",
        f"--machine-type={vm_type}",
        "--provisioning-model=SPOT",
        "--instance-termination-action=DELETE",
        "--scopes=https://www.googleapis.com/auth/cloud-platform",
        f"--metadata-from-file=startup-script={startup_file}",
        "--labels=component=hpc-experiment",
        "--quiet"
    ]
    
    subprocess.run(cmd, check=True)
    os.remove(startup_file)
    return instance_name

def delete_vm(instance_name):
    print(f"Cleaning up VM: {instance_name}...")
    cmd = [
        "gcloud", "compute", "instances", "delete", instance_name,
        f"--zone={ZONE}",
        "--quiet"
    ]
    subprocess.run(cmd)

def wait_for_results(vm_type, timeout_minutes=25):
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob_path = f"benchmarks/{vm_type}/results.json"
    blob = bucket.blob(blob_path)
    
    print(f"Waiting for results file at gs://{BUCKET_NAME}/{blob_path}...")
    start_time = time.time()
    while time.time() - start_time < timeout_minutes * 60:
        if blob.exists():
            print("Results file found!")
            return json.loads(blob.download_as_text())
        time.sleep(15)
    raise TimeoutError(f"Benchmark run for {vm_type} timed out.")

def main():
    print("Starting PredSea HPC VM Benchmark pipeline...")
    results = []
    
    for vm_type, config in VM_CONFIGS.items():
        instance_name = None
        try:
            instance_name = create_vm(vm_type, config)
            # Wait for results to be uploaded by the VM's startup script
            raw_result = wait_for_results(vm_type)
            
            wallclock = raw_result["benchmark_wallclock_minutes"]
            hourly_rate = config["price_per_hour"]
            cost = round((wallclock / 60.0) * hourly_rate, 4)
            
            summary = {
                "vm_type": vm_type,
                "vcpus": config["vcpus"],
                "spot_price_per_hour_usd": hourly_rate,
                "benchmark_wallclock_minutes": wallclock,
                "benchmark_cost_usd": cost,
                "sysbench_cpu_time_sec": raw_result.get("sysbench_cpu_time_sec"),
                "sysbench_mem_speed_mbs": raw_result.get("sysbench_mem_speed_mbs"),
                "mpi_latency_us": raw_result.get("mpi_latency_us"),
                "estimated_wrf_5day_run_minutes": None,
                "estimated_wrf_5day_run_cost_usd": None
            }
            results.append(summary)
            print(f"Result for {vm_type}: {json.dumps(summary, indent=2)}")
            
        except Exception as e:
            print(f"Error benchmarking {vm_type}: {e}")
        finally:
            if instance_name:
                delete_vm(instance_name)
                
    # Write aggregated report
    report_blob_path = "reports/vm-benchmark.json"
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    
    # Save locally first
    report_file = "vm-benchmark.json"
    with open(report_file, "w") as f:
        json.dump(results, f, indent=2)
        
    blob = bucket.blob(report_blob_path)
    blob.upload_from_filename(report_file)
    print(f"Global benchmark report uploaded to gs://{BUCKET_NAME}/{report_blob_path}")
    
if __name__ == "__main__":
    main()
