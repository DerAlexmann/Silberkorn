"""Hauptfenster ohne Bild: jeder sichtbare Knopf ist beschriftet."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def fenster():
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    from PySide6.QtWidgets import QApplication

    from silberkorn import gpu_pruefung
    from silberkorn.hauptfenster import Hauptfenster
    QApplication.instance() or QApplication([])
    befund = gpu_pruefung.ermitteln()
    if not befund.ok:
        pytest.skip("keine RTX-Karte")
    fenster = Hauptfenster(befund)
    fenster.show()
    QApplication.processEvents()
    yield fenster
    fenster.close()


def test_alle_sichtbaren_knoepfe_beschriftet(fenster):
    """Beim Start setzte niemand die Texte der KI-Karten, wenn ihre Modelle schon
    da waren - die Knoepfe blieben leer, bis ein Bild geoeffnet wurde."""
    from PySide6.QtWidgets import QPushButton
    leer = [knopf for knopf in fenster.findChildren(QPushButton)
            if knopf.isVisible() and not knopf.text().strip() and knopf.icon().isNull()]
    assert leer == []


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_fenster_passt_auf_schmale_bildschirme(fenster, sprache):
    """Mit dem Stylesheet der App wird das Fenster nicht breiter als 1100 Pixel - so passt
    es auch auf 1366 x 768 bei 125 % Skalierung (knapp 1093 Pixel nutzbar)."""
    from PySide6.QtWidgets import QApplication

    from silberkorn import farben
    from silberkorn.uebersetzung import _
    app = QApplication.instance()
    vorher = app.styleSheet()
    app.setStyleSheet(farben.stylesheet())
    _.language = sprache
    fenster.texte_auffrischen()
    try:
        QApplication.processEvents()              # neues Stylesheet und Texte auswerten
        fenster.resize(100, 700)
        QApplication.processEvents()
        assert fenster.width() <= 1090
    finally:
        _.language = "de"
        fenster.texte_auffrischen()
        app.setStyleSheet(vorher)


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_knoepfe_auch_im_schmalsten_fenster_lesbar(fenster, sprache):
    """Die Mindestbreite des Fensters ergibt sich aus dem Inhalt - kein Knopf der
    Werkzeugleiste wird enger, als seine Beschriftung es verlangt."""
    from PySide6.QtWidgets import QApplication, QPushButton

    from silberkorn.uebersetzung import _
    _.language = sprache                      # ohne die Einstellungsdatei zu beruehren
    fenster.texte_auffrischen()
    try:
        QApplication.processEvents()          # neue Texte auswerten, sonst gilt die alte Breite
        fenster.resize(100, 700)              # Qt haelt die Mindestbreite ein
        QApplication.processEvents()
        seite = fenster.bearbeiten
        leiste = [knopf for knopf in seite.findChildren(QPushButton) if knopf.parent() is seite]
        assert len(leiste) >= 7
        zu_eng = [knopf.text() for knopf in leiste if knopf.width() < knopf.sizeHint().width()]
        assert zu_eng == []
    finally:
        _.language = "de"
        fenster.texte_auffrischen()


def test_angaben_zuruecksetzen_rollt_nicht(fenster, tmp_path, monkeypatch):
    """Der Knopf schaltet sich beim Klick selbst ab - die Reglerleiste blieb dabei nicht
    stehen, sondern rollte zum naechsten Element mit Fokus ans Ende."""
    from PIL import Image
    from PySide6.QtWidgets import QApplication, QScrollArea

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)   # Datei bleibt
    pfad = str(tmp_path / "bild.jpg")
    Image.new("RGB", (64, 48), (90, 120, 150)).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        seite.angaben_felder["titel"].setText("Titel")
        seite._angabe_bearbeitet("titel")
        knopf = seite.angaben_zurueck_knopf
        leiste = next(f for f in seite.findChildren(QScrollArea) if knopf in f.findChildren(
            type(knopf)))
        leiste.ensureWidgetVisible(knopf)
        QApplication.processEvents()
        vorher = leiste.verticalScrollBar().value()
        knopf.setFocus()
        knopf.click()
        QApplication.processEvents()
        assert seite.sitzung.werte.angaben == ()
        assert leiste.verticalScrollBar().value() == vorher
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_rueckgaengig_und_wiederholen(fenster, tmp_path, monkeypatch):
    """Ein Zug am Regler ist ein Schritt, festgehalten nach einer kurzen Pause; auch
    „Zurücksetzen“ laesst sich zuruecknehmen."""
    from PIL import Image
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from silberkorn import bearbeiten_seite, einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "bild.jpg")
    Image.new("RGB", (64, 48), (90, 120, 150)).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        assert not seite.rueckgaengig_knopf.isEnabled()
        assert not seite.wiederholen_knopf.isEnabled()
        belichtung = seite.zeilen["belichtung"]
        for stufe in (110, 120, 130):              # ein Zug in mehreren Bewegungen
            belichtung.schieber.setValue(stufe)
        QTest.qWait(bearbeiten_seite.VERLAUF_PAUSE_MS + 200)
        assert seite.verlauf.kann_zurueck
        assert "Belichtung" in seite.rueckgaengig_knopf.toolTip()
        seite.zeilen["kontrast"].schieber.setValue(150)   # noch nicht festgehalten
        QApplication.processEvents()
        assert "Kontrast" in seite.rueckgaengig_knopf.toolTip()

        seite.rueckgaengig()
        assert seite.sitzung.werte.kontrast == 0 and seite.sitzung.werte.belichtung == 1.5
        seite.rueckgaengig()
        assert seite.sitzung.werte.belichtung == 0
        assert belichtung.wert() == 0 and not seite.rueckgaengig_knopf.isEnabled()
        seite.wiederholen()
        assert seite.sitzung.werte.belichtung == 1.5 and belichtung.wert() == 1.5
        assert "Kontrast" in seite.wiederholen_knopf.toolTip()

        seite.alles_zuruecksetzen()
        seite._festhalten(sofort=True)
        assert seite.sitzung.werte.belichtung == 0
        assert "Zurücksetzen" in seite.rueckgaengig_knopf.toolTip()
        seite._strg_z()
        assert seite.sitzung.werte.belichtung == 1.5 and belichtung.wert() == 1.5
        assert seite.sitzung.geaendert
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()
