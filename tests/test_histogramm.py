"""Histogramm-Feld mit den Warn-Dreiecken - Qt ohne Fenster, ohne Grafikkarte."""

from __future__ import annotations

import os

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def feld():
    from PySide6.QtWidgets import QApplication

    from silberkorn.histogramm import HistogrammFeld
    QApplication.instance() or QApplication([])
    f = HistogrammFeld(340)
    f.show()
    yield f
    f.close()


def klick(feld, ziel):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    mitte = feld._dreieck(ziel == "tiefen").boundingRect().center().toPoint()
    QTest.mouseClick(feld, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(mitte.x(), mitte.y()))


def test_groesse(feld):
    assert feld.width() == 340 and 60 <= feld.height() <= 80


def test_klick_schaltet_jedes_dreieck_einzeln(feld):
    meldungen = []
    feld.warnung_geaendert.connect(lambda lichter, tiefen: meldungen.append((lichter, tiefen)))
    klick(feld, "lichter")
    assert (feld.lichter, feld.tiefen) == (True, False)
    klick(feld, "tiefen")
    assert (feld.lichter, feld.tiefen) == (True, True)
    klick(feld, "lichter")
    assert (feld.lichter, feld.tiefen) == (False, True)
    klick(feld, "tiefen")
    assert (feld.lichter, feld.tiefen) == (False, False)
    assert meldungen == [(True, False), (True, True), (False, True), (False, False)]


def test_klick_neben_die_dreiecke_tut_nichts(feld):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(feld, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(170, 40))
    assert (feld.lichter, feld.tiefen) == (False, False)


def test_ausgeschaltet_reagiert_nicht(feld):
    feld.setEnabled(False)
    klick(feld, "lichter")
    assert not feld.lichter


def test_beide_umschalten(feld):
    feld.beide_umschalten()
    assert feld.lichter and feld.tiefen
    feld.beide_umschalten()
    assert not feld.lichter and not feld.tiefen
    feld.warnung_setzen(True, False)
    feld.beide_umschalten()                     # nicht beide an: erst beide an
    assert feld.lichter and feld.tiefen


def test_setzen_meldet_nur_auf_wunsch(feld):
    meldungen = []
    feld.warnung_geaendert.connect(lambda *a: meldungen.append(a))
    feld.warnung_setzen(True, True)
    assert meldungen == []
    feld.warnung_setzen(False, True, melden=True)
    assert meldungen == [(False, True)]


def test_zeichnen_mit_und_ohne_daten(feld):
    for daten, zahlen in ((None, None), (np.zeros((4, 256), np.int64), (0, 0)),
                          (np.random.default_rng(0).integers(0, 99, (4, 256)), (5, 7)),
                          (np.zeros((3, 10)), (1, 1))):       # falsche Form: ignorieren
        feld.daten_setzen(daten, zahlen)
        feld.warnung_setzen(True, True)
        assert not feld.grab().isNull()
        feld.setEnabled(False)
        assert not feld.grab().isNull()
        feld.setEnabled(True)


def test_dreieck_gefuellt_nur_bei_abgeschnittenen_pixeln(feld):
    """Das gefuellte Dreieck unterscheidet sich vom leeren: Farbe nahe seiner Ecke."""
    feld.daten_setzen(None)

    def farbe(ziel):
        bild = feld.grab().toImage()
        mitte = feld._dreieck(ziel == "tiefen").boundingRect().center().toPoint()
        # etwas zur Ecke hin, damit der Punkt sicher im Dreieck liegt
        x = mitte.x() + (-2 if ziel == "tiefen" else 2)
        return bild.pixelColor(x, mitte.y() - 2).name()

    leer_lichter, leer_tiefen = farbe("lichter"), farbe("tiefen")
    feld.daten_setzen(np.zeros((4, 256)), (10, 0))
    assert farbe("lichter") != leer_lichter and farbe("tiefen") == leer_tiefen
    feld.daten_setzen(np.zeros((4, 256)), (0, 10))
    assert farbe("tiefen") != leer_tiefen and farbe("lichter") == leer_lichter


def test_hinweise_in_beiden_sprachen(feld):
    from silberkorn.uebersetzung import _
    try:
        de = feld.hinweis("tiefen"), feld.hinweis("lichter")
        _.language = "en"
        en = feld.hinweis("tiefen"), feld.hinweis("lichter")
    finally:
        _.language = "de"
    assert de[0] != de[1] and en[0] != en[1]
    assert all(e != d for e, d in zip(en, de, strict=True))
