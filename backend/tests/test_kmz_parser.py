from pathlib import Path

from app.import_engine.kmz_importer import parse_kmz


def test_sutter_reference_kmz():
    path = Path(__file__).parent / "data" / "SUTTER_MASTER_FINAL_V2.kmz"
    result = parse_kmz(path.read_bytes())

    assert result.project_name == "SUTTER Master Project Final V2"
    assert len(result.features) == 26
    assert all(feature.geometry_type == "Point" for feature in result.features)
    assert all(feature.name.startswith("Pole ") for feature in result.features)
    assert result.errors == []
