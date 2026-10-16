"""Scan & Film: Staub und Kratzer ueber den Infrarotkanal - nur mit Grafikkarte."""

from __future__ import annotations

import numpy as np
import pytest

cp = pytest.importorskip("cupy")


@pytest.fixture(autouse=True)
def grafikkarte():
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")


HOEHE, BREITE = 300, 450
FLECK = (slice(140, 165), slice(200, 230))     # eine breite Stelle, etwa eine Fussel


def verlauf_bild():
    """Ein glatter Farbverlauf - so ist leicht zu pruefen, ob eine Fuellung passt."""
    y, x = np.mgrid[0:HOEHE, 0:BREITE]
    return (np.stack([x / BREITE, y / HOEHE, np.full(x.shape, 0.5)], -1) * 0.8 + 0.1
            ).astype(np.float32)


def mit_staub(seed=5):
    """Bild und Infrarot eines Filmscans: der Film gleichmaessig hell, Staub darin dunkel,
    im Bild schwarz."""
    zufall = np.random.default_rng(seed)
    bild = verlauf_bild()
    ir = np.full((HOEHE, BREITE), 0.85, dtype=np.float32)
    ir += zufall.normal(0, 0.008, ir.shape).astype(np.float32)
    punkte = []
    while len(punkte) < 40:
        y, x = int(zufall.integers(10, HOEHE - 10)), int(zufall.integers(10, BREITE - 10))
        if 120 <= y <= 185 and 180 <= x <= 250:
            continue                                   # nicht an die breite Stelle
        if any(abs(y - py) < 12 and abs(x - px) < 12 for py, px in punkte):
            continue                                   # Punkte nicht verschmelzen lassen
        punkte.append((y, x))
        ir[y - 1:y + 2, x - 1:x + 2] = 0.2
        bild[y - 1:y + 2, x - 1:x + 2] = 0.0
    ir[FLECK] = 0.1
    bild[FLECK] = 0.0
    return bild, np.clip(ir, 0, 1), punkte


def test_film_infrarot_wird_erkannt_landschaft_nicht():
    from silberkorn import staub
    _bild, ir, _punkte = mit_staub()
    assert staub.ist_filmscan(cp.asarray(ir))
    # Ein Luftbild im Nah-Infrarot: Felder, Wald und Wasser - grosse helle und dunkle Flaechen
    zufall = np.random.default_rng(1)
    flecken = zufall.random((15, 23)).astype(np.float32)
    landschaft = np.kron(flecken, np.ones((20, 20), dtype=np.float32))[:HOEHE, :BREITE]
    assert not staub.ist_filmscan(cp.asarray(landschaft))


def test_finden_und_empfindlichkeit():
    from silberkorn import staub
    _bild, ir, punkte = mit_staub()
    ir[49:52, 49:52] = 0.85 * 0.85                     # nur schwach dunkler: feiner Staub
    dunkel = staub.dunkelheit(cp.asarray(ir))
    maske, _kern, anzahl = staub.finden(dunkel, staub.EMPFINDLICHKEIT)
    assert anzahl == len(punkte) + 1
    maske = cp.asnumpy(maske)
    assert all(maske[y, x] for y, x in punkte) and maske[FLECK].all()
    assert maske.mean() < 0.05
    _maske, _kern, mehr = staub.finden(dunkel, 100)
    assert mehr == anzahl + 1


def test_glatt_gefuellt_passt_zur_umgebung():
    from silberkorn import staub
    bild, ir, _punkte = mit_staub()
    maske, _kern, _anzahl = staub.finden(staub.dunkelheit(cp.asarray(ir)),
                                         staub.EMPFINDLICHKEIT)
    gefuellt = cp.asnumpy(staub.glatt_fuellen(cp.asarray(bild), maske))
    assert np.abs(gefuellt - verlauf_bild()).max() < 0.03
    maske = cp.asnumpy(maske)
    assert np.array_equal(gefuellt[~maske], bild[~maske])     # sonst bleibt alles


def test_breite_stellen_gehen_an_die_ki():
    from silberkorn import staub
    _bild, ir, _punkte = mit_staub()
    maske, kern, _anzahl = staub.finden(staub.dunkelheit(cp.asarray(ir)),
                                        staub.EMPFINDLICHKEIT)
    stellen, nummern = staub.breite_stellen(maske, kern)
    assert len(nummern) == 1
    assert int(stellen[150, 210]) == nummern[0]


class Rot:
    """Statt LaMa: fuellt jede Stelle rot - leicht zu erkennen."""

    def __init__(self):
        self.aufrufe = 0

    def fuellen(self, srgb, maske):
        self.aufrufe += 1
        markiert = maske > 0.5
        zeilen = cp.flatnonzero(markiert.any(axis=1))
        spalten = cp.flatnonzero(markiert.any(axis=0))
        y0, y1 = int(zeilen[0]), int(zeilen[-1]) + 1
        x0, x1 = int(spalten[0]), int(spalten[-1]) + 1
        fuellung = cp.zeros((y1 - y0, x1 - x0, 3), dtype=cp.float32)
        fuellung[..., 0] = 1.0
        return y0, y1, x0, x1, fuellung, markiert[y0:y1, x0:x1].astype(cp.float32)


@pytest.fixture
def sitzung():
    from silberkorn import bilddatei, filter
    from silberkorn.bearbeitung import Sitzung
    bild, ir, _punkte = mit_staub()
    daten = bilddatei.Bilddaten(pixel=filter.nach_16bit(bild), profil=None, alpha=None,
                                exif=b"", pfad="scan.tif",
                                infrarot=(ir * 65535 + 0.5).astype(np.uint16))
    s = Sitzung(daten, vorschau_kante=200)
    yield s
    s.schliessen()


def test_sitzung_entfernt_und_nimmt_zurueck(sitzung):
    assert sitzung.infrarot_film and not sitzung.staub_entfernt
    vorher, _ms, _h = sitzung.vorschau()
    assert sitzung.staub_finden(50) == 41
    sitzung.staub_entfernen(50)
    assert sitzung.staub_entfernt and sitzung.staub_gefuellt == 41 and sitzung.geaendert
    voll = cp.asnumpy(sitzung._film_bild(sitzung.werte, True))
    assert np.abs(voll - verlauf_bild()).max() < 0.03
    nachher, _ms, _h = sitzung.vorschau()
    assert nachher.min() > 20 and vorher.min() < 5
    ohne, _ms, _h = sitzung.vorschau(ohne_flicken=True)      # „Vorher“ zeigt den Staub
    assert np.array_equal(ohne, vorher)
    assert sitzung.staub_verwerfen() and not sitzung.staub_entfernt
    wieder, _ms, _h = sitzung.vorschau()
    assert np.array_equal(wieder, vorher)


def test_rueckgaengig_und_zuruecksetzen(sitzung):
    from silberkorn import verlauf
    v = verlauf.Verlauf(2**30)
    v.beginnen(sitzung.stand())
    sitzung.staub_entfernen(50)
    v.festhalten(sitzung.stand())
    sitzung.stand_setzen(v.zurueck())
    assert not sitzung.staub_entfernt and not sitzung.geaendert
    sitzung.stand_setzen(v.vor())
    assert sitzung.staub_entfernt
    assert sitzung.entfernungen_verwerfen() and not sitzung.staub_entfernt


def test_breite_stelle_fuellt_die_ki_im_positiv(sitzung):
    """LaMa sieht das Positiv eines Negativs; seine Fuellung kommt in den Werten des Scans
    zurueck - umgewandelt zeigt sie wieder, was LaMa gefuellt hat."""
    from silberkorn import film
    w = sitzung.werte
    w.film = "farbnegativ"
    w.film_maske, w.film_umfang = (0.5, 0.2, 0.1), (0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    rot = Rot()
    sitzung.staub_entfernen(50, rot)
    assert rot.aufrufe == 1
    positiv = cp.asnumpy(sitzung._film_bild(w, True))
    assert np.allclose(positiv[150, 210], (1.0, 0.0, 0.0), atol=1e-3)
    assert film.aktiv(w.film, w.film_maske, w.film_umfang)


def test_luftbild_bietet_keine_staubsuche():
    from silberkorn import bilddatei, filter
    from silberkorn.bearbeitung import Sitzung
    zufall = np.random.default_rng(2)
    flecken = zufall.random((15, 23)).astype(np.float32)
    landschaft = np.kron(flecken, np.ones((20, 20), dtype=np.float32))[:HOEHE, :BREITE]
    daten = bilddatei.Bilddaten(pixel=filter.nach_8bit(verlauf_bild()), profil=None,
                                alpha=None, exif=b"", pfad="luft.tif",
                                infrarot=(landschaft * 255).astype(np.uint8))
    s = Sitzung(daten, vorschau_kante=200)
    try:
        assert s.infrarot_da and not s.infrarot_film
    finally:
        s.schliessen()
