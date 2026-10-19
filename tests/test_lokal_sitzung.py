"""Lokale Anpassungen in der Sitzung: Geometrie, Ansicht, Export - nur mit Grafikkarte."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from silberkorn import lokal

cp = pytest.importorskip("cupy")


def grafikkarte():
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")


def oben_heller(belichtung=1.0):
    """Verlauf von oben (voll) bis zur Mitte (keine Wirkung)."""
    teil = lokal.Teil("verlauf", (0.5, 0.0, 0.5, 0.5))
    werte = tuple(belichtung if n == "belichtung" else 0.0 for n in lokal.NAMEN)
    return lokal.Maske("Himmel", (teil,), werte)


@pytest.fixture
def sitzung():
    grafikkarte()
    from silberkorn import bilddatei
    from silberkorn.bearbeitung import Sitzung
    pixel = np.full((120, 160, 3), 60, dtype=np.uint8)
    daten = bilddatei.Bilddaten(pixel=pixel, profil=None, alpha=None, exif=b"", pfad="t.png")
    s = Sitzung(daten, vorschau_kante=80)
    yield s
    s.schliessen()


def voll(sitzung):
    bild, _ms, _h = sitzung.ausschnitt(0, 0, *sitzung.ausgabe_form()[::-1])
    return bild.astype(int)


def test_maske_wirkt_oben(sitzung):
    sitzung.werte.masken = (oben_heller(),)
    bild = voll(sitzung)
    assert bild[0].mean() > bild[-1].mean() + 20
    assert np.all(bild[-50:] == 60)
    vorschau, _ms, _h = sitzung.vorschau()
    assert vorschau[0].mean() > vorschau[-1].mean() + 20


def test_maske_folgt_der_drehung(sitzung):
    sitzung.werte.masken = (oben_heller(),)
    sitzung.werte.drehung90 = 1                       # rechts herum: oben wird rechts
    bild = voll(sitzung)
    assert bild.shape[:2] == (160, 120)
    assert bild[:, -1].mean() > bild[:, 0].mean() + 20


def test_hundert_prozent_wie_gespeichert(sitzung, tmp_path):
    sitzung.werte.masken = (oben_heller(0.8),)
    sitzung.werte.begradigen = 7.0
    ansicht = voll(sitzung)
    pfad = str(tmp_path / "lokal.png")
    sitzung.exportieren(pfad)
    assert np.array_equal(ansicht, np.asarray(Image.open(pfad).convert("RGB")).astype(int))


def test_maske_zeigen_faerbt_ein(sitzung):
    m = oben_heller(0.0)                               # ohne Wirkung - zeigen geht trotzdem
    sitzung.werte.masken = (m,)
    sitzung.lokal_zeigen = 0
    bild = voll(sitzung)
    assert bild[0, :, 0].mean() > bild[0, :, 2].mean() + 40     # rot eingefaerbt
    assert np.all(bild[-50:] == 60)
    sitzung.lokal_zeigen = None
    assert np.all(voll(sitzung) == 60)


def test_aus_wirkt_nicht_und_speicher_raeumt_auf(sitzung):
    sitzung.werte.masken = (oben_heller(),)
    voll(sitzung)
    assert sitzung._lokal_raster
    sitzung.werte.masken = (lokal.Maske("Aus", oben_heller().teile, oben_heller().werte,
                                        an=False),)
    assert np.all(voll(sitzung) == 60)
    sitzung.werte.masken = ()
    voll(sitzung)
    sitzung.vorschau()
    assert not sitzung._lokal_raster
