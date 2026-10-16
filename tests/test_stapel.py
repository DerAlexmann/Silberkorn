"""Stapel: freie Namen und gepruefter Namenszusatz."""

import pytest

pytest.importorskip("cupy")

from silberkorn.stapel import freier_name, zusatz_pruefen  # noqa: E402


def test_freier_name(tmp_path):
    assert freier_name(str(tmp_path), "a", ".jpg").endswith("a.jpg")
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "a-2.jpg").write_bytes(b"x")
    assert freier_name(str(tmp_path), "a", ".jpg").endswith("a-3.jpg")


@pytest.mark.parametrize("text, erwartet", [
    ("-bearbeitet", "-bearbeitet"), ("  _v2 ", "_v2"), ("", ""),
    ("/../x", None), ("a:b", None), ("ende.", None), ("tab\tx", None),
])
def test_zusatz(text, erwartet):
    assert zusatz_pruefen(text) == erwartet
