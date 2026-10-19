"""Tests fuer das Filmkorn: gleich in jeder Groesse, in Streifen und auf der Grafikkarte."""

from __future__ import annotations

import numpy as np
import pytest

from silberkorn import filter as f
from silberkorn import korn, voreinstellungen, werteformat

MITTELGRAU = 118                      # sRGB-kodiert knapp unter der Mitte


def grau(hoehe=200, breite=300, wert=MITTELGRAU, typ=np.uint8):
    return np.full((hoehe, breite, 3), wert, dtype=typ)


def gpu_vorhanden():
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    return cp


def test_aus_aendert_nichts():
    bild = grau()
    assert korn.auflegen(bild, f.Einstellungen()) is bild


def test_staerke_wie_vorgesehen():
    werte = f.Einstellungen(korn=100, korn_groesse=100, korn_rauheit=0)
    # Lange Kante wie KORN_BEZUG: die Masche ist groesser als ein Pixel, nichts wird gemittelt
    feld = korn.feld(400, 600, werte, (korn.KORN_BEZUG, korn.KORN_BEZUG))
    assert abs(float(feld.std()) - 1) < 0.1 and abs(float(feld.mean())) < 0.1


def test_einfarbig_und_in_den_mitteltoenen():
    werte = f.Einstellungen(korn=80)
    form = (3000, 4000)                   # so gross, dass nichts gemittelt wird
    ergebnis = korn.auflegen(grau(), werte, form=form).astype(int)
    assert np.array_equal(ergebnis[..., 0], ergebnis[..., 1])
    assert np.array_equal(ergebnis[..., 1], ergebnis[..., 2])
    assert ergebnis.std() > 4
    for rein in (0, 255):
        assert np.array_equal(korn.auflegen(grau(wert=rein), werte, form=form), grau(wert=rein))
    dunkel = korn.auflegen(grau(wert=12), werte, form=form).astype(int)
    assert dunkel.std() < ergebnis.std()


def test_immer_dasselbe_korn():
    werte = f.Einstellungen(korn=50)
    assert np.array_equal(korn.auflegen(grau(), werte), korn.auflegen(grau(), werte))


def test_streifen_ergeben_das_ganze_bild(monkeypatch):
    """Die 100-%-Ansicht und das KI-Hochskalieren rechnen Ausschnitte - sie muessen genau
    zum ganzen Bild passen."""
    werte = f.Einstellungen(korn=70, korn_groesse=60, korn_rauheit=80)
    bild = grau(300, 220)
    ganz = korn.auflegen(bild, werte)
    teil = korn.auflegen(bild[130:250, 40:200], werte, form=(300, 220), y0=130, x0=40)
    assert np.array_equal(teil, ganz[130:250, 40:200])
    monkeypatch.setattr(korn, "STREIFEN", 7)
    assert np.array_equal(korn.auflegen(bild, werte), ganz)


def test_korn_waechst_mit_dem_bild():
    """Doppelt so grosses Bild: Das Korn ist doppelt so grob - verkleinert man es wieder,
    sieht es aus wie das kleine Bild."""
    werte = f.Einstellungen(korn=100, korn_groesse=100, korn_rauheit=0)
    klein = korn.feld(500, 500, werte, (4000, 4000))
    gross = korn.feld(1000, 1000, werte, (8000, 8000))

    def nachbar(feld):           # wie stark sich benachbarte Pixel unterscheiden
        return float(np.abs(np.diff(feld, axis=1)).mean() / feld.std())

    assert nachbar(gross) < 0.75 * nachbar(klein)
    gross_verkleinert = gross.reshape(500, 2, 500, 2).mean(axis=(1, 3))
    assert abs(nachbar(gross_verkleinert) - nachbar(klein)) < 0.1 * nachbar(klein)


def test_vorschau_zeigt_feines_korn_schwaecher():
    werte = f.Einstellungen(korn=100, korn_groesse=0, korn_rauheit=0)
    voll = korn.feld(300, 300, werte, (4000, 4000))
    vorschau = korn.feld(300, 300, werte, (1000, 1000))     # Masche 0,25 Pixel
    assert 0.15 < float(vorschau.std() / voll.std()) < 0.4


def test_groesse_und_rauheit_veraendern_das_korn():
    def nachbar(**art):
        feld = korn.feld(400, 400, f.Einstellungen(korn=100, **art), (4000, 4000))
        return float(np.abs(np.diff(feld, axis=1)).mean() / feld.std())

    assert nachbar(korn_groesse=100, korn_rauheit=0) < nachbar(korn_groesse=0, korn_rauheit=0)


@pytest.mark.parametrize("lange_kante", [4000, 1500])
def test_rauheit_laesst_das_korn_klumpen(lange_kante):
    """Rauheit aendert nicht die Staerke, sondern wie gleichmaessig sie verteilt ist - auch
    in der verkleinerten Vorschau sichtbar."""
    def korn_von(rauheit):
        werte = f.Einstellungen(korn=100, korn_rauheit=rauheit)
        return korn.feld(640, 640, werte, (lange_kante, lange_kante))

    def fleckig(feld):          # wie sehr die Staerke von Block zu Block schwankt
        bloecke = feld.reshape(40, 16, 40, 16).std(axis=(1, 3))
        return float(bloecke.std() / bloecke.mean())

    glatt, mittel, rau = korn_von(0), korn_von(50), korn_von(100)
    assert fleckig(rau) > fleckig(mittel) > 2 * fleckig(glatt)
    assert abs(float(rau.std() / glatt.std()) - 1) < 0.1


@pytest.mark.parametrize("typ, hoechst", [(np.uint16, 65535), (np.float32, 255.0)])
def test_andere_typen(typ, hoechst):
    werte = f.Einstellungen(korn=60)
    acht = korn.auflegen(grau(), werte).astype(np.float64) / 255
    bild = (grau().astype(np.float64) / 255 * hoechst).astype(typ)
    anders = korn.auflegen(bild, werte, hoechst if typ == np.float32 else None)
    assert anders.dtype == typ
    assert np.abs(anders.astype(np.float64) / hoechst - acht).max() < 1.5 / 255


def test_einstellungen_dateien_voreinstellungen():
    assert f.Einstellungen(korn_groesse=80, korn_rauheit=10).ist_neutral() is False
    assert f.Einstellungen().ist_neutral()
    werte = f.Einstellungen(korn=40, korn_groesse=70, korn_rauheit=20)
    assert werteformat.aus_dict(werteformat.als_dict(werte)).werte == werte
    gelesen = werteformat.aus_dict({"korn": 1e9, "korn_groesse": "grob", "korn_rauheit": True})
    assert gelesen.werte.korn == 100
    assert set(gelesen.verworfen) == {"korn_groesse", "korn_rauheit"}
    assert "korn" in voreinstellungen.VORGABE


def test_cuda_wie_numpy():
    cp = gpu_vorhanden()
    werte = f.Einstellungen(korn=90, korn_groesse=40, korn_rauheit=70)
    bild = np.random.default_rng(3).integers(0, 256, (150, 210, 3), dtype=np.uint8)
    referenz = korn.auflegen(bild, werte)
    gpu = cp.asnumpy(korn.auflegen(cp.asarray(bild), werte))
    assert np.abs(referenz.astype(int) - gpu.astype(int)).max() <= 1
