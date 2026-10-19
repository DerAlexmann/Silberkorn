"""Tests fuer lokale Anpassungen: Masken rastern, wirken, lesen - Referenz und CUDA."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from silberkorn import filter as f
from silberkorn import lokal, voreinstellungen, werteformat

H, W = 60, 90


def gpu_vorhanden():
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    return cp


def verlauf(ax=0.0, ay=0.0, bx=0.0, by=1.0, **art):
    return lokal.Teil("verlauf", (ax, ay, bx, by), **art)


def radial(cx=0.5, cy=0.5, rx=0.2, ry=0.1, winkel=0.0, weich=50.0, **art):
    return lokal.Teil("radial", (cx, cy, rx, ry, winkel, weich), **art)


def maske(*teile, **werte):
    zahlen = tuple(float(werte.get(n, 0.0)) for n in lokal.NAMEN)
    return lokal.Maske("Test", tuple(teile), zahlen)


def gewicht(m, hoehe=H, breite=W):
    return lokal.gewicht(m, hoehe, breite, (H, W))


@pytest.fixture
def bild():
    zufall = np.random.default_rng(8)
    return zufall.random((H, W, 3), dtype=np.float32) * 0.8 + 0.05


# ----------------------------------------------------------------------
# Rastern
# ----------------------------------------------------------------------

def test_verlauf_von_voll_nach_null():
    g = gewicht(maske(verlauf(ay=0.0, by=1.0)))
    spalte = g[:, 10]
    assert spalte[0] > 0.99 and spalte[-1] < 0.01
    assert np.all(np.diff(spalte) <= 1e-6)                 # nimmt nach unten ab
    assert np.allclose(g, g[:, :1])                         # waagrecht gleich


def test_radial_innen_voll_aussen_null_und_gedreht():
    g = gewicht(maske(radial(rx=0.3, ry=0.1, weich=0)))
    assert g[H // 2, W // 2] == 1 and g[0, 0] == 0
    # Lange Achse waagrecht: 0,3 * 90 = 27 Pixel; senkrecht nur 9
    assert g[H // 2, W // 2 + 20] == 1 and g[H // 2 + 15, W // 2] == 0
    gedreht = gewicht(maske(radial(rx=0.3, ry=0.1, winkel=90, weich=0)))
    assert gedreht[H // 2 + 20, W // 2] == 1 and gedreht[H // 2, W // 2 + 20] == 0


def test_weicher_rand_laeuft_aus():
    g = gewicht(maske(radial(rx=0.3, ry=0.3, weich=80)))
    zeile = g[H // 2, W // 2:]
    assert zeile[0] == 1 and zeile[-1] == 0
    assert ((zeile > 0.05) & (zeile < 0.95)).sum() > 5


def test_umkehren_dazu_weg_schnitt():
    oben = verlauf(ay=0.0, by=0.5)
    kreis = radial(rx=0.15, ry=0.15, weich=0)
    g_oben, g_kreis = gewicht(maske(oben)), gewicht(maske(kreis))
    assert np.allclose(gewicht(maske(dataclasses.replace(oben, umkehren=True))), 1 - g_oben)
    assert np.allclose(gewicht(maske(oben, kreis)), np.maximum(g_oben, g_kreis))
    assert np.allclose(gewicht(maske(oben, dataclasses.replace(kreis, modus="weg"))),
                       g_oben * (1 - g_kreis))
    assert np.allclose(gewicht(maske(oben, dataclasses.replace(kreis, modus="schnitt"))),
                       g_oben * g_kreis)


def test_vorschau_zeigt_dasselbe_kleiner():
    m = maske(radial(cx=0.3, cy=0.6, rx=0.2, ry=0.1, winkel=30, weich=60))
    voll = gewicht(m, 120, 180)
    klein = lokal.gewicht(m, 60, 90, (120, 180))
    assert np.abs(voll.reshape(60, 2, 90, 2).mean(axis=(1, 3)) - klein).max() < 0.05


def test_versatz_auf_der_leinwand():
    """KI-Erweiterung: Das Original liegt versetzt auf einer groesseren Leinwand."""
    m = maske(radial(rx=0.15, ry=0.15, weich=0))
    ohne = gewicht(m)
    mit = lokal.gewicht(m, H + 20, W + 40, (H, W), versatz=(30, 5), faktor=(1.0, 1.0))
    assert np.array_equal(mit[5:5 + H, 30:30 + W], ohne)


# ----------------------------------------------------------------------
# Wirken
# ----------------------------------------------------------------------

def test_ohne_masken_unveraendert(bild):
    assert lokal.anwenden(bild, None) is bild
    assert np.array_equal(f.anwenden(bild, f.Einstellungen(), lokal=None), bild)


def test_volle_maske_wie_globaler_regler(bild):
    """Wirkt eine Maske ueberall voll, gleicht sie dem Regler fuer das ganze Bild."""
    voll = np.ones((H, W), dtype=np.float32)
    for name, wert in (("belichtung", 0.7), ("temperatur", 40), ("toenung", -30),
                       ("kontrast", 50), ("kontrast", -40), ("lichter", -60), ("tiefen", 70),
                       ("klarheit", 50), ("saettigung", -50), ("dunst", 40), ("dunst", -30),
                       ("schaerfe", 80)):
        m = maske(radial(), **{name: wert})
        lokal_ = lokal.anwenden(bild, [(voll, m.werte)])
        ganz = f.anwenden(bild, f.Einstellungen(**{name: wert}))
        assert np.abs(lokal_ - ganz).max() < 2e-3, name


def test_wirkt_nur_im_bereich(bild):
    g = gewicht(maske(verlauf(ay=0.0, by=0.3)))
    m = maske(verlauf(), belichtung=1.0)
    ergebnis = lokal.anwenden(bild, [(g, m.werte)])
    assert np.allclose(ergebnis[-10:], bild[-10:])
    assert np.allclose(ergebnis[:2], bild[:2] * 2, rtol=0.02)


def test_masken_addieren_sich(bild):
    voll = np.ones((H, W), dtype=np.float32)
    a, b = maske(radial(), belichtung=0.5), maske(radial(), belichtung=0.5)
    zwei = lokal.anwenden(bild, [(voll, a.werte), (voll, b.werte)])
    assert np.allclose(zwei, bild * 2, rtol=1e-4)


def test_negative_schaerfe_zeichnet_weich(bild):
    voll = np.ones((H, W), dtype=np.float32)
    weich = lokal.anwenden(bild, [(voll, maske(radial(), schaerfe=-100).werte)])
    assert np.abs(np.diff(weich, axis=1)).mean() < 0.5 * np.abs(np.diff(bild, axis=1)).mean()


# ----------------------------------------------------------------------
# Einstellungen, Datei, Voreinstellungen
# ----------------------------------------------------------------------

def test_neutral_und_wirkt():
    assert f.Einstellungen().ist_neutral()
    m = maske(radial(), belichtung=0.5)
    assert not f.Einstellungen(masken=(m,)).ist_neutral()
    assert m.wirkt()
    assert not maske(radial()).wirkt()
    assert not dataclasses.replace(m, an=False).wirkt()
    assert not dataclasses.replace(m, teile=()).wirkt()


def test_werteformat_hin_und_zurueck():
    masken = (maske(verlauf(0.1, 0.2, 0.3, 0.9), radial(winkel=-30, modus="weg",
                                                        umkehren=True), kontrast=20),
              dataclasses.replace(maske(radial(), belichtung=-1.25), name="Himmel", an=False))
    werte = f.Einstellungen(masken=masken)
    gelesen = werteformat.aus_dict(werteformat.als_dict(werte))
    assert gelesen.werte == werte and not gelesen.verworfen


def _roh(**aenderung):
    daten = {"name": "M", "an": True, "werte": [0.0] * len(lokal.NAMEN),
             "teile": [{"art": "radial", "modus": "dazu", "umkehren": False,
                        "daten": [0.5, 0.5, 0.2, 0.2, 0.0, 50.0]}]}
    daten.update(aenderung)
    return [daten]


@pytest.mark.parametrize("wert", [
    "maske", {"name": "M"}, [1, 2], _roh(werte=[0.0] * 9), _roh(werte=[float("nan")] * 10),
    _roh(an="ja"), _roh(name=5), _roh(teile="radial"), _roh(geheim=1),
    _roh(teile=[{"art": "pinsel", "daten": [], "striche": "malen"}]),
    _roh(teile=[{"art": "radial", "daten": [0.5] * 6, "striche": []}]),
    _roh(teile=[{"art": "radial", "modus": "oder", "daten": [0.5] * 6}]),
    _roh(teile=[{"art": "radial", "daten": [0.5] * 5}]),
    _roh(teile=[{"art": "radial", "daten": [0.5] * 5 + ["x"]}]),
    _roh(teile=[{"art": "radial", "daten": [0.5] * 6, "umkehren": 1}]),
    _roh(teile=[{"art": "verlauf", "daten": [0, 0, 1, 1], "pfad": "C:/x"}]),
    _roh() * (lokal.MAX_MASKEN + 1),
    _roh(teile=_roh()[0]["teile"] * (lokal.MAX_TEILE + 1)),
])
def test_werteformat_verwirft_unpassendes(wert):
    gelesen = werteformat.aus_dict({"masken": wert})
    assert "masken" in gelesen.verworfen and gelesen.werte.masken == ()


def test_werteformat_begrenzt_und_saeubert():
    roh = _roh(name="Him\nmel\x07" + "x" * 200, werte=[1e9] * 10)
    roh[0]["teile"][0]["daten"] = [9.0, -9.0, 0.0, 99.0, 999.0, -5.0]
    m = werteformat.aus_dict({"masken": roh}).werte.masken[0]
    assert m.name.startswith("Him mel") and len(m.name) <= lokal.MAX_NAME
    assert "\x07" not in m.name
    assert m.werte[lokal.NAMEN.index("belichtung")] == 4.0
    assert m.teile[0].daten == (2.0, -1.0, 0.002, 2.0, 180.0, 0.0)


def test_voreinstellung_gruppe_nicht_vorgewaehlt():
    assert voreinstellungen.GRUPPEN["lokal"] == ("masken",)
    assert "lokal" not in voreinstellungen.VORGABE


# ----------------------------------------------------------------------
# GPU
# ----------------------------------------------------------------------

def test_cuda_wie_referenz(bild):
    cp = gpu_vorhanden()
    m1 = maske(verlauf(ay=0.1, by=0.7), radial(cx=0.7, rx=0.15, ry=0.2, modus="weg"),
               belichtung=0.6, kontrast=30, klarheit=40, saettigung=-30, schaerfe=50,
               temperatur=25, dunst=20)
    m2 = maske(radial(cx=0.3, cy=0.4, rx=0.25, ry=0.15, winkel=20), tiefen=50, lichter=-40,
               schaerfe=-60, dunst=-20, toenung=15)
    werte = f.Einstellungen(kontrast=10, saettigung=10)
    karten = [(gewicht(m), m.werte) for m in (m1, m2)]
    referenz = f.anwenden_ausgabe(bild, werte, 1.0, lokal=karten)
    gpu_karten = [(cp.asarray(g), w) for g, w in karten]
    gpu = cp.asnumpy(f.anwenden_ausgabe(cp.asarray(bild), werte, 1.0, lokal=gpu_karten))
    assert np.abs(referenz.astype(int) - gpu.astype(int)).max() <= 1
    raster = cp.asnumpy(lokal.gewicht(m1, H, W, (H, W), xp=cp))
    assert np.abs(raster - karten[0][0]).max() < 1e-5


# ----------------------------------------------------------------------
# Bearbeiten auf der Leinwand
# ----------------------------------------------------------------------

def test_neuer_verlauf_und_klick():
    teil = lokal.neuer_teil("verlauf", (10, 20), (10, 50), 90, 60)
    assert teil.daten == pytest.approx((10 / 90, 20 / 60, 10 / 90, 50 / 60))
    assert lokal.neuer_teil("verlauf", (10, 20), (10.2, 20), 90, 60) is None


def test_neuer_radial_und_klick():
    teil = lokal.neuer_teil("radial", (45, 30), (63, 39), 90, 60)
    assert teil.daten[:4] == pytest.approx((0.5, 0.5, 18 / 90, 9 / 90))
    klick = lokal.neuer_teil("radial", (45, 30), (45, 30), 90, 60)
    assert klick.daten[2] == klick.daten[3] == lokal.RADIAL_KLICK


def test_griffe_ziehen_radial():
    teil = radial(cx=0.5, cy=0.5, rx=0.2, ry=0.1, winkel=0.0)
    g = lokal.griffe(teil, 90, 60)
    assert g["x+"] == pytest.approx((45 + 18, 30))
    breiter = lokal.gezogen(teil, "x+", g["x+"], (45 + 27, 30), 90, 60)
    assert breiter.daten[2] == pytest.approx(0.3)
    verschoben = lokal.gezogen(teil, "mitte", (45, 30), (54, 36), 90, 60)
    assert verschoben.daten[:2] == pytest.approx((0.6, 0.6))
    # Drehgriff nach rechts gezogen: die Ellipse dreht um 90 Grad
    gedreht = lokal.gezogen(teil, "dreh", g["dreh"], (80, 30), 90, 60)
    assert gedreht.daten[4] == pytest.approx(90.0)
    g = lokal.griffe(gedreht, 90, 60)
    assert g["x+"] == pytest.approx((45, 30 + 18))


def test_griffe_ziehen_verlauf_und_linien():
    teil = verlauf(0.1, 0.1, 0.1, 0.5)
    b_neu = lokal.gezogen(teil, "b", (9, 30), (18, 45), 90, 60)
    assert b_neu.daten == pytest.approx((0.1, 0.1, 0.2, 0.75))
    beide = lokal.gezogen(teil, "mitte", (9, 18), (18, 18), 90, 60)
    assert beide.daten == pytest.approx((0.2, 0.1, 0.2, 0.5))
    assert len(lokal.linien(teil, 90, 60)) == 4
    assert len(lokal.linien(radial(weich=50), 90, 60)) == 3


def test_gezogen_bleibt_im_bereich():
    teil = lokal.gezogen(radial(), "mitte", (0, 0), (10000, -10000), 90, 60)
    assert teil.daten[0] == 2.0 and teil.daten[1] == -1.0


# ----------------------------------------------------------------------
# Pinsel
# ----------------------------------------------------------------------

def strich(*punkte, radius=0.05, weich=0.0, deckkraft=100.0, radieren=False):
    return lokal.Strich(radius, weich, deckkraft, radieren, tuple(float(z) for z in punkte))


def pinsel(*striche, **art):
    return lokal.Teil("pinsel", (), striche=tuple(striche), **art)


def test_strich_deckt_seinen_weg():
    # waagrechter Strich auf halber Hoehe, Radius 0,05 * 90 = 4,5 Pixel
    g = gewicht(maske(pinsel(strich(0.2, 0.5, 0.8, 0.5))))
    assert g[30, 18:72].min() == 1.0
    assert g[30, :10].max() == 0.0 and g[30, 80:].max() == 0.0
    assert g[30 - 3, 45] == 1.0 and g[30 - 6, 45] == 0.0


def test_einzelner_punkt_ist_eine_scheibe():
    g = gewicht(maske(pinsel(strich(0.5, 0.5, radius=0.1))))
    assert g[30, 45] == 1.0 and g[30, 45 + 8] == 1.0 and g[30, 45 + 10] == 0.0


def test_radieren_und_deckkraft():
    malen = strich(0.1, 0.5, 0.9, 0.5)
    halb = gewicht(maske(pinsel(strich(0.1, 0.5, 0.9, 0.5, deckkraft=50))))
    assert halb[30, 45] == pytest.approx(0.5)
    zweimal = gewicht(maske(pinsel(strich(0.1, 0.5, 0.9, 0.5, deckkraft=50),
                                   strich(0.1, 0.5, 0.9, 0.5, deckkraft=50))))
    assert zweimal[30, 45] == pytest.approx(0.75)
    weg = gewicht(maske(pinsel(malen, strich(0.5, 0.2, 0.5, 0.8, radieren=True))))
    assert weg[30, 45] == 0.0 and weg[30, 20] == 1.0


def test_weicher_strich_laeuft_aus():
    g = gewicht(maske(pinsel(strich(0.1, 0.5, 0.9, 0.5, radius=0.1, weich=100))))
    spalte = g[:, 45]
    assert spalte[30] > 0.95 and spalte[30 - 12] == 0
    assert ((spalte > 0.05) & (spalte < 0.95)).sum() >= 6


def test_pinsel_speicher_rechnet_nur_den_letzten_strich(monkeypatch):
    erster, zweiter = strich(0.1, 0.2, 0.9, 0.2), strich(0.1, 0.7, 0.5, 0.7)
    speicher = {}
    m = maske(pinsel(erster, zweiter))
    ohne = gewicht(m)
    mit = lokal.gewicht(m, H, W, (H, W), pinsel_speicher=speicher)
    assert np.array_equal(ohne, mit) and len(speicher) == 1
    gerechnet = []
    echt = lokal._strich_gewicht
    monkeypatch.setattr(lokal, "_strich_gewicht",
                        lambda s, *a: gerechnet.append(s) or echt(s, *a))
    laenger = strich(0.1, 0.7, 0.5, 0.7, 0.8, 0.9)
    lokal.gewicht(maske(pinsel(erster, laenger)), H, W, (H, W), pinsel_speicher=speicher)
    assert gerechnet == [laenger]


def test_pinsel_umkehren_und_abziehen():
    kreis = radial(rx=0.3, ry=0.3, weich=0)
    strich_ = strich(0.0, 0.5, 1.0, 0.5)
    g = gewicht(maske(kreis, pinsel(strich_, modus="weg")))
    assert g[30, 45] == 0.0 and g[20, 45] == 1.0
    umgekehrt = gewicht(maske(pinsel(strich_, umkehren=True)))
    assert umgekehrt[30, 45] == 0.0 and umgekehrt[5, 45] == 1.0


def test_pinsel_hin_und_zurueck_und_nicht_uebertragbar():
    m = maske(radial(), pinsel(strich(0.1, 0.1, 0.2, 0.3, radieren=True, weich=30),
                               strich(0.5, 0.5)), belichtung=0.5)
    werte = f.Einstellungen(masken=(m, maske(pinsel(strich(0.3, 0.3)), kontrast=10)))
    gelesen = werteformat.aus_dict(werteformat.als_dict(werte))
    assert gelesen.werte == werte and not gelesen.verworfen
    uebrig = lokal.uebertragbar(werte.masken)
    assert len(uebrig) == 1 and [t.art for t in uebrig[0].teile] == ["radial"]
    auswahl = voreinstellungen.Auswahl(("lokal",))
    daten = voreinstellungen.als_dict(werte, auswahl)
    assert len(daten["werte"]["masken"]) == 1


def _pinsel_roh(**strich_):
    s = {"radius": 0.05, "weich": 0, "deckkraft": 100, "radieren": False,
         "punkte": [0.1, 0.1]}
    s.update(strich_)
    return _roh(teile=[{"art": "pinsel", "daten": [], "striche": [s]}])


@pytest.mark.parametrize("wert", [
    _pinsel_roh(punkte=[]), _pinsel_roh(punkte=[0.1, 0.2, 0.3]), _pinsel_roh(punkte="0.1"),
    _pinsel_roh(punkte=[0.1, float("inf")]), _pinsel_roh(radieren=0),
    _pinsel_roh(radius=None), _pinsel_roh(farbe="rot"),
    _pinsel_roh(punkte=[0.5] * (2 * lokal.MAX_PUNKTE + 2)),
])
def test_pinsel_verwirft_unpassendes(wert):
    gelesen = werteformat.aus_dict({"masken": wert})
    assert "masken" in gelesen.verworfen


def test_pinsel_zu_viele_punkte_insgesamt():
    roh = _pinsel_roh(punkte=[0.5] * (lokal.MAX_PUNKTE + 2))
    roh[0]["teile"][0]["striche"] *= 2
    assert "masken" in werteformat.aus_dict({"masken": roh}).verworfen


def test_pinsel_cuda_wie_numpy():
    cp = gpu_vorhanden()
    m = maske(pinsel(strich(0.1, 0.2, 0.4, 0.8, 0.9, 0.3, radius=0.08, weich=60),
                     strich(0.5, 0.1, 0.5, 0.9, radius=0.03, radieren=True, deckkraft=70),
                     strich(0.7, 0.7)))
    referenz = gewicht(m)
    gpu = cp.asnumpy(lokal.gewicht(m, H, W, (H, W), xp=cp))
    assert np.abs(referenz - gpu).max() < 1e-4


# ----------------------------------------------------------------------
# KI- und Bereichsteile
# ----------------------------------------------------------------------

def test_bereich_mit_weichem_uebergang_und_offenen_raendern():
    werte = np.linspace(0, 100, 101, dtype=np.float32)
    mitte = lokal._bereich(werte, 40, 60, 10)
    assert mitte[50] == 1 and mitte[29] == 0 and mitte[71] == 0
    assert 0 < mitte[35] < 1 and 0 < mitte[65] < 1
    oben = lokal._bereich(werte, 70, 100, 10)
    assert oben[100] == 1 and oben[59] == 0
    unten = lokal._bereich(werte, 0, 30, 0)
    assert unten[0] == 1 and unten[30] == 1 and unten[32] == 0
    assert np.array_equal(lokal._bereich(werte, 60, 40, 10), mitte)     # vertauscht


def quellen_maske(*teile):
    return maske(*teile, belichtung=1.0)


def test_helligkeit_tiefe_motiv_objekt_aus_quellen():
    hell = np.tile(np.linspace(0, 1, W, dtype=np.float32), (H, 1))
    oben = lokal.Teil("helligkeit", (70.0, 100.0, 0.0))
    g = lokal.gewicht(quellen_maske(oben), H, W, (H, W), quellen={"helligkeit": hell})
    assert g[0, -1] == 1 and g[0, 0] == 0
    tiefe = lokal.Teil("tiefe", (0.0, 30.0, 0.0))
    g = lokal.gewicht(quellen_maske(tiefe), H, W, (H, W), quellen={"tiefe": hell})
    assert g[0, 0] == 1 and g[0, -1] == 0
    motiv = np.zeros((H, W), np.float32)
    motiv[10:20, 10:20] = 1
    klicks = (0.5, 0.5, 1.0)
    for teil, quellen in ((lokal.Teil("motiv", ()), {"motiv": motiv}),
                          (lokal.Teil("objekt", klicks), {("objekt", klicks): motiv})):
        g = lokal.gewicht(quellen_maske(teil), H, W, (H, W), quellen=quellen)
        assert np.array_equal(g, motiv)
        umgekehrt = lokal.gewicht(quellen_maske(dataclasses.replace(teil, umkehren=True)),
                                  H, W, (H, W), quellen=quellen)
        assert np.array_equal(umgekehrt, 1 - motiv)


def test_ohne_quelle_wirkt_der_teil_nicht():
    for teil in (lokal.Teil("motiv", ()), lokal.Teil("objekt", (0.5, 0.5, 1.0)),
                 lokal.Teil("tiefe", (0.0, 100.0, 0.0)), lokal.Teil("farbe", (0.0, 30.0, 0.0))):
        assert not lokal.gewicht(quellen_maske(teil), H, W, (H, W)).any()


def test_farbbereich_trifft_den_farbton_und_laesst_grau():
    farbton = np.tile(np.linspace(0, 359, W, dtype=np.float32), (H, 1))
    buntheit = np.ones((H, W), np.float32)
    buntheit[:10] = 0                                       # grau
    teil = lokal.Teil("farbe", (180.0, 20.0, 0.0))
    g = lokal.gewicht(quellen_maske(teil), H, W, (H, W),
                      quellen={"farbton": farbton, "buntheit": buntheit})
    spalte_180 = int(np.argmin(np.abs(farbton[0] - 180)))
    assert g[30, spalte_180] == 1 and g[30, 0] == 0 and g[30, -1] == 0
    assert not g[:10].any()
    # Ueber die Grenze 360/0 hinweg
    rot = lokal.Teil("farbe", (355.0, 20.0, 0.0))
    g = lokal.gewicht(quellen_maske(rot), H, W, (H, W),
                      quellen={"farbton": farbton, "buntheit": buntheit})
    assert g[30, 0] == 1 and g[30, -1] == 1


def test_quellen_von_und_uebertragbar():
    klicks = (0.2, 0.3, 1.0, 0.4, 0.4, 0.0)
    m = maske(lokal.Teil("motiv", ()), lokal.Teil("objekt", klicks, modus="weg"),
              lokal.Teil("tiefe", (0, 50, 10)), lokal.Teil("helligkeit", (0, 50, 10)),
              lokal.Teil("farbe", (10, 20, 30)), radial())
    assert lokal.quellen_von(m) == {"motiv", ("objekt", klicks), "tiefe", "helligkeit",
                                    "farbe"}
    uebrig = lokal.uebertragbar((m,))[0]
    assert [t.art for t in uebrig.teile] == ["motiv", "tiefe", "helligkeit", "farbe", "radial"]
    nur_objekt = maske(lokal.Teil("objekt", klicks), radial(modus="schnitt"))
    assert lokal.uebertragbar((nur_objekt,))[0].teile[0].modus == "dazu"


def test_objekt_klicks_lesen():
    klicks = [0.25, 0.5, 1, 1.5, -2.0, 0]
    teil = {"art": "objekt", "modus": "dazu", "umkehren": False, "daten": klicks}
    roh = _roh(teile=[teil])
    gelesen = werteformat.aus_dict({"masken": roh})
    assert gelesen.werte.masken[0].teile[0].daten == (0.25, 0.5, 1.0, 1.0, 0.0, 0.0)
    for falsch in ([0.1, 0.2], [0.1, 0.2, "ja"], [0.1, 0.2, float("nan")],
                   [0.5, 0.5, 1.0] * (lokal.MAX_KLICKS + 1)):
        teil["daten"] = falsch
        assert "masken" in werteformat.aus_dict({"masken": _roh(teile=[teil])}).verworfen
    assert werteformat.lokal_klicks("x") is None


def test_bereiche_hin_und_zurueck():
    m = maske(lokal.Teil("tiefe", (10.0, 60.0, 5.0)), lokal.Teil("helligkeit", (0, 40, 20)),
              lokal.Teil("farbe", (200.0, 30.0, 50.0), umkehren=True), lokal.Teil("motiv", ()),
              lokal.Teil("objekt", (0.1, 0.2, 1.0), modus="schnitt"), kontrast=20)
    werte = f.Einstellungen(masken=(m,))
    gelesen = werteformat.aus_dict(werteformat.als_dict(werte))
    assert gelesen.werte == werte and not gelesen.verworfen
