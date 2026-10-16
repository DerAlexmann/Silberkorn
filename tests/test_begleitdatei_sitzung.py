"""Begleitdatei mit der Sitzung: eine Bearbeitung sichern und an einem frisch geoeffneten
Bild wiederherstellen - nur mit Grafikkarte."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from silberkorn import begleitdatei

cp = pytest.importorskip("cupy")


def grafikkarte():
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")


class Weiss:
    """Statt LaMa: fuellt alles Markierte weiss."""
    beschleuniger = "Test"

    def fuellen(self, srgb, maske):
        zeilen = cp.flatnonzero((maske > 0.5).any(axis=1))
        spalten = cp.flatnonzero((maske > 0.5).any(axis=0))
        y0, y1, x0, x1 = int(zeilen[0]), int(zeilen[-1]) + 1, int(spalten[0]), int(spalten[-1]) + 1
        return (y0, y1, x0, x1, cp.ones((y1 - y0, x1 - x0, 3), cp.float32),
                cp.ascontiguousarray(maske[y0:y1, x0:x1]))


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


class Rauschen:
    """Statt FLUX: erfindet Raender aus Rauschen."""

    def raender(self, srgb, gross_b, gross_h, x, y, seed, _fortschritt):
        rng = cp.random.default_rng(seed)
        return rng.random((gross_h, gross_b, 3), dtype=cp.float32)


@pytest.fixture
def bild(tmp_path):
    grafikkarte()
    rng = np.random.default_rng(3)
    pfad = tmp_path / "foto.png"
    Image.fromarray(rng.integers(0, 256, (120, 160, 3), dtype=np.uint8)).save(pfad)
    return str(pfad)


def _sitzung(pfad):
    from silberkorn import bilddatei
    from silberkorn.bearbeitung import Sitzung
    return Sitzung(bilddatei.laden(pfad), vorschau_kante=80)


def _voll(sitzung):
    bild, _ms, _h = sitzung.ausschnitt(0, 0, *sitzung.ausgabe_form()[::-1])
    return bild.astype(int)


def test_bearbeitung_kommt_wieder(bild):
    a = _sitzung(bild)
    assert not a.begleit_geaendert and not a.bearbeitet
    a.werte.belichtung = 0.7
    a.werte.hg_saettigung = -80.0
    a.ki_freistellen(Linke())
    a.ki_tiefe(Verlauf())
    a.werte.bokeh = 60.0
    a.pinseln([(40.0, 60.0)], 10.0, True)
    a.ki_entfernen(Weiss())
    a.ki_erweitern(Rauschen(), 2.0, seed=7)
    assert a.begleit_geaendert and a.bearbeitet
    vorschau = a.begleit_vorschau()
    klein = Image.open(io.BytesIO(vorschau))
    assert klein.format == "WEBP" and max(klein.size) <= 256
    begleitdatei.schreiben(bild, a.begleit_inhalt(vorschau), begleitdatei.fingerabdruck(bild))
    a.begleit_gesichert()
    assert not a.begleit_geaendert
    erwartet = _voll(a)
    a.schliessen()

    b = _sitzung(bild)
    hoehe, breite = b.original.shape[:2]
    inhalt = begleitdatei.lesen(bild, hoehe, breite, b.grundwerte())
    assert inhalt.passt and inhalt.verworfen == []
    b.begleit_anwenden(inhalt)
    assert not b.begleit_geaendert and not b.geaendert
    assert b.entfernt == 1 and b.erweitert and b.ki_maske_da and b.ki_tiefe_da
    ergebnis = _voll(b)
    assert ergebnis.shape == erwartet.shape
    assert np.abs(ergebnis - erwartet).max() <= 3
    b.schliessen()


def test_staub_kommt_wieder(bild):
    from silberkorn.bearbeitung import _Staub
    a = _sitzung(bild)
    stellen = cp.asarray([5, 500, 9000], dtype=cp.int64)
    werte = cp.ones((3, 3), dtype=cp.float32)
    sauber = a.original.copy()
    sauber.reshape(-1, 3)[stellen] = werte
    a._staub = _Staub(stellen, werte, a._vorschau_von(sauber).copy(), 3)
    a._flicken_stand = 99
    begleitdatei.schreiben(bild, a.begleit_inhalt(), begleitdatei.fingerabdruck(bild))
    erwartet = _voll(a)
    a.schliessen()

    b = _sitzung(bild)
    b.begleit_anwenden(begleitdatei.lesen(bild, *b.original.shape[:2]))
    assert b.staub_entfernt and b.staub_gefuellt == 3
    assert np.abs(_voll(b) - erwartet).max() <= 1
    b.schliessen()


def test_ki_staerke_ohne_ergebnis_wird_neu_gerechnet(bild):
    a = _sitzung(bild)
    a.werte.ki_rauschen = 60.0
    a.werte.ki_farbe = 30.0
    b = _sitzung(bild)
    b.begleit_anwenden(a.begleit_inhalt())
    assert b.werte.ki_rauschen == 60.0
    assert b.ki_neu_zu_rechnen() == ["ki_rauschen", "ki_farbe"]
    a.schliessen()
    b.schliessen()


def test_fremde_leinwand_wird_abgelehnt(bild):
    a = _sitzung(bild)
    a.ki_erweitern(Rauschen(), 2.0, seed=1)
    inhalt = a.begleit_inhalt()
    inhalt.erweiterung.x += 2                     # liegt nicht, wo Silberkorn sie plant
    b = _sitzung(bild)
    with pytest.raises(begleitdatei.BegleitFehler):
        b.begleit_anwenden(inhalt)
    assert not b.erweitert and not b.bearbeitet    # nichts uebernommen
    a.schliessen()
    b.schliessen()


def test_zurueckgesetzt_heisst_nichts_zu_sichern(bild):
    a = _sitzung(bild)
    a.werte.kontrast = 30.0
    assert a.bearbeitet
    a.werte = a.grundwerte()
    assert not a.bearbeitet
    a.schliessen()
