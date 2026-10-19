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

    from silberkorn import einstellungen, gpu_pruefung
    from silberkorn.hauptfenster import Hauptfenster
    QApplication.instance() or QApplication([])
    befund = gpu_pruefung.ermitteln()
    if not befund.ok:
        pytest.skip("keine RTX-Karte")
    # Nichts aus der echten Einstellungsdatei: kein echter Vorschau-Cache, kein zuletzt
    # gezeigter Ordner mit eigenen Bildern
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(einstellungen, "load_config", lambda: {})
        fenster = Hauptfenster(befund)
    fenster.show()
    QApplication.processEvents()
    yield fenster
    fenster.close()


@pytest.fixture(autouse=True)
def ohne_begleitdateien(monkeypatch, tmp_path):
    """Keine Begleitdateien und keine Frage danach - es sei denn, ein Test will sie. Und
    der Vorschau-Cache liegt nie am echten Ort: Ein Test, der ihn umzieht, loeschte sonst
    den Cache des Anwenders."""
    from silberkorn import einstellungen, vorschau_cache
    monkeypatch.setattr(einstellungen, "begleitdateien", lambda: False)
    monkeypatch.setattr(vorschau_cache, "standard_ordner", lambda: str(tmp_path / "standard"))


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


def test_schwarzweiss_und_toenung(fenster, tmp_path, monkeypatch):
    """Schalter, Filter- und Tönungsvorlagen wirken aufs Bild, sind je ein Schritt und
    lassen sich zuruecknehmen."""
    import numpy as np
    from PIL import Image

    from silberkorn import einstellungen
    from silberkorn import filter as f
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "bild.png")
    Image.new("RGB", (64, 48), (200, 60, 40)).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        assert seite.sw_box.isEnabled() and not seite.sw_filter_wahl.isEnabled()
        assert not seite.sw_zeilen[0].schieber.isEnabled()
        seite.sw_box.setChecked(True)
        assert seite.sitzung.werte.sw and seite.sw_zeilen[0].schieber.isEnabled()
        bild, _ms, _h = seite.sitzung.vorschau()
        bild = np.asarray(bild).astype(int)
        assert np.abs(bild[..., 0] - bild[..., 2]).max() <= 1          # grau

        seite.sw_filter_wahl.activated.emit(seite.sw_filter_wahl.findData("rot"))
        assert seite.sitzung.werte.sw_mischer == f.SW_FILTER["rot"]
        seite.sw_zeilen[0].schieber.setValue(seite.sw_zeilen[0].schieber.value() + 10)
        assert seite.sw_filter_wahl.currentIndex() == -1             # eigene Mischung

        seite.ton_vorlage_wahl.activated.emit(seite.ton_vorlage_wahl.findData("sepia"))
        assert tuple(getattr(seite.sitzung.werte, n) for n in f.TONUNG) \
            == f.TONUNG_VORLAGEN["sepia"]
        assert seite.zeilen["ton_schatten_saettigung"].wert() == 35
        seite._festhalten(sofort=True)
        assert "Tönungsvorlage" in seite.rueckgaengig_knopf.toolTip()
        seite.rueckgaengig()
        assert not seite.sitzung.werte.tonung_aktiv()
        assert seite.ton_vorlage_wahl.currentData() == ""
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_lokale_anpassungen(fenster, tmp_path, monkeypatch):
    """Maske anlegen, Radial aufziehen, Regler, Griff ziehen, Teil dazu, Rueckgaengig."""
    import numpy as np
    from PIL import Image
    from PySide6.QtCore import Qt

    from silberkorn import einstellungen, lokal
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "bild.png")
    Image.new("RGB", (160, 120), (70, 70, 70)).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        assert not seite.lokal_bereich.isVisibleTo(seite)
        seite.lokal_neue_maske("radial")
        assert seite.leinwand.lokalmodus and seite.leinwand.lokal_neu == "radial"
        assert len(seite.sitzung.werte.masken) == 1
        # Von der Mitte nach aussen ziehen (Bildpunkte = Original, keine Geometrie)
        seite._lokal_gezogen("neu", -1, "radial", 80, 60, 110, 75, False)
        seite._lokal_gezogen("neu", -1, "radial", 80, 60, 120, 80, True)
        maske = seite.sitzung.werte.masken[0]
        assert len(maske.teile) == 1 and seite.leinwand.lokal_neu is None
        assert maske.teile[0].daten[:4] == pytest.approx((0.5, 0.5, 0.25, 0.125))
        assert len(seite.leinwand.lokal_formen) == 1
        seite.lokal_zeilen["belichtung"].schieber.setValue(
            seite.lokal_zeilen["belichtung"].schieber.value() + 20)          # +1 EV
        assert lokal.wert(seite.sitzung.werte.masken[0], "belichtung") == 1.0
        bild, _ms, _h = seite.sitzung.vorschau()
        bild = np.asarray(bild).astype(int)
        mitte, ecke = bild[bild.shape[0] // 2, bild.shape[1] // 2], bild[2, 2]
        assert mitte[0] > ecke[0] + 20

        # Griff „x+“ ziehen macht die Ellipse breiter
        g = seite.leinwand.lokal_formen[0]["griffe"]["x+"]
        seite._lokal_gezogen("griff", 0, "x+", *g, g[0] + 20, g[1], True)
        assert seite.sitzung.werte.masken[0].teile[0].daten[2] == pytest.approx(0.375, abs=0.01)
        # Zweiter Teil: Verlauf, abgezogen
        seite.lokal_teil_neu("verlauf")
        seite._lokal_gezogen("neu", -1, "verlauf", 80, 0, 80, 60, True)
        seite._festhalten(sofort=True)
        seite.lokal_modus_wahl.activated.emit(seite.lokal_modus_wahl.findData("weg"))
        teile = seite.sitzung.werte.masken[0].teile
        assert [t.art for t in teile] == ["radial", "verlauf"] and teile[1].modus == "weg"
        assert seite.lokal_teile.count() == 2

        seite.lokal_zeigen_box.setChecked(True)
        seite._zeichnen()
        assert seite.sitzung.lokal_zeigen == 0
        seite._festhalten(sofort=True)
        assert "Lokale Anpassungen" in seite.rueckgaengig_knopf.toolTip()
        seite.rueckgaengig()
        assert seite.sitzung.werte.masken[0].teile[1].modus == "dazu"

        seite.lokal_duplizieren()
        assert len(seite.sitzung.werte.masken) == 2 and seite._lokal_maske == 1
        seite.lokal_liste.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert not seite.sitzung.werte.masken[0].an
        seite.lokal_teil_loeschen()
        assert len(seite.sitzung.werte.masken[1].teile) == 1
        seite._abbrechen()                                        # Esc
        assert not seite.leinwand.lokalmodus
        seite._zeichnen()
        assert seite.sitzung.lokal_zeigen is None
        assert not seite.lokal_bereich.isVisibleTo(seite)
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_kartenwahl_springt_und_laeuft_mit(fenster):
    """Die Auswahl ueber den Karten nennt jede Karte, springt zu ihr und zeigt beim Rollen
    die oberste. Leinwand und erste Karte beginnen auf derselben Hoehe."""
    from PySide6.QtWidgets import QApplication, QFrame

    seite = fenster.bearbeiten
    fenster.resize(1100, 700)
    QApplication.processEvents()
    wahl, leiste = seite.kartenwahl, seite.reglerleiste
    karten = leiste.widget().findChildren(QFrame, "karte")
    assert len(seite.karten) == len(karten) == wahl.count() >= 20
    assert [wahl.itemText(i) for i in range(wahl.count())] == [
        seite._karten_titel[k] for k in seite.karten]
    assert seite.leinwand.y() == leiste.y()
    balken = leiste.verticalScrollBar()
    try:
        for nummer in (5, wahl.count() - 1, 0):
            seite.zu_karte(nummer, weich=False)
            assert balken.value() == min(seite.karten[nummer].y(), balken.maximum())
            assert wahl.currentIndex() == nummer
        mitte = seite.karten[8]
        assert mitte.y() < balken.maximum()
        balken.setValue(mitte.y() + 3)            # von Hand gerollt
        assert wahl.currentIndex() == 8
        assert wahl.view().sizeHintForRow(0) < 30   # kompakt: alle Karten passen in die Liste
    finally:
        balken.setValue(0)


def test_scan_und_film(fenster, tmp_path, monkeypatch):
    """Die Karte wandelt ein Negativ um, die Pipette misst den Filmrand, Rueckgaengig nimmt
    beides zurueck. Ein RGBI-Scan meldet seinen Infrarotkanal."""
    import numpy as np
    import tifffile
    from PySide6.QtWidgets import QApplication
    from test_film import MASKE, graukeil, mit_filmrand, negativ_von

    from silberkorn import bilddatei, einstellungen, filter
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "negativ.tif")
    bilddatei.speichern(pfad, filter.nach_16bit(mit_filmrand(negativ_von(graukeil()))))
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        assert seite.karten.index(seite.film_art.parentWidget()) == \
            [seite._karten_titel[k] for k in seite.karten].index("Motiv & Hintergrund") - 1
        assert not seite.film_pipette_knopf.isEnabled()
        assert not seite.staub_teil.isVisibleTo(seite)
        seite.film_art.setCurrentIndex(seite.film_art.findData("farbnegativ"))
        seite._festhalten(sofort=True)
        werte = seite.sitzung.werte
        assert werte.film == "farbnegativ" and len(werte.film_umfang) == 6
        assert seite.film_pipette_knopf.isEnabled()
        automatisch = werte.film_maske

        seite.film_pipette_knopf.setChecked(True)
        assert seite._klick_ziel == "film"
        seite._bild_geklickt(15.0, 40.0, True)
        seite._festhalten(sofort=True)
        assert seite._klick_ziel is None and not seite.film_pipette_knopf.isChecked()
        assert np.allclose(seite.sitzung.werte.film_maske, MASKE, rtol=0.01)
        assert "Scan & Film" in seite.rueckgaengig_knopf.toolTip()

        seite.rueckgaengig()
        assert seite.sitzung.werte.film_maske == automatisch
        seite.rueckgaengig()
        assert seite.sitzung.werte.film == "" and seite.film_art.currentData() == ""
        assert not seite.film_pipette_knopf.isEnabled()

        rgbi = str(tmp_path / "rgbi.tif")
        pixel = np.zeros((20, 30, 4), dtype=np.uint8)
        tifffile.imwrite(rgbi, pixel, photometric="rgb", extrasamples=[0])
        seite.oeffnen(rgbi)
        QApplication.processEvents()
        assert seite.staub_teil.isVisibleTo(seite)
        assert seite.sitzung.daten.alpha is None
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_staub_entfernen(fenster, tmp_path, monkeypatch):
    """Ein RGBI-Filmscan: Fundstellen zeigen, Staub entfernen, Rueckgaengig. Ein Luftbild
    bietet die Suche nicht an."""
    import numpy as np
    import tifffile
    from test_staub import mit_staub

    from silberkorn import einstellungen, filter
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    bild, ir, _punkte = mit_staub()
    pfad = str(tmp_path / "scan.tif")
    tifffile.imwrite(pfad, np.dstack([filter.nach_16bit(bild), (ir * 65535).astype(np.uint16)]),
                     photometric="rgb", extrasamples=[0])
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        assert seite.staub_knopf.isEnabled() and not seite.staub_weg_knopf.isEnabled()
        seite.staub_zeigen_box.setChecked(True)
        assert seite.sitzung.staub_fund[1] == 41 and "41" in seite.staub_hinweis.text()
        seite.staub_entfernen()
        seite._festhalten(sofort=True)
        assert seite.sitzung.staub_entfernt and seite.staub_weg_knopf.isEnabled()
        assert not seite.staub_zeigen_box.isChecked()
        assert "Staub entfernt" in seite.rueckgaengig_knopf.toolTip()
        seite.rueckgaengig()
        assert not seite.sitzung.staub_entfernt and not seite.staub_weg_knopf.isEnabled()

        zufall = np.random.default_rng(2)
        landschaft = np.kron(zufall.random((15, 23)), np.ones((20, 20)))[:300, :450]
        luft = str(tmp_path / "luftbild.tif")
        tifffile.imwrite(luft, np.dstack([filter.nach_8bit(bild),
                                          (landschaft * 255).astype(np.uint8)]),
                         photometric="rgb", extrasamples=[0])
        seite.oeffnen(luft)
        assert seite.staub_teil.isVisibleTo(seite) and not seite.staub_knopf.isEnabled()
        assert "Motiv selbst" in seite.staub_hinweis.text()
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_fotos_trennen(fenster, tmp_path, monkeypatch):
    """Fotos trennen speichert die gewaehlten Fotos und oeffnet das gewaehlte."""
    from test_trennen import scan

    from silberkorn import bilddatei, einstellungen, filter
    from silberkorn.trennen_dialog import TrennenDialog
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "platte.png")
    bilddatei.speichern(pfad, filter.nach_8bit(scan()))

    def annehmen(dialog):
        dialog.kacheln[0].setChecked(False)
        dialog.oeffnen_wahl.setCurrentIndex(dialog.oeffnen_wahl.findData(2))
        return TrennenDialog.DialogCode.Accepted

    monkeypatch.setattr(TrennenDialog, "exec", annehmen)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        assert seite.trennen_knopf.isEnabled()
        seite.fotos_trennen()
        namen = sorted(p.name for p in tmp_path.iterdir())
        assert namen == ["platte-01.png", "platte-02.png", "platte.png"]
        assert seite.sitzung.daten.name == "platte-02.png"   # Foto 3 ist die zweite Datei
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_begleitdatei_beim_wechsel(fenster, tmp_path, monkeypatch):
    """Beim Wechsel des Bildes wird die Bearbeitung neben das Bild gesichert und beim
    naechsten Oeffnen wiederhergestellt; alles zurueckgesetzt, verschwindet die Datei."""
    from PIL import Image

    from silberkorn import begleitdatei, einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    monkeypatch.setattr(einstellungen, "begleitdateien", lambda: True)
    erstes, zweites = str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")
    Image.new("RGB", (64, 48), (90, 120, 150)).save(erstes)
    Image.new("RGB", (64, 48), (150, 120, 90)).save(zweites)
    seite = fenster.bearbeiten
    seite.oeffnen(erstes)
    try:
        seite.zeilen["kontrast"].schieber.setValue(140)
        assert seite.sitzung.werte.kontrast != 0
        kontrast = seite.sitzung.werte.kontrast
        seite.oeffnen(zweites)                     # ohne Nachfrage: die Bearbeitung ist gesichert
        assert seite.sitzung.daten.name == "b.jpg"
        assert os.path.isfile(begleitdatei.pfad_fuer(erstes))
        assert not os.path.exists(begleitdatei.pfad_fuer(zweites))   # unbearbeitet

        seite.oeffnen(erstes)
        assert seite.sitzung.werte.kontrast == kontrast
        assert seite.zeilen["kontrast"].wert() == kontrast
        assert not seite.sitzung.begleit_geaendert and not seite.verlauf.kann_zurueck

        seite.alles_zuruecksetzen()
        seite.oeffnen(zweites)
        assert not os.path.exists(begleitdatei.pfad_fuer(erstes))
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_voreinstellung_und_kopieren(fenster, tmp_path, monkeypatch):
    """Eine Voreinstellung sichern und anwenden, Einstellungen kopieren und einfuegen -
    beides laesst sich zuruecknehmen."""
    from PIL import Image

    from silberkorn import einstellungen, voreinstellungen
    from silberkorn.voreinstellung_dialog import VoreinstellungDialog
    monkeypatch.setattr(einstellungen, "programm_ordner", lambda: str(tmp_path))

    def annehmen(dialog):
        if dialog.name is not None:
            dialog.name.setText("Mein Look")
        return VoreinstellungDialog.DialogCode.Accepted

    monkeypatch.setattr(VoreinstellungDialog, "exec", annehmen)
    pfad = str(tmp_path / "bild.jpg")
    Image.new("RGB", (64, 48), (90, 120, 150)).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        seite.zeilen["kontrast"].schieber.setValue(140)
        seite.zeilen["begradigen"].schieber.setValue(120)    # Geometrie geht nicht mit
        kontrast = seite.sitzung.werte.kontrast
        seite.voreinstellung_sichern()
        assert voreinstellungen.namen() == ["Mein Look"]
        assert seite.vor_wahl.currentText() == "Mein Look"

        seite.alles_zuruecksetzen()
        seite._festhalten(sofort=True)
        seite.voreinstellung_anwenden()
        seite._festhalten(sofort=True)
        assert seite.sitzung.werte.kontrast == kontrast
        assert seite.sitzung.werte.begradigen == 0
        assert "Voreinstellung" in seite.rueckgaengig_knopf.toolTip()
        seite.rueckgaengig()
        assert seite.sitzung.werte.kontrast == 0

        seite.zeilen["kontrast"].schieber.setValue(60)
        seite.einstellungen_kopieren()
        assert seite.vor_einfuegen_knopf.isEnabled()
        wert = seite.sitzung.werte.kontrast
        seite.alles_zuruecksetzen()
        seite.einstellungen_einfuegen()
        assert seite.sitzung.werte.kontrast == wert
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def _warten(bedingung, sekunden=10.0):
    import time

    from PySide6.QtWidgets import QApplication
    ende = time.monotonic() + sekunden
    while not bedingung() and time.monotonic() < ende:
        QApplication.processEvents()
        time.sleep(0.01)
    return bedingung()


def test_ordneransicht(fenster, tmp_path, monkeypatch):
    """Kacheln entstehen im Hintergrund, eine Begleitdatei ist markiert, Doppelklick
    oeffnet das Bild zum Bearbeiten."""
    from PIL import Image

    from silberkorn import begleitdatei, einstellungen, vorschaubilder
    from silberkorn.filter import Einstellungen
    from silberkorn.ordner_seite import BEARBEITET_ROLLE, ZUSTAND_ROLLE
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    for name, farbe in (("b10.jpg", (200, 0, 0)), ("b2.png", (0, 200, 0)),
                        ("c.jpg", (0, 0, 200))):
        Image.new("RGB", (64, 48), farbe).save(tmp_path / name)
    (tmp_path / "notiz.txt").write_text("kein Bild")
    (tmp_path / "kaputt.jpg").write_bytes(b"kein jpeg")
    (tmp_path / "unter").mkdir()
    (tmp_path / ".versteckt").mkdir()
    bearbeitet = str(tmp_path / "c.jpg")
    begleitdatei.schreiben(bearbeitet, begleitdatei.Inhalt(
        Einstellungen(kontrast=20.0),
        vorschau=vorschaubilder.kodieren(Image.new("RGB", (32, 24), (255, 255, 0)))),
        begleitdatei.fingerabdruck(bearbeitet))
    seite = fenster.ordner
    fenster.reiter.setCurrentWidget(seite)
    seite.ordner_zeigen(str(tmp_path))
    modell = seite.modell
    try:
        assert [os.path.basename(p) for p in modell.pfade] == \
            ["unter", "b2.png", "b10.jpg", "c.jpg", "kaputt.jpg"]   # Ordner zuerst, sortiert
        for zeile in range(5):
            modell.data(modell.index(zeile), BEARBEITET_ROLLE)   # wie beim Zeichnen
        bilder = modell.pfade[1:4]
        assert _warten(lambda: all(p in modell._bilder for p in bilder)
                       and modell.data(modell.index(4), ZUSTAND_ROLLE) == "fehlt")
        assert modell.data(modell.index(0), ZUSTAND_ROLLE) == "ordner"
        assert modell.data(modell.index(3), BEARBEITET_ROLLE) is True
        assert modell.data(modell.index(1), BEARBEITET_ROLLE) is False

        seite._doppelklick(modell.index(0))               # in den Unterordner
        assert seite.ordner == str(tmp_path / "unter") and modell.pfade == []
        seite.ordner_hoch()
        assert seite.ordner == str(tmp_path)
        seite._doppelklick(modell.index(3))
        assert fenster.reiter.currentWidget() is fenster.bearbeiten
        assert fenster.bearbeiten.sitzung.werte.kontrast == 20.0
    finally:
        fenster.bearbeiten.schliessen()
        fenster.bearbeiten._knoepfe_freischalten()
        seite.ordner_zeigen("")
        fenster.reiter.setCurrentWidget(fenster.bearbeiten)


@pytest.mark.skipif(os.name != "nt", reason="DPAPI nur unter Windows")
def test_vorschau_cache_einrichten(fenster, tmp_path, monkeypatch):
    """Der Dialog legt den Cache an, teure Vorschaubilder landen darin; 0 MB entfernt ihn."""
    from PIL import Image

    from silberkorn import einstellungen, ordner_seite, vorschau_cache, vorschaubilder
    konfiguration = {}
    monkeypatch.setattr(einstellungen, "load_config", lambda: dict(konfiguration))
    monkeypatch.setattr(einstellungen, "save_config",
                        lambda daten: konfiguration.update(daten) or True)
    monkeypatch.setattr(vorschaubilder, "TEUER_MS", -1)   # alles gilt als teuer
    ablage = tmp_path / "cache"
    bilder = tmp_path / "bilder"
    bilder.mkdir()
    Image.new("RGB", (64, 48), (90, 120, 150)).save(bilder / "a.png")
    wahl = {"mb": 16}

    def annehmen(dialog):
        dialog.groesse.setValue(wahl["mb"])
        dialog._ort = str(ablage)
        return ordner_seite.CacheDialog.DialogCode.Accepted

    monkeypatch.setattr(ordner_seite.CacheDialog, "exec", annehmen)
    seite = fenster.ordner
    datei = ablage / vorschau_cache.DATEINAME
    try:
        seite.cache_einstellen(True)
        assert konfiguration["vorschau_cache_mb"] == 16
        assert _warten(lambda: datei.exists() and seite._cache_stand is not None)
        assert 15 * 2**20 < os.path.getsize(datei) <= 16 * 2**20
        seite.ordner_zeigen(str(bilder))
        seite.modell.data(seite.modell.index(0), ordner_seite.BEARBEITET_ROLLE)
        assert _warten(lambda: seite.modell.pfade[0] in seite.modell._bilder)
        seite.dienst.befehl("stand")
        assert _warten(lambda: seite._cache_stand is not None and seite._cache_stand[2] == 1)

        wahl["mb"] = 0
        seite.cache_einstellen(False)
        assert _warten(lambda: not datei.exists())
    finally:
        seite.ordner_zeigen("")


def test_stapel(fenster, tmp_path, monkeypatch):
    """Eine Voreinstellung auf mehrere Bilder legen, Begleitdateien schreiben und ausgeben -
    nie ueber eine vorhandene Datei; ein kaputtes Bild haelt die anderen nicht auf."""
    from PIL import Image

    from silberkorn import begleitdatei, einstellungen, ordner_seite, voreinstellungen
    from silberkorn.filter import Einstellungen
    from silberkorn.stapel_dialog import StapelDialog
    monkeypatch.setattr(einstellungen, "programm_ordner", lambda: str(tmp_path / "programm"))
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    voreinstellungen.sichern("Kontrast", voreinstellungen.als_dict(
        Einstellungen(kontrast=30.0), voreinstellungen.Auswahl()))
    bilder = tmp_path / "bilder"
    bilder.mkdir()
    Image.new("RGB", (64, 48), (90, 120, 150)).save(bilder / "a.jpg")
    Image.new("RGB", (64, 48), (150, 120, 90)).save(bilder / "b.png")
    (bilder / "kaputt.jpg").write_bytes(b"kein jpeg")
    ziel = bilder / "bearbeitet"
    ziel.mkdir()
    (ziel / "a-bearbeitet.jpg").write_bytes(b"schon da")

    def annehmen(dialog):
        dialog.wahl.setCurrentIndex(dialog.wahl.findData("Kontrast"))
        dialog.begleit.setChecked(True)
        dialog.ausgeben.setChecked(True)
        dialog.format.setCurrentIndex(0)                      # JPEG
        return StapelDialog.DialogCode.Accepted

    berichte = []
    monkeypatch.setattr(StapelDialog, "exec", annehmen)
    monkeypatch.setattr(ordner_seite.QMessageBox, "exec",
                        lambda box: berichte.append((box.text(), box.detailedText())) or 0)
    seite = fenster.ordner
    seite.ordner_zeigen(str(bilder))
    try:
        seite.liste.selectAll()
        assert sorted(os.path.basename(p) for p in seite.gewaehlte_bilder()) == \
            ["a.jpg", "b.png", "kaputt.jpg"]                  # ohne den Ordner
        assert seite.stapel_knopf.isEnabled()
        seite.stapel_starten()
        assert berichte and berichte[0][0].startswith("2 von 3")
        assert "kaputt.jpg" in berichte[0][1]
        assert (ziel / "a-bearbeitet.jpg").read_bytes() == b"schon da"   # nicht ueberschrieben
        assert sorted(p.name for p in ziel.iterdir()) == \
            ["a-bearbeitet-2.jpg", "a-bearbeitet.jpg", "b-bearbeitet.jpg"]
        for name in ("a.jpg", "b.png"):
            pfad = str(bilder / name)
            inhalt = begleitdatei.lesen(pfad, 48, 64)
            assert inhalt.werte.kontrast == 30.0 and inhalt.vorschau is not None
    finally:
        seite.ordner_zeigen("")
