"""KI- und Bereichsteile lokaler Masken in der Sitzung: Motiv, Objekt per Klick, Tiefe,
Helligkeit, Farbe - und die Begleitdatei. Nur mit Grafikkarte; Ersatz statt der Netze."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from silberkorn import begleitdatei, lokal

cp = pytest.importorskip("cupy")


def grafikkarte():
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")


class Linke:
    """Statt BiRefNet: die linke Haelfte ist das Motiv."""

    def maske(self, srgb):
        maske = cp.zeros(srgb.shape[:2], cp.float32)
        maske[:, : srgb.shape[1] // 2] = 1
        return maske


class Verlauf:
    """Statt Depth Anything: oben fern, unten nah."""

    def tiefe(self, srgb):
        return cp.tile(cp.linspace(0, 1, 30, dtype=cp.float32)[:, None], (1, 40))


class Kreise:
    """Statt SAM: jeder Klick dazu ist eine Scheibe mit Radius 15, jeder weg nimmt eine
    weg."""

    def bild_setzen(self, srgb):
        self.form = srgb.shape[:2]

    def roh(self, punkte, _vorige):
        return list(punkte)

    def maske(self, punkte):
        hoehe, breite = self.form
        y, x = cp.mgrid[:hoehe, :breite]
        maske = cp.zeros((hoehe, breite), cp.float32)
        for px, py, dazu in punkte:
            scheibe = ((x - px) ** 2 + (y - py) ** 2) <= 15 ** 2
            maske = cp.where(scheibe, 1.0 if dazu else 0.0, maske).astype(cp.float32)
        return maske


def heller(*teile):
    return lokal.Maske("Test", tuple(teile),
                       tuple(1.0 if n == "belichtung" else 0.0 for n in lokal.NAMEN))


@pytest.fixture
def bild(tmp_path):
    """Links rot, rechts blau, von oben nach unten heller."""
    grafikkarte()
    hoehe, breite = 120, 160
    hell = np.linspace(40, 220, hoehe)[:, None]
    pixel = np.zeros((hoehe, breite, 3), np.float64)
    pixel[:, : breite // 2] = np.stack([hell, hell * 0.2, hell * 0.2], -1)[:, :1]
    pixel[:, breite // 2:] = np.stack([hell * 0.2, hell * 0.3, hell], -1)[:, :1]
    pfad = tmp_path / "bild.png"
    Image.fromarray(pixel.astype(np.uint8)).save(pfad)
    return str(pfad)


def _sitzung(pfad):
    from silberkorn import bilddatei
    from silberkorn.bearbeitung import Sitzung
    return Sitzung(bilddatei.laden(pfad), vorschau_kante=80)


def _voll(sitzung):
    bild, _ms, _h = sitzung.ausschnitt(0, 0, *sitzung.ausgabe_form()[::-1])
    return bild.astype(int)


def test_motiv(bild):
    s = _sitzung(bild)
    s.werte.masken = (heller(lokal.Teil("motiv", ())),)
    ohne = _voll(s)
    assert s.lokal_ki_fehlt() == ["lokal_motiv"]
    assert "lokal_motiv" in s.ki_neu_zu_rechnen()
    s.lokal_motiv(Linke())
    assert s.lokal_ki_fehlt() == [] and s.lokal_ki_da(("motiv",))
    mit = _voll(s)
    assert (mit[:, :70] > ohne[:, :70]).all() and np.array_equal(mit[:, 90:], ohne[:, 90:])
    s.schliessen()


def test_tiefe_und_helligkeit(bild):
    s = _sitzung(bild)
    s.werte.masken = (heller(lokal.Teil("tiefe", (60.0, 100.0, 0.0))),)
    assert s.lokal_ki_fehlt() == ["lokal_tiefe"]
    s.ki_tiefe(Verlauf())
    ergebnis = _voll(s)
    grund = _voll(_sitzung(bild))
    assert np.array_equal(ergebnis[:40], grund[:40])        # fern: unberuehrt
    assert (ergebnis[-10:] > grund[-10:]).all()              # nah: heller
    # Gesaettigte Farben sind dunkel: das helle Rot unten hat sRGB-kodiert etwa 45 %
    s.werte.masken = (heller(lokal.Teil("helligkeit", (0.0, 20.0, 0.0))),)
    ergebnis = _voll(s)
    assert (ergebnis[:5] > grund[:5]).all()
    assert np.array_equal(ergebnis[-3:, :70], grund[-3:, :70])
    s.schliessen()


def test_farbe_und_pipette(bild):
    s = _sitzung(bild)
    farbton = s.farbton_an(120.0, 60.0)                      # rechts: blau
    assert farbton is not None and 230 < farbton < 290
    s.werte.masken = (heller(lokal.Teil("farbe", (farbton, 20.0, 0.0))),)
    ergebnis, grund = _voll(s), _voll(_sitzung(bild))
    assert np.array_equal(ergebnis[:, :70], grund[:, :70])
    assert (ergebnis[:, 90:, 2] >= grund[:, 90:, 2]).all()
    assert (ergebnis[60:, 90:, 2] > grund[60:, 90:, 2]).all()
    s.schliessen()


def test_objekt_per_klick(bild):
    s = _sitzung(bild)
    sam = Kreise()
    s.lokal_klicks_beginnen()
    s.ki_auswahl_beginnen(sam, "lokal")
    s.ki_klick(sam, 40.0, 60.0, True, "lokal")
    klicks = (40 / 160, 60 / 120, 1.0)
    s.lokal_objekt_merken(klicks)
    s.werte.masken = (heller(lokal.Teil("objekt", klicks)),)
    ergebnis, grund = _voll(s), _voll(_sitzung(bild))
    assert (ergebnis[60, 35:45] > grund[60, 35:45]).all()
    assert np.array_equal(ergebnis[:, 80:], grund[:, 80:])
    # Ein zweiter Klick ist ein neuer Stand; der alte bleibt fuer Rueckgaengig
    s.ki_klick(sam, 120.0, 60.0, True, "lokal")
    zwei = (*klicks, 120 / 160, 60 / 120, 1.0)
    s.lokal_objekt_merken(zwei)
    assert s.lokal_ki_da(("objekt", klicks)) and s.lokal_ki_da(("objekt", zwei))
    assert s.lokal_ki_fehlt() == []                          # ein Objekt rechnet keiner nach
    s.schliessen()


def test_begleitdatei_bringt_motiv_und_objekt_zurueck(bild):
    a = _sitzung(bild)
    a.lokal_motiv(Linke())
    sam = Kreise()
    a.lokal_klicks_beginnen()
    a.ki_auswahl_beginnen(sam, "lokal")
    a.ki_klick(sam, 120.0, 60.0, True, "lokal")
    klicks = (120 / 160, 60 / 120, 1.0)
    a.lokal_objekt_merken(klicks)
    a.werte.masken = (heller(lokal.Teil("motiv", ()), lokal.Teil("objekt", klicks)),)
    erwartet = _voll(a)
    inhalt = a.begleit_inhalt()
    assert [k for k, _m in inhalt.lokal_ki] == [("motiv",), ("objekt", klicks)]
    begleitdatei.schreiben(bild, inhalt, begleitdatei.fingerabdruck(bild))
    a.schliessen()

    b = _sitzung(bild)
    hoehe, breite = b.original.shape[:2]
    gelesen = begleitdatei.lesen(bild, hoehe, breite, b.grundwerte())
    assert gelesen.passt and not gelesen.verworfen
    b.begleit_anwenden(gelesen)
    assert b.lokal_ki_da(("motiv",)) and b.lokal_ki_da(("objekt", klicks))
    assert np.abs(_voll(b) - erwartet).max() <= 2
    b.schliessen()


@pytest.mark.parametrize("kopf", [
    [{"art": "pinsel"}], [{"art": "motiv", "pfad": "C:/x"}], [{"art": "objekt"}],
    [{"art": "objekt", "klicks": [0.1, 0.2]}], "motiv", [{"art": "motiv"}] * 21,
])
def test_begleitdatei_verwirft_falsche_eintraege(bild, kopf):
    import json
    import zipfile
    a = _sitzung(bild)
    a.lokal_motiv(Linke())
    a.werte.masken = (heller(lokal.Teil("motiv", ())),)
    begleitdatei.schreiben(bild, a.begleit_inhalt(), begleitdatei.fingerabdruck(bild))
    hoehe, breite = a.original.shape[:2]
    a.schliessen()
    pfad = begleitdatei.pfad_fuer(bild)
    with zipfile.ZipFile(pfad) as archiv:
        teile = {name: archiv.read(name) for name in archiv.namelist()}
    daten = json.loads(teile[begleitdatei.JSON_NAME])
    daten["lokal_ki"] = kopf
    teile[begleitdatei.JSON_NAME] = json.dumps(daten).encode()
    with zipfile.ZipFile(pfad, "w") as archiv:
        for name, inhalt in teile.items():
            archiv.writestr(name, inhalt)
    with pytest.raises(begleitdatei.BegleitFehler):
        begleitdatei.lesen(bild, hoehe, breite)
