from pathlib import Path


def test_failed_vm_preserves_diagnostics_and_stops():
    startup = Path("scripts/vm_startup.sh").read_text()

    assert "local exit_code=$?" in startup
    assert "/workspace/outputs/FAILURE" in startup
    assert "shutdown -h now" in startup
    assert 'elif [[ ${exit_code} -eq 0 ]]' in startup
    assert 'gcloud compute instances delete "${NAME}"' in startup
    assert startup.index('elif [[ ${exit_code} -eq 0 ]]') < startup.index(
        'gcloud compute instances delete "${NAME}"'
    )
