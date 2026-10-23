"""Automatik: Auto-Ton, Auto-Weißabgleich, Pipette und Auto-Begradigen (nur die
Rechenfunktionen)."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from silberkorn import automatik as a
from silberkorn import filter as f
from silberkorn import geometrie


def _cupy():
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    return cp


def szene(median: float, streuung: float, farbe=(1.0, 1.0, 1.0), n: int = 96):
    """Ein Bild aus weichen Wellen: Helligkeit (sRGB) um `median`, linear, mit Farbfaktoren."""
    rng = np.random.default_rng(7)
    y, x = np.mgrid[0:n, 0:n] / n
    feld = np.zeros((n, n))
    for _ in range(6):
        fx, fy, p = rng.uniform(1, 4, 2).tolist() + [rng.uniform(0, 6.3)]
        feld += np.sin(2 * math.pi * (fx * x + fy * y) + p)
    feld = (feld - feld.mean()) / feld.std()
    v = np.clip(median + streuung * feld, 0, 1).astype(np.float32)
    return (f.srgb_zu_linear(v)[..., None] * np.asarray(farbe, np.float32)).astype(np.float32)


def renderer(bild):
    """Die echte Filterkette (NumPy) mit den vier Werten - wie ein Render der Sitzung."""
    return lambda ton: f.nach_8bit(f.anwenden(bild, f.Einstellungen(**ton.felder())))


def wirkung(bild, ton):
    return a._messen(renderer(bild)(ton))


# --------------------------------------------------------------------------
# Weißabgleich
# --------------------------------------------------------------------------

def grauverlauf(n: int = 80):
    rng = np.random.default_rng(3)
    grau = f.srgb_zu_linear(rng.uniform(0.1, 0.9, (n, n, 1)).astype(np.float32))
    return grau * np.ones(3, np.float32)


@pytest.mark.parametrize("temperatur, toenung", [(30, 0), (-40, 10), (0, 25), (60, -20),
                                                 (-100, 0), (15, -35)])
def test_farbstich_wird_neutralisiert(temperatur, toenung):
    """Die Umkehrung passt zu filter.weissabgleich (Zahlen 0,35 und 0,25): Mit dem Ergebnis
    ist das Grau wieder grau, und die Werte liegen auf dem Raster der Regler."""
    stich = f.weissabgleich(grauverlauf(), temperatur, toenung)
    t, to = a.weissabgleich_auto(stich)
    assert (t, to) == (-temperatur, -toenung)
    korrigiert = f.weissabgleich(stich, t, to)
    assert np.abs(korrigiert[..., 0] - korrigiert[..., 2]).max() < 1e-5
    assert np.abs(korrigiert[..., 1] - korrigiert[..., 2]).max() < 1e-5


def test_neutrales_bild_bleibt_neutral():
    assert a.weissabgleich_auto(grauverlauf()) == (0.0, 0.0)


def test_begrenzt_auf_den_reglerbereich():
    """Ein sehr starker Stich laesst sich mit ±100 nicht ganz ausgleichen - kein Ueberlauf."""
    stark = grauverlauf() * np.asarray([2.5, 1.0, 0.25], np.float32)
    stark = np.clip(stark, 0, 0.9)
    t, to = a.weissabgleich_auto(stark)
    assert -100 <= t <= 100 and -100 <= to <= 100 and t == -100


def test_grosse_farbige_flaeche_zieht_nicht():
    """Wiese (60 %) und Grau mit warmem Stich: Gemessen wird das Neutrale."""
    rng = np.random.default_rng(1)
    bild = np.empty((100, 100, 3), np.float32)
    bild[:60] = (0.05, 0.35, 0.04)
    bild[60:] = (0.3, 0.3, 0.3)
    bild *= rng.uniform(0.95, 1.05, bild.shape[:2] + (1,)).astype(np.float32)
    stich = f.weissabgleich(bild, 30, 0)
    t, to = a.weissabgleich_auto(stich)
    assert abs(t + 30) <= 2 and abs(to) <= 3


def test_abgeschnittene_stellen_zaehlen_nicht():
    """Ein ausgebrannter Himmel und tiefes Schwarz verfaelschen den Stich nicht."""
    stich = f.weissabgleich(grauverlauf(), 25, 5)
    stich[:20] = 1.0                     # weiss, abgeschnitten
    stich[20:30] = 0.0
    assert a.weissabgleich_auto(stich) == (-25, -5)


def test_ist_unabhaengig_vom_zustand_und_stabil():
    """Zweimal dasselbe Ergebnis; nach der Korrektur gibt es nichts mehr zu tun."""
    stich = f.weissabgleich(grauverlauf(), -20, 12)
    erst = a.weissabgleich_auto(stich)
    assert a.weissabgleich_auto(stich) == erst
    assert a.weissabgleich_auto(f.weissabgleich(stich, *erst)) == (0.0, 0.0)


@pytest.mark.parametrize("bild", [
    np.zeros((40, 40, 3), np.float32),                                  # schwarz
    np.ones((40, 40, 3), np.float32),                                   # weiss
    np.full((40, 40, 3), (0.5, 0.0, 0.1), np.float32),                  # ein Kanal bei 0
    np.full((40, 40, 3), np.nan, np.float32),                           # nichts Endliches
    np.full((2, 2, 3), 0.3, np.float32),                                # winzig
    np.full((1, 1, 3), 0.3, np.float32),
], ids=["schwarz", "weiss", "kanal_null", "nan", "winzig", "ein_pixel"])
def test_wb_grenzfaelle_ohne_wert(bild):
    assert a.weissabgleich_auto(bild) is None


def test_einfarbiges_bild_gibt_endliche_werte():
    t, to = a.weissabgleich_auto(np.full((40, 40, 3), (0.5, 0.2, 0.1), np.float32))
    assert math.isfinite(t) and math.isfinite(to)
    assert -100 <= t <= 100 and -100 <= to <= 100
    assert a.weissabgleich_auto(np.full((40, 40, 3), 0.3, np.float32)) == (0.0, 0.0)


def test_pipette_macht_den_punkt_neutral():
    bild = f.weissabgleich(grauverlauf(), 35, -10)
    t, to = a.weissabgleich_punkt(bild, 30.4, 41.7)
    korrigiert = f.weissabgleich(bild, t, to)
    assert (t, to) == (-35, 10)
    assert np.abs(korrigiert[41, 30] - korrigiert[41, 30].mean()).max() < 1e-5


def test_pipette_mittelt_ueber_die_umgebung():
    """Ein einzelnes verrauschtes Pixel stoert nicht: 5 x 5 Pixel werden gemittelt."""
    bild = np.full((30, 30, 3), 0.4, np.float32)
    bild[15, 15] = (0.8, 0.2, 0.2)
    t, to = a.weissabgleich_punkt(bild, 15, 15)
    assert abs(t) < 15 and abs(to) < 15     # ein einzelnes Pixel gaebe weit mehr
    assert a.weissabgleich_punkt(bild, 5, 5) == (0.0, 0.0)


@pytest.mark.parametrize("farbe", [(0, 0, 0), (1, 1, 1), (0.6, 0.0, 0.2), (0.001, 0.001, 0.001)])
def test_pipette_auf_unbrauchbarer_stelle(farbe):
    bild = np.full((20, 20, 3), farbe, np.float32)
    assert a.weissabgleich_punkt(bild, 10, 10) is None


@pytest.mark.parametrize("x, y", [(-1, 5), (5, -1), (20, 5), (5, 20), (1e9, 1e9)])
def test_pipette_ausserhalb(x, y):
    assert a.weissabgleich_punkt(np.full((20, 20, 3), 0.3, np.float32), x, y) is None


def test_pipette_am_rand():
    bild = np.full((20, 20, 3), (0.4, 0.3, 0.2), np.float32)
    assert a.weissabgleich_punkt(bild, 0, 0) == a.weissabgleich_punkt(bild, 10, 10)
    assert a.weissabgleich_punkt(bild, 19.9, 19.9) is not None


def test_wb_numpy_und_cupy_gleich():
    cp = _cupy()
    stich = f.weissabgleich(grauverlauf(), -25, 15)
    stich[:30] *= np.asarray([1.0, 1.4, 1.0], np.float32)       # und etwas Farbe dazu
    assert a.weissabgleich_auto(cp.asarray(stich)) == a.weissabgleich_auto(stich)
    assert a.weissabgleich_punkt(cp.asarray(stich), 40, 60) == a.weissabgleich_punkt(stich, 40, 60)


# --------------------------------------------------------------------------
# Ton
# --------------------------------------------------------------------------

def test_ton_felder_sind_echte_regler():
    namen = {r.name: r for r in f.REGLER}
    for name in a.Ton().felder():
        assert name in namen and namen[name].gruppe == "licht"
        assert hasattr(f.Einstellungen(), name)
    assert set(a.Ton().felder()) == {"belichtung", "kontrast", "lichter", "tiefen"}


def auf_raster(ton):
    for name, wert in ton.felder().items():
        regler = f.REGLER_NACH_NAME[name]
        assert regler.minimum <= wert <= regler.maximum
        assert abs(wert / regler.schritt - round(wert / regler.schritt)) < 1e-6


def test_gut_belichtetes_bild_bleibt_fast_gleich():
    bild = szene(0.45, 0.2)
    ton = a.ton_automatisch(renderer(bild))
    assert ton == a.Ton()


def test_dunkles_bild_wird_heller():
    bild = szene(0.15, 0.08)
    ton = a.ton_automatisch(renderer(bild))
    auf_raster(ton)
    assert ton.belichtung > 1.0 and ton.tiefen > 0
    vorher, nachher = wirkung(bild, a.Ton()), wirkung(bild, ton)
    assert nachher.median > vorher.median + 0.1
    assert nachher.schwarz < vorher.schwarz


def test_helles_bild_wird_dunkler():
    bild = szene(0.8, 0.12)
    ton = a.ton_automatisch(renderer(bild))
    auf_raster(ton)
    assert ton.belichtung < -0.5
    vorher, nachher = wirkung(bild, a.Ton()), wirkung(bild, ton)
    assert nachher.median < vorher.median - 0.1
    assert nachher.weiss < vorher.weiss


def test_flaues_bild_bekommt_kontrast():
    bild = szene(0.5, 0.06)
    ton = a.ton_automatisch(renderer(bild))
    auf_raster(ton)
    assert ton.kontrast > 20 and abs(ton.belichtung) <= 0.2
    vorher, nachher = wirkung(bild, a.Ton()), wirkung(bild, ton)
    assert nachher.p95 - nachher.p5 > vorher.p95 - vorher.p5 + 0.03


def test_harter_kontrast_holt_lichter_und_tiefen_zurueck():
    bild = szene(0.45, 0.45)
    ton = a.ton_automatisch(renderer(bild))
    auf_raster(ton)
    assert ton.lichter < 0 and ton.tiefen > 0
    vorher, nachher = wirkung(bild, a.Ton()), wirkung(bild, ton)
    assert nachher.weiss < vorher.weiss and nachher.schwarz < vorher.schwarz


def test_aufhellen_schiebt_die_lichter_nicht_weit_ueber_das_weiss():
    """Dunkles Bild mit einer hellen Lampe: nur so viel Belichtung, wie die Lichter tragen."""
    bild = szene(0.15, 0.08)
    bild[:20, :20] = f.srgb_zu_linear(np.float32(0.95))        # 4 % der Flaeche
    ton = a.ton_automatisch(renderer(bild))
    assert ton.belichtung <= 1.0
    assert wirkung(bild, ton).weiss < 5


def test_ton_ist_stabil():
    """Immer von den vier Werten auf 0 aus: gleiches Bild, gleiches Ergebnis."""
    bild = szene(0.2, 0.2)
    erst = a.ton_automatisch(renderer(bild))
    assert a.ton_automatisch(renderer(bild)) == erst


def test_ton_ignoriert_die_jetzigen_werte_nicht_aber_misst_ohne_sie():
    """Der Aufrufer reicht jedes Mal nur ton an render - der Render der Sitzung setzt die
    vier Felder selbst. Hier: render bekommt als erstes Ton() (alles 0)."""
    gesehen = []

    def render(ton):
        gesehen.append(ton)
        return renderer(szene(0.2, 0.1))(ton)

    a.ton_automatisch(render)
    assert gesehen[0] == a.Ton() and len(gesehen) <= 4


@pytest.mark.parametrize("wert", [0, 255, 128])
def test_ton_grenzfaelle_einfarbig(wert):
    bild = np.full((32, 32, 3), wert, np.uint8)
    ton = a.ton_automatisch(lambda _ton: bild)
    auf_raster(ton)
    assert all(math.isfinite(v) for v in ton.felder().values())


def test_ton_winzig():
    bild = np.full((1, 1, 3), 40, np.uint8)
    auf_raster(a.ton_automatisch(lambda _ton: bild))
    auf_raster(a.ton_automatisch(lambda _ton: np.zeros((0, 0, 3), np.uint8)))


def test_ton_numpy_und_cupy_gleich():
    cp = _cupy()
    for median, streuung in ((0.15, 0.08), (0.8, 0.12), (0.45, 0.45)):
        bild = szene(median, streuung)
        render = renderer(bild)
        ton_cpu = a.ton_automatisch(render)
        ton_gpu = a.ton_automatisch(lambda ton, render=render: cp.asarray(render(ton)))
        assert dataclasses.astuple(ton_cpu) == dataclasses.astuple(ton_gpu)


# --------------------------------------------------------------------------
# Zahlen des Weißabgleichs gegen Referenz und Kernel
# --------------------------------------------------------------------------

def _stich_grau(temperatur, toenung):
    rng = np.random.default_rng(11)
    grau = f.srgb_zu_linear(rng.uniform(0.15, 0.5, (64, 64, 1)).astype(np.float32))
    return f.weissabgleich(grau * np.ones(3, np.float32), temperatur, toenung)


def _mittelwerte(bild):
    return tuple(float(w) for w in bild.reshape(-1, 3).mean(axis=0))


@pytest.mark.parametrize("temperatur, toenung", [(40, 0), (-30, 20), (0, -35), (25, 15)])
def test_wb_konstanten_gelten_in_referenz_und_kernel(temperatur, toenung):
    """WB_TEMPERATUR und WB_TOENUNG stimmen mit filter.weissabgleich überein - und, wenn eine
    Grafikkarte da ist, mit dem Kernel: Mit den berechneten Werten wird der Stich neutral."""
    stich = _stich_grau(temperatur, toenung)
    ergebnis = a.weissabgleich_aus_mittel(*_mittelwerte(stich))
    assert ergebnis == (-temperatur, -toenung)
    korrigiert = f.weissabgleich(stich, *ergebnis)
    assert np.abs(korrigiert[..., 0] - korrigiert[..., 2]).max() < 1e-5
    assert np.abs(korrigiert[..., 1] - korrigiert[..., 2]).max() < 1e-5
    # Die Zahlen selbst: so wirkt Temperatur 100 / Tönung 100 in der Referenz
    ein = f.weissabgleich(np.ones((1, 1, 3), np.float32), 100, 0)[0, 0]
    assert math.isclose(math.log(ein[0] / ein[2]) / 2, a.WB_TEMPERATUR, rel_tol=1e-4)
    ein = f.weissabgleich(np.ones((1, 1, 3), np.float32), 0, 100)[0, 0]
    assert math.isclose(math.log(ein[1] / math.sqrt(ein[0] * ein[2])), -a.WB_TOENUNG,
                        rel_tol=1e-4)
    try:
        cp = _cupy()
    except pytest.skip.Exception:
        return
    werte = f.Einstellungen(temperatur=ergebnis[0], toenung=ergebnis[1])
    ausgabe = cp.asnumpy(f.anwenden_ausgabe(cp.asarray(stich), werte)).astype(int)
    assert (ausgabe.max(axis=2) - ausgabe.min(axis=2)).max() <= 1


# --------------------------------------------------------------------------
# Randwerte des Tons
# --------------------------------------------------------------------------

def test_ton_rein_weiss_wird_nicht_heller():
    bild = np.full((32, 32, 3), 255, np.uint8)
    assert a.ton_automatisch(lambda _ton: bild).belichtung <= 0


def test_ton_rein_schwarz_hoechstens_zwei_lichtwerte():
    bild = np.zeros((32, 32, 3), np.uint8)
    assert a.ton_automatisch(lambda _ton: bild).belichtung <= 2


def test_ton_ausgebranntes_weiss_holt_lichter_zurueck():
    bild = szene(0.3, 0.1)
    bild[:, :29] = 1.0                                          # rund 30 % reines Weiß
    ton = a.ton_automatisch(renderer(bild))
    assert ton.lichter < 0
    assert wirkung(bild, ton).weiss < wirkung(bild, a.Ton()).weiss


# --------------------------------------------------------------------------
# Begradigen
# --------------------------------------------------------------------------

def gerade_szene(n_hoehe: int = 480, n_breite: int = 640, seed: int = 0):
    """Gerade Rechtecke verschiedener Helligkeit auf einem Grund - wie Fassaden und Fenster."""
    rng = np.random.default_rng(seed)
    bild = np.full((n_hoehe, n_breite, 3), 0.2, np.float32)
    for _ in range(25):
        y, x = rng.integers(0, n_hoehe - 80), rng.integers(0, n_breite - 80)
        h, b = rng.integers(30, 160), rng.integers(30, 160)
        bild[y:y + h, x:x + b] = rng.uniform(0.05, 0.9, 3)
    return bild


def schief(winkel: float, **geom):
    """Die gerade Szene, um `winkel` Grad gedreht (so wie begradigen=winkel sie drehen würde)."""
    return geometrie.anwenden(gerade_szene(), geometrie.Geometrie(begradigen=winkel, **geom))


@pytest.mark.parametrize("winkel", [-7.0, -2.0, 3.5, 12.0, 19.0])
def test_neigung_findet_den_gegenwinkel(winkel):
    """Begradigen=-winkel stellt das um `winkel` gedrehte Bild wieder gerade."""
    gemessen = a.neigung(schief(winkel))
    assert gemessen is not None
    assert gemessen == pytest.approx(-winkel, abs=0.4)
    schritt = f.REGLER_NACH_NAME["begradigen"].schritt
    assert gemessen / schritt == pytest.approx(round(gemessen / schritt), abs=1e-6)


def test_neigung_gerades_bild_ist_null():
    assert a.neigung(gerade_szene()) == pytest.approx(0.0, abs=0.2)


def test_neigung_ueber_dem_suchbereich_wird_nicht_erkannt():
    assert a.neigung(schief(30.0)) is None


def test_neigung_ohne_linien():
    assert a.neigung(np.full((300, 400, 3), 0.3, np.float32)) is None
    rauschen = np.random.default_rng(1).random((300, 400, 3), dtype=np.float32)
    assert a.neigung(rauschen) is None
    assert a.neigung(np.zeros((0, 0, 3), np.float32)) is None


def test_neigung_zu_kleines_bild():
    assert a.neigung(np.full((15, 400, 3), 0.5, np.float32)) is None
    assert a.neigung(np.full((400, 15, 3), 0.5, np.float32)) is None


def test_neigung_ungerade_masse_ueber_einer_megapixel():
    bild = geometrie.anwenden(gerade_szene(1001, 1333), geometrie.Geometrie(begradigen=-4.0))
    assert bild.shape[0] * bild.shape[1] > 1_000_000
    assert a.neigung(bild) == pytest.approx(4.0, abs=0.4)


def test_neigung_ist_stabil_und_unabhaengig_vom_zoom():
    bild = schief(-5.0)
    assert a.neigung(bild) == a.neigung(bild)
    gross = geometrie.anwenden(gerade_szene(960, 1280), geometrie.Geometrie(begradigen=-5.0))
    assert a.neigung(gross) == pytest.approx(a.neigung(bild), abs=0.3)


@pytest.mark.parametrize("spiegeln", [False, True])
@pytest.mark.parametrize("drehung90", [0, 1, 2, 3])
def test_begradigen_rundlauf_mit_geometrie(spiegeln, drehung90):
    """Mit dem Ergebnis (umgerechnet fürs Spiegeln) ist das Bild nach der echten Geometrie
    gerade - auch gespiegelt und um 90 Grad gedreht."""
    quelle = schief(7.0)
    winkel = a.neigung(quelle)
    regler = a.begradigen_fuer(winkel, spiegeln)
    ergebnis = geometrie.anwenden(quelle, geometrie.Geometrie(
        begradigen=regler, spiegeln=spiegeln, drehung90=drehung90))
    assert abs(a.neigung(ergebnis)) < 0.5
    # Ohne Umrechnung wäre das Spiegelbild doppelt so schief
    if spiegeln:
        falsch = geometrie.anwenden(quelle, geometrie.Geometrie(
            begradigen=winkel, spiegeln=True, drehung90=drehung90))
        assert abs(a.neigung(falsch)) > 10


def test_neigung_numpy_und_cupy_gleich():
    cp = _cupy()
    for winkel in (-7.0, 3.5, 0.0):
        bild = schief(winkel)
        assert a.neigung(cp.asarray(bild)) == pytest.approx(a.neigung(bild), abs=0.2)
    assert a.neigung(cp.full((300, 400, 3), 0.3, cp.float32)) is None
