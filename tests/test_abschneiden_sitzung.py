"""Histogramm und Abschneide-Warnung in der Sitzung: nur Anzeige, nie im gespeicherten
Bild - nur mit Grafikkarte."""

from __future__ import annotations

import inspect

import numpy as np
import pytest
from PIL import Image

from silberkorn import lokal

cp = pytest.importorskip("cupy")

BEIDE = (True, True)


def grafikkarte():
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")


def sitzung_von(pixel):
    grafikkarte()
    from silberkorn import bilddatei
    from silberkorn.bearbeitung import Sitzung
    daten = bilddatei.Bilddaten(pixel=pixel, profil=None, alpha=None, exif=b"", pfad="t.png")
    return Sitzung(daten, vorschau_kante=80)


@pytest.fixture
def sitzung():
    """Oben links Lichter (Rot 255), unten rechts Tiefen (Blau 0), sonst Grau 100."""
    pixel = np.full((120, 160, 3), 100, dtype=np.uint8)
    pixel[:60, :80] = (255, 100, 100)
    pixel[60:, 80:] = (100, 100, 0)
    s = sitzung_von(pixel)
    yield s
    s.schliessen()


def voll(sitzung, **kwargs):
    hoehe, breite = sitzung.ausgabe_form()
    return sitzung.ausschnitt(0, 0, breite, hoehe, **kwargs)


def test_markierung_in_vorschau_und_ausschnitt(sitzung):
    for bild, lichter, tiefen, grau in (
            (sitzung.vorschau(abschneiden_zeigen=BEIDE)[0], (10, 10), (50, 70), (10, 70)),
            (voll(sitzung, abschneiden_zeigen=BEIDE)[0], (20, 20), (100, 140), (20, 140))):
        assert bild[lichter].tolist() == [255, 0, 0]
        assert bild[tiefen].tolist() == [0, 0, 255]
        # was nicht abgeschnitten ist, bleibt unmarkiert grau (Vorschau: kleine Rundung)
        assert np.abs(bild[grau].astype(int) - 100).max() <= 2


def test_ohne_wahl_keine_markierung(sitzung):
    klein = sitzung.vorschau()[0]
    gross = voll(sitzung)[0]
    assert klein[10, 10].tolist() != [255, 0, 0] and abs(int(klein[10, 10, 1]) - 100) <= 2
    assert gross[20, 20].tolist() == [255, 100, 100]
    assert gross[100, 140].tolist() == [100, 100, 0]


def test_lichter_und_tiefen_einzeln(sitzung):
    nur_lichter = voll(sitzung, abschneiden_zeigen=(True, False))[0]
    assert nur_lichter[20, 20].tolist() == [255, 0, 0]
    assert nur_lichter[100, 140].tolist() == [100, 100, 0]
    nur_tiefen = voll(sitzung, abschneiden_zeigen=(False, True))[0]
    assert nur_tiefen[20, 20].tolist() == [255, 100, 100]
    assert nur_tiefen[100, 140].tolist() == [0, 0, 255]


def test_zahlen_der_abgeschnittenen_pixel(sitzung):
    voll(sitzung)
    lichter, tiefen = sitzung.abgeschnitten
    assert lichter == 60 * 80 and tiefen == 60 * 80
    sitzung.vorschau()
    assert sitzung.abgeschnitten[0] > 0 and sitzung.abgeschnitten[1] > 0


def test_speichern_ohne_markierung(sitzung, tmp_path):
    voll(sitzung, abschneiden_zeigen=BEIDE)          # die Anzeige war markiert
    pfad = str(tmp_path / "aus.png")
    sitzung.exportieren(pfad)
    gespeichert = np.asarray(Image.open(pfad).convert("RGB"))
    assert gespeichert[20, 20].tolist() == [255, 100, 100]
    assert gespeichert[100, 140].tolist() == [100, 100, 0]
    # und das zwischengespeicherte Vollbild bleibt unmarkiert
    assert np.array_equal(voll(sitzung)[0], gespeichert)


def test_unbearbeitete_vorschau_ohne_wahl_unmarkiert(sitzung):
    bild = sitzung.vorschau(unbearbeitet=True)[0]
    assert bild[10, 10].tolist() != [255, 0, 0]


def test_vorher_haelfte_ist_nie_markiert(sitzung):
    sitzung.vorschau(abschneiden_zeigen=BEIDE)
    voll(sitzung, abschneiden_zeigen=BEIDE)
    vorher = sitzung.vorher_vorschau()
    assert vorher[10, 10].tolist() != [255, 0, 0] and vorher[50, 70].tolist() != [0, 0, 255]
    hoehe, breite = sitzung.ausgabe_form()
    ausschnitt = sitzung.vorher_ausschnitt(0, 0, breite, hoehe)
    assert ausschnitt[20, 20].tolist() == [255, 100, 100]
    assert ausschnitt[100, 140].tolist() == [100, 100, 0]


def test_umschalten_rechnet_das_vollbild_nicht_neu(sitzung, monkeypatch):
    aufrufe = []
    echt = sitzung._rendern

    def zaehlen(*args, **kwargs):
        aufrufe.append(1)
        return echt(*args, **kwargs)

    voll(sitzung)
    monkeypatch.setattr(sitzung, "_rendern", zaehlen)
    for wahl in ((True, False), BEIDE, (False, True), (False, False)):
        voll(sitzung, abschneiden_zeigen=wahl)
    assert aufrufe == []
    sitzung.werte.belichtung = 5.0                   # eine Aenderung rechnet dagegen neu
    voll(sitzung, abschneiden_zeigen=BEIDE)
    assert len(aufrufe) == 1


def test_histogramm_ist_das_des_ganzen_bildes(sitzung, monkeypatch):
    """In der 100-%-Ansicht zaehlt das Histogramm nicht nur den sichtbaren Teil, und
    Verschieben rechnet es nicht neu."""
    hoehe, breite = sitzung.ausgabe_form()
    _bild, _ms, ganz = sitzung.ausschnitt(0, 0, breite, hoehe)
    assert ganz.shape == (4, 256)
    assert (hoehe, breite) == (120, 160)
    stichprobe = np.full((120, 160, 3), 100, np.uint8)
    stichprobe[:60, :80] = (255, 100, 100)
    stichprobe[60:, 80:] = (100, 100, 0)
    from silberkorn import abschneiden
    erwartet = abschneiden.histogramme(stichprobe, abschneiden.schrittweite(120, 160))
    assert np.array_equal(ganz, erwartet)
    # ein kleiner Ausschnitt aus dem grauen Teil: dasselbe Histogramm
    aufrufe = []
    monkeypatch.setattr(abschneiden, "histogramme",
                        lambda *a, **k: aufrufe.append(1) or erwartet)
    for x0 in (0, 10, 40):
        _b, _ms, klein = sitzung.ausschnitt(x0, 70, 30, 20)
        assert np.array_equal(klein, ganz)
    assert aufrufe == []


def test_overlay_farben_zaehlen_nicht_als_abschneiden():
    """Die Farbe der Maskenansicht ersetzt hier eine abgeschnittene Tiefe (Gruen 0 wird
    32); gezaehlt und markiert wird das Bild darunter."""
    pixel = np.full((120, 160, 3), 100, dtype=np.uint8)
    pixel[:60] = (100, 0, 100)
    s = sitzung_von(pixel)
    try:
        s.werte.masken = (lokal.Maske("A", (lokal.Teil("verlauf", (0.5, 0.0, 0.5, 0.5)),),
                                      tuple(0.0 for _ in lokal.NAMEN)),)
        ohne = voll(s)[0]
        assert s.abgeschnitten == (0, 60 * 160)
        s.lokal_zeigen = 0
        mit = voll(s, abschneiden_zeigen=BEIDE)[0]
        assert s.abgeschnitten == (0, 60 * 160)           # wie ohne Maskenansicht
        assert mit[0, 80].tolist() == [0, 0, 255]         # markiert, nicht die Overlayfarbe
        assert ohne[0, 80].tolist() == [100, 0, 100]
        assert mit[100, 80].tolist() == [100, 100, 100]
        # die Vorschau ebenso
        s.vorschau()
        assert s.abgeschnitten[1] > 0
    finally:
        s.schliessen()


def test_rendern_gibt_das_bild_vor_dem_overlay_heraus():
    pixel = np.full((120, 160, 3), 100, dtype=np.uint8)
    s = sitzung_von(pixel)
    try:
        s.werte.masken = (lokal.Maske("A", (lokal.Teil("verlauf", (0.5, 0.0, 0.5, 0.5)),),
                                      tuple(0.0 for _ in lokal.NAMEN)),)
        klar: dict = {}
        s._rendern(s.werte, False, s._speicher, zeigen=True, klar=klar)
        assert "bild" not in klar                         # kein Overlay, nichts zu retten
        s.lokal_zeigen = 0
        s._rendern(s.werte, False, s._speicher, zeigen=True, klar=klar)
        assert "bild" in klar
        assert cp.asnumpy(klar["bild"]).max() <= 101      # grau, ohne Overlayfarbe
    finally:
        s.schliessen()


# ---------------------------------------------------------------------------
# Alles, was ausgibt, bleibt ohne Markierung
# ---------------------------------------------------------------------------

def test_ausgabewege_kennen_keine_markierung():
    """Waechter: Speichern, Drucken, Veroeffentlichen und das Rendern selbst bieten die
    Markierung gar nicht erst an - sie gibt es nur in vorschau() und ausschnitt()."""
    from silberkorn.bearbeitung import Sitzung
    for name in ("exportieren", "druckbild", "veroeffentlichen", "_rendern", "_ausgang",
                 "fotos_speichern"):
        assert "abschneiden_zeigen" not in inspect.signature(getattr(Sitzung, name)).parameters
    for name in ("vorschau", "ausschnitt"):
        assert "abschneiden_zeigen" in inspect.signature(getattr(Sitzung, name)).parameters


def test_druckbild_ohne_markierung(sitzung):
    referenz = sitzung.druckbild()
    assert referenz[20, 20].tolist() == [255, 100, 100]
    sitzung.vorschau(abschneiden_zeigen=BEIDE)
    voll(sitzung, abschneiden_zeigen=BEIDE)
    assert np.array_equal(sitzung.druckbild(), referenz)


def test_veroeffentlichen_ohne_markierung(sitzung, tmp_path):
    from silberkorn.veroeffentlichen import Vorlage
    vorlage = Vorlage(kante=1920, format=".png", urheber="", copyright="")
    ohne = str(tmp_path / "ohne.png")
    sitzung.veroeffentlichen(ohne, vorlage)
    sitzung.vorschau(abschneiden_zeigen=BEIDE)
    voll(sitzung, abschneiden_zeigen=BEIDE)
    mit = str(tmp_path / "mit.png")
    sitzung.veroeffentlichen(mit, vorlage)
    erst = np.asarray(Image.open(ohne).convert("RGB"))
    danach = np.asarray(Image.open(mit).convert("RGB"))
    assert np.array_equal(erst, danach)
    # nicht nur gleich, sondern wirklich ohne Rot und Blau der Markierung
    assert np.abs(danach[20, 20].astype(int) - (255, 100, 100)).max() <= 2
    assert np.abs(danach[100, 140].astype(int) - (100, 100, 0)).max() <= 2


def test_exportieren_16_bit_und_stapelweg_ohne_markierung(sitzung, tmp_path):
    """Der Stapel ruft exportieren() der Sitzung auf, genau wie Speichern."""
    ohne = str(tmp_path / "ohne.png")
    sitzung.exportieren(ohne, bits=16)
    sitzung.vorschau(abschneiden_zeigen=BEIDE)
    voll(sitzung, abschneiden_zeigen=BEIDE)
    mit = str(tmp_path / "mit.png")
    sitzung.exportieren(mit, bits=16)
    assert np.array_equal(np.asarray(Image.open(ohne)), np.asarray(Image.open(mit)))
    bild = np.asarray(Image.open(mit))
    assert bild[20, 20, 1] > 0 and bild[100, 140, 0] > 0      # Gruen bzw. Rot nicht genullt


# ---------------------------------------------------------------------------
# Farben der Ansichten (Tiefe, Staub, Klick-Markierung, Maske) zaehlen nicht
# ---------------------------------------------------------------------------

def _tiefe(s):
    """Links Tiefe 1 (Ansicht weiss), rechts 0 (schwarz) - das Bild darunter ist grau."""
    hoehe, breite = s.original.shape[:2]
    tiefe = cp.zeros((hoehe // 4, breite // 4), dtype=cp.float32)
    tiefe[:, :breite // 8] = 1.0
    s._ki_tiefe = tiefe
    s.tiefe_zeigen = True


def _staub(s):
    maske = cp.zeros(s.original.shape[:2], dtype=cp.float32)
    maske[:, :80] = 1.0
    s._staub_fund = (0.5, maske, s._vorschau_von(maske), 1, None)
    s.staub_zeigen = True


def _klick(s):
    ebene = cp.zeros(s.original.shape[:2], dtype=cp.float32)
    ebene[:, :80] = 1.0
    s._entfern_klick = (ebene, s._vorschau_von(ebene))


def _maske(s):
    ebene = cp.zeros(s.original.shape[:2], dtype=cp.float32)      # alles Hintergrund
    s._ki_maske = (ebene, s._vorschau_von(ebene))
    s.maske_zeigen = True


@pytest.mark.parametrize("ansicht, grund, kanal", [
    (_tiefe, (100, 100, 100), None),
    (_staub, (100, 100, 254), 2),         # 0,45 * 254 + 0,55 * 255 ergibt gerundet 255
    (_klick, (100, 100, 254), 2),
    (_maske, (254, 100, 100), 0),         # 0,4 * 254 + 0,6 * 255 ergibt gerundet 255
])
def test_ansichtsfarben_zaehlen_nicht_und_werden_nicht_markiert(ansicht, grund, kanal):
    s = sitzung_von(np.full((120, 160, 3), grund, dtype=np.uint8))
    try:
        ansicht(s)
        ohne_wahl = voll(s)[0]
        assert s.abgeschnitten == (0, 0)                  # das Bild darunter: nichts am Anschlag
        mit = voll(s, abschneiden_zeigen=BEIDE)[0]
        assert s.abgeschnitten == (0, 0)
        assert np.array_equal(mit, ohne_wahl)             # nichts davon wurde eingefaerbt
        if kanal is None:                                 # Tiefenansicht: Weiss und Schwarz
            assert mit[60, 5].tolist() == [255, 255, 255]
            assert mit[60, 150].tolist() == [0, 0, 0]
        else:                                             # die Ansichtsfarbe selbst erreicht 255
            assert mit[60, 5, kanal] == 255
        vorschau = s.vorschau(abschneiden_zeigen=BEIDE)[0]
        assert s.abgeschnitten == (0, 0)
        assert np.array_equal(vorschau, s.vorschau()[0])
    finally:
        s.schliessen()
