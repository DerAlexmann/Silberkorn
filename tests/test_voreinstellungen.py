"""Voreinstellungen: Gruppen, Film, Ablage und sichere Namen."""

import dataclasses
import json

import pytest

from silberkorn import einstellungen
from silberkorn import voreinstellungen as vor
from silberkorn.filter import Einstellungen


@pytest.fixture(autouse=True)
def eigener_ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(einstellungen, "programm_ordner", lambda: str(tmp_path))
    return tmp_path


def _werte() -> Einstellungen:
    return Einstellungen(belichtung=1.0, kontrast=20.0, zuschnitt=(0.1, 0.1, 0.9, 0.9),
                         film="farbnegativ", film_maske=(0.8, 0.5, 0.3),
                         film_umfang=(0.1, 0.1, 0.1, 1.0, 1.0, 1.0), ki_rauschen=50.0)


def test_gruppen_decken_alle_felder():
    alle = {f.name for f in dataclasses.fields(Einstellungen)}
    gruppiert = [name for gruppe in vor.GRUPPEN.values() for name in gruppe]
    assert set(gruppiert) == alle
    assert len(gruppiert) == len(alle)             # jedes Feld in genau einer Gruppe


def test_nur_gewaehlte_gruppen_und_film_neu_schaetzen():
    daten = vor.als_dict(_werte(), vor.Auswahl())
    basis = Einstellungen(zuschnitt=(0.2, 0.2, 0.8, 0.8), saettigung=-10.0)
    gelesen = vor.anwenden(json.loads(json.dumps(daten)), basis)
    w = gelesen.ergebnis.werte
    assert (w.belichtung, w.kontrast, w.film) == (1.0, 20.0, "farbnegativ")
    assert w.zuschnitt == (0.2, 0.2, 0.8, 0.8)    # Geometrie war nicht gewaehlt
    assert w.saettigung == 0.0                     # Grundregler ganz uebernommen
    assert w.ki_rauschen == 0.0
    assert w.film_maske == () and gelesen.film_schaetzen


def test_film_messung_mitnehmen():
    daten = vor.als_dict(_werte(), vor.Auswahl(film_messung=True))
    gelesen = vor.anwenden(daten, Einstellungen())
    assert gelesen.ergebnis.werte.film_maske == (0.8, 0.5, 0.3)
    assert not gelesen.film_schaetzen


def test_sichern_laden_loeschen(eigener_ordner):
    vor.sichern("Kodak Portra", vor.als_dict(_werte(), vor.Auswahl()))
    assert vor.namen() == ["Kodak Portra"]
    assert vor.laden("Kodak Portra")["werte"]["belichtung"] == 1.0
    vor.loeschen("Kodak Portra")
    assert vor.namen() == []


@pytest.mark.parametrize("name", ["", " ", "a/b", "..\\x", "..", "CON", "con.txt", "LPT1",
                                  "x" * 61, "Ende.", "null\x00byte", "rtl‮name", "C:x", "a*b"])
def test_ungueltige_namen(name):
    assert vor.name_pruefen(name) is None
    with pytest.raises(vor.VoreinstellungFehler):
        vor.sichern(name, vor.als_dict(Einstellungen(), vor.Auswahl()))


def test_name_wird_gesaeubert():
    assert vor.name_pruefen("  Mein   Look ") == "Mein Look"
    assert vor.vorgeschlagener_name("C:/x/Mein:Look?.json") == "MeinLook"
    assert vor.vorgeschlagener_name("CON.json") == "Voreinstellung"


def test_importieren_prueft_und_schreibt_neu(tmp_path):
    fremd = tmp_path / "fremd.json"
    daten = vor.als_dict(_werte(), vor.Auswahl())
    daten["werte"]["belichtung"] = 1e9
    daten["werte"]["boese"] = "x"
    daten["unbekannt"] = {"a": 1}
    fremd.write_text(json.dumps(daten), encoding="utf-8")
    vor.importieren(str(fremd), "Fremd")
    gelesen = vor.anwenden(vor.laden("Fremd"), Einstellungen())
    assert gelesen.ergebnis.werte.belichtung == 5.0


@pytest.mark.parametrize("inhalt", [b"kein json", b"[]", b'{"kennung": "x"}',
                                    b'{"kennung": "silberkorn-voreinstellung", "format": 1, '
                                    b'"gruppen": [], "werte": {"belichtung": Infinity}}'])
def test_importieren_lehnt_ab(tmp_path, inhalt):
    fremd = tmp_path / "fremd.json"
    fremd.write_bytes(inhalt)
    with pytest.raises(vor.VoreinstellungFehler):
        vor.importieren(str(fremd), "Fremd")
    assert vor.namen() == []
