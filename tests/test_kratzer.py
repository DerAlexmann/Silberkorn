"""Scan & Film: Schaeden mit KI finden und die Fundmaske nachbessern - nur mit Grafikkarte."""

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


from silberkorn import bilddatei, filter, ki, kratzer, staub  # noqa: E402
from silberkorn.bearbeitung import Sitzung  # noqa: E402

HOEHE, BREITE = 120, 160
KRATZER = (slice(50, 54), slice(30, 130))          # im Bild schwarz
ZWEITER = (slice(90, 94), slice(40, 60))           # schwacher Fund


class Finder:
    """Statt des Netzes: wahrscheinlich ist, was im Graubild dunkel ist."""

    def __init__(self):
        self.aufrufe = []

    def karte(self, grau, kachel, fortschritt=None):
        self.aufrufe.append((grau.shape, kachel))
        karte = cp.clip((0.5 - grau) / 2, 0, 1).astype(cp.float32)
        if fortschritt is not None:
            fortschritt(1, 1)
        return karte


def bild():
    werte = np.full((HOEHE, BREITE, 3), 0.8, dtype=np.float32)
    werte[KRATZER] = 0.0
    werte[ZWEITER] = 0.45
    return werte


def sitzung_von(werte=None, infrarot=None) -> Sitzung:
    pixel = ((bild() if werte is None else werte) * 65535).astype(np.uint16)
    if infrarot is not None:
        infrarot = (infrarot * 65535).astype(np.uint16)
    daten = bilddatei.Bilddaten(pixel, None, None, b"", "test.tif", infrarot=infrarot)
    return Sitzung(daten, vorschau_kante=1024)


def test_schwelle_trifft_das_original():
    assert kratzer.EMPFINDLICHKEIT == 50
    assert kratzer.schwelle(50) == pytest.approx(0.4)
    assert kratzer.schwelle(0) > kratzer.schwelle(100) > 0
    assert kratzer.schwelle(-5) == kratzer.schwelle(0)
    assert kratzer.schwelle(500) == kratzer.schwelle(100)


@pytest.mark.parametrize(("kante", "faktor"), [(100, 1), (2048, 1), (2049, 2), (4096, 2),
                                               (4097, 3)])
def test_rechenfaktor_haelt_die_kurze_seite(kante, faktor):
    assert kratzer.rechenfaktor(kante, 9000) == faktor
    assert kratzer.rechenfaktor(9000, kante) == faktor


def test_grosse_bilder_sieht_das_netz_verkleinert():
    finder = Finder()
    srgb = cp.zeros((2100, 2101, 3), dtype=cp.float32)
    karte, faktor = kratzer.karte(srgb, finder, 512)
    assert faktor == 2 and karte.shape == (1050, 1050)
    assert finder.aufrufe == [((1050, 1050), 512)]


def test_graubild_im_bereich_des_netzes():
    grau = kratzer.graubild(cp.asarray([[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]], dtype=cp.float32))
    assert grau[0].tolist() == pytest.approx([-1.0, 1.0])


def test_finden_rechnet_auf_die_bildgroesse_hoch():
    karte = cp.zeros((4, 5), dtype=cp.float32)
    karte[3, 4] = 0.9                                # liegt am Rand, der abgeschnitten war
    maske, kern, anzahl = kratzer.finden(karte, 2, (9, 11), 50)
    assert maske.shape == kern.shape == (9, 11)
    assert anzahl == 1 and bool(kern[8, 10]) and bool(kern[6, 8]) and not bool(kern[5, 7])
    assert bool(maske[5, 7])                         # gewachsen


def test_ablauf_finden_empfindlichkeit_entfernen():
    sitzung = sitzung_von()
    finder = Finder()
    assert not sitzung.staub_suchbar and sitzung.staub_fund is None
    sitzung.kratzer_finden(finder, 256, 50)
    assert sitzung.staub_suchbar and sitzung.staub_fund == (50, 1)
    sitzung.staub_finden(100)
    assert sitzung.staub_fund == (100, 2)
    assert len(finder.aufrufe) == 1                  # die Schwelle rechnet das Netz nicht neu

    sitzung.staub_entfernen(100)
    assert sitzung.staub_entfernt and sitzung.staub_gefuellt == 2
    gefuellt = cp.asnumpy(sitzung._film_bild(sitzung.werte, True))
    assert gefuellt[KRATZER].min() > 0.2

    sitzung.staub_verwerfen()
    assert not sitzung.staub_entfernt
    sitzung.schliessen()


def test_netz_sieht_den_scan_ohne_fuellung_und_als_positiv():
    sitzung = sitzung_von()
    gesehen = []

    class Merker(Finder):
        def karte(self, grau, kachel, fortschritt=None):
            gesehen.append(float(grau[52, 80]))
            return super().karte(grau, kachel, fortschritt)

    sitzung.kratzer_finden(Merker(), 256, 50)
    sitzung.staub_entfernen(50)
    sitzung.kratzer_finden(Merker(), 256, 50)        # der Kratzer ist noch da
    assert gesehen[0] == gesehen[1] == pytest.approx(-1.0)
    sitzung.schliessen()


def test_film_aendern_macht_die_karte_ungueltig():
    sitzung = sitzung_von()
    sitzung.kratzer_finden(Finder(), 256, 50)
    w = sitzung.werte
    w.film, w.film_maske, w.film_umfang = "farbnegativ", (0.9, 0.5, 0.3), (0.1,) * 3 + (0.9,) * 3
    assert not sitzung.staub_suchbar and sitzung.kratzer_veraltet
    assert sitzung.staub_fund is None
    sitzung.staub_pinseln([(10, 10)], 5, True)       # ohne gueltigen Fund nichts anzulegen
    assert sitzung._staub_korrektur is None
    sitzung.schliessen()


def test_pinsel_uebersteht_die_empfindlichkeit():
    sitzung = sitzung_von()
    sitzung.kratzer_finden(Finder(), 256, 50)
    sitzung.staub_pinseln([(80, 52)], 60, False)     # den Kratzer ganz wegnehmen
    sitzung.staub_pinseln([(20, 20)], 4, True)       # dafuer anderswo einen Fleck
    sitzung.staub_zaehlen()
    assert sitzung.staub_fund[1] == 1

    sitzung.staub_finden(60)                         # neue Schwelle, Striche bleiben
    assert sitzung.staub_fund[1] == 1
    maske, kern = sitzung._fund_masken()
    assert not bool(maske[52, 80]) and bool(maske[20, 20]) and bool(kern[20, 20])
    ebene = cp.asnumpy(sitzung._fund_ebene(False))
    assert ebene[52, 80] == 0 and ebene[20, 20] == 1

    sitzung.staub_entfernen(60)
    assert sitzung.staub_gefuellt == 1
    gefuellt = cp.asnumpy(sitzung._film_bild(sitzung.werte, True))
    assert gefuellt[KRATZER].max() == 0              # was radiert ist, bleibt
    sitzung.schliessen()


def test_pinsel_dreht_den_letzten_strich_um():
    sitzung = sitzung_von()
    sitzung.kratzer_finden(Finder(), 256, 50)
    sitzung.staub_pinseln([(80, 52)], 8, False)
    sitzung.staub_pinseln([(80, 52)], 8, True)
    assert bool(sitzung._fund_masken()[0][52, 80])
    sitzung.schliessen()


def test_zuruecksetzen_nimmt_die_striche_mit():
    sitzung = sitzung_von()
    sitzung.kratzer_finden(Finder(), 256, 50)
    sitzung.staub_pinseln([(20, 20)], 4, True)
    sitzung.entfernungen_verwerfen()
    assert sitzung._staub_korrektur is None
    sitzung.schliessen()


def test_striche_gehen_nicht_in_den_rueckgaengig_stand():
    sitzung = sitzung_von()
    sitzung.kratzer_finden(Finder(), 256, 50)
    sitzung.staub_entfernen(50)
    stand = sitzung.stand()
    sitzung.staub_verwerfen()
    assert cp.asnumpy(sitzung._film_bild(sitzung.werte, True))[KRATZER].max() == 0
    sitzung.stand_setzen(stand)
    assert sitzung.staub_entfernt
    assert cp.asnumpy(sitzung._film_bild(sitzung.werte, True))[KRATZER].min() > 0.2
    sitzung.schliessen()


def test_begleitdatei_bringt_die_fuellung_ohne_karte_und_striche():
    a = sitzung_von()
    a.kratzer_finden(Finder(), 256, 50)
    a.staub_pinseln([(20, 20)], 4, True)
    a.staub_entfernen(50)
    inhalt = a.begleit_inhalt()
    a.schliessen()

    b = sitzung_von()
    b.begleit_anwenden(inhalt)
    assert b.staub_entfernt and b.staub_gefuellt == 2
    assert cp.asnumpy(b._film_bild(b.werte, True))[KRATZER].min() > 0.2
    assert not b.staub_suchbar and b.staub_fund is None and b._staub_korrektur is None
    assert b.staub_verwerfen()
    b.schliessen()


def test_abbruch_laesst_die_alte_karte_stehen():
    class Bricht(Finder):
        def karte(self, grau, kachel, fortschritt=None):
            raise ki.KiAbbruch()

    sitzung = sitzung_von()
    with pytest.raises(ki.KiAbbruch):
        sitzung.kratzer_finden(Bricht(), 256, 50)
    assert sitzung._kratzer is None and sitzung.staub_fund is None

    sitzung.kratzer_finden(Finder(), 256, 50)
    with pytest.raises(ki.KiAbbruch):
        sitzung.kratzer_finden(Bricht(), 256, 50)
    assert sitzung.staub_fund == (50, 1)
    sitzung.schliessen()


def test_suche_ohne_karte_meldet_sich_laut():
    sitzung = sitzung_von()
    with pytest.raises(ValueError, match="KI-Karte"):
        sitzung.staub_finden(50)
    sitzung.schliessen()


def _film_wechseln(sitzung):
    w = sitzung.werte
    w.film, w.film_maske, w.film_umfang = "farbnegativ", (0.9, 0.5, 0.3), (0.1,) * 3 + (0.9,) * 3


def test_film_zurueck_macht_die_karte_wieder_gueltig():
    sitzung = sitzung_von()
    sitzung.kratzer_finden(Finder(), 256, 50)
    _film_wechseln(sitzung)
    with pytest.raises(ValueError, match="KI-Karte"):
        sitzung.staub_entfernen(50)                  # nie mit der Karte des alten Positivs
    w = sitzung.werte
    w.film, w.film_maske, w.film_umfang = "", (), ()
    assert sitzung.staub_suchbar and sitzung.staub_fund == (50, 1)
    sitzung.schliessen()


def test_neue_suche_nach_filmwechsel_verwirft_die_striche():
    sitzung = sitzung_von()
    sitzung.kratzer_finden(Finder(), 256, 50)
    sitzung.staub_pinseln([(20, 20)], 4, True)
    sitzung.kratzer_finden(Finder(), 256, 50)        # gleiches Positiv: Striche gelten weiter
    assert sitzung._staub_korrektur is not None
    _film_wechseln(sitzung)
    sitzung.kratzer_finden(Finder(), 256, 50)
    assert sitzung._staub_korrektur is None
    sitzung.schliessen()


def test_karte_passt_bei_verkleinertem_bild(monkeypatch):
    monkeypatch.setattr(kratzer, "KURZE_SEITE", 50)
    werte = np.full((121, 163, 3), 0.8, dtype=np.float32)
    werte[60:66, 20:100] = 0.0
    werte[-6:, -6:] = 0.0                            # im Rest, den das Verkleinern abschneidet
    sitzung = sitzung_von(werte)
    finder = Finder()
    sitzung.kratzer_finden(finder, 256, 50)
    assert finder.aufrufe == [((40, 54), 256)]
    maske = sitzung._fund_masken()[0]
    assert maske.shape == (121, 163)
    assert bool(maske[62, 60]) and not bool(maske[20, 60])
    sitzung.schliessen()


def test_pinsel_in_verkleinerter_vorschau():
    werte = np.full((1200, 1600, 3), 0.8, dtype=np.float32)
    werte[500:504, 300:1300] = 0.0
    daten = bilddatei.Bilddaten((werte * 65535).astype(np.uint16), None, None, b"", "test.tif")
    sitzung = Sitzung(daten, vorschau_kante=400)
    faktor = round(1 / sitzung.vorschau_massstab)
    assert faktor > 1
    sitzung.kratzer_finden(Finder(), 256, 50)
    sitzung.staub_pinseln([(800, 200)], 40, True)
    voll, klein = sitzung._fund_ebene(True), sitzung._fund_ebene(False)
    assert voll.shape == (1200, 1600) and klein.shape == sitzung.vorschau_original.shape[:2]
    assert float(voll[200, 800]) == 1 and float(klein[200 // faktor, 800 // faktor]) == 1
    assert float(klein[100 // faktor, 800 // faktor]) == 0
    sitzung.schliessen()


def test_infrarot_bleibt_die_quelle():
    ir = np.full((HOEHE, BREITE), 0.85, dtype=np.float32)
    ir[KRATZER] = 0.1
    sitzung = sitzung_von(infrarot=ir)
    assert sitzung.staub_suchbar and not sitzung.kratzer_bereit
    sitzung.staub_finden(50)
    assert sitzung.staub_fund[1] == 1
    sitzung.staub_pinseln([(10, 10)], 3, True)       # nachbessern geht auch hier
    sitzung.staub_zaehlen()
    assert sitzung.staub_fund[1] == 2
    sitzung.schliessen()


def test_kachel_naehte_bleiben_unsichtbar():
    """Die Karte entsteht aus ueberlappenden Kacheln - ein gleiches Ergebnis je Kachel darf
    keine Spur hinterlassen."""
    netz = _kachelnetz(lambda eingabe: cp.ones_like(eingabe) * 0.25)
    karte = netz.karte(cp.zeros((200, 300), dtype=cp.float32), 96)
    assert karte.shape == (200, 300)
    assert cp.allclose(karte, 0.25)


def _kachelnetz(kachel):
    netz = ki.Schadenfinder.__new__(ki.Schadenfinder)
    netz.modell = ki.SCHADEN_MODELLE["kratzer"]
    netz.tensorrt = False
    netz._kachel = kachel
    return netz


def test_ueberblenden_setzt_jede_kachel_an_ihre_stelle():
    netz = _kachelnetz(lambda eingabe: eingabe * 0.5)
    y, x = cp.mgrid[0:201, 0:307]
    eingabe = ((y + x) / 508).astype(cp.float32)
    assert cp.allclose(netz.karte(eingabe, 96), eingabe * 0.5, atol=1e-5)


def test_speichermangel_halbiert_die_kachel():
    groessen = []

    def kachel(eingabe):
        groessen.append(max(eingabe.shape[2:]))
        if groessen[-1] > 256:
            raise cp.cuda.memory.OutOfMemoryError(1, 0)
        return cp.ones_like(eingabe) * 0.25

    karte = _kachelnetz(kachel).karte(cp.zeros((300, 300), dtype=cp.float32), 1024)
    assert cp.allclose(karte, 0.25)
    assert groessen[0] > 256 and min(groessen) < 256


def test_dauerhafter_speichermangel_wird_zum_ki_fehler():
    def kachel(_eingabe):
        raise cp.cuda.memory.OutOfMemoryError(1, 0)

    with pytest.raises(ki.KiFehler, match="Grafikspeicher"):
        _kachelnetz(kachel).karte(cp.zeros((64, 64), dtype=cp.float32), 256)


def test_schaden_modell_eingetragen():
    modell = ki.SCHADEN_MODELLE["kratzer"]
    assert ki.ALLE_MODELLE["kratzer"] is modell
    assert modell.release == ki.MODELL_RELEASE_10 and modell.lizenz == "MIT"
    assert modell.ausgabe_kanaele == 1 and modell.vielfaches == 16
    assert ki.DATEIEN[modell.datei] == (modell.sha256, 150583117)


@pytest.mark.skipif(not ki.vorhanden(ki.SCHADEN_MODELLE["kratzer"]), reason="Modell fehlt")
def test_echtes_modell_findet_einen_hellen_kratzer():
    """Ein heller Strich auf einem ruhigen Bild ist das, wofuer das Netz gelernt hat."""
    werte = np.full((512, 512, 3), 0.3, dtype=np.float32)
    zufall = np.random.default_rng(3)
    werte += zufall.normal(0, 0.01, werte.shape[:2])[..., None].astype(np.float32)
    for x in range(60, 450):
        y = 256 + int(40 * np.sin(x / 50))
        werte[y - 1:y + 1, x] = 1.0
    srgb = filter.linear_zu_srgb(cp.asarray(np.clip(werte, 0, 1)))
    finder = ki.Schadenfinder()
    karte, faktor = kratzer.karte(srgb, finder, 256)
    assert faktor == 1 and karte.shape == (512, 512)
    assert 0 <= float(karte.min()) and float(karte.max()) <= 1
    maske, _kern, anzahl = kratzer.finden(karte, 1, (512, 512), 50)
    assert anzahl >= 1
    assert bool(maske[256 + int(40 * np.sin(200 / 50)), 200])
    assert float(maske.mean()) < 0.05


def test_staub_anzahl():
    maske = cp.zeros((10, 10), dtype=bool)
    maske[1, 1] = maske[8, 8] = True
    assert staub.anzahl(maske) == 2
