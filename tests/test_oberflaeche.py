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


def test_lokaler_pinsel(fenster, tmp_path, monkeypatch):
    """Pinsel: der erste Strich legt den Teil an, Punkte folgen mit Abstand, rechts radiert,
    Groesse mit [ und ]."""
    import numpy as np
    from PIL import Image

    from silberkorn import einstellungen, lokal
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "bild.png")
    Image.new("RGB", (160, 120), (70, 70, 70)).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        seite.lokal_neue_maske("pinsel")
        assert seite.leinwand.lokal_pinsel and seite.lokal_malen_feld.isVisibleTo(seite)
        assert seite.lokal_zeigen_box.isChecked()
        assert seite.sitzung.werte.masken[0].teile == ()
        seite._lokal_gemalt(20, 60, False, True)
        for x in (20.5, 21, 40, 60, 80):     # 20,5: naeher als 0,2 Radius (0,64 px), faellt weg
            seite._lokal_gemalt(x, 60, False, False)
        teil = seite.sitzung.werte.masken[0].teile[0]
        assert teil.art == "pinsel" and len(teil.striche) == 1
        assert len(teil.striche[0].punkte) == 2 * 5
        assert teil.striche[0].radius == pytest.approx(0.2 * 0.1)
        seite._lokal_gemalt(50, 40, True, True)          # zweiter Strich radiert
        seite._lokal_gemalt(50, 80, True, False)
        teil = seite.sitzung.werte.masken[0].teile[0]
        assert [s.radieren for s in teil.striche] == [False, True]
        assert len(seite.sitzung.werte.masken[0].teile) == 1

        seite.lokal_zeilen["belichtung"].schieber.setValue(
            seite.lokal_zeilen["belichtung"].schieber.value() + 20)
        seite.lokal_zeigen_box.setChecked(False)
        seite._zeichnen()
        bild, _ms, _h = seite.sitzung.vorschau()
        bild = np.asarray(bild).astype(int)
        h, w = bild.shape[:2]
        assert bild[h // 2, w // 5, 0] > bild[h // 5, w // 5, 0] + 20     # gemalt: heller
        assert abs(bild[h // 2, int(w * 50 / 160), 0] - 70) < 8           # radiert

        groesse = seite.malen_zeilen["malen_groesse"].wert()
        seite._malen_groesse_schritt(1)
        assert seite.malen_zeilen["malen_groesse"].wert() > groesse
        assert seite._malen["malen_groesse"] == seite.malen_zeilen["malen_groesse"].wert()
        # Ein anderer Teil gewaehlt: der Pinsel ruht
        seite.lokal_teil_neu("radial")
        assert not seite.leinwand.lokal_pinsel
        assert lokal.uebertragbar(seite.sitzung.werte.masken) == ()
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_lokale_bereiche_und_pipette(fenster, tmp_path, monkeypatch):
    """Helligkeits- und Farbbereich aus dem Menue, Regler des Teils, Pipette."""
    import numpy as np
    from PIL import Image

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "bild.png")
    pixel = np.zeros((120, 160, 3), np.uint8)
    pixel[:, :80] = (200, 40, 40)
    pixel[:, 80:] = (40, 60, 200)
    Image.fromarray(pixel).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        menue = seite.lokal_neu_knopf.menu()
        assert len([a for a in menue.actions() if not a.isSeparator()]) == 8
        seite.lokal_neue_maske("farbe")
        teil = seite.sitzung.werte.masken[0].teile[0]
        assert teil.art == "farbe" and seite.lokal_bereich_felder["farbe"].isVisibleTo(seite)
        assert not seite.lokal_ki_feld.isVisibleTo(seite)
        seite.lokal_pipette_knopf.setChecked(True)
        assert seite._klick_ziel == "lokal_farbe"
        seite._bild_geklickt(40.0, 60.0, True)                     # rot
        assert seite._klick_ziel is None
        farbton = seite.sitzung.werte.masken[0].teile[0].daten[0]
        assert farbton < 50 or farbton > 340
        seite.lokal_zeilen["belichtung"].schieber.setValue(
            seite.lokal_zeilen["belichtung"].schieber.value() + 20)
        seite.lokal_zeigen_box.setChecked(False)
        seite._zeichnen()
        bild, _ms, _h = seite.sitzung.vorschau()
        bild = np.asarray(bild).astype(int)
        w = bild.shape[1]
        assert bild[30, w // 4, 0] > 230 and abs(bild[30, 3 * w // 4, 2] - 200) <= 2

        seite.lokal_teil_neu("helligkeit")
        zeilen = seite.lokal_bereich_zeilen["helligkeit"]
        assert seite.lokal_bereich_felder["helligkeit"].isVisibleTo(seite)
        assert not seite.lokal_bereich_felder["farbe"].isVisibleTo(seite)
        zeilen[0].setzen(10)
        zeilen[0]._bewegt()
        assert seite.sitzung.werte.masken[0].teile[1].daten[0] == 10
        seite.lokal_modus_wahl.activated.emit(seite.lokal_modus_wahl.findData("schnitt"))
        assert seite.sitzung.werte.masken[0].teile[1].modus == "schnitt"
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_kartenwahl_springt_und_laeuft_mit(fenster):
    """Die Auswahl ueber den Karten nennt jede Karte, springt zu ihr und zeigt beim Rollen
    die oberste. Die Leinwand beginnt auf der Hoehe des Histogramms, die erste Karte
    darunter."""
    from PySide6.QtWidgets import QApplication, QFrame

    seite = fenster.bearbeiten
    fenster.resize(1100, 700)
    QApplication.processEvents()
    wahl, leiste = seite.kartenwahl, seite.reglerleiste
    karten = leiste.widget().findChildren(QFrame, "karte")
    assert len(seite.karten) == len(karten) == wahl.count() >= 20
    assert [wahl.itemText(i) for i in range(wahl.count())] == [
        seite._karten_titel[k] for k in seite.karten]
    assert seite.leinwand.y() == seite.histogramm.y()
    assert seite.histogramm.geometry().bottom() < leiste.y()
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


def test_vergleich_knopf_taste_und_pausen(fenster, tmp_path):
    """◧ rastet ein, Y schaltet ihn um, der Zuschnitt pausiert die Trennlinie; ohne Bild ist
    der Knopf aus, und „Vorher“ bleibt davon unberuehrt."""
    from PIL import Image
    from PySide6.QtGui import QShortcut
    from PySide6.QtWidgets import QApplication
    seite = fenster.bearbeiten
    knopf, leinwand = seite.vergleich_knopf, seite.leinwand
    taste_y = next(k for k in seite.findChildren(QShortcut) if k.key().toString() == "Y")
    assert knopf.text() == "◧" and knopf.isCheckable() and not knopf.isEnabled()
    pfad = str(tmp_path / "bild.png")
    Image.new("RGB", (64, 48), (90, 120, 150)).save(pfad)
    seite.oeffnen(pfad)
    try:
        QApplication.processEvents()
        assert knopf.isEnabled() and not knopf.isChecked() and not leinwand.vergleich
        taste_y.activated.emit()                              # die Taste Y
        assert knopf.isChecked() and leinwand.vergleich and leinwand.vergleich_gilt()
        QApplication.processEvents()
        assert leinwand._bild_vorher is not None              # die linke Haelfte ist da
        assert not seite._vorher                              # „Vorher“-Sperren bleiben offen
        seite.zuschneiden(True)                               # Zuschnittmodus
        assert leinwand.zuschnitt is not None
        assert knopf.isChecked() and not leinwand.vergleich_gilt()
        seite.zuschnitt_abbrechen()
        QApplication.processEvents()
        assert leinwand.vergleich_gilt() and leinwand._bild_vorher is not None
        seite.vorher_knopf.pressed.emit()                     # „Vorher“ gedrueckt halten
        assert seite._vorher and not leinwand.vergleich_gilt() and knopf.isChecked()
        seite.vorher_knopf.released.emit()
        QApplication.processEvents()
        assert not seite._vorher and leinwand.vergleich_gilt()
        taste_y.activated.emit()
        assert not knopf.isChecked() and not leinwand.vergleich
    finally:
        seite.vergleich_knopf.setChecked(False)
        seite.schliessen()
        seite._knoepfe_freischalten()
    assert not knopf.isEnabled()


def test_vergleich_knopf_bleibt_beim_bildwechsel_an(fenster, tmp_path):
    from PIL import Image
    seite = fenster.bearbeiten
    erstes, zweites = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    Image.new("RGB", (64, 48), (90, 120, 150)).save(erstes)
    Image.new("RGB", (48, 64), (150, 120, 90)).save(zweites)
    seite.oeffnen(erstes)
    try:
        seite.vergleich_knopf.setChecked(True)
        seite.oeffnen(zweites)
        assert seite.vergleich_knopf.isChecked() and seite.leinwand.vergleich
    finally:
        seite.vergleich_knopf.setChecked(False)
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_histogramm_warnung_taste_j_und_gemerkter_zustand(fenster, tmp_path, monkeypatch):
    """Das Histogramm steht fest ueber den Karten, J schaltet beide Warnungen, der Zustand
    landet in der Einstellungsdatei - und „Vorher“ zeigt nie die Markierung."""
    from PIL import Image
    from PySide6.QtGui import QShortcut
    from PySide6.QtWidgets import QApplication

    from silberkorn import einstellungen
    from silberkorn.bearbeiten_seite import REGLERLEISTE_BREITE
    gemerkt: dict = {}
    monkeypatch.setattr(einstellungen, "load_config", lambda: dict(gemerkt))
    monkeypatch.setattr(einstellungen, "save_config",
                        lambda daten: gemerkt.update(daten) or True)
    def warnung():
        return {k: v for k, v in gemerkt.items() if k.startswith("warnung")}

    seite = fenster.bearbeiten
    feld = seite.histogramm
    assert feld.width() == REGLERLEISTE_BREITE and not feld.isEnabled()
    assert not seite.reglerleiste.isAncestorOf(feld)          # rollt nicht mit
    assert feld.geometry().bottom() < seite.reglerleiste.geometry().top()
    taste_j = next(k for k in seite.findChildren(QShortcut) if k.key().toString() == "J")
    taste_j.activated.emit()                                  # ohne Bild: nichts
    assert not feld.lichter and gemerkt == {}
    pfad = str(tmp_path / "bild.png")
    Image.new("RGB", (64, 48), (255, 120, 0)).save(pfad)
    seite.oeffnen(pfad)
    aufrufe = []
    echt = seite.sitzung.vorschau

    def merken(*args, **kwargs):
        aufrufe.append(kwargs.get("abschneiden_zeigen"))
        return echt(*args, **kwargs)

    monkeypatch.setattr(seite.sitzung, "vorschau", merken)
    try:
        QApplication.processEvents()
        assert feld.isEnabled() and feld.abgeschnitten == (48 * 64, 48 * 64)   # R 255 und B 0
        taste_j.activated.emit()
        QApplication.processEvents()
        assert feld.lichter and feld.tiefen
        assert warnung() == {"warnung_lichter": True, "warnung_tiefen": True}
        assert aufrufe[-1] == (True, True)
        seite.vorher_knopf.pressed.emit()
        QApplication.processEvents()
        assert aufrufe[-1] == (False, False)
        seite.vorher_knopf.released.emit()
        QApplication.processEvents()
        assert aufrufe[-1] == (True, True)
        feld.warnung_setzen(True, False, melden=True)         # wie ein Klick aufs Dreieck
        assert warnung() == {"warnung_lichter": True, "warnung_tiefen": False}
        taste_j.activated.emit()                              # nicht beide an: beide an
        assert feld.lichter and feld.tiefen
        taste_j.activated.emit()
        assert not feld.lichter and not feld.tiefen
        assert warnung() == {"warnung_lichter": False, "warnung_tiefen": False}
    finally:
        feld.warnung_setzen(False, False)
        seite.schliessen()
        seite._knoepfe_freischalten()
    assert not feld.isEnabled() and feld.abgeschnitten == (0, 0)


def test_histogramm_und_warnung_in_der_100_prozent_ansicht(fenster, tmp_path, monkeypatch):
    """Die 100-%-Ansicht fragt den Ausschnitt mit der Wahl der Warnung an, bei gedrueckter
    „Vorher“-Taste ohne; beide Histogramme (Karten und Feld) bekommen ihre Daten."""
    import numpy as np
    from PIL import Image
    from PySide6.QtWidgets import QApplication

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "load_config", lambda: {})
    monkeypatch.setattr(einstellungen, "save_config", lambda daten: True)
    seite = fenster.bearbeiten
    pfad = str(tmp_path / "bild.png")
    Image.new("RGB", (64, 48), (255, 120, 0)).save(pfad)
    seite.oeffnen(pfad)
    aufrufe = []
    echt = seite.sitzung.ausschnitt

    def merken(*args, **kwargs):
        aufrufe.append(kwargs.get("abschneiden_zeigen"))
        return echt(*args, **kwargs)

    try:
        QApplication.processEvents()
        # Eingepasst: die Form der Daten beider Histogramme
        assert seite.kurven.flaeche.histogramm.shape == (256,)
        assert seite.histogramm.abgeschnitten == (48 * 64, 48 * 64)
        monkeypatch.setattr(seite.sitzung, "ausschnitt", merken)
        seite.histogramm.warnung_setzen(True, True)
        seite.leinwand.zoom_setzen(1.0)                       # 100 %
        QApplication.processEvents()
        seite._zeichnen()
        assert seite.leinwand.zoom == 1.0
        assert aufrufe and aufrufe[-1] == (True, True)
        assert seite.kurven.flaeche.histogramm.shape == (256,)
        assert seite.histogramm.abgeschnitten == (48 * 64, 48 * 64)
        seite.vorher_knopf.pressed.emit()
        QApplication.processEvents()
        assert aufrufe[-1] == (False, False)
        seite.vorher_knopf.released.emit()
        QApplication.processEvents()
        assert aufrufe[-1] == (True, True)
        seite.histogramm.warnung_setzen(True, False)
        seite._zeichnen()
        assert aufrufe[-1] == (True, False)
        assert isinstance(seite.kurven.flaeche.histogramm, np.ndarray)
    finally:
        seite.histogramm.warnung_setzen(False, False)
        seite.leinwand.zoom_setzen(None)
        seite.schliessen()
        seite._knoepfe_freischalten()


def _stich_bild(pfad, links=(130, 120, 110), rechts=(110, 120, 130)):
    """Zwei Hälften mit entgegengesetztem Farbstich, dazu etwas Helligkeitsstreuung."""
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(5)
    bild = np.empty((96, 128, 3), np.float32)
    bild[:, :64] = links
    bild[:, 64:] = rechts
    bild *= rng.uniform(0.7, 1.1, bild.shape[:2] + (1,))
    Image.fromarray(np.clip(bild, 0, 255).astype(np.uint8)).save(pfad)


def _nur_geaendert(seite, vorher, erlaubt):
    """Die Felder der Werte, die sich gegenüber `vorher` geändert haben, liegen in `erlaubt`."""
    from silberkorn import verlauf
    geaendert = set(verlauf.unterschied(
        verlauf.Stand(vorher, ()), verlauf.Stand(seite.sitzung.werte, ())))
    assert geaendert <= set(erlaubt), geaendert


def test_automatik_ohne_bild_gesperrt_und_keine_neuen_einstellungen(fenster):
    import dataclasses

    from silberkorn import filter as f
    seite = fenster.bearbeiten
    assert seite.sitzung is None
    for knopf in (seite.ton_auto_knopf, seite.wb_auto_knopf, seite.wb_pipette_knopf):
        assert not knopf.isEnabled()
    # Die Automatik setzt nur vorhandene Reglerwerte - kein eigenes Feld in den Einstellungen
    namen = {feld.name for feld in dataclasses.fields(f.Einstellungen)}
    assert not {n for n in namen if "auto" in n or "pipette" in n}


def test_auto_ton_ein_schritt_und_stabil(fenster, tmp_path, monkeypatch):
    import dataclasses

    import numpy as np
    from PIL import Image

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "dunkel.png")
    rng = np.random.default_rng(2)
    Image.fromarray(rng.integers(5, 70, (60, 80, 3)).astype(np.uint8)).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        assert seite.ton_auto_knopf.isEnabled()
        vorher = dataclasses.replace(seite.sitzung.werte)
        seite.ton_auto_knopf.click()
        werte = seite.sitzung.werte
        assert werte.belichtung > 0.5 and werte.tiefen >= 0
        assert seite.zeilen["belichtung"].wert() == werte.belichtung
        assert "Auto-Ton" in fenster.statusmeldung.text()
        _nur_geaendert(seite, vorher, ("belichtung", "kontrast", "lichter", "tiefen"))
        seite._festhalten(sofort=True)
        assert "Auto-Ton" in seite.rueckgaengig_knopf.toolTip()
        erster = dataclasses.replace(werte)
        # Noch einmal: dasselbe Ergebnis, kein weiterer Schritt
        seite.ton_auto_knopf.click()
        seite._festhalten(sofort=True)
        assert seite.sitzung.werte == erster
        seite.rueckgaengig()                      # ein Schritt zurück: alles wie am Anfang
        assert seite.sitzung.werte == vorher and not seite.rueckgaengig_knopf.isEnabled()
        seite.wiederholen()
        assert seite.sitzung.werte == erster
        # Andere Regler bleiben: erst Sättigung setzen, dann Auto
        seite.zeilen["saettigung"].schieber.setValue(
            seite.zeilen["saettigung"].schieber.value() + 20)
        seite._festhalten(sofort=True)
        mit_saettigung = dataclasses.replace(seite.sitzung.werte)
        seite.ton_auto_knopf.click()
        assert seite.sitzung.werte.saettigung == mit_saettigung.saettigung == 20
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_auto_weissabgleich_ein_schritt_und_sperre_bei_schwarzweiss(fenster, tmp_path,
                                                                    monkeypatch):
    import dataclasses

    import numpy as np

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "stich.png")
    _stich_bild(pfad, (130, 120, 110), (130, 120, 110))         # überall warm
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        assert seite.wb_auto_knopf.isEnabled() and seite.wb_pipette_knopf.isEnabled()
        vorher = dataclasses.replace(seite.sitzung.werte)
        seite.wb_auto_knopf.click()
        werte = seite.sitzung.werte
        assert werte.temperatur < -10
        assert seite.zeilen["temperatur"].wert() == werte.temperatur
        assert "Auto-Weißabgleich" in fenster.statusmeldung.text()
        _nur_geaendert(seite, vorher, ("temperatur", "toenung"))
        bild = np.asarray(seite.sitzung.vorschau()[0]).astype(int)
        assert np.abs(bild.mean(axis=(0, 1)) - bild.mean()).max() < 4          # im Mittel grau
        seite._festhalten(sofort=True)
        erster = dataclasses.replace(werte)
        seite.wb_auto_knopf.click()                               # stabil
        seite._festhalten(sofort=True)
        assert seite.sitzung.werte == erster
        seite.rueckgaengig()
        assert seite.sitzung.werte == vorher and not seite.rueckgaengig_knopf.isEnabled()

        # Schwarzweiß sperrt Auto-Weißabgleich und Pipette, nicht Auto-Ton
        seite.wb_pipette_knopf.setChecked(True)
        assert seite._klick_ziel == "wb" and seite.leinwand.klickmodus
        seite.sw_box.setChecked(True)
        assert seite._klick_ziel is None and not seite.leinwand.klickmodus
        assert not seite.wb_pipette_knopf.isChecked()
        assert not seite.wb_auto_knopf.isEnabled() and not seite.wb_pipette_knopf.isEnabled()
        assert seite.ton_auto_knopf.isEnabled()
        seite.wb_pipette_knopf.setChecked(True)                   # gesperrt: tut nichts
        assert seite._klick_ziel is None
        seite.wb_pipette_knopf.setChecked(False)
        seite.sw_box.setChecked(False)
        assert seite.wb_auto_knopf.isEnabled() and seite.wb_pipette_knopf.isEnabled()
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_wb_pipette_klick_esc_und_andere_modi(fenster, tmp_path, monkeypatch):
    import dataclasses

    import numpy as np
    from PySide6.QtWidgets import QApplication

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "stich.png")
    _stich_bild(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    leinwand = seite.leinwand
    try:
        QApplication.processEvents()
        seite.vergleich_knopf.setChecked(True)
        assert leinwand.vergleich_gilt()
        vorher = dataclasses.replace(seite.sitzung.werte)

        seite.wb_pipette_knopf.setChecked(True)
        assert seite._klick_ziel == "wb" and leinwand.klickmodus
        assert seite.wb_pipette_knopf.isChecked()
        assert not leinwand.vergleich_gilt()                      # die Trennlinie ruht
        assert leinwand.cursor().shape().name == "CrossCursor"
        seite._bild_geklickt(30.0, 40.0, False)                   # rechte Taste: nichts
        assert seite._klick_ziel == "wb" and seite.sitzung.werte == vorher
        seite._abbrechen()                                        # Esc
        assert seite._klick_ziel is None and not seite.wb_pipette_knopf.isChecked()
        assert not leinwand.klickmodus and leinwand.vergleich_gilt()
        assert seite.sitzung.werte == vorher

        seite.wb_pipette_knopf.setChecked(True)                   # nochmal drücken bricht ab
        seite.wb_pipette_knopf.setChecked(False)
        assert seite._klick_ziel is None and seite.sitzung.werte == vorher

        # Andere Modi beenden die Pipette
        seite.wb_pipette_knopf.setChecked(True)
        seite.zuschneiden(True)
        assert seite._klick_ziel is None and not seite.wb_pipette_knopf.isChecked()
        seite.zuschnitt_abbrechen()
        seite.wb_pipette_knopf.setChecked(True)
        seite.pinsel_beginnen()
        assert seite._klick_ziel is None and not seite.wb_pipette_knopf.isChecked()
        seite.pinsel_beenden()
        seite.wb_pipette_knopf.setChecked(True)
        seite.flaechen_beginnen()
        assert seite._klick_ziel is None and not seite.wb_pipette_knopf.isChecked()
        seite.flaechen_beenden()
        seite.wb_pipette_knopf.setChecked(True)
        seite.lokal_neue_maske("farbe")                           # Maskenmodus
        assert seite._klick_ziel is None and leinwand.lokalmodus
        seite.lokal_beenden()
        seite.sitzung.werte.masken = ()

        # Ein Klick links im warmen Teil: dieser Punkt wird neutral, die Pipette endet
        seite.wb_pipette_knopf.setChecked(True)
        seite._bild_geklickt(30.0, 40.0, True)
        werte = seite.sitzung.werte
        assert seite._klick_ziel is None and not seite.wb_pipette_knopf.isChecked()
        assert werte.temperatur < -10 and "Weißabgleich" in fenster.statusmeldung.text()
        assert seite.zeilen["temperatur"].wert() == werte.temperatur
        _nur_geaendert(seite, vorher, ("temperatur", "toenung"))
        bild = np.asarray(seite.sitzung.vorschau()[0]).astype(int)
        punkt = bild[35:46, 25:36].mean(axis=(0, 1))
        assert np.abs(punkt - punkt.mean()).max() < 4
        seite._festhalten(sofort=True)
        assert "Pipette" in seite.rueckgaengig_knopf.toolTip()

        # Rechts im kalten Teil: anderes Ergebnis
        seite.wb_pipette_knopf.setChecked(True)
        seite._bild_geklickt(100.0, 40.0, True)
        assert seite.sitzung.werte.temperatur > 10
    finally:
        seite.vergleich_knopf.setChecked(False)
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_wb_pipette_auf_schwarz_meldet_und_aendert_nichts(fenster, tmp_path, monkeypatch):
    import dataclasses

    import numpy as np
    from PIL import Image

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "schwarz.png")
    bild = np.full((48, 64, 3), 120, np.uint8)
    bild[:, :20] = 0
    Image.fromarray(bild).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        vorher = dataclasses.replace(seite.sitzung.werte)
        seite.wb_pipette_knopf.setChecked(True)
        seite._bild_geklickt(8.0, 20.0, True)
        assert seite.sitzung.werte == vorher and seite._klick_ziel is None
        assert "nichts messen" in fenster.statusmeldung.text()
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_automatik_misst_im_zuschnitt(fenster, tmp_path, monkeypatch):
    """Ein Rand, der weggeschnitten ist, darf das Ergebnis nicht beeinflussen - weder beim
    Ton noch beim Weißabgleich noch bei der Pipette; ohne Zuschnitt wirkt er."""
    import numpy as np
    from PIL import Image

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    seite = fenster.bearbeiten
    rng = np.random.default_rng(9)
    mitte = (rng.uniform(0.5, 1.0, (64, 96, 1)) * np.asarray([130, 120, 110])).astype(np.uint8)
    ergebnisse = []
    for nummer, rand in enumerate(((255, 0, 255), (0, 255, 0), (0, 0, 0))):
        bild = np.empty((96, 128, 3), np.uint8)
        bild[:] = rand
        bild[16:80, 16:112] = mitte
        pfad = str(tmp_path / f"rand{nummer}.png")
        Image.fromarray(bild).save(pfad)
        seite.oeffnen(pfad)
        try:
            sitzung = seite.sitzung
            ohne = (sitzung.ton_automatisch(), sitzung.weissabgleich_auto())
            sitzung.werte.zuschnitt = (16 / 128, 16 / 96, 112 / 128, 80 / 96)
            mit = (sitzung.ton_automatisch(), sitzung.weissabgleich_auto(),
                   sitzung.weissabgleich_punkt(40.0, 30.0))
            seite.auto_weissabgleich()
            ergebnisse.append((ohne, mit, (sitzung.werte.temperatur, sitzung.werte.toenung)))
        finally:
            seite.schliessen()
            seite._knoepfe_freischalten()
    (_, erst, gesetzt), *rest = ergebnisse
    for _ohne, mit, gesetzt_i in rest:
        assert mit == erst and gesetzt_i == gesetzt
    assert erst[1][0] < -10 and gesetzt == erst[1]
    assert erst[2] is not None
    # Ohne Zuschnitt zählt der Rand (die Ränder sind verschieden)
    assert len({ohne for ohne, _mit, _g in ergebnisse}) > 1


def test_automatik_im_zuschnittmodus_uebernimmt_den_rahmen(fenster, tmp_path, monkeypatch):
    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "stich.png")
    _stich_bild(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        seite.zuschneiden(True)
        seite.leinwand.zuschnitt = (0.0, 0.0, 0.5, 1.0)
        seite.wb_auto_knopf.click()
        assert seite.leinwand.zuschnitt is None
        assert seite.sitzung.werte.zuschnitt == (0.0, 0.0, 0.5, 1.0)
        assert seite.sitzung.werte.temperatur < -10                # nur die warme Hälfte
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def _vier_viertel(pfad):
    """Vier verschieden getönte Viertel: oben links warm, oben rechts kalt, unten links grün,
    unten rechts magenta."""
    import numpy as np
    from PIL import Image
    bild = np.empty((96, 128, 3), np.uint8)
    bild[:48, :64] = (135, 120, 108)
    bild[:48, 64:] = (108, 120, 135)
    bild[48:, :64] = (112, 130, 112)
    bild[48:, 64:] = (130, 112, 130)
    Image.fromarray(bild).save(pfad)


@pytest.mark.parametrize("drehung, spiegeln, zuschnitt", [
    (1, False, (0.0, 0.0, 1.0, 1.0)),
    (3, False, (0.0, 0.0, 1.0, 1.0)),
    (0, True, (0.0, 0.0, 1.0, 1.0)),
    (1, True, (0.0, 0.0, 1.0, 1.0)),
    (1, False, (0.05, 0.1, 0.95, 1.0)),
    (2, True, (0.05, 0.1, 0.95, 1.0)),
])
def test_pipette_trifft_den_geklickten_punkt_mit_geometrie(fenster, tmp_path, monkeypatch,
                                                           drehung, spiegeln, zuschnitt):
    """Gedreht, gespiegelt, zugeschnitten: Der Klick im fertigen Bild macht genau diese Stelle
    neutral - in jedem der vier Viertel."""
    import numpy as np

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "viertel.png")
    _vier_viertel(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        sitzung = seite.sitzung
        sitzung.werte.drehung90 = drehung
        sitzung.werte.spiegeln = spiegeln
        sitzung.werte.zuschnitt = zuschnitt
        hoehe, breite = sitzung.ausgabe_form()
        ergebnisse = set()
        for fy in (0.25, 0.75):
            for fx in (0.25, 0.75):
                x, y = fx * breite, fy * hoehe
                seite.wb_pipette_knopf.setChecked(True)
                seite._bild_geklickt(x, y, True)
                assert seite._klick_ziel is None
                bild = np.asarray(sitzung.vorschau()[0]).astype(int)
                assert bild.shape[:2] == (hoehe, breite)
                punkt = bild[int(y) - 2:int(y) + 3, int(x) - 2:int(x) + 3].mean(axis=(0, 1))
                assert np.abs(punkt - punkt.mean()).max() < 4, (fx, fy, punkt)
                ergebnisse.add((sitzung.werte.temperatur, sitzung.werte.toenung))
        assert len(ergebnisse) == 4              # vier verschiedene Viertel gemessen
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


@pytest.mark.parametrize("aufruf, methode, fehler", [
    ("auto_ton", "ton_automatisch", "speicher"),
    ("auto_ton", "ton_automatisch", "ki"),
    ("auto_weissabgleich", "weissabgleich_auto", "speicher"),
    ("auto_weissabgleich", "weissabgleich_auto", "ki"),
    ("pipette", "weissabgleich_punkt", "speicher"),
    ("pipette", "weissabgleich_punkt", "ki"),
])
def test_automatik_fehlerweg_aendert_nichts(fenster, tmp_path, monkeypatch, aufruf, methode,
                                            fehler):
    import dataclasses

    from PySide6.QtWidgets import QApplication

    from silberkorn import einstellungen, ki
    from silberkorn.cuda import cupy as cp
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "stich.png")
    _stich_bild(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        meldungen = []
        monkeypatch.setattr(seite, "_fehler", lambda text, einzelheiten: meldungen.append(
            (text, einzelheiten, QApplication.overrideCursor() is None)))

        def scheitern(*_args, **_kwargs):
            raise (cp.cuda.memory.OutOfMemoryError(1, 1) if fehler == "speicher"
                   else ki.KiFehler("kaputt"))
        monkeypatch.setattr(seite.sitzung, methode, scheitern)
        vorher = dataclasses.replace(seite.sitzung.werte)
        if aufruf == "pipette":
            seite.wb_pipette_knopf.setChecked(True)
            seite._bild_geklickt(30.0, 40.0, True)
        else:
            getattr(seite, aufruf)()
        assert len(meldungen) == 1
        _text, einzelheiten, cursor_zurueck = meldungen[0]
        assert cursor_zurueck                      # die Meldung kommt erst nach dem Aufräumen
        assert ("kaputt" if fehler == "ki" else "Grafikspeicher") in einzelheiten
        assert QApplication.overrideCursor() is None
        assert seite.sitzung.werte == vorher
        seite._festhalten(sofort=True)
        assert not seite.rueckgaengig_knopf.isEnabled()
        assert seite._klick_ziel is None and not seite.wb_pipette_knopf.isChecked()
        assert not seite.leinwand.klickmodus
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_auto_ton_ueberschreibt_vorhandene_werte_und_rueckgaengig(fenster, tmp_path,
                                                                  monkeypatch):
    import numpy as np
    from PIL import Image

    from silberkorn import einstellungen
    from silberkorn import filter as f
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "dunkel.png")
    rng = np.random.default_rng(2)
    Image.fromarray(rng.integers(5, 70, (60, 80, 3)).astype(np.uint8)).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    vier = ("belichtung", "kontrast", "lichter", "tiefen")

    def setzen(name, wert):
        setattr(seite.sitzung.werte, name, wert)
        seite.zeilen[name].setzen(wert)

    try:
        seite.auto_ton()
        seite._festhalten(sofort=True)
        ab_null = {n: getattr(seite.sitzung.werte, n) for n in vier}
        assert ab_null["belichtung"] > 0.5
        # Extremwerte, dann Auto: dasselbe wie ab 0
        for name in vier:
            regler = f.REGLER_NACH_NAME[name]
            setzen(name, regler.minimum if name == "lichter" else regler.maximum)
        seite._festhalten(sofort=True)
        seite.auto_ton()
        seite._festhalten(sofort=True)
        assert {n: getattr(seite.sitzung.werte, n) for n in vier} == ab_null
        # Sättigung bleibt; zwei Schritte zurück: erst Auto-Ton, dann Sättigung
        for name in vier:
            setzen(name, 0.0)
        seite._festhalten(sofort=True)
        seite.zeilen["saettigung"].schieber.setValue(
            seite.zeilen["saettigung"].schieber.value() + 20)
        seite._festhalten(sofort=True)
        seite.auto_ton()
        seite._festhalten(sofort=True)
        werte = seite.sitzung.werte
        assert werte.saettigung == 20 and werte.belichtung == ab_null["belichtung"]
        seite.rueckgaengig()
        assert seite.sitzung.werte.saettigung == 20
        assert all(getattr(seite.sitzung.werte, n) == 0 for n in vier)
        seite.rueckgaengig()
        assert seite.sitzung.werte.saettigung == 0
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_auto_ton_laesst_den_vorschau_zwischenspeicher_unberuehrt(fenster, tmp_path,
                                                                 monkeypatch):
    import numpy as np
    from PIL import Image

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "dunkel.png")
    rng = np.random.default_rng(4)
    Image.fromarray(rng.integers(5, 70, (60, 80, 3)).astype(np.uint8)).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        sitzung = seite.sitzung
        sitzung.werte.rauschen = 30                   # eine teure Zwischenstufe im Speicher
        erst = np.array(sitzung.vorschau()[0])
        sitzung.ton_automatisch()
        zweit = np.array(sitzung.vorschau()[0])
        assert np.array_equal(erst, zweit)
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_bild_schliessen_beendet_die_pipette_und_vorher_sperrt_den_klick(fenster, tmp_path,
                                                                         monkeypatch):
    import dataclasses

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "stich.png")
    _stich_bild(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        # „Vorher“ gedrückt: der Klick setzt nichts
        vorher = dataclasses.replace(seite.sitzung.werte)
        seite.wb_pipette_knopf.setChecked(True)
        seite.vorher_knopf.pressed.emit()
        seite._bild_geklickt(30.0, 40.0, True)
        assert seite.sitzung.werte == vorher and seite._klick_ziel == "wb"
        seite.vorher_knopf.released.emit()
        # Bild schließen bei aktiver Pipette (so wie der Stapel: schließen, dann freischalten)
        seite.schliessen()
        seite._knoepfe_freischalten()
        assert seite._klick_ziel is None and not seite.leinwand.klickmodus
        assert not seite.wb_pipette_knopf.isChecked()
        assert not seite.wb_pipette_knopf.isEnabled()
        assert not seite.wb_auto_knopf.isEnabled() and not seite.ton_auto_knopf.isEnabled()
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_automatik_meldet_anschlag_und_zuruecksetzen(fenster, tmp_path, monkeypatch):
    import numpy as np
    from PIL import Image

    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    seite = fenster.bearbeiten
    rng = np.random.default_rng(6)
    hinweis = "Ende des Reglers"

    def oeffnen(name, bild):
        seite.schliessen()                        # sonst fragt „Änderungen verwerfen?“
        seite._knoepfe_freischalten()
        pfad = str(tmp_path / name)
        Image.fromarray(bild).save(pfad)
        seite.oeffnen(pfad)

    try:
        # Sehr dunkel: Belichtung am Anschlag
        oeffnen("schwarz.png", rng.integers(1, 6, (60, 80, 3)).astype(np.uint8))
        seite.auto_ton()
        assert seite.sitzung.werte.belichtung == 2.0
        assert hinweis in fenster.statusmeldung.text()
        # Gut belichtet: kein Hinweis; vorhandene Werte werden zurückgesetzt gemeldet
        rampe = np.linspace(40, 200, 80).astype(np.uint8)[None, :, None]
        oeffnen("gut.png", np.broadcast_to(rampe, (60, 80, 3)).copy())
        seite.auto_ton()
        assert "keine Korrektur" in fenster.statusmeldung.text()
        assert "zurückgesetzt" not in fenster.statusmeldung.text()
        assert hinweis not in fenster.statusmeldung.text()
        seite.sitzung.werte.belichtung = 1.0
        seite.sitzung.werte.lichter = -30.0
        seite.auto_ton()
        werte = seite.sitzung.werte
        assert (werte.belichtung, werte.kontrast, werte.lichter, werte.tiefen) == (0, 0, 0, 0)
        assert "zurückgesetzt" in fenster.statusmeldung.text()
        # Starker Stich: Temperatur am Anschlag (Auto und Pipette)
        oeffnen("stich.png", np.full((60, 80, 3), (200, 120, 40), np.uint8))
        seite.auto_weissabgleich()
        assert seite.sitzung.werte.temperatur == -100
        assert hinweis in fenster.statusmeldung.text()
        seite.sitzung.werte.temperatur = 0.0
        seite.wb_pipette_knopf.setChecked(True)
        seite._bild_geklickt(40.0, 30.0, True)
        assert seite.sitzung.werte.temperatur == -100
        assert hinweis in fenster.statusmeldung.text()
        # Leichter Stich: kein Hinweis
        oeffnen("leicht.png", np.full((60, 80, 3), (130, 120, 110), np.uint8))
        seite.auto_weissabgleich()
        assert hinweis not in fenster.statusmeldung.text()
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()
