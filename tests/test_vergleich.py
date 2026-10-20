"""Vergleich Vorher/Nachher in der Sitzung: gleiche Geometrie, Cache, KI-Raender - nur mit
Grafikkarte."""

from __future__ import annotations

import numpy as np
import pytest

cp = pytest.importorskip("cupy")


@pytest.fixture
def sitzung():
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    from silberkorn import bilddatei
    from silberkorn.bearbeitung import Sitzung
    zufall = np.random.default_rng(3)
    pixel = zufall.integers(20, 200, (120, 160, 3), dtype=np.uint8)
    daten = bilddatei.Bilddaten(pixel=pixel, profil=None, alpha=None, exif=b"", pfad="t.png")
    s = Sitzung(daten, vorschau_kante=80)
    yield s
    s.schliessen()


def test_vorher_hat_die_geometrie_des_bearbeiteten_bildes(sitzung):
    from silberkorn import geometrie
    sitzung.werte.drehung90 = 1
    sitzung.werte.zuschnitt = (0.1, 0.2, 0.8, 0.9)
    sitzung.werte.belichtung = 60.0
    hoehe, breite = sitzung.ausgabe_form()
    assert (hoehe, breite) != sitzung.original.shape[:2]
    nachher, _ms, _h = sitzung.ausschnitt(0, 0, breite, hoehe)
    vorher = sitzung.vorher_ausschnitt(0, 0, breite, hoehe)
    assert vorher.shape == nachher.shape
    klein_nachher, _ms, _h = sitzung.vorschau()
    assert sitzung.vorher_vorschau().shape == klein_nachher.shape
    # Wie das bearbeitete Bild, nur ohne Regler: derselbe Ausschnitt, gleiche Pixel
    erwartet, _ms, _h = sitzung.ausschnitt(0, 0, breite, hoehe,
                                           werte=geometrie.nur_geometrie(sitzung.werte))
    assert np.array_equal(vorher, erwartet)
    assert not np.array_equal(vorher, nachher)


def test_reglerbewegung_rechnet_vorher_nicht_neu(sitzung, monkeypatch):
    rechnungen = []
    echt = sitzung._vorher_rendern
    monkeypatch.setattr(sitzung, "_vorher_rendern",
                        lambda werte, voll: rechnungen.append(voll) or echt(werte, voll))
    sitzung.vorher_vorschau()
    sitzung.vorher_ausschnitt(0, 0, 160, 120)
    assert rechnungen == [False, True]
    for belichtung in (10.0, 30.0, 50.0):
        sitzung.werte.belichtung = belichtung
        sitzung.werte.kontrast = belichtung / 2
        sitzung.werte.korn = 20.0
        sitzung.vorschau()
        sitzung.ausschnitt(0, 0, 160, 120)
        sitzung.vorher_vorschau()
        sitzung.vorher_ausschnitt(0, 0, 160, 120)
    assert rechnungen == [False, True]                       # kein weiteres Mal
    sitzung.werte.drehung90 = 2                              # die Geometrie zaehlt
    sitzung.vorher_vorschau()
    sitzung.vorher_ausschnitt(0, 0, 160, 120)
    assert rechnungen == [False, True, False, True]
    sitzung.vollbild_vergessen()                             # gibt auch das Vorher-Vollbild her
    sitzung.vorher_ausschnitt(0, 0, 160, 120)
    assert rechnungen == [False, True, False, True, True]


def test_vorher_ohne_flicken_und_ohne_regler(sitzung):
    sitzung.werte.belichtung = 80.0
    sitzung.werte.sw = True
    erwartet, _ms, _h = sitzung.vorschau(unbearbeitet=True, ohne_flicken=True)
    assert np.array_equal(sitzung.vorher_vorschau(), erwartet)


def test_vorher_nach_ki_erweitern_hat_graue_raender(sitzung):
    """Original bei x = 40 in einer Leinwand von 240 x 120: links das Original an seinem
    Platz, die erfundenen Raender grau - und dieselbe Form wie das bearbeitete Bild."""
    class Weiss:
        def raender(self, srgb, gross_b, gross_h, x, y, seed, fortschritt=None):
            return cp.ones((gross_h, gross_b, 3), dtype=cp.float32)

    original, _ms, _h = sitzung.ausschnitt(0, 0, 160, 120)
    sitzung.ki_erweitern(Weiss(), 2.0, seed=1)
    hoehe, breite = sitzung.ausgabe_form()
    assert (hoehe, breite) == (120, 240)
    nachher, _ms, _h = sitzung.ausschnitt(0, 0, breite, hoehe)
    vorher = sitzung.vorher_ausschnitt(0, 0, breite, hoehe)
    assert vorher.shape == nachher.shape
    assert nachher[60, 5].min() > 200                          # erfundener Rand: weiss
    assert np.abs(vorher[60, 5].astype(int) - 128).max() <= 1  # links neutral grau
    assert np.abs(vorher[60, 235].astype(int) - 128).max() <= 1
    assert np.array_equal(vorher[:, 40:200], original)         # Original unverwischt am Platz
    klein, _ms, _h = sitzung.vorschau()
    vorher_klein = sitzung.vorher_vorschau()
    assert vorher_klein.shape == klein.shape
    # Auch in der kleinen Vorschau (nicht nur im Vollbild): die Raender sind neutral grau
    assert klein[30, 2].min() > 200                            # bearbeitet: erfundener Rand weiss
    assert np.abs(vorher_klein[30, 2].astype(int) - 128).max() <= 1
    assert np.abs(vorher_klein[30, klein.shape[1] - 3].astype(int) - 128).max() <= 1
    # Eine andere Leinwand rechnet das Vorher-Bild neu
    sitzung.erweiterung_verwerfen()
    assert sitzung.vorher_ausschnitt(0, 0, 160, 120).shape == (120, 160, 3)


class Weiss:
    """Statt LaMa: fuellt alles Markierte weiss."""
    beschleuniger = "Test"

    def fuellen(self, srgb, maske):
        zeilen = cp.flatnonzero((maske > 0.5).any(axis=1))
        spalten = cp.flatnonzero((maske > 0.5).any(axis=0))
        if zeilen.size == 0:
            return None
        y0, y1, x0, x1 = int(zeilen[0]), int(zeilen[-1]) + 1, int(spalten[0]), int(spalten[-1]) + 1
        return (y0, y1, x0, x1, cp.ones((y1 - y0, x1 - x0, 3), cp.float32),
                cp.ascontiguousarray(maske[y0:y1, x0:x1]))


def test_vorher_ohne_entfernte_objekte(sitzung):
    """Dort, wo ein Objekt entfernt wurde, zeigt „Vorher“ das Original."""
    from silberkorn.filter import Einstellungen
    sitzung.pinseln([(40.0, 60.0)], 10.0, True)
    assert sitzung.ki_entfernen(Weiss()) is not None
    nachher, _ms, _h = sitzung.vorschau()
    stelle = (30, 20)                                          # Vorschau: halbe Groesse
    assert nachher[stelle].min() > 200                         # bearbeitet: weiss gefuellt
    vorher = sitzung.vorher_vorschau()
    erwartet, _ms, _h = sitzung.vorschau(werte=Einstellungen(), ohne_flicken=True)
    assert np.array_equal(vorher, erwartet)
    assert np.abs(vorher[stelle].astype(int) - nachher[stelle].astype(int)).max() > 100
    original, _ms, _h = sitzung.ausschnitt(0, 0, 160, 120, Einstellungen(), ohne_flicken=True)
    assert np.array_equal(sitzung.vorher_ausschnitt(0, 0, 160, 120), original)
    assert sitzung.ausschnitt(0, 0, 160, 120)[0][60, 40].min() >= 254   # bearbeitet: Flicken


@pytest.fixture
def negativ_sitzung():
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    from silberkorn import bilddatei
    from silberkorn.bearbeitung import Sitzung
    # Ein orange gefaerbtes Negativ mit Verlauf: ein Positiv sieht ganz anders aus
    verlauf = np.linspace(0.2, 1.0, 160, dtype=np.float32)[None, :, None]
    maske = np.array([0.9, 0.5, 0.3], dtype=np.float32)[None, None, :]
    pixel = np.repeat((verlauf * maske * 255).astype(np.uint8), 120, axis=0)
    daten = bilddatei.Bilddaten(pixel=pixel, profil=None, alpha=None, exif=b"", pfad="n.png")
    s = Sitzung(daten, vorschau_kante=80)
    yield s
    s.schliessen()


def test_vorher_zeigt_negativ_unveraendert(negativ_sitzung):
    from silberkorn import geometrie
    from silberkorn.filter import Einstellungen
    s = negativ_sitzung
    s.werte.film = "farbnegativ"
    s.werte.film_maske, s.werte.film_umfang = s.film_schaetzen("farbnegativ")
    nachher, _ms, _h = s.vorschau()
    vorher = s.vorher_vorschau()
    erwartet, _ms, _h = s.vorschau(werte=geometrie.nur_geometrie(s.werte), ohne_flicken=True)
    assert np.array_equal(vorher, erwartet)
    negativ, _ms, _h = s.vorschau(werte=Einstellungen())
    assert np.array_equal(vorher, negativ)                     # ohne Umwandlung
    assert vorher.shape == nachher.shape
    assert np.abs(vorher.astype(int) - nachher.astype(int)).mean() > 20
    # Auch im 100-%-Ausschnitt bleibt es das Negativ
    voll, _ms, _h = s.ausschnitt(0, 0, 160, 120, Einstellungen())
    assert np.array_equal(s.vorher_ausschnitt(0, 0, 160, 120), voll)


# Je Geometriefeld ein gueltiger, vom Neutralen abweichender Wert. Das Objektivprofil
# braucht keine Datenbank: neutrale Terme samt Bezug sind ein vollstaendiges Profil und
# unterscheiden sich vom leeren Tupel.
GEAENDERT = {
    "drehung90": 1, "spiegeln": True, "zuschnitt": (0.1, 0.2, 0.8, 0.9), "begradigen": 3.0,
    "perspektive_v": 10.0, "perspektive_h": -10.0, "verzeichnung": 5.0, "vignette": 20.0,
    "ca_rot": 4.0, "ca_blau": -4.0, "objektivprofil": (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0,
                                                       0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 1.0),
}


def test_geaendert_deckt_alle_geometriefelder_ab():
    from silberkorn import geometrie
    assert set(GEAENDERT) == set(geometrie.GEOMETRIE_FELDER)


@pytest.mark.parametrize("feld", sorted(GEAENDERT))
def test_vorher_neu_bei_jeder_geometrieaenderung(sitzung, monkeypatch, feld):
    from silberkorn import geometrie
    neutral = geometrie.aus(sitzung.werte)
    rechnungen = []
    echt = sitzung._vorher_rendern
    monkeypatch.setattr(sitzung, "_vorher_rendern",
                        lambda werte, voll: rechnungen.append(voll) or echt(werte, voll))
    sitzung.vorher_vorschau()
    sitzung.vorher_ausschnitt(0, 0, 160, 120)
    assert rechnungen == [False, True]
    sitzung.vorher_vorschau()                                  # unveraendert: Zwischenspeicher
    assert rechnungen == [False, True]
    setattr(sitzung.werte, feld, GEAENDERT[feld])
    assert geometrie.aus(sitzung.werte) != neutral             # der Wert weicht wirklich ab
    sitzung.vorher_vorschau()
    assert rechnungen == [False, True, False]
    sitzung.vorher_ausschnitt(0, 0, 160, 120)
    assert rechnungen == [False, True, False, True]
