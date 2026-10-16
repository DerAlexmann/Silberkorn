"""Scan & Film: Negative umwandeln - die Formeln mit NumPy, die Sitzung auf der Grafikkarte."""

from __future__ import annotations

import numpy as np
import pytest

from silberkorn import film
from silberkorn import filter as f

MASKE = (0.47, 0.17, 0.10)          # Durchlaessigkeit einer orangen Filmmaske
STEILHEIT = (0.55, 0.6, 0.7)         # jede Farbschicht des Films ist anders steil


def negativ_von(positiv, maske=MASKE, steilheit=STEILHEIT):
    """Ein kuenstliches Farbnegativ: Dichte waechst mit dem Logarithmus des Lichts, je Kanal
    verschieden steil, ueber der Dichte der Filmmaske."""
    dichte = np.maximum(np.log10(np.maximum(positiv, 1e-4)) + 3.0, 0) * np.asarray(steilheit)
    return (np.asarray(maske) * 10.0 ** -dichte).astype(np.float32)


def graukeil(hoehe=60, breite=200):
    """Grau von Schwarz bis Weiss, dazu eine farbige Flaeche. Das dunkelste Zehntel hat den
    Film nicht belichtet."""
    licht = np.logspace(-3.3, 0, breite, dtype=np.float32)
    bild = np.repeat(np.repeat(licht[None, :, None], hoehe, 0), 3, 2)
    bild[:10, :40] = (0.6, 0.2, 0.05)
    return bild


def mit_filmrand(negativ, rand=12):
    """Rundherum unbelichteter Film, aussen der schwarze Halter des Scanners und ein
    ueberstrahltes Perforationsloch."""
    hoehe, breite = negativ.shape[:2]
    bild = np.zeros((hoehe + 4 * rand, breite + 4 * rand, 3), dtype=np.float32)
    bild[rand:-rand, rand:-rand] = MASKE
    bild[2 * rand:-2 * rand, 2 * rand:-2 * rand] = negativ
    bild[rand:rand + 6, rand + 20:rand + 30] = 1.0
    return bild


def test_ohne_negativ_bleibt_das_bild():
    bild = graukeil()
    for art in ("", "dia"):
        assert film.umkehren(bild, art, MASKE, (0,) * 6) is bild
    assert film.umkehren(bild, "farbnegativ", (), ()) is bild
    assert not film.aktiv("farbnegativ", MASKE, ())
    assert film.schaetzen(bild, "dia") == ((), ())


def test_maske_aus_den_hellsten_stellen():
    """Ohne Filmrand sind die tiefsten Schatten des Motivs fast so hell wie die Maske."""
    maske = film.maske_schaetzen(negativ_von(graukeil()))
    assert np.allclose(maske, MASKE, rtol=0.02)


def test_maske_aus_dem_filmrand_ohne_loch_und_halter():
    maske = film.maske_schaetzen(mit_filmrand(negativ_von(graukeil())))
    assert np.allclose(maske, MASKE, rtol=1e-4)


def test_grau_bleibt_grau():
    """Unterschiedlich steile Farbschichten und die Maske hinterlassen keinen Farbstich -
    von den Tiefen bis zu den Lichtern."""
    positiv = graukeil()
    negativ = negativ_von(positiv)
    maske, umfang = film.schaetzen(negativ, "farbnegativ")
    ergebnis = film.umkehren(negativ.copy(), "farbnegativ", maske, umfang)
    grau = ergebnis[30, 20:]
    assert (np.ptp(grau, axis=-1) <= 0.01 * np.maximum(grau.max(axis=-1), 0.05)).all()
    hell = grau[:, 1]
    assert (np.diff(hell) >= -1e-6).all() and hell[-1] > 0.9 and hell[0] < 0.02
    # Ueber den Tiefen: ein Potenzgesetz des Originals, wie bei echtem Film
    innen = (hell > 0.1) & (hell < 0.95)
    nah = np.corrcoef(np.log(hell[innen]), np.log(positiv[30, 20:, 1][innen]))[0, 1]
    assert nah > 0.995
    rot, gruen, blau = ergebnis[5, 20]
    assert rot > gruen > blau                  # die farbige Flaeche bleibt orange


def test_filmrand_und_halter_verschieben_schwarz_und_weiss_nicht():
    """Der Filmrand setzt nicht den Schwarzpunkt, der Halter nicht den Weisspunkt."""
    gerahmt = mit_filmrand(negativ_von(graukeil()))
    ergebnis = film.umkehren(gerahmt.copy(), "farbnegativ", *film.schaetzen(gerahmt, "farbnegativ"))
    grau = ergebnis[54, 44:-24]
    assert (np.ptp(grau, axis=-1) <= 0.01 * np.maximum(grau.max(axis=-1), 0.05)).all()
    assert grau[:, 1].max() > 0.9 and grau[:, 1].min() < 0.02


def test_pipette_macht_den_film_zum_schwarzpunkt():
    gerahmt = mit_filmrand(negativ_von(graukeil()))
    maske = film.maske_messen(gerahmt, 15, 40)
    umfang = film.umfang_schaetzen(gerahmt, maske, schwarz_ist_maske=True)
    assert umfang[:3] == (0.0, 0.0, 0.0)
    ergebnis = film.umkehren(gerahmt.copy(), "farbnegativ", maske, umfang)
    assert np.abs(ergebnis[15, 40]).max() < 1e-4       # der Filmrand ist schwarz


def test_pipette_misst_den_filmrand():
    bild = mit_filmrand(negativ_von(graukeil()))
    assert np.allclose(film.maske_messen(bild, 15, 40), MASKE, rtol=1e-5)


def test_schwarzweiss_negativ_wird_grau():
    negativ = negativ_von(graukeil(), maske=(0.8, 0.78, 0.75), steilheit=(0.6,) * 3)
    maske, umfang = film.schaetzen(negativ, "sw_negativ")
    ergebnis = film.umkehren(negativ.copy(), "sw_negativ", maske, umfang)
    assert np.array_equal(ergebnis[..., 0], ergebnis[..., 2])


def test_einstellungen_mit_film_sind_nicht_neutral():
    assert not f.Einstellungen(film="dia").ist_neutral()
    assert f.Einstellungen(film="").ist_neutral()


# ----------------------------------------------------------------------
# Sitzung auf der Grafikkarte
# ----------------------------------------------------------------------

@pytest.fixture
def sitzung():
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    from silberkorn import bilddatei
    from silberkorn.bearbeitung import Sitzung
    pixel = f.nach_16bit(mit_filmrand(negativ_von(graukeil())))
    daten = bilddatei.Bilddaten(pixel=pixel, profil=None, alpha=None, exif=b"", pfad="n.tif")
    s = Sitzung(daten, vorschau_kante=150)
    yield s
    s.schliessen()


def test_sitzung_wandelt_vor_allen_reglern(sitzung):
    vorher, _ms, _h = sitzung.vorschau()
    sitzung.werte.film = "farbnegativ"
    sitzung.werte.film_maske, sitzung.werte.film_umfang = sitzung.film_schaetzen("farbnegativ")
    nachher, _ms, _h = sitzung.vorschau()
    unbearbeitet, _ms, _h = sitzung.vorschau(unbearbeitet=True)
    assert np.array_equal(unbearbeitet, vorher)            # „Vorher“ zeigt das Negativ
    zeile = nachher[nachher.shape[0] // 2].astype(int)
    innen = zeile[30:-30]
    assert np.abs(innen[:, 0] - innen[:, 2]).max() <= 3   # grau, nicht orange
    assert innen[-1, 1] > innen[0, 1] + 100                # und nicht mehr umgekehrt
    assert (np.diff(innen[:, 1]) >= -1).all()


def test_pipette_in_der_sitzung(sitzung):
    maske, umfang = sitzung.film_maske_messen(15, 40)
    assert np.allclose(maske, MASKE, rtol=0.01) and len(umfang) == 6


def test_ki_entrauschen_sieht_das_positiv(sitzung):
    import cupy as cp

    class Merken:
        beschleuniger = "Test"
        mittel = None

        def rechnen(self, srgb, kachel, fortschritt=None):
            Merken.mittel = cp.asnumpy(srgb.reshape(-1, 3).mean(axis=0))
            return srgb.copy()

    sitzung.werte.film = "farbnegativ"
    sitzung.werte.film_maske, sitzung.werte.film_umfang = sitzung.film_schaetzen("farbnegativ")
    sitzung.ki_entrauschen(Merken(), 64)
    rot, _gruen, blau = Merken.mittel
    assert abs(rot - blau) < 0.1                           # das Negativ waere orange
    sitzung.werte.ki_rauschen = 100
    mit, _ms, _h = sitzung.vorschau()
    sitzung.werte.ki_rauschen = 0
    ohne, _ms, _h = sitzung.vorschau()
    assert np.abs(mit.astype(int) - ohne.astype(int)).max() <= 1


@pytest.mark.parametrize("art", ["farbnegativ", "sw_negativ"])
def test_zurueck_kehrt_die_umwandlung_um(art):
    """Eine Fuellung, die am Positiv entsteht, kommt in den Werten des Scans zurueck."""
    negativ = negativ_von(graukeil())
    maske, umfang = film.schaetzen(negativ, art)
    positiv = film.umkehren(negativ.copy(), art, maske, umfang)
    wieder = film.umkehren(film.zurueck(positiv, art, maske, umfang), art, maske, umfang)
    assert np.allclose(wieder, positiv, atol=1e-4)
    assert film.zurueck(positiv, "", maske, umfang) is positiv
