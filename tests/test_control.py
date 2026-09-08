import numpy as np
import pytest

from pyargus.formats import control


def test_pnez_and_penz_orders(tmp_path):
    path = tmp_path / "ctrl.csv"
    path.write_text("101,1000.0,2000.0,55.5,MARK\n102,1001.0,2001.0,56.5\n")
    ids, e, n, z = control.read_control_csv(path, "pnez")
    assert ids == ["101", "102"]
    assert np.allclose(n, [1000.0, 1001.0]) and np.allclose(e, [2000.0, 2001.0])
    ids, e, n, z = control.read_control_csv(path, "penz")
    assert np.allclose(e, [1000.0, 1001.0]) and np.allclose(n, [2000.0, 2001.0])
    assert np.allclose(z, [55.5, 56.5])


def test_order_is_never_guessed(tmp_path):
    path = tmp_path / "ctrl.csv"
    path.write_text("101,1.0,2.0,3.0\n")
    with pytest.raises(ValueError, match="order"):
        control.read_control_csv(path, "nezp")


def test_malformed_row_names_its_line(tmp_path):
    path = tmp_path / "ctrl.csv"
    path.write_text("101,1.0,2.0,3.0\n102,not-a-number,2.0,3.0\n")
    with pytest.raises(ValueError, match="line 2"):
        control.read_control_csv(path, "pnez")


def test_multiple_files_and_duplicate_ids(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("1,10.0,20.0,30.0\n")
    b.write_text("2,11.0,21.0,31.0\n")
    ids, e, n, z = control.read_control_csvs([a, b], "pnez")
    assert ids == ["1", "2"] and z.size == 2
    b.write_text("1,11.0,21.0,31.0\n")
    with pytest.raises(ValueError, match="duplicate"):
        control.read_control_csvs([a, b], "pnez")


def test_empty_file_refuses(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("\n")
    with pytest.raises(ValueError, match="no control rows"):
        control.read_control_csv(path, "pnez")
