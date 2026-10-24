"""Kontaktbogen: Raster, Seiten, Ausgabe als PDF und der Dialog."""

from __future__ import annotations

import math
import os
import re

import numpy as np
import pytest
from PIL import Image

from silberkorn import bewertung, kontaktbogen
from silberkorn.kontaktbogen import Vorgaben

A4 = (0.0, 0.0, 210.0, 297.0)


def _stand(wert: int) -> bewertung.Stand:
    return bewertung.Stand(wert, "eigen")


# --------------------------------------------------------------------------
# Vorgaben
# --------------------------------------------------------------------------

def test_vorgaben_rundlauf_und_vorgabe():
    assert Vorgaben.aus_dict(None) == Vorgaben()
    eigen = Vorgaben(drucker="X", papier="A3", quer=True, spalten=6, ausschuss_weglassen=False)
    assert Vorgaben.aus_dict(eigen.als_dict()) == eigen


@pytest.mark.parametrize("daten, erwartet", [
    ({"spalten": 99}, Vorgaben(spalten=kontaktbogen.SPALTEN_MAX)),
    ({"spalten": -3}, Vorgaben(spalten=kontaktbogen.SPALTEN_MIN)),
    ({"spalten": 5.0, "quer": 1, "ausschuss_weglassen": "nein"}, Vorgaben()),
    ({"spalten": True}, Vorgaben()),                 # bool ist hier keine Zahl
    ({"drucker": ["\\\\server\\x"], "papier": 3}, Vorgaben()),
    ([1, 2], Vorgaben()),
])
def test_vorgaben_nehmen_nur_gueltiges(daten, erwartet):
    assert Vorgaben.aus_dict(daten) == erwartet


# --------------------------------------------------------------------------
# Raster
# --------------------------------------------------------------------------

@pytest.mark.parametrize("blatt", [A4, (0.0, 0.0, 297.0, 210.0), (4.2, 4.2, 201.6, 288.6),
                                   (0.0, 0.0, 101.6, 152.4)])
@pytest.mark.parametrize("spalten", range(kontaktbogen.SPALTEN_MIN, kontaktbogen.SPALTEN_MAX + 1))
def test_alle_zellen_liegen_im_bedruckbaren_bereich(blatt, spalten):
    gitter = kontaktbogen.raster(blatt, spalten)
    x, y, breite, hoehe = blatt
    assert gitter.spalten == spalten and gitter.zeilen >= 1
    letzte = gitter.zelle(gitter.je_seite - 1)
    for feld in (gitter.zelle(0)[0], letzte[0], letzte[1], gitter.kopf):
        fx, fy, fb, fh = feld
        assert fx >= x - 1e-6 and fy >= y - 1e-6
        assert fx + fb <= x + breite + 1e-6 and fy + fh <= y + hoehe + 1e-6
    erste, zweite = gitter.zelle(0)[0], gitter.zelle(1)[0]
    assert zweite[0] >= erste[0] + erste[2]           # nebeneinander, ohne Ueberlappung


def test_mehr_spalten_kleinere_bilder_weniger_seiten():
    vier, acht = kontaktbogen.raster(A4, 4), kontaktbogen.raster(A4, 8)
    assert acht.kante < vier.kante
    assert acht.seiten(200) < vier.seiten(200)


def test_seiten_und_druckpixel():
    gitter = kontaktbogen.raster(A4, 4)
    assert gitter.seiten(0) == 1 and gitter.seiten(1) == 1
    assert gitter.seiten(gitter.je_seite) == 1 and gitter.seiten(gitter.je_seite + 1) == 2
    assert gitter.kante_px() == round(gitter.kante / 25.4 * 300)
    assert kontaktbogen.raster((0, 0, 30, 30), 8).kante_px() == 64      # nie winzig


def test_flaches_papier_verkleinert_das_bildfeld():
    gitter = kontaktbogen.raster((0.0, 0.0, 400.0, 40.0), 2)
    assert gitter.zeilen == 1
    feld, zeile = gitter.zelle(0)
    assert zeile[1] + zeile[3] <= 40.0 + 1e-6


def test_beschriftung_und_auswahl():
    assert kontaktbogen.beschriftung("a.jpg", _stand(0)) == "a.jpg"
    assert kontaktbogen.beschriftung("a.jpg", _stand(3)) == "a.jpg  ★★★"
    assert kontaktbogen.beschriftung("a.jpg", _stand(bewertung.AUSSCHUSS)) == "a.jpg  ✕"
    eintraege = [("a", _stand(2)), ("b", _stand(bewertung.AUSSCHUSS)), ("c", _stand(0))]
    assert [p for p, _s in kontaktbogen.auswahl(eintraege, True)] == ["a", "c"]
    assert kontaktbogen.auswahl(eintraege, False) == eintraege


def test_a4_wird_erkannt():
    assert kontaktbogen.ist_a4(210, 297) and kontaktbogen.ist_a4(297.4, 209.6)
    assert not kontaktbogen.ist_a4(215.9, 279.4)                        # Letter


# --------------------------------------------------------------------------
# Ausgabe als PDF - ohne Grafikkarte, mit erfundenen Bildern
# --------------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pdf_drucker(pfad):
    from PySide6.QtGui import QPageSize
    from PySide6.QtPrintSupport import QPrinter
    drucker = QPrinter(QPrinter.PrinterMode.HighResolution)
    drucker.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    drucker.setOutputFileName(str(pfad))
    drucker.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    drucker.setFullPage(True)
    return drucker


def _farbbild(pfad, kante):
    from PySide6.QtGui import QColor, QImage
    bild = QImage(kante, kante * 2 // 3, QImage.Format.Format_RGB888)
    bild.fill(QColor(200, 40, 40))
    return bild


def _seiten(pfad) -> int:
    from PySide6.QtPdf import QPdfDocument
    dokument = QPdfDocument()
    dokument.load(str(pfad))
    return dokument.pageCount()


def test_pdf_hat_so_viele_seiten_wie_das_raster(app, tmp_path):
    gitter = kontaktbogen.raster(A4, 4)
    eintraege = [(f"bild{n}.jpg", _stand(n % 6)) for n in range(gitter.je_seite * 2 + 1)]
    gerufen, fortschritt = [], []
    pfad = tmp_path / "bogen.pdf"

    def laden(pfad_, kante):
        gerufen.append((pfad_, kante))
        return _farbbild(pfad_, kante)

    fehlt = kontaktbogen.ausgeben(_pdf_drucker(pfad), gitter, eintraege, "Ordner",
                                  lambda n, m: f"{n}/{m}",
                                  lambda name, anteil: fortschritt.append(anteil) or True, laden)
    assert fehlt == []
    assert _seiten(pfad) == 3
    assert [p for p, _k in gerufen] == [p for p, _s in eintraege]      # in dieser Reihenfolge
    assert {k for _p, k in gerufen} == {gitter.kante_px()}
    assert fortschritt == sorted(fortschritt) and fortschritt[-1] < 1


def test_nicht_ladbare_bilder_bleiben_grau_und_werden_genannt(app, tmp_path):
    from silberkorn import bilddatei
    gitter = kontaktbogen.raster(A4, 4)
    eintraege = [("gut.jpg", _stand(0)), ("kaputt.jpg", _stand(0)), ("weg.jpg", _stand(0))]

    def laden(pfad, kante):
        if pfad == "kaputt.jpg":
            raise bilddatei.BildFehler("kaputt")
        if pfad == "weg.jpg":
            raise OSError("weg")
        return _farbbild(pfad, kante)

    pfad = tmp_path / "bogen.pdf"
    fehlt = kontaktbogen.ausgeben(_pdf_drucker(pfad), gitter, eintraege, "Ordner",
                                  lambda n, m: "", lambda *_a: True, laden)
    assert fehlt == [("kaputt.jpg", "kaputt"), ("weg.jpg", "weg")]
    assert _seiten(pfad) == 1


def test_abbruch_wirft_und_laedt_nichts_mehr(app, tmp_path):
    gitter = kontaktbogen.raster(A4, 8)
    eintraege = [(f"bild{n}.jpg", _stand(0)) for n in range(gitter.je_seite + 5)]
    geladen = []

    def fortschritt(name, _anteil):
        return name != "bild3.jpg"

    with pytest.raises(kontaktbogen.Abbruch):
        kontaktbogen.ausgeben(_pdf_drucker(tmp_path / "bogen.pdf"), gitter, eintraege, "O",
                              lambda n, m: "", fortschritt,
                              lambda p, k: geladen.append(p) or _farbbild(p, k))
    assert geladen == ["bild0.jpg", "bild1.jpg", "bild2.jpg"]


def test_drucker_lehnt_ab(app, monkeypatch):
    from PySide6.QtGui import QPainter
    monkeypatch.setattr(QPainter, "begin", lambda self, geraet: False)
    with pytest.raises(OSError):
        kontaktbogen.ausgeben(_pdf_drucker("x.pdf"), kontaktbogen.raster(A4, 4),
                              [("a", _stand(0))], "O", lambda n, m: "", lambda *_a: True,
                              _farbbild)


# --------------------------------------------------------------------------
# Dialog
# --------------------------------------------------------------------------

@pytest.fixture
def ohne_drucker(app, monkeypatch):
    from PySide6.QtPrintSupport import QPrinterInfo
    monkeypatch.setattr(QPrinterInfo, "availablePrinterNames", staticmethod(lambda: []))
    monkeypatch.setattr(QPrinterInfo, "defaultPrinterName", staticmethod(lambda: ""))


def _dialog(eintraege, vorgaben=None, vorschau=lambda _p: None):
    from silberkorn.kontaktbogen_dialog import KontaktbogenDialog
    return KontaktbogenDialog(None, eintraege, "D:/Fotos", vorgaben or Vorgaben(), vorschau)


def test_dialog_ohne_drucker_bietet_pdf_auf_a4(ohne_drucker):
    from silberkorn.drucken_dialog import PDF
    dialog = _dialog([(f"{n}.jpg", _stand(0)) for n in range(30)])
    try:
        assert dialog.drucker_wahl.count() == 1 and dialog.ist_pdf()
        assert dialog.drucker_wahl.currentData() == PDF
        assert dialog.papier_wahl.currentText().startswith("A4")
        assert dialog.los_knopf.text() == "Als PDF speichern …" and dialog.los_knopf.isEnabled()
        gitter = dialog.raster()
        assert dialog.bogen.seiten == math.ceil(30 / gitter.je_seite)
        assert f"{dialog.bogen.seiten} Seiten" in dialog.info.text()
        drucker = dialog.drucker()
        assert drucker is not None and drucker.outputFormat() == drucker.OutputFormat.PdfFormat
        assert dialog.vorgaben().drucker == PDF
    finally:
        dialog.deleteLater()


def test_dialog_spalten_lage_und_blaettern(ohne_drucker):
    dialog = _dialog([(f"{n}.jpg", _stand(0)) for n in range(30)])
    try:
        vorher = dialog.bogen.seiten
        assert not dialog.zurueck.isEnabled() and dialog.vor.isEnabled()
        dialog.vor.click()
        assert dialog.bogen.seite == 2 and dialog.zurueck.isEnabled()
        assert dialog.seite_info.text() == f"Seite 2/{vorher}"
        dialog.spalten.setValue(8)
        assert dialog.bogen.seiten < vorher and dialog.bogen.seite <= dialog.bogen.seiten
        hoch = dialog.raster()
        dialog.lage.setCurrentIndex(1)
        assert dialog.bogen.groesse_mm[0] > dialog.bogen.groesse_mm[1]
        assert dialog.raster().zeilen < hoch.zeilen
        assert dialog.vorgaben() == Vorgaben(drucker=dialog.drucker_wahl.currentData(),
                                             papier=dialog.papier_wahl.currentText(),
                                             quer=True, spalten=8)
    finally:
        dialog.deleteLater()


def test_dialog_ausschuss(ohne_drucker):
    eintraege = [("a.jpg", _stand(2)), ("b.jpg", _stand(bewertung.AUSSCHUSS))]
    dialog = _dialog(eintraege)
    try:
        assert dialog.ausschuss.isEnabled() and dialog.ausschuss.isChecked()
        assert [p for p, _s in dialog.eintraege()] == ["a.jpg"]
        assert dialog.info.text().startswith("1 Bild ")
        dialog.ausschuss.setChecked(False)
        assert dialog.eintraege() == eintraege
    finally:
        dialog.deleteLater()
    ohne = _dialog([("a.jpg", _stand(2))], Vorgaben(ausschuss_weglassen=True))
    try:
        assert not ohne.ausschuss.isEnabled()
    finally:
        ohne.deleteLater()


def test_dialog_nur_ausschuss_sperrt_den_knopf(ohne_drucker):
    dialog = _dialog([("b.jpg", _stand(bewertung.AUSSCHUSS))])
    try:
        assert not dialog.los_knopf.isEnabled()
        dialog.ausschuss.setChecked(False)
        assert dialog.los_knopf.isEnabled()
    finally:
        dialog.deleteLater()


def test_dialog_vorschau_zeichnet_die_kacheln(ohne_drucker):
    from PySide6.QtGui import QColor, QPixmap
    gefragt = []
    kachel = QPixmap(200, 120)
    kachel.fill(QColor(0, 0, 255))

    def vorschau(pfad):
        gefragt.append(pfad)
        return kachel if pfad == "a.jpg" else None

    dialog = _dialog([("a.jpg", _stand(0)), ("b.jpg", _stand(0))], vorschau=vorschau)
    try:
        bild = dialog.bogen.grab().toImage()
        blau = sum(1 for x in range(0, bild.width(), 4) for y in range(0, bild.height(), 4)
                   if bild.pixelColor(x, y).blue() > 200 and bild.pixelColor(x, y).red() < 50)
        assert blau > 20
        assert gefragt[:2] == ["a.jpg", "b.jpg"]
    finally:
        dialog.deleteLater()


def test_dialog_merkt_gewaehlten_drucker_und_papier(app, monkeypatch):
    from PySide6.QtPrintSupport import QPrinterInfo
    monkeypatch.setattr(QPrinterInfo, "availablePrinterNames", staticmethod(lambda: []))
    dialog = _dialog([("a.jpg", _stand(0))], Vorgaben(papier="A3", quer=True, spalten=3))
    try:
        assert dialog.papier_wahl.currentText().startswith("A3")
        assert dialog.lage.currentIndex() == 1 and dialog.spalten.value() == 3
    finally:
        dialog.deleteLater()


# --------------------------------------------------------------------------
# Mit Grafikkarte: das Bild mit seiner Bearbeitung
# --------------------------------------------------------------------------

def test_zellbild_traegt_die_bearbeitung_der_begleitdatei(app, tmp_path):
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    from silberkorn import begleitdatei, bilddatei
    from silberkorn.bearbeitung import Sitzung
    pfad = str(tmp_path / "grau.png")
    Image.fromarray(np.full((300, 600, 3), 100, np.uint8)).save(pfad)

    roh = kontaktbogen.zellbild(pfad, 120)
    assert (roh.width(), roh.height()) == (120, 60)
    grau = roh.pixelColor(60, 30).red()

    sitzung = Sitzung(bilddatei.laden(pfad), 120)
    sitzung.werte.belichtung = 1.0
    begleitdatei.schreiben(pfad, sitzung.begleit_inhalt(), begleitdatei.fingerabdruck(pfad))
    sitzung.schliessen()
    hell = kontaktbogen.zellbild(pfad, 120).pixelColor(60, 30).red()
    assert hell > grau + 20
    assert os.path.isfile(begleitdatei.pfad_fuer(pfad))


def test_zellbild_kaputte_datei_wirft_bildfehler(app, tmp_path):
    pytest.importorskip("cupy")
    from silberkorn import bilddatei
    pfad = tmp_path / "kaputt.jpg"
    pfad.write_bytes(b"kein Bild")
    with pytest.raises(bilddatei.BildFehler):
        kontaktbogen.zellbild(str(pfad), 100)


def test_nichts_im_modul_braucht_qt_beim_import():
    """Wie drucken.py: Qt erst in den Funktionen - das Modul laesst sich ohne laden."""
    quelle = open(kontaktbogen.__file__, encoding="utf-8").read()
    kopf = quelle.split("\ndef ", 1)[0]
    assert not re.search(r"^from PySide6|^import PySide6", kopf, re.MULTILINE)


def test_unerwarteter_fehler_verwirft_den_auftrag(app, tmp_path, monkeypatch):
    from PySide6.QtPrintSupport import QPrinter
    verworfen = []
    monkeypatch.setattr(QPrinter, "abort", lambda self: verworfen.append(1) or True)

    def laden(pfad, kante):
        raise RuntimeError("Programmfehler")

    with pytest.raises(RuntimeError):
        kontaktbogen.ausgeben(_pdf_drucker(tmp_path / "b.pdf"), kontaktbogen.raster(A4, 4),
                              [("a", _stand(0))], "O", lambda n, m: "", lambda *_a: True, laden)
    assert verworfen == [1]


def test_abbruch_verwirft_den_auftrag(app, tmp_path, monkeypatch):
    from PySide6.QtPrintSupport import QPrinter
    verworfen = []
    monkeypatch.setattr(QPrinter, "abort", lambda self: verworfen.append(1) or True)
    with pytest.raises(kontaktbogen.Abbruch):
        kontaktbogen.ausgeben(_pdf_drucker(tmp_path / "b.pdf"), kontaktbogen.raster(A4, 4),
                              [("a", _stand(0))], "O", lambda n, m: "", lambda *_a: False,
                              _farbbild)
    assert verworfen == [1]


def test_druckerfehler_am_ende_wird_gemeldet(app, tmp_path, monkeypatch):
    from PySide6.QtPrintSupport import QPrinter
    monkeypatch.setattr(QPrinter, "printerState", lambda self: QPrinter.PrinterState.Error)
    with pytest.raises(OSError):
        kontaktbogen.ausgeben(_pdf_drucker(tmp_path / "b.pdf"), kontaktbogen.raster(A4, 4),
                              [("a", _stand(0))], "O", lambda n, m: "", lambda *_a: True,
                              _farbbild)


def test_gpu_fehler_bei_einem_bild_macht_es_grau(app, tmp_path):
    cp = pytest.importorskip("cupy")

    def laden(pfad, kante):
        if pfad == "b":
            raise cp.cuda.memory.OutOfMemoryError(1, 0)
        return _farbbild(pfad, kante)

    fehlt = kontaktbogen.ausgeben(_pdf_drucker(tmp_path / "b.pdf"), kontaktbogen.raster(A4, 4),
                                  [("a", _stand(0)), ("b", _stand(0))], "O", lambda n, m: "",
                                  lambda *_a: True, laden)
    assert [p for p, _g in fehlt] == ["b"]


def test_kopf_namen_und_sterne_stehen_im_pdf(app, tmp_path):
    from PySide6.QtPdf import QPdfDocument
    gitter = kontaktbogen.raster(A4, 8)
    eintraege = [(f"C:/x/bild{n}.jpg", _stand(n % 3)) for n in range(gitter.je_seite + 1)]
    pfad = tmp_path / "bogen.pdf"
    kontaktbogen.ausgeben(_pdf_drucker(pfad), gitter, eintraege, "D:/Fotos/Urlaub",
                          lambda n, m: f"Seite {n}/{m}", lambda *_a: True, _farbbild)
    dokument = QPdfDocument()
    dokument.load(str(pfad))
    erste, zweite = dokument.getAllText(0).text(), dokument.getAllText(1).text()
    assert "D:/Fotos/Urlaub" in erste and "Seite 1/2" in erste and "Seite 2/2" in zweite
    assert "bild1.jpg" in erste and "\u2605" in erste and "bild0.jpg" in erste
    assert f"bild{gitter.je_seite}.jpg" in zweite


def test_seite_zeichnen_bild_unten_buendig_und_platzhalter_grau(app):
    from PySide6.QtGui import QColor, QImage, QPainter
    gitter = kontaktbogen.raster(A4, 2)
    leinwand = QImage(420, 594, QImage.Format.Format_RGB888)
    leinwand.fill(QColor(255, 255, 255))
    quer = QImage(300, 100, QImage.Format.Format_RGB888)
    quer.fill(QColor(0, 0, 255))
    maler = QPainter(leinwand)
    kontaktbogen.seite_zeichnen(maler, 2.0, gitter, "Kopf", "1/1", [(quer, "a"), (None, "b")])
    maler.end()
    (x, y, b, h), _zeile = gitter.zelle(0)
    unten = leinwand.pixelColor(round((x + b / 2) * 2), round((y + h - 1) * 2))
    oben = leinwand.pixelColor(round((x + b / 2) * 2), round((y + 1) * 2))
    assert unten.blue() > 200 and unten.red() < 50              # unten buendig
    assert oben == QColor(255, 255, 255)
    (x, y, b, h), _zeile = gitter.zelle(1)
    assert leinwand.pixelColor(round((x + b / 2) * 2), round((y + h / 2) * 2)) == QColor(
        *kontaktbogen.PLATZHALTER)


def test_dialog_querformat_kommt_beim_drucker_an(ohne_drucker):
    from PySide6.QtGui import QPageLayout
    dialog = _dialog([("a.jpg", _stand(0))], Vorgaben(quer=True))
    try:
        rand = dialog.drucker().pageLayout().fullRect(QPageLayout.Unit.Millimeter)
        assert (round(rand.width()), round(rand.height())) == (297, 210)
        dialog.lage.setCurrentIndex(0)
        rand = dialog.drucker().pageLayout().fullRect(QPageLayout.Unit.Millimeter)
        assert (round(rand.width()), round(rand.height())) == (210, 297)
    finally:
        dialog.deleteLater()


def test_drucker_wahl_mit_druckern(app, monkeypatch):
    from PySide6.QtPrintSupport import QPrinterInfo

    from silberkorn.drucken import Vorgaben as DruckVorgaben
    from silberkorn.drucken_dialog import PDF, DruckenDialog
    monkeypatch.setattr(QPrinterInfo, "availablePrinterNames",
                        staticmethod(lambda: ["Erster", "Zweiter"]))
    monkeypatch.setattr(QPrinterInfo, "defaultPrinterName", staticmethod(lambda: "Zweiter"))
    for gemerkt, erwartet in ((PDF, PDF), ("", "Zweiter"), ("Weg", "Zweiter"),
                              ("Erster", "Erster")):
        dialog = _dialog([("a.jpg", _stand(0))], Vorgaben(drucker=gemerkt))
        try:
            assert dialog.drucker_wahl.currentData() == erwartet
            assert dialog.drucker_wahl.count() == 3
        finally:
            dialog.deleteLater()
    druck = DruckenDialog(None, np.zeros((6, 9, 3), np.uint8), (60, 90), DruckVorgaben())
    try:
        assert druck.drucker_wahl.findData(PDF) == -1 and druck.drucker_wahl.count() == 2
    finally:
        druck.deleteLater()
