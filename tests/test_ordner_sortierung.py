"""Natuerliche Sortierung der Ordneransicht."""

import pytest

pytest.importorskip("PySide6")

from silberkorn.ordner_seite import _natuerlich  # noqa: E402 - erst nach der Pruefung


def test_zahlen_nach_wert():
    namen = ["Bild10.jpg", "bild2.jpg", "Bild1.jpg"]
    assert sorted(namen, key=_natuerlich) == ["Bild1.jpg", "bild2.jpg", "Bild10.jpg"]


def test_hochgestellte_und_fremde_ziffern():
    # "²" ist fuer isdigit() eine Ziffer, int() kennt sie aber nicht
    namen = ["Raum 1².jpg", "Raum 1.jpg", "x³y.png", "Bild ٣.jpg", "Bild 2.jpg"]
    assert sorted(namen, key=_natuerlich) == [
        "Bild 2.jpg", "Bild ٣.jpg", "Raum 1.jpg", "Raum 1².jpg", "x³y.png"]
