"""Drucken: Lage auf dem Blatt, Vorbereitung des Bildes, Ausgabe als PDF statt auf Papier."""

from __future__ import annotations

import os
import re

import numpy as np
import pytest

from silberkorn import drucken
from silberkorn.drucken import Vorgaben, platzieren

ZOLL = drucken.MM_JE_ZOLL


def test_vorgaben_aus_der_datei():
    v = Vorgaben.aus_dict({"groesse": "13x18", "rand": 5, "randlos": True, "fuellen": 1,
                           "eigen_breite": 500.0, "drucker": 7})
    assert (v.groesse, v.rand, v.randlos) == ("13x18", 5.0, True)
    assert v.fuellen is False                    # 1 ist kein bool
    assert v.eigen_breite == drucken.EIGEN_MAX_CM and v.drucker == ""
    assert Vorgaben.aus_dict({"groesse": "a4"}).groesse == "seite"
    assert Vorgaben.aus_dict(None) == Vorgaben()
    assert Vorgaben(groesse="eigen", eigen_breite=12, eigen_hoehe=8).format_mm() == (120, 80)


def test_ganz_zeigen_mittig():
    """Hochformat 2000 x 3000 auf 100 x 100 mm: 66,7 x 100 mm, waagrecht mittig."""
    p = platzieren(2000, 3000, (10.0, 20.0, 100.0, 100.0))
    x, y, b, h = p.ziel
    assert (round(b, 3), h) == (66.667, 100.0)
    assert (round(x, 3), y) == (26.667, 20.0)
    assert p.ausschnitt == (0, 0, 2000, 3000)
    assert p.dpi == pytest.approx(3000 / (100 / ZOLL))


def test_flaeche_fuellen_beschneidet_gleichmaessig():
    p = platzieren(3000, 2000, (0.0, 0.0, 100.0, 100.0), fuellen=True)
    assert p.ziel == (0.0, 0.0, 100.0, 100.0)
    assert p.ausschnitt == (500, 0, 2500, 2000)


def test_format_folgt_dem_bild():
    """10 x 15 cm liegt quer, wenn das Bild quer ist - und wird kleiner, wenn es nicht passt."""
    quer = platzieren(3000, 2000, (0.0, 0.0, 297.0, 210.0), (101.6, 152.4))
    assert quer.ziel[2:] == pytest.approx((152.4, 101.6))
    assert not quer.verkleinert
    hoch = platzieren(2000, 3000, (0.0, 0.0, 210.0, 297.0), (101.6, 152.4))
    assert hoch.ziel[2:] == pytest.approx((101.6, 152.4))
    zu_gross = platzieren(2000, 3000, (0.0, 0.0, 100.0, 140.0), (203.0, 305.0))
    assert zu_gross.verkleinert and zu_gross.ziel[3] <= 140.0 + 1e-9


def test_rand_und_knapp():
    assert drucken.flaeche((5.0, 5.0, 100.0, 150.0), 10.0) == (15.0, 15.0, 80.0, 130.0)
    assert drucken.flaeche((0.0, 0.0, 10.0, 10.0), 50.0)[2] >= 2.0     # bleibt bedruckbar
    p = platzieren(600, 400, (0.0, 0.0, 152.4, 101.6))                    # 100 dpi
    assert p.knapp and drucken.ki_faktor(p) == 2
    p = platzieren(300, 200, (0.0, 0.0, 152.4, 101.6))                    # 50 dpi
    assert drucken.ki_faktor(p) == 4
    assert drucken.ki_faktor(platzieren(1800, 1200, (0.0, 0.0, 152.4, 101.6))) == 0


def test_zehn_mal_fuenfzehn_erkannt():
    assert drucken.passt_zur_vorgabe(101.6, 152.4)
    assert drucken.passt_zur_vorgabe(152.0, 102.0)
    assert not drucken.passt_zur_vorgabe(210.0, 297.0)


def test_vorbereiten_auf_druckpixel():
    rgb = np.zeros((300, 400, 3), np.uint8)
    rgb[:, 200:] = 255
    p = platzieren(400, 300, (0.0, 0.0, 101.6, 76.2))                     # 4 x 3 Zoll
    groesse = drucken.druckpixel(p, 1200)
    assert groesse == (1200, 900)                # hoechstens 300 dpi, nicht 1200
    fertig = drucken.vorbereiten(rgb, p, groesse)
    assert fertig.shape == (900, 1200, 3)
    assert fertig[450, 100].max() == 0 and fertig[450, 1100].min() == 255
    # Nach KI-Vergroesserung um 2 liegt derselbe Ausschnitt doppelt so gross vor
    doppelt = np.repeat(np.repeat(rgb, 2, axis=0), 2, axis=1)
    probe = np.s_[50::100, 50::100]                # nicht an der Kante, dort schwingt Lanczos
    assert np.array_equal(drucken.vorbereiten(doppelt, p, groesse, faktor=2)[probe],
                          fertig[probe])


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_druck_als_pdf(app, tmp_path):
    """Ohne Papier: der Drucker schreibt ein PDF in 10 x 15 cm, und das Bild ist darin."""
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QPageSize
    from PySide6.QtPrintSupport import QPrinter
    drucker = QPrinter(QPrinter.PrinterMode.HighResolution)
    drucker.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    pfad = str(tmp_path / "druck.pdf")
    drucker.setOutputFileName(pfad)
    drucker.setPageSize(QPageSize(QSizeF(4, 6), QPageSize.Unit.Inch, "10 x 15"))
    drucker.setFullPage(True)
    rgb = np.full((300, 200, 3), (200, 40, 40), np.uint8)
    p = platzieren(200, 300, (5.0, 5.0, 91.6, 142.4))
    drucken.drucken(drucker, rgb, p)
    inhalt = open(pfad, "rb").read()
    assert inhalt.startswith(b"%PDF")
    seite = re.search(rb"/MediaBox \[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", inhalt)
    assert seite and (round(float(seite.group(1))), round(float(seite.group(2)))) == (288, 432)
    assert b"/Image" in inhalt


def test_dialog_zeigt_groesse_auf_dem_papier(app, monkeypatch):
    """Ohne Drucker (wie in der CI): Vorschau auf A4 ohne Rand, Drucken gesperrt."""
    from PySide6.QtPrintSupport import QPrinterInfo

    from silberkorn.drucken_dialog import DruckenDialog
    monkeypatch.setattr(QPrinterInfo, "availablePrinterNames", staticmethod(lambda: []))
    vorschau = np.full((60, 90, 3), 128, np.uint8)
    dialog = DruckenDialog(None, vorschau, (2000, 3000), Vorgaben(groesse="10x15"))
    try:
        p = dialog.platz()
        assert p.ziel[2:] == pytest.approx((152.4, 101.6))
        assert "15,2 cm" in dialog.info.text()
        assert dialog.ki_faktor() == 0
        assert dialog.drucker() is None and not dialog.drucken_knopf.isEnabled()
        assert "Kein Drucker" in dialog.hinweis.text()
        dialog.groesse_wahl.setCurrentIndex(dialog.groesse_wahl.findData("eigen"))
        dialog.eigen_breite.setValue(30.0)
        dialog.eigen_hoehe.setValue(20.0)
        assert dialog.vorgaben().format_mm() == (300.0, 200.0)
        assert dialog.vorgaben().groesse == "eigen"
    finally:
        dialog.deleteLater()


def test_druckbild_auf_weiss():
    """Durchsichtiges kommt auf weisses Papier, nicht schwarz."""
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    from silberkorn import bilddatei
    from silberkorn.bearbeitung import Sitzung
    pixel = np.full((40, 60, 3), 0, dtype=np.uint8)
    alpha = np.zeros((40, 60), dtype=np.uint8)
    alpha[:, :30] = 255
    daten = bilddatei.Bilddaten(pixel=pixel, profil=None, alpha=alpha, exif=b"", pfad="t.png")
    sitzung = Sitzung(daten, vorschau_kante=60)
    try:
        rgb = sitzung.druckbild()
        assert rgb.dtype == np.uint8 and rgb.shape == (40, 60, 3)
        assert rgb[20, 10].max() <= 1 and rgb[20, 50].min() >= 254
        assert not sitzung.geaendert
    finally:
        sitzung.schliessen()
