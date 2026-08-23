import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Import the app resolver
from api.app import create_app

@pytest.fixture
def client():
    # Setup test environment
    with patch.dict("os.environ", {"PREDSEA_ENV": "test", "PREDSEA_BIGQUERY_DATASET": "test_dataset"}):
        app = create_app()
        with TestClient(app) as c:
            yield c

@patch("bigquery_export.resolve_config")
@patch("google.cloud.bigquery.Client")
@patch("scripts.model_comparison.run_evaluation")
def test_evaluate_forecasts_success(mock_run, mock_bq_client, mock_resolve, client):
    # Mock BigQuery config resolution
    mock_config = MagicMock()
    mock_config.project_id = "test-project"
    mock_config.dataset_id = "test-dataset"
    mock_config.table_id = "test-table"
    mock_resolve.return_value = mock_config

    # Mock the return value of run_evaluation
    mock_report = {
        "evaluation_date": "2026-07-06",
        "data_source": "real",
        "status": "compared",
        "variables": {
            "wind_speed": {
                "predsea_wrf": {"status": "compared", "metrics_own_model": {"rmse": 1.2}},
                "ecmwf_baseline": {"status": "compared", "metrics_baseline": {"rmse": 1.5}}
            }
        }
    }
    mock_run.return_value = mock_report

    # Call the endpoint
    response = client.get("/forecasts/evaluate?date=2026-07-06&location=Palma&lookback_days=2&min_sample_size=3")

    # Assertions
    assert response.status_code == 200
    assert response.json() == mock_report

    # Check mock call arguments
    mock_run.assert_called_once_with(
        client=mock_bq_client.return_value,
        project_id="test-project",
        dataset="test-dataset",
        evidence_table="test-table",
        station_table="station_metadata",
        target_date="2026-07-06",
        lookback_days=2,
        max_station_distance_nm=25.0,
        time_tolerance_minutes=30,
        min_sample_size=3,
        location_name="Palma"
    )

@patch("bigquery_export.resolve_config")
def test_evaluate_forecasts_not_configured(mock_resolve, client):
    # Mock BigQuery config resolution to None
    mock_resolve.return_value = None

    response = client.get("/forecasts/evaluate")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
