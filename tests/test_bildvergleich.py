"""Bilder vergleichen: Reihe, Speicher, Kopplung und der Dialog.

Der Dialog laeuft mit erfundenen Bildern - ohne Grafikkarte; nur `laden` selbst
braucht sie.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from silberkorn import bewertung, bildvergleich
from silberkorn.bildvergleich import Reihe, Speicher, Vergleichsbild

# --------------------------------------------------------------------------
# Reihe: wer links und wer rechts steht
# --------------------------------------------------------------------------


def test_reihe_braucht_zwei_bilder():
    with pytest.raises(ValueError):
        Reihe(["a"])


def test_reihe_lehnt_doppelte_bilder_ab():
    with pytest.raises(ValueError):
        Reihe(["a", "b", "a"])


def test_reihe_mit_zwei_bildern_blaettert_nicht_und_tauscht():
    reihe = Reihe(["a", "b"])
    assert (reihe.links, reihe.rechts, reihe.blaetterbar) == ("a", "b", False)
    reihe.blaettern(1)
    assert (reihe.links, reihe.rechts) == ("a", "b")
    assert reihe.stelle() == (1, 1)
    reihe.tauschen()
    assert (reihe.links, reihe.rechts) == ("b", "a")


def test_reihe_blaettert_rechts_im_kreis_der_favorit_bleibt():
    reihe = Reihe(["a", "b", "c", "d"])
    assert reihe.blaetterbar
    gesehen = []
    for _i in range(4):
        gesehen.append(reihe.rechts)
        reihe.blaettern(1)
    assert gesehen == ["b", "c", "d", "b"]
    assert reihe.links == "a"
    assert reihe.rechts == "c"
    reihe.blaettern(-1)
    reihe.blaettern(-1)                           # rueckwaerts ueber den Anfang
    assert (reihe.rechts, reihe.stelle()) == ("d", (3, 3))


def test_reihe_tauschen_macht_den_kandidaten_zum_favoriten():
    reihe = Reihe(["a", "b", "c", "d"])
    reihe.blaettern(1)                            # rechts: c
    reihe.tauschen()
    assert (reihe.links, reihe.rechts) == ("c", "a")
    # Blaettern laeuft jetzt durch alle ausser c - der alte Favorit ist Kandidat
    gesehen = []
    for _i in range(3):
        gesehen.append(reihe.rechts)
        reihe.blaettern(1)
    assert sorted(gesehen) == ["a", "b", "d"]


# --------------------------------------------------------------------------
# Speicher, Kopplung, Ausschnitt
# --------------------------------------------------------------------------

def test_speicher_laedt_jedes_bild_einmal_und_vergisst_das_aelteste():
    geladen = []

    def laden(pfad):
        geladen.append(pfad)
        return Vergleichsbild(pfad)

    speicher = Speicher(laden, platz=2)
    erstes = speicher.holen("a")
    assert speicher.holen("a") is erstes
    speicher.holen("b")
    speicher.holen("a")                           # zuletzt gebraucht: a, dann ...
    speicher.holen("c")                           # ... verdraengt b, nicht a
    assert (speicher.da("a"), speicher.da("b"), speicher.da("c")) == (True, False, True)
    assert geladen == ["a", "b", "c"]
    speicher.leeren()
    assert not speicher.da("a")


def test_speicher_behaelt_fehlschlaege_nicht():
    """Was sich nicht laden liess, wird beim naechsten Mal neu versucht."""
    versuche = []

    def laden(pfad):
        versuche.append(pfad)
        return Vergleichsbild(pfad, fehler="Grafikspeicher" if len(versuche) == 1 else "")

    speicher = Speicher(laden)
    assert speicher.holen("a").fehler
    assert not speicher.da("a")
    assert not speicher.holen("a").fehler
    assert speicher.da("a") and versuche == ["a", "a"]


def test_mitte_uebertragen_an_dieselbe_stelle_im_verhaeltnis():
    # (Hoehe, Breite): ein Viertel der Breite, die halbe Hoehe
    assert bildvergleich.mitte_uebertragen((75.0, 100.0), (200, 300), (400, 600)) == (150.0, 200.0)
    assert bildvergleich.mitte_uebertragen((150.0, 50.0), (100, 300), (100, 300)) == (150.0, 50.0)


def test_ausschnitt_ist_der_bereich_ohne_kopie():
    bild = np.arange(5 * 7 * 3, dtype=np.uint8).reshape(5, 7, 3)
    teil = bildvergleich.ausschnitt(bild, (2, 1, 3, 2))
    assert teil.shape == (2, 3, 3)
    assert np.array_equal(teil, bild[1:3, 2:5])
    assert np.shares_memory(teil, bild)


def test_auf_weiss_ohne_alphakanal():
    rgba = np.zeros((1, 3, 4), np.uint8)
    rgba[0, 0] = (10, 20, 30, 255)                 # deckend
    rgba[0, 1] = (10, 20, 30, 0)                   # durchsichtig: weiss
    rgba[0, 2] = (0, 0, 0, 128)                    # halb: grau
    rgb = bildvergleich._auf_weiss(rgba)
    assert rgb.shape == (1, 3, 3)
    assert tuple(rgb[0, 0]) == (10, 20, 30)
    assert tuple(rgb[0, 1]) == (255, 255, 255)
    assert 120 <= rgb[0, 2, 0] <= 130
    drei = np.ones((2, 2, 3), np.uint8)
    assert bildvergleich._auf_weiss(drei).shape == (2, 2, 3)


# --------------------------------------------------------------------------
# Dialog - mit erfundenen Bildern
# --------------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


FORMEN = {"a.jpg": (200, 300), "b.jpg": (400, 600), "c.jpg": (100, 100), "d.jpg": (1, 1),
          "e.jpg": (3000, 4000)}


def _erfunden(pfad: str) -> Vergleichsbild:
    name = os.path.basename(pfad)
    if name.startswith("kaputt"):
        return Vergleichsbild(pfad, fehler="kein Bild")
    if name == "wirft.jpg":
        raise RuntimeError("unerwartet")
    hoehe, breite = FORMEN[name]
    voll = np.zeros((hoehe, breite, 3), np.uint8)
    voll[..., 0] = np.arange(breite, dtype=np.uint16)[None, :] % 256    # Rot = Spalte
    voll[..., 1] = np.arange(hoehe, dtype=np.uint16)[:, None] % 256     # Gruen = Zeile
    return Vergleichsbild(pfad, vorschau=voll[::2, ::2].copy(), voll=voll, datum="2024-05-17 14:03",
                          datum_aufnahme=True, aufnahme={"kamera": "Testkamera",
                                                         "belichtung": "1/125 s · f/8"})


@pytest.fixture
def ablauf(app):
    """Ein Dialog mit drei Bildern; Laden und Bewerten werden mitgeschrieben."""
    from silberkorn.bildvergleich_dialog import VergleichDialog
    protokoll = {"geladen": [], "bewertet": [], "erlaubt": True}

    def laden(pfad):
        protokoll["geladen"].append(os.path.basename(pfad))
        return _erfunden(pfad)

    def bewerten(pfad, wert, melden):
        protokoll["bewertet"].append((os.path.basename(pfad), wert))
        if not protokoll["erlaubt"]:
            melden("verboten", True)
        return protokoll["erlaubt"]

    def starten(namen=("a.jpg", "b.jpg", "c.jpg"), staende=None):
        dialog = VergleichDialog(None, [os.path.join("ordner", n) for n in namen],
                                 staende or {}, bewerten, lambda stand: "gesperrt: " + stand.art,
                                 laden)
        dialog.resize(1000, 700)
        dialog.show()
        app.processEvents()                       # zeigt und rechnet (showEvent)
        app.processEvents()
        protokoll["dialog"] = dialog
        return dialog

    protokoll["starten"] = starten
    yield protokoll
    if protokoll.get("dialog") is not None:
        protokoll["dialog"].close()


def _name(seite):
    return seite.name.text()


def test_dialog_zeigt_favorit_und_kandidat(ablauf):
    dialog = ablauf["starten"]()
    assert (_name(dialog.links), _name(dialog.rechts)) == ("a.jpg", "b.jpg")
    assert dialog.links.titel.text() == "Favorit"
    assert dialog.stelle.text() == "Kandidat 1/2"
    assert dialog.zurueck_knopf.isVisible() and dialog.vor_knopf.isVisible()
    angaben = dialog.links.angaben.text()
    assert "300 × 200 px" in angaben
    assert "Aufnahme 2024-05-17 14:03" in angaben
    assert "Testkamera" in angaben and "f/8" in angaben
    assert dialog.links.leinwand.voll_form == (200, 300)
    assert dialog.links.leinwand._bild is not None
    assert ablauf["geladen"] == ["a.jpg", "b.jpg"]


def test_dialog_blaettert_und_tauscht_ohne_neu_zu_rechnen(ablauf):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    dialog = ablauf["starten"]()
    QTest.keyClick(dialog, Qt.Key.Key_Right)
    assert (_name(dialog.links), _name(dialog.rechts)) == ("a.jpg", "c.jpg")
    assert dialog.stelle.text() == "Kandidat 2/2"
    dialog.vor_knopf.click()                       # im Kreis: wieder b
    assert _name(dialog.rechts) == "b.jpg"
    dialog.tauschen_knopf.click()
    assert (_name(dialog.links), _name(dialog.rechts)) == ("b.jpg", "a.jpg")
    assert ablauf["geladen"] == ["a.jpg", "b.jpg", "c.jpg"]     # nichts doppelt


def test_dialog_mit_zwei_bildern_ohne_blaettern(ablauf):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    dialog = ablauf["starten"](("a.jpg", "b.jpg"))
    assert not dialog.vor_knopf.isVisible() and not dialog.stelle.isVisible()
    QTest.keyClick(dialog, Qt.Key.Key_Right)
    assert _name(dialog.rechts) == "b.jpg"
    assert dialog.tauschen_knopf.toolTip() == "Die beiden Seiten tauschen."
    dialog.tauschen_knopf.click()
    assert (_name(dialog.links), _name(dialog.rechts)) == ("b.jpg", "a.jpg")


def test_gekoppelte_ansicht_folgt_im_verhaeltnis(ablauf):
    dialog = ablauf["starten"]()
    links, rechts = dialog.links.leinwand, dialog.rechts.leinwand
    dialog.voll_knopf.click()
    assert links.zoom == rechts.zoom == 1.0
    links.ansicht_uebernehmen(1.0, (75.0, 50.0))            # ein Viertel, ein Viertel
    assert rechts.mitte == pytest.approx((150.0, 100.0))
    # Gezeigt wird rechts der sichtbare Ausschnitt des vollen Bildes
    x0, y0, breite, hoehe = rechts.sichtbarer_bereich()
    assert (rechts._bild.width(), rechts._bild.height()) == (breite, hoehe)
    assert rechts._ausschnitt_ort == (x0, y0)
    assert rechts._bild.pixelColor(0, 0).red() == x0 % 256
    dialog.einpassen_knopf.click()
    assert links.zoom is None and rechts.zoom is None


def test_entkoppelt_bleibt_die_andere_seite_stehen(ablauf):
    dialog = ablauf["starten"]()
    links, rechts = dialog.links.leinwand, dialog.rechts.leinwand
    dialog.koppeln_knopf.click()
    assert not dialog.koppeln_knopf.isChecked()
    links.zoom_setzen(2.0)
    assert links.zoom == 2.0 and rechts.zoom is None
    dialog.koppeln_knopf.click()                   # wieder gekoppelt: rechts holt auf
    assert rechts.zoom == 2.0


def test_blaettern_behaelt_zoom_und_lage_im_verhaeltnis(ablauf):
    dialog = ablauf["starten"]()
    rechts = dialog.rechts.leinwand
    dialog.voll_knopf.click()
    rechts.ansicht_uebernehmen(1.0, (450.0, 100.0))         # b: drei Viertel, ein Viertel
    dialog.blaettern(1)                            # c ist 100 x 100
    assert rechts.voll_form == (100, 100)
    assert rechts.zoom == 1.0
    assert rechts.mitte == pytest.approx((75.0, 25.0))


def test_bewerten_schreibt_und_zeigt_die_sterne(ablauf):
    dialog = ablauf["starten"]()
    sterne = dialog.links.bewertung.sterne
    sterne[2].click()
    assert ablauf["bewertet"] == [("a.jpg", 3)]
    assert [k.text() for k in sterne] == ["★", "★", "★", "☆", "☆"]
    assert dialog.staende[os.path.join("ordner", "a.jpg")] == bewertung.Stand(3, "eigen")
    assert dialog.bewertet
    sterne[2].click()                              # derselbe Stern noch einmal: entfernt
    assert ablauf["bewertet"][-1] == ("a.jpg", 0)
    dialog.rechts.bewertung.ausschuss.click()
    assert ablauf["bewertet"][-1] == ("b.jpg", bewertung.AUSSCHUSS)
    assert dialog.rechts.bewertung.ausschuss.isChecked()
    dialog.rechts.bewertung.ausschuss.click()      # aufheben
    assert ablauf["bewertet"][-1] == ("b.jpg", 0)
    assert not dialog.rechts.bewertung.ausschuss.isChecked()


def test_bewerten_abgelehnt_laesst_alles_wie_es_war(ablauf):
    dialog = ablauf["starten"]()
    ablauf["erlaubt"] = False
    dialog.links.bewertung.sterne[4].click()
    dialog.links.bewertung.ausschuss.click()
    assert [k.text() for k in dialog.links.bewertung.sterne] == ["☆"] * 5
    assert not dialog.links.bewertung.ausschuss.isChecked()
    assert not dialog.bewertet
    assert dialog.meldung.text() == "verboten"
    assert dialog.meldung.objectName() == "warnung"


def test_fremde_bewertung_ist_gesperrt(ablauf):
    pfad = os.path.join("ordner", "b.jpg")
    dialog = ablauf["starten"](staende={pfad: bewertung.Stand(4, "fremd")})
    leiste = dialog.rechts.bewertung
    assert [k.text() for k in leiste.sterne] == ["★"] * 4 + ["☆"]
    assert not any(k.isEnabled() for k in leiste.sterne)
    assert not leiste.ausschuss.isEnabled()
    assert leiste.sterne[0].toolTip() == "gesperrt: fremd"
    assert dialog.links.bewertung.sterne[0].isEnabled()


def test_nicht_ladbares_bild_wird_genannt(ablauf):
    dialog = ablauf["starten"](("a.jpg", "kaputt.jpg"))
    leinwand = dialog.rechts.leinwand
    assert leinwand.leer.text() == "Lässt sich nicht laden"
    assert leinwand.hinweis.text() == "kein Bild"
    assert leinwand._bild is None
    dialog.voll_knopf.click()                      # Zoomen stoert die kaputte Seite nicht
    assert dialog.links.leinwand.zoom == 1.0 and leinwand._bild is None


def test_bearbeiten_schliesst_mit_dem_bild(ablauf):
    from PySide6.QtWidgets import QDialog
    dialog = ablauf["starten"]()
    dialog.rechts.bearbeiten_knopf.click()
    assert dialog.zu_bearbeiten == os.path.join("ordner", "b.jpg")
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.links.bild is None and dialog.rechts.bild is None   # Speicher frei
    assert not dialog._speicher.da(os.path.join("ordner", "a.jpg"))


def test_bedienelemente_haben_namen(ablauf):
    dialog = ablauf["starten"]()
    for knopf in (dialog.koppeln_knopf, dialog.zurueck_knopf, dialog.vor_knopf,
                  dialog.tauschen_knopf, dialog.voll_knopf, *dialog.links.bewertung.sterne,
                  dialog.links.bewertung.ausschuss):
        assert knopf.accessibleName(), knopf.text()


def test_unerwartete_ausnahme_wird_zur_fehlerseite(ablauf, capsys):
    from PySide6.QtWidgets import QApplication
    dialog = ablauf["starten"](("a.jpg", "wirft.jpg", "b.jpg"))
    leinwand = dialog.rechts.leinwand
    assert leinwand.leer.text() == "Lässt sich nicht laden"
    assert leinwand.hinweis.text() == "RuntimeError: unerwartet"
    assert QApplication.overrideCursor() is None             # die Sanduhr ist wieder weg
    assert "RuntimeError" in capsys.readouterr().err         # der Ablauf steht im Protokoll
    dialog.blaettern(1)
    assert _name(dialog.rechts) == "b.jpg" and leinwand._bild is not None


def test_nicht_ladbares_wird_beim_naechsten_mal_neu_versucht(ablauf):
    dialog = ablauf["starten"](("a.jpg", "kaputt.jpg", "b.jpg"))
    dialog.blaettern(1)
    dialog.blaettern(-1)
    assert ablauf["geladen"].count("kaputt.jpg") == 2
    assert ablauf["geladen"].count("a.jpg") == 1


def test_favorit_wird_beim_blaettern_nur_einmal_gerechnet(ablauf):
    """Speicher fuer drei Bilder, fuenf im Vergleich: der Favorit bleibt trotzdem."""
    dialog = ablauf["starten"](("a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"))
    for _i in range(4):
        dialog.blaettern(1)
    for _i in range(4):
        dialog.blaettern(-1)
    assert ablauf["geladen"].count("a.jpg") == 1
    assert all(ablauf["geladen"].count(n) <= 3 for n in ("b.jpg", "c.jpg", "d.jpg", "e.jpg"))
    assert _name(dialog.links) == "a.jpg" and _name(dialog.rechts) == "b.jpg"


def test_bewertung_bleibt_nach_tauschen_und_blaettern(ablauf):
    dialog = ablauf["starten"]()
    dialog.links.bewertung.sterne[2].click()       # a: drei Sterne
    dialog.tauschen()                              # a steht jetzt rechts
    assert [k.text() for k in dialog.rechts.bewertung.sterne][:3] == ["★"] * 3
    dialog.tauschen()
    dialog.blaettern(1)
    dialog.blaettern(1)
    assert [k.text() for k in dialog.links.bewertung.sterne][:3] == ["★"] * 3
    assert ablauf["bewertet"] == [("a.jpg", 3)]


def test_kaputte_seite_weg_und_zurueck_mit_zoom(ablauf):
    dialog = ablauf["starten"](("a.jpg", "kaputt.jpg", "b.jpg"))
    dialog.voll_knopf.click()
    dialog.blaettern(1)                            # von der kaputten Seite weg ...
    rechts = dialog.rechts.leinwand
    assert rechts.voll_form == (400, 600) and rechts.zoom == 1.0
    hoehe, breite = rechts.voll_form
    assert 0 <= rechts.mitte[0] <= breite and 0 <= rechts.mitte[1] <= hoehe
    dialog.blaettern(1)                            # ... und wieder hin
    assert rechts.voll_form is None and rechts._bild is None
    dialog.einpassen_knopf.click()


def test_zwei_kaputte_bilder(ablauf):
    dialog = ablauf["starten"](("kaputt1.jpg", "kaputt2.jpg"))
    dialog.voll_knopf.click()
    dialog.tauschen()
    assert dialog.links.leinwand._bild is None and dialog.rechts.leinwand._bild is None


def test_100_prozent_am_rand_und_sehr_kleine_bilder(ablauf):
    dialog = ablauf["starten"](("e.jpg", "d.jpg"))         # 4000 x 3000 neben 1 x 1
    links, rechts = dialog.links.leinwand, dialog.rechts.leinwand
    dialog.voll_knopf.click()
    for mitte in ((0.0, 0.0), (4000.0, 3000.0), (-500.0, 9999.0)):
        links.ansicht_uebernehmen(1.0, mitte)
        assert 0 <= links.mitte[0] <= 4000 and 0 <= links.mitte[1] <= 3000
        x0, y0, breite, hoehe = links.sichtbarer_bereich()
        assert (links._bild.width(), links._bild.height()) == (breite, hoehe)
        assert links._ausschnitt_ort == (x0, y0)
        assert 0 <= rechts.mitte[0] <= 1 and 0 <= rechts.mitte[1] <= 1
    assert rechts._bild is not None


def test_bewerten_unerwartete_ausnahme_wird_gemeldet(ablauf):
    dialog = ablauf["starten"]()

    def kaputt(*_a):
        raise PermissionError("gesperrt")

    dialog._bewerten = kaputt
    dialog.links.bewertung.sterne[0].click()
    assert "PermissionError: gesperrt" in dialog.meldung.text()
    assert dialog.meldung.objectName() == "warnung"
    assert dialog.links.bewertung.sterne[0].text() == "☆"


def test_schliessen_gibt_die_bilder_frei(ablauf):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    dialog = ablauf["starten"]()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
    assert dialog.links.bild is None
    assert not dialog._speicher.da(os.path.join("ordner", "a.jpg"))


def test_angaben_verkleinert_und_veraltet():
    from silberkorn.bildvergleich_dialog import angaben_text
    bild = Vergleichsbild("x.jpg", voll=np.zeros((10, 20, 3), np.uint8), verkleinert=True,
                          datum="2024-01-02 03:04", veraltet=True, bearbeitet=True,
                          verworfen=True)
    text = angaben_text(bild)
    assert "20 × 10 px (verkleinert" in text
    assert "Geändert 2024-01-02 03:04" in text
    assert "passt nicht ganz" in text and "Mit der Bearbeitung" not in text
    assert "Ungültige Werte" in text


# --------------------------------------------------------------------------
# Laden - mit Grafikkarte
# --------------------------------------------------------------------------

@pytest.fixture
def gpu():
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    return cp


def test_laden_traegt_die_bearbeitung_der_begleitdatei(gpu, tmp_path):
    from PIL import Image

    from silberkorn import begleitdatei, bilddatei
    from silberkorn.bearbeitung import Sitzung
    pfad = str(tmp_path / "grau.png")
    Image.fromarray(np.full((300, 600, 3), 100, np.uint8)).save(pfad)

    roh = bildvergleich.laden(pfad, kante=120)
    assert not roh.fehler and not roh.bearbeitet and not roh.verkleinert
    assert roh.form == (300, 600)
    assert roh.vorschau.shape == (60, 120, 3)
    assert not roh.datum_aufnahme and roh.datum               # Aenderungsdatum der Datei

    sitzung = Sitzung(bilddatei.laden(pfad), 120)
    sitzung.werte.belichtung = 1.0
    begleitdatei.schreiben(pfad, sitzung.begleit_inhalt(), begleitdatei.fingerabdruck(pfad))
    sitzung.schliessen()
    hell = bildvergleich.laden(pfad, kante=120)
    assert hell.bearbeitet
    assert hell.voll[150, 300, 0] > roh.voll[150, 300, 0] + 20
    assert hell.vorschau[30, 60, 0] > roh.vorschau[30, 60, 0] + 20


def test_laden_veraltete_begleitdatei_und_schreibt_nichts(gpu, tmp_path):
    from PIL import Image

    from silberkorn import begleitdatei, bilddatei
    from silberkorn.bearbeitung import Sitzung
    pfad = str(tmp_path / "grau.png")
    Image.fromarray(np.full((300, 600, 3), 100, np.uint8)).save(pfad)
    sitzung = Sitzung(bilddatei.laden(pfad), 120)
    sitzung.werte.belichtung = 1.0
    begleitdatei.schreiben(pfad, sitzung.begleit_inhalt(), begleitdatei.fingerabdruck(pfad))
    sitzung.schliessen()
    Image.fromarray(np.full((300, 600, 3), 90, np.uint8)).save(pfad)     # das Bild ist neu
    vorher = {n: (tmp_path / n).read_bytes() for n in os.listdir(tmp_path)}

    bild = bildvergleich.laden(pfad, kante=120)
    assert bild.bearbeitet and bild.veraltet
    assert {n: (tmp_path / n).read_bytes() for n in os.listdir(tmp_path)} == vorher


def test_laden_kaputte_datei_meldet_den_grund(gpu, tmp_path):
    pfad = tmp_path / "kaputt.jpg"
    pfad.write_bytes(b"kein Bild")
    bild = bildvergleich.laden(str(pfad))
    assert bild.fehler
    assert bild.voll is None and bild.vorschau is None and bild.form is None


def test_laden_ohne_grafikspeicher_nimmt_die_vorschau(gpu, tmp_path, monkeypatch):
    from PIL import Image

    from silberkorn.bearbeitung import Sitzung
    pfad = str(tmp_path / "gross.png")
    Image.fromarray(np.full((300, 600, 3), 100, np.uint8)).save(pfad)

    def voll(*_a, **_k):
        raise gpu.cuda.memory.OutOfMemoryError(2**34, 2**33, 0)

    monkeypatch.setattr(Sitzung, "druckbild", voll)
    bild = bildvergleich.laden(pfad, kante=120)
    assert not bild.fehler
    assert bild.verkleinert
    assert bild.voll is bild.vorschau and bild.form == (60, 120)


def test_nichts_im_modul_braucht_qt_beim_import():
    """Wie drucken.py: Qt und Grafikkarte erst in den Funktionen."""
    quelle = open(bildvergleich.__file__, encoding="utf-8").read()
    kopf = quelle.split("\ndef ", 1)[0].split("\nclass ", 1)[0]
    assert "PySide6" not in kopf and "cupy" not in kopf and "from .cuda" not in kopf
