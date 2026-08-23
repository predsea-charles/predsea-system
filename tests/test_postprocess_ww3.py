from scripts.postprocess_ww3 import build_ounf_input


def test_ounf_input_includes_all_required_traditional_control_records():
    records = [line for line in build_ounf_input().splitlines() if not line.startswith("$")]

    assert records == [
        "20260805 000000 3600 25",
        "N",
        "HS DIR SPR WND DTD FC CFX",
        "3 4 2 1",
        "0 1 2",
        "T",
        "ww3.",
        "8",
        "1 1000000 1 1000000",
    ]
