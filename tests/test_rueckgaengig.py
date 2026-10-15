"""Rueckgaengig in der Sitzung: Staende festhalten und wiederherstellen - nur mit Grafikkarte."""

from __future__ import annotations

import numpy as np
import pytest

from silberkorn import verlauf

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


class Unveraendert:
    """Statt SCUNet: gibt das Bild unveraendert zurueck."""
    beschleuniger = "Test"

    def rechnen(self, srgb, _kachel, _fortschritt):
        return srgb.copy()


@pytest.fixture
def sitzung():
    grafikkarte()
    from silberkorn import bilddatei
    from silberkorn.bearbeitung import Sitzung
    pixel = np.full((120, 160, 3), 64, dtype=np.uint8)
    daten = bilddatei.Bilddaten(pixel=pixel, profil=None, alpha=None, exif=b"", pfad="t.png")
    s = Sitzung(daten, vorschau_kante=80)
    yield s
    s.schliessen()


def voll(sitzung, **art):
    bild, _ms, _h = sitzung.ausschnitt(0, 0, *sitzung.ausgabe_form()[::-1], **art)
    return bild.astype(int)


def entfernen(sitzung, x=40.0, y=60.0):
    sitzung.pinseln([(x, y)], 10.0, True)
    sitzung.ki_entfernen(Weiss())


def test_werte_sind_eine_kopie(sitzung):
    stand = sitzung.stand()
    sitzung.werte.belichtung = 1.0
    assert stand.werte.belichtung == 0.0
    sitzung.stand_setzen(stand)
    assert sitzung.werte.belichtung == 0.0
    sitzung.werte.kontrast = 20.0
    assert stand.werte.kontrast == 0.0              # auch nach dem Setzen eine eigene Kopie


def test_entfernen_zuruecknehmen_und_wiederholen(sitzung):
    v = verlauf.Verlauf(budget=2**30)
    v.beginnen(sitzung.stand())
    entfernen(sitzung)
    assert v.festhalten(sitzung.stand())
    assert voll(sitzung)[60, 40].min() >= 254
    sitzung.stand_setzen(v.zurueck())
    assert sitzung.entfernt == 0 and np.abs(voll(sitzung) - 64).max() <= 1
    assert not sitzung.geaendert
    sitzung.stand_setzen(v.vor())
    assert sitzung.entfernt == 1 and voll(sitzung)[60, 40].min() >= 254
    assert sitzung.geaendert


def test_zuruecksetzen_laesst_sich_zuruecknehmen(sitzung):
    """„Zurücksetzen“ leert die Liste der Flicken - der festgehaltene Stand behaelt sie."""
    v = verlauf.Verlauf(budget=2**30)
    v.beginnen(sitzung.stand())
    entfernen(sitzung)
    sitzung.werte.belichtung = 1.0
    v.festhalten(sitzung.stand())
    sitzung.werte = sitzung.grundwerte()
    sitzung.entfernungen_verwerfen()
    v.festhalten(sitzung.stand())
    sitzung.stand_setzen(v.zurueck())
    assert sitzung.entfernt == 1 and sitzung.werte.belichtung == 1.0


def test_gespeichert_bleibt_eindeutig(sitzung, tmp_path):
    """Nach dem Zuruecknehmen und einer neuen Entfernung ist das Bild geaendert, auch wenn
    gleich viele Objekte entfernt sind wie beim Speichern."""
    v = verlauf.Verlauf(budget=2**30)
    v.beginnen(sitzung.stand())
    entfernen(sitzung, 40.0)
    v.festhalten(sitzung.stand())
    sitzung.exportieren(str(tmp_path / "aus.png"))
    assert not sitzung.geaendert
    sitzung.stand_setzen(v.zurueck())
    assert sitzung.geaendert
    entfernen(sitzung, 120.0)
    assert sitzung.entfernt == 1 and sitzung.geaendert


def test_flicken_veraendern_das_entrauschte_bild_nicht(sitzung):
    """Bei KI-Entrauschen auf 100 % ist das entrauschte Bild selbst das Ausgangsbild. Die
    Flicken landeten bei jeder Vorschau darin - „Vorher“ und Rueckgaengig zeigten das
    entfernte Objekt dann nicht mehr."""
    sitzung.ki_entrauschen(Unveraendert(), 64)
    sitzung.werte.ki_rauschen = 100.0
    vorher = sitzung.stand()
    entfernen(sitzung)
    sitzung.vorschau()
    voll(sitzung)
    assert np.abs(voll(sitzung, ohne_flicken=True) - 64).max() <= 1
    sitzung.stand_setzen(vorher)
    assert np.abs(voll(sitzung) - 64).max() <= 1


def test_neue_maske_beginnt_neue_klicks(sitzung):
    sitzung._ki_maske = (cp.ones((120, 160), cp.float32), cp.ones((60, 80), cp.float32))
    vorher = sitzung.stand()
    sitzung._klickstand["maske"].punkte.append((1.0, 2.0, True))
    sitzung._ki_maske = (cp.zeros((120, 160), cp.float32), cp.zeros((60, 80), cp.float32))
    sitzung.stand_setzen(vorher)
    assert sitzung.klicks == [] and sitzung.ki_maske_da
