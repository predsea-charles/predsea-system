#!/usr/bin/env python3
"""
PredSea Weekly Model Bias Computation Script.
Runs weekly (typically via Cloud Scheduler) to calculate mean bias, RMSE, and correlation
metrics between our own models (WRF, CROCO, SWAN) and physical buoy observations.
Upserts the computed metrics into BigQuery predsea_validation.model_bias table.
"""
from __future__ import annotations

import argparse
import sys
from google.cloud import bigquery


def compute_bias_metrics(
    project_id: str | None,
    dataset: str,
    table: str,
    evidence_rows_table: str,
    lookback_days: int,
    dry_run: bool = False
):
    """
    Computes bias metrics comparing forecast vs observation data
    and merges/upserts results into BigQuery.
    """
    client = bigquery.Client(project=project_id)
    project = project_id or client.project

    source_table_ref = f"{project}.{dataset}.{evidence_rows_table}"
    target_table_ref = f"{project}.{dataset}.{table}"

    print(f"📈 Starting model bias computation across the last {lookback_days} days...")
    print(f"   Source table: `{source_table_ref}`")
    print(f"   Target table: `{target_table_ref}`")

    # Define the core subquery that computes the stats
    subquery = f"""
        WITH matched_data AS (
          SELECT 
            fc.provider,
            obs.station_id,
            fc.variable,
            EXTRACT(MONTH FROM fc.target_time_utc) as month,
            EXTRACT(HOUR FROM fc.target_time_utc) as hour,
            fc.value as fc_val,
            obs.value as obs_val
          FROM `{source_table_ref}` fc
          JOIN `{source_table_ref}` obs
            ON fc.reference_station_id = obs.station_id
            AND fc.variable = obs.variable
            AND fc.target_time_utc = obs.observed_at_utc
          WHERE fc.record_type = 'forecast'
            AND obs.record_type = 'observation'
            AND fc.target_time_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_days} DAY)
            AND obs.observed_at_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_days} DAY)
            -- NOTE: was 'predsea_wrf', 'predsea_roms', 'predsea_swan' between the two
            -- 2026-07-02 fixes. scripts/daily_orchestrator.py never calls
            -- roms_forecast_ingestor.py -- the real ocean-model providers it ingests are
            -- 'predsea_croco' and 'predsea_nemo' (see croco_forecast_ingestor.py /
            -- nemo_forecast_ingestor.py). 'predsea_roms' rows only exist if someone runs
            -- roms_forecast_ingestor.py by hand, which isn't part of the automatic pipeline.
            AND fc.provider IN ('predsea_wrf', 'predsea_croco', 'predsea_nemo', 'predsea_swan')
            AND fc.value IS NOT NULL
            AND obs.value IS NOT NULL
            -- KNOWN LIMITATION (see model_comparison.py for the fix): fc.reference_station_id
            -- is a place/route-point id (e.g. "palma", "palma_ibiza_3"), not a real buoy
            -- station id, so this exact-match join will return ~0 rows against real data
            -- until forecast rows are matched to observation stations by nearest distance
            -- instead of by id equality. Do not treat an empty result here as "no bias" --
            -- it currently means "the join can't find the stations at all".
        )
        SELECT 
          provider,
          station_id,
          variable,
          month,
          hour,
          COUNT(*) as data_points,
          AVG(fc_val - obs_val) as mean_bias,
          SQRT(AVG(POW(fc_val - obs_val, 2))) as rmse,
          COALESCE(CORR(fc_val, obs_val), 0.0) as correlation
        FROM matched_data
        GROUP BY provider, station_id, variable, month, hour
        ORDER BY provider, station_id, variable, month, hour
    """

    if dry_run:
        print("⚡ [DRY RUN] Executing query to inspect computed metrics without modifying the table...")
        try:
            query_job = client.query(subquery)
            results = list(query_job.result())
            print(f"\n✅ Dry run complete. Found {len(results)} matching metric groups:")
            if results:
                print(f"{'Provider':<15} | {'Station ID':<15} | {'Variable':<15} | {'Month':<5} | {'Hour':<5} | {'Count':<6} | {'Bias':<10} | {'RMSE':<10} | {'Corr':<6}")
                print("-" * 100)
                for r in results[:20]:
                    print(f"{r.provider:<15} | {r.station_id:<15} | {r.variable:<15} | {r.month:<5} | {r.hour:<5} | {r.data_points:<6} | {r.mean_bias:<10.4f} | {r.rmse:<10.4f} | {r.correlation:<6.3f}")
                if len(results) > 20:
                    print(f"... and {len(results) - 20} more rows.")
            else:
                print("ℹ️ No matched forecast-observation pairs found for the given lookback period.")
        except Exception as e:
            print(f"❌ Error during dry run query: {e}")
            sys.exit(1)
        return

    # Execute MERGE query
    merge_query = f"""
        MERGE `{target_table_ref}` target
        USING (
          {subquery}
        ) source
        ON target.provider = source.provider
          AND target.station_id = source.station_id
          AND target.variable = source.variable
          AND target.month = source.month
          AND target.hour = source.hour
        WHEN MATCHED THEN
          UPDATE SET 
            mean_bias = source.mean_bias,
            rmse = source.rmse,
            correlation = source.correlation,
            updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
          INSERT (provider, station_id, variable, month, hour, mean_bias, rmse, correlation, updated_at)
          VALUES (source.provider, source.station_id, source.variable, source.month, source.hour, source.mean_bias, source.rmse, source.correlation, CURRENT_TIMESTAMP())
    """

    print("🚀 Executing merge operation in BigQuery...")
    try:
        query_job = client.query(merge_query)
        # Wait for the job to complete
        query_job.result()
        
        # Query job statistics
        num_dml_affected_rows = query_job.num_dml_affected_rows
        print(f"✅ Merge operation completed successfully.")
        print(f"ℹ️ Total rows inserted/updated: {num_dml_affected_rows}")
    except Exception as e:
        print(f"❌ Error executing merge operation: {e}")
        sys.exit(1)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Calculate and upsert weekly model bias stats.")
    parser.add_argument("--project", help="GCP Project ID (defaults to active gcloud project).")
    parser.add_argument("--dataset", default="predsea_validation", help="BigQuery dataset containing tables.")
    parser.add_argument("--table", default="model_bias", help="Target table to upsert stats into.")
    parser.add_argument("--evidence-rows-table", default="evidence_rows", help="Source evidence rows table.")
    parser.add_argument("--lookback-days", type=int, default=7, help="Number of lookback days for validation metrics.")
    parser.add_argument("--dry-run", action="store_true", help="Print stats instead of upserting into table.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    compute_bias_metrics(
        project_id=args.project,
        dataset=args.dataset,
        table=args.table,
        evidence_rows_table=args.evidence_rows_table,
        lookback_days=args.lookback_days,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
