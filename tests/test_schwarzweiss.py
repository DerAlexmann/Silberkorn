"""Tests fuer Schwarzweiss mit Mischer und Teiltonung - Referenz und CUDA."""

from __future__ import annotations

import numpy as np
import pytest

from silberkorn import filter as f
from silberkorn import voreinstellungen, werteformat

N = len(f.FARBBEREICHE)


def gpu_vorhanden():
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    return cp


def farbe(rgb):
    return np.full((4, 4, 3), rgb, dtype=np.float32)


def hell(rgb):
    return float(f.nach_oklab(rgb)[0, 0, 0])


@pytest.fixture
def bild():
    zufall = np.random.default_rng(5)
    rgb = zufall.random((64, 80, 3), dtype=np.float32) * 0.9
    rgb[:8] = np.linspace(0, 1, 80, dtype=np.float32)[None, :, None]   # Grauverlauf
    return rgb


# ----------------------------------------------------------------------
# Schwarzweiss
# ----------------------------------------------------------------------

def test_aus_aendert_nichts(bild):
    assert f.schwarzweiss(bild, f.Einstellungen()) is bild
    assert f.teiltonung(bild, f.Einstellungen()) is bild


def test_ergebnis_ist_grau_mit_oklab_helligkeit(bild):
    grau = f.schwarzweiss(bild, f.Einstellungen(sw=True))
    assert np.allclose(grau[..., 0], grau[..., 1]) and np.allclose(grau[..., 1], grau[..., 2])
    assert np.allclose(np.cbrt(grau[..., 0]), f.nach_oklab(bild)[..., 0], atol=1e-5)


def test_grau_bleibt_beim_mischen_unveraendert():
    grau = np.linspace(0, 1, 50, dtype=np.float32)[:, None, None].repeat(3, axis=2)
    ergebnis = f.schwarzweiss(grau, f.Einstellungen(sw=True, sw_mischer=(100.0,) * N))
    assert np.allclose(ergebnis, grau, atol=1e-5)


def test_rotfilter_hellt_rot_auf_und_dunkelt_blau_ab():
    werte = f.Einstellungen(sw=True, sw_mischer=f.SW_FILTER["rot"])
    neutral = f.Einstellungen(sw=True)
    rot, blau = farbe((0.6, 0.05, 0.03)), farbe((0.03, 0.08, 0.6))
    assert f.schwarzweiss(rot, werte)[0, 0, 0] > f.schwarzweiss(rot, neutral)[0, 0, 0] * 1.2
    assert f.schwarzweiss(blau, werte)[0, 0, 0] < f.schwarzweiss(blau, neutral)[0, 0, 0] * 0.8


def test_mischer_wirkt_nur_auf_seinen_bereich():
    nur_gruen = tuple(50.0 if name == "gruen" else 0.0 for name in f.FARBBEREICHE)
    werte = f.Einstellungen(sw=True, sw_mischer=nur_gruen)
    neutral = f.Einstellungen(sw=True)
    gruen, rot = farbe((0.1, 0.5, 0.08)), farbe((0.6, 0.05, 0.03))
    assert f.schwarzweiss(gruen, werte)[0, 0, 0] > f.schwarzweiss(gruen, neutral)[0, 0, 0]
    assert np.allclose(f.schwarzweiss(rot, werte), f.schwarzweiss(rot, neutral), atol=1e-6)


def test_vorlagen_im_bereich():
    for werte in f.SW_FILTER.values():
        assert len(werte) == N and all(-100 <= w <= 100 for w in werte)
    for werte in f.TONUNG_VORLAGEN.values():
        assert len(werte) == len(f.TONUNG)
        for name, wert in zip(f.TONUNG, werte, strict=True):
            regler = f.REGLER_NACH_NAME[name]
            assert regler.minimum <= wert <= regler.maximum


# ----------------------------------------------------------------------
# Teiltonung
# ----------------------------------------------------------------------

def test_tonung_faerbt_grau_im_farbton_ein():
    grau = farbe((0.18, 0.18, 0.18))
    for winkel in (55.0, 250.0):
        werte = f.Einstellungen(ton_schatten_farbton=winkel, ton_schatten_saettigung=60,
                                ton_lichter_farbton=winkel, ton_lichter_saettigung=60)
        lab = f.nach_oklab(f.teiltonung(grau, werte))[0, 0]
        ergebnis = np.degrees(np.arctan2(lab[2], lab[1])) % 360
        assert abs(ergebnis - winkel) < 1.0
        assert np.hypot(lab[1], lab[2]) > 0.03


def test_tonung_haelt_helligkeit_und_laesst_weiss_und_schwarz():
    werte = f.Einstellungen(ton_schatten_farbton=55, ton_schatten_saettigung=80,
                            ton_lichter_farbton=240, ton_lichter_saettigung=80)
    mittel = farbe((0.2, 0.2, 0.2))
    assert abs(hell(f.teiltonung(mittel, werte)) - hell(mittel)) < 1e-4
    for rand in (0.0, 1.0):
        ton = f.teiltonung(farbe((rand, rand, rand)), werte)
        assert np.allclose(ton, rand, atol=1e-5)


def test_schatten_und_lichter_getrennt():
    werte = f.Einstellungen(ton_schatten_farbton=250, ton_schatten_saettigung=80,
                            ton_lichter_farbton=70, ton_lichter_saettigung=80)
    dunkel = f.teiltonung(farbe((0.03, 0.03, 0.03)), werte)[0, 0]
    licht = f.teiltonung(farbe((0.7, 0.7, 0.7)), werte)[0, 0]
    assert dunkel[2] > dunkel[0]           # Schatten blau
    assert licht[0] > licht[2]             # Lichter warm


def test_balance_verschiebt_die_grenze():
    mitte = farbe((0.12, 0.12, 0.12))      # OkLab-Helligkeit knapp unter 0,5

    def anteil_lichter(balance):
        werte = f.Einstellungen(ton_lichter_farbton=70, ton_lichter_saettigung=80,
                                ton_balance=balance)
        lab = f.nach_oklab(f.teiltonung(mitte, werte))[0, 0]
        return np.hypot(lab[1], lab[2])

    assert anteil_lichter(100) > anteil_lichter(0) > anteil_lichter(-100)


# ----------------------------------------------------------------------
# Einstellungen, Dateien, Voreinstellungen
# ----------------------------------------------------------------------

def test_neutral_und_farbton_allein_aendert_nichts():
    assert f.Einstellungen().ist_neutral()
    assert f.Einstellungen(ton_lichter_farbton=10, ton_schatten_farbton=300).ist_neutral()
    assert not f.Einstellungen(sw=True).ist_neutral()
    assert not f.Einstellungen(sw_mischer=f.SW_FILTER["gelb"]).ist_neutral()
    assert not f.Einstellungen(ton_schatten_saettigung=10).ist_neutral()


def test_werteformat_hin_und_zurueck():
    werte = f.Einstellungen(sw=True, sw_mischer=f.SW_FILTER["orange"],
                            ton_lichter_farbton=75, ton_lichter_saettigung=20,
                            ton_schatten_farbton=55, ton_schatten_saettigung=35,
                            ton_balance=-15)
    gelesen = werteformat.aus_dict(werteformat.als_dict(werte))
    assert gelesen.werte == werte and not gelesen.verworfen


@pytest.mark.parametrize("name, wert", [
    ("sw", 1), ("sw", "ja"), ("sw_mischer", [0.0] * 7), ("sw_mischer", [float("nan")] * 8),
    ("sw_mischer", "rot"), ("ton_balance", True),
])
def test_werteformat_verwirft_unpassendes(name, wert):
    gelesen = werteformat.aus_dict({name: wert})
    assert name in gelesen.verworfen
    assert getattr(gelesen.werte, name) == getattr(f.Einstellungen(), name)


def test_werteformat_begrenzt():
    gelesen = werteformat.aus_dict({"sw_mischer": [500.0] * 8, "ton_lichter_farbton": 999})
    assert gelesen.werte.sw_mischer == (100.0,) * 8
    assert gelesen.werte.ton_lichter_farbton == 360


def test_voreinstellung_nimmt_schwarzweiss_mit():
    assert "schwarzweiss" in voreinstellungen.VORGABE
    assert set(voreinstellungen.GRUPPEN["schwarzweiss"]) == {*f.SW_FELDER, *f.TONUNG}


# ----------------------------------------------------------------------
# GPU gegen Referenz
# ----------------------------------------------------------------------

@pytest.mark.parametrize("werte", [
    f.Einstellungen(sw=True),
    f.Einstellungen(sw=True, sw_mischer=(60, -40, 30, 100, -100, -60, 20, 80), saettigung=20),
    f.Einstellungen(ton_lichter_farbton=75, ton_lichter_saettigung=40,
                    ton_schatten_farbton=250, ton_schatten_saettigung=70, ton_balance=30),
    f.Einstellungen(sw=True, sw_mischer=f.SW_FILTER["rot"], ton_lichter_farbton=75,
                    ton_lichter_saettigung=20, ton_schatten_farbton=55,
                    ton_schatten_saettigung=35, hsl_luminanz=(20, 0, 0, -30, 0, 40, 0, 0)),
])
def test_cuda_wie_referenz(bild, werte):
    cp = gpu_vorhanden()
    referenz = f.anwenden_ausgabe(bild, werte, 0.5)
    gpu = cp.asnumpy(f.anwenden_ausgabe(cp.asarray(bild), werte, 0.5))
    assert np.abs(referenz.astype(int) - gpu.astype(int)).max() <= 1
