"""Leinwand: Trennlinie des Vergleichs - Qt ohne Bildschirm, ohne Grafikkarte."""

from __future__ import annotations

import os

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from silberkorn.leinwand import Leinwand  # noqa: E402

ROT = (200, 20, 20)
BLAU = (20, 20, 200)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def einfarbig(hoehe, breite, farbe):
    return np.full((hoehe, breite, 3), farbe, dtype=np.uint8)


@pytest.fixture
def leinwand(app):
    """Bild 300 x 200 in einem Fenster von 500 x 400: bei Einpassung in Originalgroesse."""
    fenster = Leinwand()
    fenster.resize(500, 400)
    fenster.voll_form = (200, 300)
    fenster.zeigen(einfarbig(200, 300, ROT), einfarbig(200, 300, BLAU))
    fenster.vergleich = True
    fenster.show()
    app.processEvents()
    yield fenster
    fenster.close()


def punkt(x, y):
    return QPoint(round(x), round(y))


def mitte_y(leinwand):
    return leinwand._bildflaeche().center().y()


def farbe_bei(leinwand, x, y):
    bild = leinwand.grab().toImage()
    pixel = bild.pixelColor(round(x), round(y))
    return pixel.red(), pixel.green(), pixel.blue()


def test_trenner_ziehen_aendert_die_lage(leinwand):
    start = leinwand._trenner_x()
    y = mitte_y(leinwand)
    QTest.mousePress(leinwand, Qt.MouseButton.LeftButton, pos=punkt(start, y))
    assert leinwand._trenner_ziehen is not None
    QTest.mouseMove(leinwand, punkt(start - 60, y))
    QTest.mouseRelease(leinwand, Qt.MouseButton.LeftButton, pos=punkt(start - 60, y))
    assert leinwand._trenner_ziehen is None
    assert leinwand._trenner_x() == pytest.approx(start - 60, abs=1.5)
    assert leinwand.trenner < 0.5


def test_trenner_bleibt_im_bild(leinwand):
    bild = leinwand._bildflaeche()
    y = mitte_y(leinwand)
    QTest.mousePress(leinwand, Qt.MouseButton.LeftButton, pos=punkt(leinwand._trenner_x(), y))
    QTest.mouseMove(leinwand, punkt(bild.left() - 80, y))
    QTest.mouseRelease(leinwand, Qt.MouseButton.LeftButton, pos=punkt(bild.left() - 80, y))
    assert leinwand._trenner_x() == pytest.approx(bild.left(), abs=0.5)


def test_doppelklick_auf_den_griff_setzt_die_mitte_und_zoomt_nicht(leinwand):
    leinwand.trenner = 0.3
    x, y = leinwand._trenner_x(), mitte_y(leinwand)
    QTest.mouseDClick(leinwand, Qt.MouseButton.LeftButton, pos=punkt(x, y))
    assert leinwand.trenner == 0.5
    assert leinwand.zoom is None


def test_doppelklick_neben_der_linie_wechselt_den_zoom(leinwand):
    x = leinwand._trenner_x() + 80
    QTest.mouseDClick(leinwand, Qt.MouseButton.LeftButton, pos=punkt(x, mitte_y(leinwand)))
    assert leinwand.zoom == 1.0
    assert leinwand.trenner == 0.5                           # unberuehrt


def test_klick_ausserhalb_geht_an_die_normale_behandlung(leinwand):
    leinwand.zoom = 2.0                                      # gezoomt: Ziehen verschiebt
    x, y = leinwand._trenner_x() + 40, mitte_y(leinwand)
    QTest.mousePress(leinwand, Qt.MouseButton.LeftButton, pos=punkt(x, y))
    assert leinwand._trenner_ziehen is None
    assert leinwand._ziehen is not None and leinwand._ziehen[0] == "schieben"
    QTest.mouseRelease(leinwand, Qt.MouseButton.LeftButton, pos=punkt(x, y))


def test_cursor_ueber_der_linie(leinwand):
    x, y = leinwand._trenner_x(), mitte_y(leinwand)
    QTest.mouseMove(leinwand, punkt(x + 3, y))
    assert leinwand.cursor().shape() == Qt.CursorShape.SizeHorCursor
    QTest.mouseMove(leinwand, punkt(x + 60, y))
    assert leinwand.cursor().shape() != Qt.CursorShape.SizeHorCursor


@pytest.mark.parametrize("modus", ["klickmodus", "pinselmodus", "flaechenmodus", "lokalmodus",
                                   "lokal_pinsel", "zuschnitt", "aussetzen"])
def test_vergleich_ruht_in_diesen_modi(leinwand, modus):
    x, y = leinwand._trenner_x(), mitte_y(leinwand)
    assert leinwand.vergleich_gilt() and leinwand._trenner_bei(punkt(x, y))
    if modus == "zuschnitt":
        leinwand.zuschnitt = (0.0, 0.0, 1.0, 1.0)
    elif modus == "aussetzen":
        leinwand.vergleich_aussetzen = True
    else:
        setattr(leinwand, modus, True)
    assert not leinwand.vergleich_gilt()
    assert not leinwand._trenner_bei(punkt(x, y))
    QTest.mousePress(leinwand, Qt.MouseButton.LeftButton, pos=punkt(x, y))
    assert leinwand._trenner_ziehen is None
    QTest.mouseRelease(leinwand, Qt.MouseButton.LeftButton, pos=punkt(x, y))
    # Ohne Pausengrund ist der Vergleich wieder da
    if modus == "zuschnitt":
        leinwand.zuschnitt = None
    elif modus == "aussetzen":
        leinwand.vergleich_aussetzen = False
    else:
        setattr(leinwand, modus, False)
    assert leinwand.vergleich_gilt() and leinwand._trenner_bei(punkt(x, y))


def test_links_vorher_rechts_nachher(leinwand):
    x, y = leinwand._trenner_x(), mitte_y(leinwand) + 50
    assert farbe_bei(leinwand, x - 40, y) == BLAU            # links: das Vorher-Bild
    assert farbe_bei(leinwand, x + 40, y) == ROT             # rechts: das bearbeitete
    leinwand.trenner = 0.25                                  # die Linie wandert mit
    x = leinwand._trenner_x()
    assert farbe_bei(leinwand, x - 20, y) == BLAU
    assert farbe_bei(leinwand, x + 20, y) == ROT


@pytest.mark.parametrize("ohne", ["vergleich", "aussetzen", "zuschnitt", "klickmodus"])
def test_ohne_vergleich_nur_das_bearbeitete_bild(leinwand, ohne):
    x, y = leinwand._trenner_x(), mitte_y(leinwand) + 50
    if ohne == "vergleich":
        leinwand.vergleich = False
    elif ohne == "aussetzen":
        leinwand.vergleich_aussetzen = True
    elif ohne == "zuschnitt":
        leinwand.zuschnitt = (0.0, 0.0, 1.0, 1.0)
    else:
        leinwand.klickmodus = True
    assert farbe_bei(leinwand, x - 40, y) == ROT
    assert farbe_bei(leinwand, x + 40, y) == ROT


def test_zeichnen_ohne_vorher_bild_fordert_es_einmal_an(leinwand, app):
    angefordert = []
    leinwand.vergleich_gebraucht.connect(lambda: angefordert.append(1))
    leinwand.zeigen(einfarbig(200, 300, ROT))                # die Seite lieferte nichts
    leinwand.grab()
    app.processEvents()
    leinwand.grab()
    app.processEvents()
    assert angefordert == [1]
    leinwand.zeigen(einfarbig(200, 300, ROT), einfarbig(200, 300, BLAU))
    leinwand.grab()
    app.processEvents()
    assert angefordert == [1]


def test_zeichnen_ohne_bild_und_mit_ausschnitt_stuerzt_nicht(leinwand, app):
    leinwand.zeigen(None)
    leinwand.grab()
    leinwand.voll_form = (2000, 3000)
    leinwand.zoom = 1.0
    leinwand.mitte = (1500.0, 1000.0)
    leinwand.zeigen_ausschnitt(einfarbig(400, 480, ROT), 1260, 800, einfarbig(400, 480, BLAU))
    x, y = leinwand._trenner_x(), mitte_y(leinwand) + 50
    assert farbe_bei(leinwand, x - 40, y) == BLAU
    assert farbe_bei(leinwand, x + 40, y) == ROT


def test_trenner_gehoert_zum_fenster_nicht_zum_bild(leinwand):
    leinwand.voll_form = (2000, 3000)                        # grosses Bild: fuellt das Fenster
    leinwand.trenner = 0.3
    eingepasst = leinwand._trenner_x()
    leinwand.zoom_setzen(2.0)
    assert leinwand._trenner_x() == pytest.approx(eingepasst)
    leinwand.mitte = (400.0, 300.0)                          # Verschieben aendert nichts
    assert leinwand._trenner_x() == pytest.approx(eingepasst)
    assert leinwand.trenner == 0.3


def test_ansicht_uebernehmen_begrenzt_und_meldet_einmal(leinwand):
    gemeldet = []
    leinwand.ansicht_geaendert.connect(lambda: gemeldet.append(leinwand.zoom))
    leinwand.ansicht_uebernehmen(2.0, (-50.0, 900.0))        # ausserhalb: an den Rand
    assert leinwand.zoom == 2.0 and leinwand.mitte == (0.0, 200.0)
    assert gemeldet == [2.0]
    leinwand.ansicht_uebernehmen(None, (10.0, 10.0))         # eingepasst: die Mitte zaehlt nicht
    assert leinwand.zoom is None and leinwand.mitte == (0.0, 200.0)
    assert gemeldet == [2.0, None]
    leinwand.voll_form = None                                # ohne Bild: nichts
    leinwand.ansicht_uebernehmen(1.0, (5.0, 5.0))
    assert leinwand.zoom is None and gemeldet == [2.0, None]
