"""Avoid silently choosing a lens in ambiguous calibration deliveries."""
import pytest
from pyargus.imagery.camera import find_cal

def test_missing_image_sidecar_refuses_multiple_cameras(tmp_path):
    for name in ("nadir.cal", "port.cal"):
        (tmp_path / name).write_text("{}")
    with pytest.raises(ValueError, match="multiple .cal files"):
        find_cal(tmp_path / "flight_N_001.JPG")

@pytest.mark.parametrize("sidecar", ["frame.JPG.cal", "frame.cal"])
def test_exact_sidecar_wins_over_ambiguous_folder(tmp_path, sidecar):
    for name in (sidecar, "nadir.cal", "port.cal"):
        (tmp_path / name).write_text("{}")
    assert find_cal(tmp_path / "frame.JPG") == tmp_path / sidecar

def test_child_flight_calibration_is_not_parent_fallback(tmp_path):
    other = tmp_path / "other_flight"
    other.mkdir()
    (other / "camera.cal").write_text("{}")
    assert find_cal(tmp_path / "frame.JPG") is None

def test_unique_uppercase_sidecar_is_usable(tmp_path):
    shared = tmp_path / "camera.CAL"
    shared.write_text("{}")
    assert find_cal(tmp_path / "frame.JPG") == shared
