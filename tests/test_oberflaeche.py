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
    for knopf in (seite.ton_auto_knopf, seite.wb_auto_knopf, seite.wb_pipette_knopf,
                  seite.gerade_auto_knopf):
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


def test_auto_begradigen_ein_schritt_stabil_und_auch_bei_schwarzweiss(fenster, tmp_path,
                                                                       monkeypatch):
    import dataclasses

    import numpy as np
    from PIL import Image

    from silberkorn import einstellungen, geometrie
    from silberkorn import filter as f
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    rng = np.random.default_rng(5)
    gerade = np.full((240, 320, 3), 0.2, np.float32)
    for _ in range(20):
        y, x = rng.integers(0, 160), rng.integers(0, 240)
        gerade[y:y + rng.integers(20, 80), x:x + rng.integers(20, 80)] = rng.uniform(0.05, 0.9, 3)
    schief = geometrie.anwenden(gerade, geometrie.Geometrie(begradigen=4.0))
    pfad = str(tmp_path / "schief.png")
    Image.fromarray(np.asarray(f.nach_8bit(schief))).save(pfad)
    leer = str(tmp_path / "leer.png")
    Image.fromarray(np.full((60, 80, 3), 90, np.uint8)).save(leer)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        assert seite.gerade_auto_knopf.isEnabled()
        assert seite.gerade_auto_knopf.accessibleName()
        vorher = dataclasses.replace(seite.sitzung.werte)
        seite.gerade_auto_knopf.click()
        werte = seite.sitzung.werte
        assert werte.begradigen == pytest.approx(-4.0, abs=0.5)
        assert seite.zeilen["begradigen"].wert() == werte.begradigen
        assert "Auto-Begradigen" in fenster.statusmeldung.text()
        _nur_geaendert(seite, vorher, ("begradigen",))
        seite._festhalten(sofort=True)
        assert "Auto-Begradigen" in seite.rueckgaengig_knopf.toolTip()
        erster = dataclasses.replace(werte)
        seite.gerade_auto_knopf.click()                           # absolut: dasselbe
        seite._festhalten(sofort=True)
        assert seite.sitzung.werte == erster
        seite.rueckgaengig()
        assert seite.sitzung.werte == vorher and not seite.rueckgaengig_knopf.isEnabled()
        # Schwarzweiß sperrt den Knopf nicht
        seite.sw_box.setChecked(True)
        assert seite.gerade_auto_knopf.isEnabled()
        seite.gerade_auto_knopf.click()
        assert seite.sitzung.werte.begradigen == pytest.approx(-4.0, abs=0.5)
        seite.sw_box.setChecked(False)
        # Ohne klare Linien bleibt der Wert, und die Statuszeile sagt es
        seite.schliessen()
        seite.oeffnen(leer)
        seite.gerade_auto_knopf.click()
        assert seite.sitzung.werte.begradigen == 0.0
        assert "Keine klaren Linien" in fenster.statusmeldung.text()
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def _schiefes_bild(pfad: str, winkel: float = 4.0):
    """Gerade Rechtecke, um `winkel` Grad gedreht, als PNG."""
    import numpy as np
    from PIL import Image

    from silberkorn import filter as f
    from silberkorn import geometrie
    rng = np.random.default_rng(5)
    gerade = np.full((240, 320, 3), 0.2, np.float32)
    for _ in range(20):
        y, x = rng.integers(0, 160), rng.integers(0, 240)
        gerade[y:y + rng.integers(20, 80), x:x + rng.integers(20, 80)] = rng.uniform(0.05, 0.9, 3)
    schief = geometrie.anwenden(gerade, geometrie.Geometrie(begradigen=winkel))
    Image.fromarray(np.asarray(f.nach_8bit(schief))).save(pfad)


def _gerendert_schief(seite) -> float:
    """Neigung des Bildes, wie die Sitzung es fertig rendert."""
    from silberkorn import automatik
    from silberkorn import filter as f
    return automatik.neigung(f.von_8bit(seite.sitzung.vorschau()[0]))


def test_begradigen_auto_spiegeln_und_drehen_in_der_sitzung(fenster, tmp_path, monkeypatch):
    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "schief.png")
    _schiefes_bild(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        werte = seite.sitzung.werte
        ungespiegelt = seite.sitzung.begradigen_auto()
        assert ungespiegelt == pytest.approx(-4.0, abs=0.5)
        for spiegeln, drehung90 in ((True, 0), (True, 1), (False, 1)):
            werte.spiegeln, werte.drehung90 = spiegeln, drehung90
            winkel = seite.sitzung.begradigen_auto()
            assert winkel == (-ungespiegelt if spiegeln else ungespiegelt)
            werte.begradigen = winkel
            assert abs(_gerendert_schief(seite)) < 0.7, (spiegeln, drehung90)
        # Gegenprobe: mit dem Wert des ungespiegelten Bildes bliebe das Spiegelbild schief
        werte.spiegeln, werte.drehung90, werte.begradigen = True, 0, ungespiegelt
        assert abs(_gerendert_schief(seite)) > 5
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_begradigen_auto_ignoriert_den_jetzigen_wert_und_misst_im_zuschnitt(
        fenster, tmp_path, monkeypatch):
    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "schief.png")
    _schiefes_bild(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        werte = seite.sitzung.werte
        bei_null = seite.sitzung.begradigen_auto()
        werte.begradigen = 10.0
        assert seite.sitzung.begradigen_auto() == bei_null
        werte.zuschnitt = (0.1, 0.1, 0.9, 0.9)
        seite.gerade_auto_knopf.click()               # mit Zuschnitt kein Absturz
        assert seite.sitzung.werte.begradigen == pytest.approx(bei_null, abs=0.5)
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_auto_begradigen_am_anschlag_und_sperre_nach_schliessen(fenster, tmp_path, monkeypatch):
    from silberkorn import automatik, einstellungen
    from silberkorn import filter as f
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "schief.png")
    _schiefes_bild(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        # _auf_regler klemmt auf den Reglerbereich (±45), nicht auf den Suchbereich (±20)
        regler = f.REGLER_NACH_NAME["begradigen"]
        assert automatik._auf_regler("begradigen", 99) == regler.maximum == 45.0
        assert automatik._auf_regler("begradigen", -99) == regler.minimum
        assert automatik._auf_regler("begradigen", 25) == 25.0
        monkeypatch.setattr(seite.sitzung, "begradigen_auto", lambda: regler.maximum)
        seite.gerade_auto_knopf.click()
        assert seite.sitzung.werte.begradigen == regler.maximum
        assert "am Ende des Reglers" in fenster.statusmeldung.text()
        seite.schliessen()
        seite._knoepfe_freischalten()                 # wie nach dem Schließen im Programm
        assert not seite.gerade_auto_knopf.isEnabled()
        fenster.melden("unberührt")
        seite.auto_begradigen()                       # ohne Bild: tut nichts
        assert fenster.statusmeldung.text() == "unberührt"
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


@pytest.mark.parametrize("art", ["ki", "speicher"])
def test_auto_begradigen_fehler_meldet_und_aendert_nichts(fenster, tmp_path, monkeypatch, art):
    import dataclasses

    import cupy as cp
    from PySide6.QtWidgets import QApplication

    from silberkorn import einstellungen, ki
    monkeypatch.setattr(einstellungen, "save_config", lambda _daten: None)
    pfad = str(tmp_path / "schief.png")
    _schiefes_bild(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(pfad)
    try:
        seite._festhalten(sofort=True)
        tooltip = seite.rueckgaengig_knopf.toolTip()
        vorher = dataclasses.replace(seite.sitzung.werte)
        fehler = (ki.KiFehler("kaputt") if art == "ki"
                  else cp.cuda.memory.OutOfMemoryError(1, 1))

        def werfen():
            raise fehler
        monkeypatch.setattr(seite.sitzung, "begradigen_auto", werfen)
        gemeldet = []
        monkeypatch.setattr(seite, "_fehler", lambda text, einzelheiten: gemeldet.append(text))
        seite.gerade_auto_knopf.click()
        seite._festhalten(sofort=True)
        assert gemeldet
        assert seite.sitzung.werte == vorher
        assert seite.rueckgaengig_knopf.toolTip() == tooltip
        assert QApplication.overrideCursor() is None
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
    ("auto_begradigen", "begradigen_auto", "speicher"),
    ("auto_begradigen", "begradigen_auto", "ki"),
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


# --------------------------------------------------------------------------
# Bewertung: Sterne und Ausschuss in der Ordneransicht und im Feld „Bewertung“
# --------------------------------------------------------------------------

def _bewertungen_warten():
    """Bis das Lesen der Bewertungsdateien im Hintergrund fertig und angekommen ist."""
    import threading

    from PySide6.QtWidgets import QApplication
    _warten(lambda: not any(t.name == "Bewertungen" and t.is_alive()
                            for t in threading.enumerate()))
    for _i in range(3):
        QApplication.processEvents()


def _kachel_ort(seite, pfad, ziel=None):
    """Der Punkt in der Kachel: Bildmitte, ein Stern ("stern", n) oder der Papierkorb."""
    from silberkorn import ordner_seite
    kachel = seite.liste.visualRect(seite.modell.index(seite.modell.pfade.index(pfad)))
    flaeche = ordner_seite.bild_flaeche(kachel)
    sterne, korb = ordner_seite.bewertung_felder(flaeche)
    if ziel is None:
        return flaeche.center()
    return sterne[ziel[1] - 1].center() if ziel[0] == "stern" else korb.center()


def _klicken(seite, pfad, ziel=None, doppelt=False):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    ansicht = seite.liste.viewport()
    ort = _kachel_ort(seite, pfad, ziel)
    QTest.mouseMove(ansicht, ort)
    knopf, umschalt = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    QTest.mouseClick(ansicht, knopf, umschalt, ort)
    if doppelt:                       # so kommt es von Windows: Druck, Loslassen, zweiter Druck
        QTest.mouseDClick(ansicht, knopf, umschalt, ort)


def _stand(seite, pfad):
    from silberkorn.ordner_seite import BEWERTUNG_ROLLE
    return seite.modell.data(seite.modell.index(seite.modell.pfade.index(pfad)),
                             BEWERTUNG_ROLLE)


@pytest.fixture
def bewertung_umgebung(fenster, tmp_path, monkeypatch):
    """Erlaubnis fuer Begleitdateien, Einstellungen nur im Arbeitsspeicher, drei Bilder."""
    from PIL import Image

    from silberkorn import einstellungen
    konfiguration = {}
    monkeypatch.setattr(einstellungen, "load_config", lambda: dict(konfiguration))
    monkeypatch.setattr(einstellungen, "save_config",
                        lambda daten: konfiguration.update(daten) or True)
    monkeypatch.setattr(einstellungen, "begleitdateien", lambda: True)
    for name, farbe in (("a.jpg", (200, 0, 0)), ("b.jpg", (0, 200, 0)), ("c.jpg", (0, 0, 200))):
        Image.new("RGB", (64, 48), farbe).save(tmp_path / name)
    (tmp_path / "unter").mkdir()
    seite = fenster.ordner
    fenster.reiter.setCurrentWidget(seite)
    seite.ordner_zeigen(str(tmp_path))
    _bewertungen_warten()
    yield seite, konfiguration
    fenster.bearbeiten.schliessen()
    fenster.bearbeiten._knoepfe_freischalten()
    seite.sortierung.setCurrentIndex(0)
    seite.ordner_zeigen("")
    fenster.reiter.setCurrentWidget(fenster.bearbeiten)


def test_bewertung_klicks_sterne_papierkorb(fenster, tmp_path, bewertung_umgebung):
    """Stern n setzt n Sterne, derselbe Stern nimmt sie zurueck, der Papierkorb markiert
    Ausschuss und hebt ihn auf. Weder oeffnet ein Klick das Bild noch waehlt er die Kachel;
    die Bilddatei bleibt, wie sie ist."""
    from PySide6.QtTest import QTest

    from silberkorn import bewertung
    seite, _konfiguration = bewertung_umgebung
    a = str(tmp_path / "a.jpg")
    original, zeit = open(a, "rb").read(), os.stat(a).st_mtime_ns

    assert _stand(seite, a) == bewertung.KEINE
    QTest.mouseMove(seite.liste.viewport(), _kachel_ort(seite, a))   # nur darueberfahren
    assert seite.liste.zeichner.hover_zeile == seite.modell.pfade.index(a)
    assert not (tmp_path / "a.jpg.xmp").exists()
    _klicken(seite, a, ("stern", 3))
    assert seite.liste.zeichner.hover_ziel == ("stern", 3)
    assert _stand(seite, a) == bewertung.Stand(3, "eigen") and bewertung.lesen(a).wert == 3
    assert "a.jpg" in fenster.statusmeldung.text() and "★★★" in fenster.statusmeldung.text()
    _klicken(seite, a, ("stern", 5))
    assert _stand(seite, a).wert == 5
    _klicken(seite, a, ("stern", 5))                      # derselbe Stern: Bewertung weg
    assert _stand(seite, a).wert == 0 and bewertung.lesen(a).wert == 0
    _klicken(seite, a, ("korb",))
    assert _stand(seite, a).wert == bewertung.AUSSCHUSS and bewertung.lesen(a).wert == -1
    assert "unverändert" in fenster.statusmeldung.text()
    _klicken(seite, a, ("stern", 2))                      # ein Stern hebt Ausschuss auf
    assert _stand(seite, a).wert == 2
    _klicken(seite, a, ("korb",))
    _klicken(seite, a, ("korb",))                         # an, aus
    assert _stand(seite, a).wert == 0
    # Nichts davon hat ein Bild geoeffnet oder eine Kachel gewaehlt
    assert fenster.reiter.currentWidget() is seite
    assert fenster.bearbeiten.sitzung is None
    assert seite.liste.selectionModel().selectedIndexes() == []
    assert open(a, "rb").read() == original and os.stat(a).st_mtime_ns == zeit
    # Doppelklick auf einen Stern oeffnet ebenfalls nichts
    _klicken(seite, a, ("stern", 4), doppelt=True)
    assert fenster.bearbeiten.sitzung is None and fenster.reiter.currentWidget() is seite
    assert _stand(seite, a).wert == 4
    # Abseits der Felder funktioniert der Doppelklick wie immer
    _klicken(seite, a, None, doppelt=True)
    assert fenster.reiter.currentWidget() is fenster.bearbeiten
    assert fenster.bearbeiten.sitzung is not None


def test_bewertung_unterordner_hat_nichts(fenster, tmp_path, bewertung_umgebung):
    from silberkorn.ordner_seite import BEWERTUNG_ROLLE
    seite, _konfiguration = bewertung_umgebung
    unter = str(tmp_path / "unter")
    zeile = seite.modell.pfade.index(unter)
    ort = seite.liste.visualRect(seite.modell.index(zeile)).center()
    assert seite.liste.ziel_bei(ort) == (-1, None)
    assert seite.modell.data(seite.modell.index(zeile), BEWERTUNG_ROLLE) is None
    assert seite.liste.ziel_bei(_kachel_ort(seite, str(tmp_path / "a.jpg"),
                                            ("korb",)))[1] == ("korb",)


def test_bewertung_tooltips(fenster, tmp_path, bewertung_umgebung):
    from silberkorn import bewertung
    seite, _konfiguration = bewertung_umgebung
    a = str(tmp_path / "a.jpg")
    zeile = seite.modell.pfade.index(a)
    assert "löscht nichts" in seite.liste.tooltip_fuer(zeile, ("korb",))
    assert seite.liste.tooltip_fuer(zeile, ("stern", 1)) == "1 Stern"
    assert seite.liste.tooltip_fuer(zeile, ("stern", 4)) == "4 Sterne"
    bewertung.schreiben(a, 4)
    seite.ordner_zeigen(str(tmp_path))
    _bewertungen_warten()
    zeile = seite.modell.pfade.index(a)
    assert seite.liste.tooltip_fuer(zeile, ("stern", 4)) == "Bewertung entfernen"
    bewertung.schreiben(a, -1)
    seite.ordner_zeigen(str(tmp_path))
    _bewertungen_warten()
    assert seite.liste.tooltip_fuer(seite.modell.pfade.index(a), ("korb",)) == \
        "Ausschuss aufheben"


FREMDES_XMP = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/'
    b'22-rdf-syntax-ns#"><rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/'
    b'1.0/" xmp:Rating="4"/></rdf:RDF></x:xmpmeta>')


def test_bewertung_fremde_datei_bleibt_unberuehrt(fenster, tmp_path, bewertung_umgebung):
    """Eine fremde XMP-Datei (darktable) wird gelesen und gezeigt, aber nie veraendert."""
    from silberkorn import bewertung, ordner_seite
    seite, _konfiguration = bewertung_umgebung
    b = str(tmp_path / "b.jpg")
    fremd = tmp_path / "b.jpg.xmp"
    fremd.write_bytes(FREMDES_XMP)
    os.utime(fremd, ns=(10**18, 10**18))
    vorher, zeit = fremd.read_bytes(), fremd.stat().st_mtime_ns
    seite.ordner_zeigen(str(tmp_path))
    _bewertungen_warten()
    assert _stand(seite, b) == bewertung.Stand(4, "fremd")
    zeile = seite.modell.pfade.index(b)
    assert "fremden XMP-Datei" in seite.liste.tooltip_fuer(zeile, ("stern", 2))
    for ziel in (("stern", 2), ("stern", 4), ("korb",)):
        _klicken(seite, b, ziel)
        assert "fremden XMP-Datei" in fenster.statusmeldung.text()
    assert fremd.read_bytes() == vorher and fremd.stat().st_mtime_ns == zeit
    assert _stand(seite, b).wert == 4
    assert fenster.reiter.currentWidget() is seite
    assert ordner_seite.bewertung_setzen(fenster, b, 1) is False
    assert fremd.read_bytes() == vorher and fremd.stat().st_mtime_ns == zeit


def test_bewertung_ohne_erlaubnis_und_rueckfrage(fenster, tmp_path, bewertung_umgebung,
                                                 monkeypatch):
    """Ohne Erlaubnis fuer Begleitdateien wird nichts geschrieben und nichts als gesetzt
    gezeigt; ist noch nicht gefragt, kommt die Rueckfrage - Nein schreibt nichts."""
    from PySide6.QtWidgets import QMessageBox

    from silberkorn import bearbeiten_seite, bewertung, einstellungen
    seite, konfiguration = bewertung_umgebung
    a = str(tmp_path / "a.jpg")

    monkeypatch.setattr(einstellungen, "begleitdateien", lambda: False)
    _klicken(seite, a, ("stern", 3))
    assert not (tmp_path / "a.jpg.xmp").exists() and _stand(seite, a) == bewertung.KEINE
    assert "nicht gespeichert" in fenster.statusmeldung.text()

    fragen = []
    antwort = {"wert": QMessageBox.StandardButton.No}
    monkeypatch.setattr(einstellungen, "begleitdateien", lambda: None)
    monkeypatch.setattr(bearbeiten_seite.QMessageBox, "question",
                        lambda *args: fragen.append(args[2]) or antwort["wert"])
    _klicken(seite, a, ("stern", 3))
    assert len(fragen) == 1 and "löscht nichts" in fragen[0] and "a.jpg.xmp" in fragen[0]
    assert not (tmp_path / "a.jpg.xmp").exists() and _stand(seite, a) == bewertung.KEINE
    assert konfiguration["begleitdateien"] is False
    monkeypatch.setattr(einstellungen, "begleitdateien", lambda: None)
    antwort["wert"] = QMessageBox.StandardButton.Yes
    _klicken(seite, a, ("stern", 3))
    assert _stand(seite, a).wert == 3 and bewertung.lesen(a).wert == 3
    assert konfiguration["begleitdateien"] is True


def test_bewertung_schreibfehler_wird_gemeldet(fenster, tmp_path, bewertung_umgebung,
                                               monkeypatch):
    from silberkorn import bewertung
    seite, _konfiguration = bewertung_umgebung
    a = str(tmp_path / "a.jpg")
    bewertung.schreiben(a, 2)
    seite.ordner_zeigen(str(tmp_path))
    _bewertungen_warten()

    def verweigert(**_kw):
        raise PermissionError("schreibgeschuetzt")

    monkeypatch.setattr(bewertung.tempfile, "mkstemp", verweigert)
    _klicken(seite, a, ("stern", 5))
    assert _stand(seite, a).wert == 2                     # die Anzeige luegt nicht
    assert "schreibgeschuetzt" in fenster.statusmeldung.text()     # der Grund steht dabei
    assert bewertung.lesen(a).wert == 2


def test_bewertung_sortierung(fenster, tmp_path, bewertung_umgebung):
    """Name, Datum (neueste zuerst) und Sterne; Unterordner vorn, Ausschuss immer am Ende;
    gemerkt in silberkorn.json. Nach einer Bewertung springt keine Kachel weg."""
    from PIL import Image

    from silberkorn import bewertung
    seite, konfiguration = bewertung_umgebung
    Image.new("RGB", (64, 48), (9, 9, 9)).save(tmp_path / "d.jpg")
    zeiten = {"a.jpg": 100, "b.jpg": 200, "c.jpg": 400, "d.jpg": 300}
    for name, zeit in zeiten.items():
        os.utime(tmp_path / name, (zeit, zeit))
    bewertung.schreiben(str(tmp_path / "a.jpg"), 2)
    bewertung.schreiben(str(tmp_path / "b.jpg"), 5)
    bewertung.schreiben(str(tmp_path / "c.jpg"), -1)       # die neueste, aber Ausschuss
    seite.ordner_zeigen(str(tmp_path))
    _bewertungen_warten()

    def reihenfolge():
        return [os.path.basename(p) for p in seite.modell.pfade]

    assert reihenfolge() == ["unter", "a.jpg", "b.jpg", "d.jpg", "c.jpg"]
    seite.sortierung.setCurrentIndex(seite.sortierung.findData("datum"))
    assert reihenfolge() == ["unter", "d.jpg", "b.jpg", "a.jpg", "c.jpg"]
    assert konfiguration["ordner_sortierung"] == "datum"
    seite.sortierung.setCurrentIndex(seite.sortierung.findData("sterne"))
    assert reihenfolge() == ["unter", "b.jpg", "a.jpg", "d.jpg", "c.jpg"]
    assert konfiguration["ordner_sortierung"] == "sterne"
    # Die Auswahl bleibt beim Umsortieren an ihrem Bild
    seite.liste.setCurrentIndex(seite.modell.index(reihenfolge().index("a.jpg")))
    seite.sortierung.setCurrentIndex(seite.sortierung.findData("name"))
    assert [os.path.basename(p) for p in seite.gewaehlte_bilder()] == ["a.jpg"]
    seite.sortierung.setCurrentIndex(seite.sortierung.findData("sterne"))
    # Eine neue Bewertung sortiert nicht sofort um - erst beim naechsten Einlesen
    d = str(tmp_path / "d.jpg")
    _klicken(seite, d, ("stern", 5))
    _klicken(seite, d, ("stern", 4))
    assert reihenfolge() == ["unter", "b.jpg", "a.jpg", "d.jpg", "c.jpg"]
    assert "↻" in fenster.statusmeldung.text()
    seite.neu_knopf.click()
    _bewertungen_warten()
    assert reihenfolge() == ["unter", "b.jpg", "d.jpg", "a.jpg", "c.jpg"]     # 5, 4, 2
    _klicken(seite, str(tmp_path / "a.jpg"), ("stern", 4))                    # Gleichstand
    seite.neu_knopf.click()
    _bewertungen_warten()
    assert reihenfolge() == ["unter", "b.jpg", "a.jpg", "d.jpg", "c.jpg"]     # 5, 4, 4, Ausschuss


def test_bewertung_sortierwahl_mit_ungueltigem_wert(fenster, monkeypatch):
    """Ein unbekannter Wert in silberkorn.json ergibt die Sortierung nach Name."""
    from silberkorn import einstellungen
    from silberkorn.ordner_seite import OrdnerSeite
    for wert in ("zufall", 3, None, ["datum"], "DATUM"):
        monkeypatch.setattr(einstellungen, "load_config",
                            lambda w=wert: {"ordner_sortierung": w})
        seite = OrdnerSeite(fenster)
        try:
            assert seite.sortierung.currentData() == "name"
        finally:
            seite.beenden()
    monkeypatch.setattr(einstellungen, "load_config",
                        lambda: {"ordner_sortierung": "sterne"})
    seite = OrdnerSeite(fenster)
    try:
        assert seite.sortierung.currentData() == "sterne"
    finally:
        seite.beenden()


def test_bewertung_zeichnen_hover_gesetzt_ausschuss(fenster, tmp_path, bewertung_umgebung):
    """Ohne Bewertung und ohne Maus kein Overlay; mit Maus Sterne und Papierkorb; gesetzte
    Sterne bleiben; Ausschuss blendet die Kachel ab. In beiden Farbschemata."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from silberkorn import bewertung, farben, ordner_seite
    seite, _konfiguration = bewertung_umgebung
    a = str(tmp_path / "a.jpg")
    ansicht = seite.liste.viewport()

    def bilder_da():
        for pfad in seite.modell.pfade:                   # wie beim Zeichnen: anfordern
            seite.modell.data(seite.modell.index(seite.modell.pfade.index(pfad)),
                              ordner_seite.ZUSTAND_ROLLE)
        return all(p in seite.modell._bilder for p in seite.modell.pfade[1:])

    def foto():
        """Bild der Liste samt Lage der Kachel von a.jpg (die wandert bei Ausschuss ans Ende)."""
        QApplication.processEvents()
        kachel = seite.liste.visualRect(seite.modell.index(seite.modell.pfade.index(a)))
        flaeche = ordner_seite.bild_flaeche(kachel)
        sterne, korb = ordner_seite.bewertung_felder(flaeche)
        return ansicht.grab().toImage(), kachel, flaeche, sterne[0].united(korb)

    def verschieden(x, y, bereich: QRect):
        return sum(1 for i in range(bereich.left(), bereich.right(), 2)
                   for j in range(bereich.top(), bereich.bottom(), 2)
                   if x.pixel(i, j) != y.pixel(i, j))

    def goldene(bild, bereich: QRect, schema):
        gold = QColor(farben.THEMES[schema]["STERN"])
        n = 0
        for i in range(bereich.left(), bereich.right()):
            for j in range(bereich.top(), bereich.bottom()):
                farbe = QColor(bild.pixel(i, j))
                if (abs(farbe.red() - gold.red()) < 12 and abs(farbe.green() - gold.green()) < 12
                        and abs(farbe.blue() - gold.blue()) < 12):
                    n += 1
        return n

    def neu_lesen():
        seite.ordner_zeigen(str(tmp_path))
        _bewertungen_warten()
        assert _warten(bilder_da)

    def weg_von_a():
        QTest.mouseMove(ansicht, seite.liste.visualRect(seite.modell.index(0)).center())

    assert _warten(bilder_da)
    for schema in ("light", "dark"):
        farben.CURRENT_THEME = schema
        try:
            bewertung.schreiben(a, 0)
            neu_lesen()
            weg_von_a()
            leer, kachel, flaeche, feld = foto()
            QTest.mouseMove(ansicht, flaeche.center())
            assert verschieden(leer, foto()[0], feld) > 40    # Plakette, Sterne, Papierkorb
            weg_von_a()
            assert verschieden(leer, foto()[0], kachel) == 0  # ohne Maus wieder wie vorher

            bewertung.schreiben(a, 3)
            neu_lesen()
            weg_von_a()
            drei, _kachel, _flaeche, feld3 = foto()
            assert goldene(drei, feld3, schema) > 30          # drei gefuellte Sterne bleiben
            assert goldene(leer, feld, schema) == 0

            bewertung.schreiben(a, -1)
            neu_lesen()
            weg_von_a()
            aus, _kachel, flaeche_aus, feld_aus = foto()
            assert goldene(aus, feld_aus, schema) == 0
            # Ausschuss steht am Ende; das Foto ist dort abgeblendet (heller als vorher)
            assert seite.modell.pfade[-1] == a
            punkt = (flaeche.center().x(), flaeche.bottom() - 40)
            punkt_aus = (flaeche_aus.center().x(), flaeche_aus.bottom() - 40)
            assert QColor(aus.pixel(*punkt_aus)).lightness() > QColor(
                leer.pixel(*punkt)).lightness() + 30
        finally:
            farben.CURRENT_THEME = "light"


def test_bewertung_feld_im_reiter_bearbeiten(fenster, tmp_path, bewertung_umgebung,
                                             monkeypatch):
    """Das Feld „Bewertung“ nimmt die Sterne der eigenen Datei vor denen im Bild, zaehlt dabei
    nicht als Aenderung, schreibt Aenderungen in die Datei zurueck und rührt fremde nie an;
    Ausschuss steht als „–“. „Speichern unter“ nimmt die Sterne mit, Ausschuss nicht, und legt
    keine Datei daneben an."""
    from silberkorn import bewertung, bilddatei, einstellungen, metadaten
    seite, _konfiguration = bewertung_umgebung
    bearbeiten = fenster.bearbeiten
    feld = bearbeiten.bewertung_wahl
    a = str(tmp_path / "a.jpg")

    def gespeichert(name):
        ziel = str(tmp_path / name)
        bearbeiten.sitzung.exportieren(ziel, 8)
        daten = bilddatei.laden(ziel)
        return metadaten.lesen(daten.exif, daten.xmp, daten.iptc).angaben.bewertung

    # Eigene Datei mit 4 Sternen: vorbelegt, keine Aenderung, kein „bearbeitet“
    bewertung.schreiben(a, 4)
    bearbeiten.oeffnen(a)
    assert feld.currentData() == 4 and bearbeiten.sitzung.angaben.bewertung == 4
    assert not bearbeiten.sitzung.geaendert and not bearbeiten.sitzung.bearbeitet
    assert gespeichert("aus-4.jpg") == 4
    assert sorted(p.name for p in tmp_path.glob("aus-4*")) == ["aus-4.jpg"]    # keine Datei daneben
    # Das Feld aendern schreibt die Datei; derselbe Wert in der Ordneransicht
    feld.setCurrentIndex(feld.findData(2))
    assert bewertung.lesen(a) == bewertung.Stand(2, "eigen")
    assert _stand(seite, a).wert == 2
    assert bearbeiten.sitzung.angaben.bewertung == 2 and not bearbeiten.sitzung.bearbeitet
    assert gespeichert("aus-2.jpg") == 2
    feld.setCurrentIndex(feld.findData(0))
    assert bewertung.lesen(a) == bewertung.Stand(0, "eigen")
    assert gespeichert("aus-0.jpg") == 0
    # Ordneransicht aendert das offene Bild: das Feld folgt
    from silberkorn import ordner_seite
    assert ordner_seite.bewertung_setzen(fenster, a, 5)
    assert feld.currentData() == 5 and bearbeiten.sitzung.angaben.bewertung == 5
    assert not bearbeiten.sitzung.bearbeitet
    # Ausschuss: Feld auf „–“, nimmt keine Sterne mit
    assert ordner_seite.bewertung_setzen(fenster, a, bewertung.AUSSCHUSS)
    assert feld.currentData() == 0 and bearbeiten.sitzung.angaben.bewertung == 0
    assert gespeichert("aus-ausschuss.jpg") == 0
    assert bewertung.lesen(a) == bewertung.Stand(-1, "eigen")      # die Datei bleibt Ausschuss
    # Wer aus Ausschuss Sterne im Feld waehlt, hebt ihn auf
    feld.setCurrentIndex(feld.findData(3))
    assert bewertung.lesen(a) == bewertung.Stand(3, "eigen")
    # Ohne Erlaubnis: nichts geschrieben, aber das Feld gilt fuer „Speichern unter“
    monkeypatch.setattr(einstellungen, "begleitdateien", lambda: False)
    feld.setCurrentIndex(feld.findData(1))
    assert bewertung.lesen(a) == bewertung.Stand(3, "eigen")
    assert "nicht gespeichert" in fenster.statusmeldung.text()
    assert gespeichert("aus-1.jpg") == 1
    bearbeiten.schliessen()
    bearbeiten._knoepfe_freischalten()
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".xmp" and p.name.startswith("aus-")]


def test_bewertung_feld_fremde_datei_und_bild_ohne_datei(fenster, tmp_path, bewertung_umgebung):
    """Ohne eigene Datei gilt die Bewertung im Bild; eine fremde XMP-Datei bestimmt das Feld
    nicht und bleibt auch beim Aendern des Feldes unberuehrt."""
    from silberkorn import bewertung
    seite, _konfiguration = bewertung_umgebung
    bearbeiten = fenster.bearbeiten
    feld = bearbeiten.bewertung_wahl
    b = str(tmp_path / "b.jpg")
    fremd = tmp_path / "b.jpg.xmp"
    fremd.write_bytes(FREMDES_XMP)
    os.utime(fremd, ns=(10**18, 10**18))
    vorher, zeit = fremd.read_bytes(), fremd.stat().st_mtime_ns
    bearbeiten.oeffnen(b)
    assert feld.currentData() == 0                         # das Bild hat keine Sterne
    feld.setCurrentIndex(feld.findData(5))
    assert "fremden XMP-Datei" in fenster.statusmeldung.text()
    assert fremd.read_bytes() == vorher and fremd.stat().st_mtime_ns == zeit
    assert bearbeiten.sitzung.angaben.bewertung == 5       # fuer „Speichern unter“ gilt es
    feld.setCurrentIndex(feld.findData(0))
    assert fremd.read_bytes() == vorher and fremd.stat().st_mtime_ns == zeit
    # Erst Sterne, dann „–“: die eigene Datei bleibt mit 0 stehen; ohne Sterne entsteht keine
    bearbeiten.oeffnen(str(tmp_path / "c.jpg"))
    feld.setCurrentIndex(feld.findData(2))
    feld.setCurrentIndex(feld.findData(0))
    assert bewertung.lesen(str(tmp_path / "c.jpg")) == bewertung.Stand(0, "eigen")
    bearbeiten.oeffnen(str(tmp_path / "a.jpg"))
    feld.setCurrentIndex(feld.findData(0))
    assert not (tmp_path / "a.jpg.xmp").exists()


def _feld_waehlen(feld, sterne):
    feld.setCurrentIndex(feld.findData(sterne))


def test_bewertung_rueckgaengig_wiederholen_zuruecksetzen_fuehren_die_datei_mit(
        fenster, tmp_path, bewertung_umgebung):
    """Entscheidung A: Aendert Rueckgaengig, Wiederholen oder Zuruecksetzen das Feld, folgen
    die eigene Datei und die Ordneransicht. Feld, Datei und Kachel zeigen dasselbe."""
    from silberkorn import bewertung
    seite, _konfiguration = bewertung_umgebung
    bearbeiten = fenster.bearbeiten
    feld = bearbeiten.bewertung_wahl
    a = str(tmp_path / "a.jpg")
    bewertung.schreiben(a, 2)
    bearbeiten.oeffnen(a)
    assert feld.currentData() == 2
    _feld_waehlen(feld, 4)
    assert bewertung.lesen(a).wert == 4 and _stand(seite, a).wert == 4
    bearbeiten._festhalten(sofort=True)
    bearbeiten.rueckgaengig()
    assert feld.currentData() == 2 and bearbeiten.sitzung.angaben.bewertung == 2
    assert bewertung.lesen(a) == bewertung.Stand(2, "eigen") and _stand(seite, a).wert == 2
    bearbeiten.wiederholen()
    assert feld.currentData() == 4
    assert bewertung.lesen(a).wert == 4 and _stand(seite, a).wert == 4
    # Zuruecksetzen stellt die Vorgabe her - nach dem Schreiben ist das der Wert der Datei
    bearbeiten.angaben_zuruecksetzen()
    assert feld.currentData() == 4 and bewertung.lesen(a).wert == 4


def test_bewertung_zuruecksetzen_ohne_erlaubnis_schreibt_nichts_und_fremde_bleibt(
        fenster, tmp_path, bewertung_umgebung, monkeypatch):
    from silberkorn import bewertung, einstellungen
    seite, _konfiguration = bewertung_umgebung
    bearbeiten = fenster.bearbeiten
    feld = bearbeiten.bewertung_wahl
    a, b = str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")
    bewertung.schreiben(a, 2)
    bearbeiten.oeffnen(a)
    monkeypatch.setattr(einstellungen, "begleitdateien", lambda: False)
    _feld_waehlen(feld, 5)                                 # nichts geschrieben
    assert bewertung.lesen(a).wert == 2
    assert "nicht gespeichert" in fenster.statusmeldung.text()
    bearbeiten._festhalten(sofort=True)
    bearbeiten.rueckgaengig()                              # Feld wieder 2, ohne Erlaubnis
    assert feld.currentData() == 2 and bewertung.lesen(a).wert == 2
    bearbeiten.wiederholen()
    assert feld.currentData() == 5 and bewertung.lesen(a).wert == 2
    bearbeiten.angaben_zuruecksetzen()                     # zurueck auf die Vorgabe (2)
    assert feld.currentData() == 2 and bewertung.lesen(a).wert == 2
    # Fremde Datei: Rueckgaengig und Zuruecksetzen lassen sie Byte fuer Byte stehen
    monkeypatch.setattr(einstellungen, "begleitdateien", lambda: True)
    fremd = tmp_path / "b.jpg.xmp"
    fremd.write_bytes(FREMDES_XMP)
    vorher = fremd.read_bytes()
    seite.ordner_zeigen(str(tmp_path))
    _bewertungen_warten()
    bearbeiten.oeffnen(b)
    _feld_waehlen(feld, 1)
    bearbeiten._festhalten(sofort=True)
    bearbeiten.rueckgaengig()
    bearbeiten.wiederholen()
    bearbeiten.angaben_zuruecksetzen()
    assert fremd.read_bytes() == vorher
    assert _stand(seite, b) == bewertung.Stand(4, "fremd")


def test_bewertung_ausschuss_bleibt_bei_rueckgaengig_ohne_feldaenderung(
        fenster, tmp_path, bewertung_umgebung):
    """Ausschuss steht im Feld als „–“. Ein Rueckgaengig oder Zuruecksetzen, das das Feld
    nur auf „–“ laesst, ueberschreibt ihn nicht mit 0."""
    from silberkorn import bewertung
    seite, _konfiguration = bewertung_umgebung
    bearbeiten = fenster.bearbeiten
    feld = bearbeiten.bewertung_wahl
    a = str(tmp_path / "a.jpg")
    bewertung.schreiben(a, bewertung.AUSSCHUSS)
    seite.ordner_zeigen(str(tmp_path))
    _bewertungen_warten()
    bearbeiten.oeffnen(a)
    assert feld.currentData() == 0
    # Eine andere Angabe aendern und zuruecknehmen: das Feld bleibt „–“
    bearbeiten.angaben_felder["titel"].setText("Test")
    bearbeiten.angaben_felder["titel"].textEdited.emit("Test")
    bearbeiten._festhalten(sofort=True)
    bearbeiten.rueckgaengig()
    bearbeiten.wiederholen()
    bearbeiten.angaben_zuruecksetzen()
    assert feld.currentData() == 0
    assert bewertung.lesen(a) == bewertung.Stand(-1, "eigen")
    assert _stand(seite, a).wert == bewertung.AUSSCHUSS


def test_bewertung_eigene_datei_mit_null_geht_vor_dem_bild(fenster, tmp_path,
                                                           bewertung_umgebung):
    """Entscheidung B: Die eigene Datei mit 0 gilt, nicht die 3 Sterne im Bild. Wer „–“ waehlt,
    behaelt es auch nach „Zuruecksetzen“."""
    from silberkorn import bewertung, bilddatei, metadaten
    seite, _konfiguration = bewertung_umgebung
    bearbeiten = fenster.bearbeiten
    feld = bearbeiten.bewertung_wahl
    a = str(tmp_path / "a.jpg")
    # Ein Bild mit 3 Sternen im Bild: ueber das Feld speichern
    bearbeiten.oeffnen(a)
    _feld_waehlen(feld, 3)
    ziel = str(tmp_path / "drei.jpg")
    bearbeiten.sitzung.exportieren(ziel, 8)
    bearbeiten.schliessen()
    bearbeiten._knoepfe_freischalten()
    daten = bilddatei.laden(ziel)
    assert metadaten.lesen(daten.exif, daten.xmp, daten.iptc).angaben.bewertung == 3
    assert not os.path.exists(ziel + ".xmp")
    bewertung.schreiben(ziel, 0)
    bearbeiten.oeffnen(ziel)
    assert feld.currentData() == 0 and bearbeiten.sitzung.angaben.bewertung == 0
    assert not bearbeiten.sitzung.geaendert
    # Ohne eigene Datei gilt das Bild
    os.remove(ziel + ".xmp")
    bearbeiten.oeffnen(ziel)
    assert feld.currentData() == 3
    _feld_waehlen(feld, 0)                                 # „–“ legt die Datei mit 0 an
    assert bewertung.lesen(ziel) == bewertung.Stand(0, "eigen")
    bearbeiten.angaben_zuruecksetzen()
    assert feld.currentData() == 0 and bewertung.lesen(ziel).wert == 0


def test_bewertung_unlesbar_hat_eigenen_text_und_wird_zusammengefasst(
        fenster, tmp_path, bewertung_umgebung):
    from silberkorn import bewertung, ordner_seite
    seite, _konfiguration = bewertung_umgebung
    a, b = str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")
    kaputt = tmp_path / "a.jpg.xmp"
    kaputt.write_bytes(b"<x:xmpmeta")
    (tmp_path / "b.jpg.xmp").write_bytes(FREMDES_XMP)
    seite.ordner_zeigen(str(tmp_path))
    _bewertungen_warten()
    assert _stand(seite, a) == bewertung.Stand(0, "unlesbar")
    assert _stand(seite, b) == bewertung.Stand(4, "fremd")
    assert "1 Bewertungsdatei" in fenster.statusmeldung.text()
    za, zb = seite.modell.pfade.index(a), seite.modell.pfade.index(b)
    text_a = seite.liste.tooltip_fuer(za, ("stern", 3))
    text_b = seite.liste.tooltip_fuer(zb, ("stern", 3))
    assert "nicht lesen" in text_a and "fremden XMP-Datei" in text_b and text_a != text_b
    _klicken(seite, a, ("stern", 3))
    assert "nicht lesen" in fenster.statusmeldung.text()
    assert ordner_seite.bewertung_setzen(fenster, a, 2) is False
    assert "nicht lesen" in fenster.statusmeldung.text()
    assert kaputt.read_bytes() == b"<x:xmpmeta"
    # Im Bearbeiten-Reiter: das Feld bleibt beim Bild, die Datei unberuehrt
    fenster.bearbeiten.oeffnen(a)
    assert fenster.bearbeiten.bewertung_wahl.currentData() == 0
    _feld_waehlen(fenster.bearbeiten.bewertung_wahl, 3)
    assert kaputt.read_bytes() == b"<x:xmpmeta"
    assert "nicht lesen" in fenster.statusmeldung.text()


def test_bewertung_veralteter_durchgang_aendert_nichts(fenster, tmp_path, bewertung_umgebung):
    from silberkorn import bewertung
    seite, _konfiguration = bewertung_umgebung
    a = str(tmp_path / "a.jpg")
    modell = seite.modell
    alt = modell.durchgang
    seite.ordner_zeigen(str(tmp_path))                     # neuer Durchgang
    _bewertungen_warten()
    vorher = dict(modell.bewertungen)
    assert modell.staende_laden(alt, {a: bewertung.Stand(5, "eigen")}) is False
    assert modell.bewertungen == vorher


def test_bewertung_ordner_ohne_bilder_macht_den_durchgang_ungueltig(fenster, tmp_path,
                                                                    bewertung_umgebung):
    seite, _konfiguration = bewertung_umgebung
    seite.ordner_zeigen(str(tmp_path / "unter"))
    assert seite.bewertungen._aktuell == -1


def test_sortierung_nach_datum_ohne_zeit_stuerzt_nicht_ab(tmp_path):
    """Fehlt die Zeit eines Bildes (stat gescheitert), gilt es als das aelteste."""
    from PIL import Image

    from silberkorn import bewertung, ordner_seite
    for name in ("a.jpg", "b.jpg"):
        Image.new("RGB", (8, 8)).save(tmp_path / name)
    _unter, bilder, zeiten = ordner_seite._durchsuchen(str(tmp_path))
    zeiten.pop(str(tmp_path / "a.jpg"))
    ergebnis = bewertung.sortiert(sorted(bilder), "datum", ordner_seite._nach_name, {}, zeiten)
    assert ergebnis == [str(tmp_path / "b.jpg"), str(tmp_path / "a.jpg")]


def test_bewertung_sterne_klick_zieht_kein_gummiband(fenster, tmp_path, bewertung_umgebung):
    """Ein Klick auf einen Stern gehoert der Kachel: Bewegt sich die Maus mit gedrueckter
    Taste, zieht Qt kein Gummiband ab dem vorigen Klick, die Auswahl bleibt, und danach
    markiert eine Mausbewegung ohne Taste nichts."""
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from silberkorn import bewertung
    seite, _konfiguration = bewertung_umgebung
    a, b, c = (str(tmp_path / n) for n in ("a.jpg", "b.jpg", "c.jpg"))
    ansicht = seite.liste.viewport()
    seite.liste.setSelectionMode(seite.liste.SelectionMode.ExtendedSelection)

    def ausgewaehlt():
        return sorted(os.path.basename(seite.modell.pfade[i.row()])
                      for i in seite.liste.selectionModel().selectedIndexes())

    QTest.mouseClick(ansicht, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     _kachel_ort(seite, a))                # A waehlen: Druckposition setzen
    assert ausgewaehlt() == ["a.jpg"]

    def ereignis(art, ort, taste, tasten):
        punkt = QPointF(ort)
        QApplication.sendEvent(ansicht, QMouseEvent(
            art, punkt, ansicht.mapToGlobal(punkt), taste, tasten,
            Qt.KeyboardModifier.NoModifier))

    start, ziel = _kachel_ort(seite, b, ("stern", 3)), _kachel_ort(seite, c)
    links, keine = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    ereignis(QEvent.Type.MouseMove, start, keine, keine)
    ereignis(QEvent.Type.MouseButtonPress, start, links, links)
    for schritt in range(1, 6):
        punkt = QPoint(start.x() + (ziel.x() - start.x()) * schritt // 5,
                       start.y() + (ziel.y() - start.y()) * schritt // 5)
        ereignis(QEvent.Type.MouseMove, punkt, links, links)
        assert ausgewaehlt() == ["a.jpg"]                   # nie ein Gummiband
    ereignis(QEvent.Type.MouseButtonRelease, ziel, links, keine)
    assert ausgewaehlt() == ["a.jpg"]
    assert _stand(seite, b) == bewertung.Stand(3, "eigen")
    assert seite.liste.state() == seite.liste.State.NoState
    ereignis(QEvent.Type.MouseMove, _kachel_ort(seite, a), keine, keine)
    ereignis(QEvent.Type.MouseMove, _kachel_ort(seite, c), keine, keine)
    assert ausgewaehlt() == ["a.jpg"]


# --------------------------------------------------------------------------
# Monitorprofil
# --------------------------------------------------------------------------

@pytest.fixture
def monitor(fenster, monkeypatch):
    """Ein vorgegebenes Profil statt des echten Bildschirms; danach wieder aus."""
    from silberkorn import anzeigeprofil, einstellungen
    gemerkt = []
    monkeypatch.setattr(einstellungen, "monitorprofil_setzen", gemerkt.append)
    gelesen = {"profil": None}

    def lesen(_fenster):
        if isinstance(gelesen["profil"], Exception):
            raise gelesen["profil"]
        return gelesen["profil"]

    monkeypatch.setattr(anzeigeprofil, "profil_lesen", lesen)
    yield gelesen, gemerkt
    fenster.monitor_box.blockSignals(True)
    fenster.monitor_box.setChecked(False)
    fenster.monitor_box.blockSignals(False)
    fenster.monitor_pruefen()
    assert anzeigeprofil.aktiv() is None


def _adobe():
    from test_icc import adobe_rgb_profil
    return "Breit.icc", adobe_rgb_profil()


def test_monitorprofil_ohne_profil_ausgegraut(fenster, monitor):
    from silberkorn import anzeigeprofil
    fenster.monitor_pruefen()
    assert not fenster.monitor_box.isEnabled()
    assert "kein Farbprofil" in fenster.monitor_box.toolTip()
    assert anzeigeprofil.aktiv() is None


def test_monitorprofil_srgb_ausgegraut_mit_name(fenster, monitor):
    from PIL import ImageCms

    from silberkorn import anzeigeprofil
    gelesen, _gemerkt = monitor
    gelesen["profil"] = ("sRGB Color Space Profile.icm",
                         ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    fenster.monitor_box.setChecked(True)
    assert not fenster.monitor_box.isEnabled()
    assert "sRGB Color Space Profile.icm" in fenster.monitor_box.toolTip()
    assert "entspricht sRGB" in fenster.monitor_box.toolTip()
    assert anzeigeprofil.aktiv() is None


def test_monitorprofil_ein_und_aus(fenster, monitor, monkeypatch):
    """Einschalten merkt die Wahl, rechnet die Leinwand um und laedt die Kacheln neu;
    die Bewertungen des Ordners bleiben gueltig."""
    import numpy as np

    from silberkorn import anzeigeprofil
    gelesen, gemerkt = monitor
    gelesen["profil"] = _adobe()
    fenster.monitor_pruefen()
    assert fenster.monitor_box.isEnabled() and not fenster.monitor_box.isChecked()
    assert "Breit.icc" in fenster.monitor_box.toolTip()
    assert anzeigeprofil.aktiv() is None
    zeichnen = []
    monkeypatch.setattr(fenster.bearbeiten, "zeichnen_anfordern", lambda: zeichnen.append(1))
    modell = fenster.ordner.modell
    stand, durchgang = modell._kachelstand, modell.durchgang
    leinwand = fenster.bearbeiten.leinwand
    gruen = np.zeros((4, 4, 3), np.uint8)
    gruen[..., 1] = 255

    fenster.monitor_box.setChecked(True)
    assert gemerkt == [True]
    assert anzeigeprofil.aktiv() is not None and anzeigeprofil.aktiv().name == "Breit.icc"
    assert zeichnen == [1]
    assert modell._kachelstand == stand + 1 and modell.durchgang == durchgang
    leinwand._setzen(gruen)
    farbe = leinwand._bild.pixelColor(0, 0)
    assert farbe.red() > 100 and farbe.blue() > 30

    fenster.monitor_box.setChecked(False)
    assert gemerkt == [True, False]
    assert anzeigeprofil.aktiv() is None
    assert zeichnen == [1, 1] and modell._kachelstand == stand + 2
    leinwand._setzen(gruen)
    farbe = leinwand._bild.pixelColor(0, 0)
    assert (farbe.red(), farbe.green(), farbe.blue()) == (0, 255, 0)
    leinwand._setzen(None)


def test_monitorprofil_gleiches_profil_zeichnet_nicht_neu(fenster, monitor, monkeypatch):
    """Ein erneutes Pruefen (etwa ein Wechsel auf einen Bildschirm mit demselben Profil)
    laedt weder Leinwand noch Kacheln neu; ein anderes Profil schon."""
    from silberkorn import anzeigeprofil
    gelesen, _gemerkt = monitor
    gelesen["profil"] = _adobe()
    fenster.monitor_box.setChecked(True)
    profil = anzeigeprofil.aktiv()
    zeichnen = []
    monkeypatch.setattr(fenster.bearbeiten, "zeichnen_anfordern", lambda: zeichnen.append(1))
    monkeypatch.setattr(fenster.ordner, "anzeige_geaendert", lambda: zeichnen.append(2))
    fenster.monitor_pruefen()
    assert zeichnen == [] and anzeigeprofil.aktiv() is profil
    _name, daten = _adobe()
    gelesen["profil"] = ("Anderes.icc", daten)
    fenster.monitor_pruefen()
    assert zeichnen == [1, 2] and anzeigeprofil.aktiv().name == "Anderes.icc"


def test_monitorprofil_kaputtes_profil(fenster, monitor):
    from silberkorn import anzeigeprofil
    gelesen, _gemerkt = monitor
    gelesen["profil"] = _adobe()
    fenster.monitor_box.setChecked(True)
    assert anzeigeprofil.aktiv() is not None
    gelesen["profil"] = ("Kaputt.icc", b"\x00" * 300)
    fenster.monitor_pruefen()
    assert anzeigeprofil.aktiv() is None
    assert not fenster.monitor_box.isEnabled()
    assert "Kaputt.icc" in fenster.monitor_box.toolTip()
    assert "Kaputt.icc" in fenster.statusmeldung.text()
    assert fenster.statusmeldung.objectName() == "warnung"


def test_monitorprofil_unlesbare_datei_wie_kaputtes_profil(fenster, monitor):
    from silberkorn import anzeigeprofil
    gelesen, _gemerkt = monitor
    gelesen["profil"] = anzeigeprofil.ProfilFehler("Weg.icc")
    fenster.monitor_box.setChecked(True)
    assert anzeigeprofil.aktiv() is None
    assert "Weg.icc" in fenster.monitor_box.toolTip()


def test_monitorprofil_bildschirmwechsel_prueft_neu(fenster, monitor):
    from silberkorn import anzeigeprofil
    gelesen, _gemerkt = monitor
    gelesen["profil"] = _adobe()
    fenster.monitor_box.setChecked(True)
    gelesen["profil"] = None                          # der andere Bildschirm hat keines
    fenster.windowHandle().screenChanged.emit(fenster.screen())
    assert anzeigeprofil.aktiv() is None
    assert not fenster.monitor_box.isEnabled()


def test_monitorprofil_tooltip_englisch(fenster, monitor):
    from silberkorn.uebersetzung import _
    gelesen, _gemerkt = monitor
    gelesen["profil"] = _adobe()
    fenster.monitor_pruefen()
    _.language = "en"
    fenster.texte_auffrischen()
    try:
        assert fenster.monitor_box.text() == "Monitor profile"
        assert "Breit.icc" in fenster.monitor_box.toolTip()
        assert "umrechnen" not in fenster.monitor_box.toolTip()
    finally:
        _.language = "de"
        fenster.texte_auffrischen()


def test_monitorprofil_gilt_fuer_kacheln_und_dialogvorschauen(fenster, monitor):
    import numpy as np
    from PIL import Image

    from silberkorn import drucken_dialog, ordner_seite, trennen_dialog
    gelesen, _gemerkt = monitor
    gelesen["profil"] = _adobe()
    fenster.monitor_box.setChecked(True)
    gruen = np.zeros((64, 64, 3), np.uint8)
    gruen[..., 1] = 255
    bilder = [ordner_seite._qimage(Image.fromarray(gruen)),
              trennen_dialog._pixmap(gruen).toImage(),
              drucken_dialog.Blatt(gruen)._bild]
    for bild in bilder:
        farbe = bild.pixelColor(bild.width() // 2, bild.height() // 2)
        assert farbe.red() > 100 and farbe.blue() > 30


def test_monitorprofil_alte_kacheln_verfallen_bewertungen_bleiben(fenster, monitor,
                                                                   bewertung_umgebung, tmp_path):
    """Kacheln, die noch mit dem alten Profil unterwegs sind, werden verworfen; die Sterne
    des Ordners und ein noch laufendes Lesen der Bewertungen bleiben gueltig."""
    from PySide6.QtGui import QImage

    from silberkorn import bewertung
    seite, _konfiguration = bewertung_umgebung
    modell = seite.modell
    a, b = str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")
    modell.stand_setzen(a, bewertung.Stand(4, "eigen"))
    _stand(seite, a)                                     # Kachel anfragen
    _warten(lambda: a in modell._bilder)
    gelesen, _gemerkt = monitor
    gelesen["profil"] = _adobe()
    alt = modell._kachelstand
    fenster.monitor_box.setChecked(True)
    assert modell._kachelstand == alt + 1
    assert not modell._bilder and not modell._angefragt and not modell._fehlend
    assert _stand(seite, a) == bewertung.Stand(4, "eigen")
    bild = QImage(4, 4, QImage.Format.Format_RGB888)
    modell._fertig(alt, b, bild, False)
    modell._fehlt(alt, a)
    assert b not in modell._bilder and a not in modell._fehlend
    assert modell.staende_laden(modell.durchgang, {b: bewertung.Stand(2, "fremd")})
    assert _stand(seite, b) == bewertung.Stand(2, "fremd")
    _warten(lambda: a in modell._bilder)                 # neu geladen, mit dem neuen Profil


def test_monitorprofil_aendert_vorschau_und_histogramm_nicht(fenster, monitor, tmp_path):
    """Die Sitzung liefert weiter sRGB - umgerechnet wird erst beim Zeigen. Speichern,
    Druck und Histogramm rechnen aus diesen Werten."""
    import numpy as np
    from PIL import Image

    gruen = np.zeros((48, 64, 3), np.uint8)
    gruen[..., 1] = 230
    pfad = tmp_path / "gruen.png"
    Image.fromarray(gruen).save(pfad)
    seite = fenster.bearbeiten
    seite.oeffnen(str(pfad))
    try:
        ohne, _ms, histogramm_ohne = seite.sitzung.vorschau()
        gelesen, _gemerkt = monitor
        gelesen["profil"] = _adobe()
        fenster.monitor_box.setChecked(True)
        mit, _ms, histogramm_mit = seite.sitzung.vorschau()
        assert np.array_equal(ohne, mit) and np.array_equal(histogramm_ohne, histogramm_mit)
    finally:
        seite.schliessen()
        seite._knoepfe_freischalten()


def test_monitorprofil_veroeffentlichen_vorschau(fenster, monitor):
    import numpy as np

    from silberkorn.veroeffentlichen import Vorlage
    from silberkorn.veroeffentlichen_dialog import VeroeffentlichenDialog
    gruen = np.zeros((300, 450, 3), np.uint8)
    gruen[..., 1] = 255

    def mitte():
        dialog = VeroeffentlichenDialog(None, gruen, (300, 450), Vorlage(format=".png"))
        bild = dialog.bild.pixmap().toImage()
        farbe = bild.pixelColor(bild.width() // 2, bild.height() // 2)
        dialog.deleteLater()
        return farbe.red(), farbe.green(), farbe.blue()

    assert mitte() == (0, 255, 0)
    gelesen, _gemerkt = monitor
    gelesen["profil"] = _adobe()
    fenster.monitor_box.setChecked(True)
    rot, _gruen, blau = mitte()
    assert rot > 100 and blau > 30


def test_monitorprofil_erst_kaputt_dann_gut(fenster, monitor):
    from silberkorn import anzeigeprofil
    gelesen, _gemerkt = monitor
    fenster.melden("Bereit.")
    gelesen["profil"] = ("Kaputt.icc", b"\x00" * 300)
    fenster.monitor_pruefen()                            # ausgeschaltet: keine Meldung
    assert "Kaputt.icc" in fenster.monitor_box.toolTip()
    assert "Kaputt.icc" not in fenster.statusmeldung.text()
    gelesen["profil"] = _adobe()
    fenster.monitor_pruefen()
    assert fenster.monitor_box.isEnabled()
    assert "Kaputt.icc" not in fenster.monitor_box.toolTip()
    fenster.monitor_box.setChecked(True)
    assert anzeigeprofil.aktiv() is not None
