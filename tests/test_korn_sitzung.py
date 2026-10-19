"""Filmkorn in der Sitzung: 100-%-Ansicht wie Export, nach dem KI-Hochskalieren - nur mit
Grafikkarte."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from silberkorn import korn

cp = pytest.importorskip("cupy")


def grafikkarte():
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")


class Naechster:
    """Statt Real-ESRGAN: vergroessert, indem jeder Pixel faktor x faktor mal wiederholt wird."""

    def hochskalieren(self, srgb, faktor, _kachel, bits=8, _fortschritt=None):
        hoechst, typ = (65535, np.uint16) if bits == 16 else (255, np.uint8)
        bild = cp.asnumpy((cp.clip(srgb, 0, 1) * hoechst + 0.5).astype(typ))
        return bild.repeat(faktor, axis=0).repeat(faktor, axis=1)


@pytest.fixture
def sitzung():
    grafikkarte()
    from silberkorn import bilddatei
    from silberkorn.bearbeitung import Sitzung
    pixel = np.full((120, 160, 3), 110, dtype=np.uint8)
    daten = bilddatei.Bilddaten(pixel=pixel, profil=None, alpha=None, exif=b"", pfad="t.png")
    s = Sitzung(daten, vorschau_kante=80)
    s.werte.korn = 80
    s.werte.korn_groesse = 100
    yield s
    s.schliessen()


def test_hundert_prozent_wie_gespeichert(sitzung, tmp_path):
    hoehe, breite = sitzung.ausgabe_form()
    ansicht, _ms, _h = sitzung.ausschnitt(0, 0, breite, hoehe)
    pfad = str(tmp_path / "korn.png")
    sitzung.exportieren(pfad)
    gespeichert = np.asarray(Image.open(pfad).convert("RGB"))
    assert np.array_equal(ansicht, gespeichert)
    assert ansicht.astype(int).std() > 1                       # das Korn ist da


def test_vorschau_hat_korn(sitzung):
    mit, _ms, _h = sitzung.vorschau()
    sitzung.werte.korn = 0
    ohne, _ms, _h = sitzung.vorschau()
    assert not np.array_equal(mit, ohne)
    assert ohne.astype(int).std() == 0


def test_korn_erst_nach_dem_hochskalieren(sitzung, tmp_path):
    pfad = str(tmp_path / "gross.png")
    sitzung.exportieren(pfad, ki_auftrag=(Naechster(), 2, 64))
    gross = np.asarray(Image.open(pfad).convert("RGB"))
    hoehe, breite = sitzung.ausgabe_form()
    assert gross.shape[:2] == (2 * hoehe, 2 * breite)
    # Erwartet: das glatte Bild vergroessert, darauf das Korn in der grossen Form
    sitzung.werte.korn = 0
    sitzung.exportieren(str(tmp_path / "glatt.png"), ki_auftrag=(Naechster(), 2, 64))
    glatt = np.asarray(Image.open(tmp_path / "glatt.png").convert("RGB"))
    sitzung.werte.korn = 80
    assert np.array_equal(gross, korn.auflegen(glatt, sitzung.werte))
    # Nicht vergroessertes Korn: Nachbarn in einem 2x2-Block unterscheiden sich
    assert (gross[0::2, 0::2] != gross[0::2, 1::2]).mean() > 0.3
