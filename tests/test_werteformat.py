"""Reglerwerte als JSON: hin und zurueck, und streng beim Lesen fremder Dateien."""

import dataclasses
import json

import pytest

from silberkorn import lut, werteformat
from silberkorn.filter import Einstellungen

LUT_TEXT = "LUT_3D_SIZE 2\n" + "\n".join(
    f"{r} {g} {b}" for b in (0, 1) for g in (0, 1) for r in (0, 1)) + "\n"


def _bearbeitet() -> Einstellungen:
    return Einstellungen(
        film="farbnegativ", film_maske=(0.8, 0.5, 0.3), film_umfang=(0.1, 0.1, 0.1, 1, 1, 1),
        belichtung=1.25, kontrast=-30.0, kurve_hell=((0.0, 0.1), (0.5, 0.6), (1.0, 1.0)),
        hsl_farbton=(1.0, 2, 3, 4, 5, 6, 7, 8), drehung90=3, spiegeln=True,
        zuschnitt=(0.1, 0.2, 0.9, 0.8), anonym_flaechen=(("ellipse", 0.1, 0.1, 0.3, 0.4),),
        anonym_art="weich", anonym_bloecke=12.0, metadaten_entfernen=True,
        angaben=(("bewertung", 4), ("stichwoerter", ("Berlin", "Herbst")), ("titel", "Hallo")),
        freistellen=True, ki_rauschen=70.0)


def test_alle_felder_haben_einen_leser():
    assert werteformat.alle_felder_bekannt()


def test_hin_und_zurueck():
    werte = _bearbeitet()
    daten = json.loads(json.dumps(werteformat.als_dict(werte)))
    gelesen = werteformat.aus_dict(daten)
    assert gelesen.verworfen == []
    assert gelesen.werte == werte


def test_objektivprofil_nur_als_schalter():
    werte = Einstellungen(objektivprofil=(1.0, 2.0, 3.0))
    daten = werteformat.als_dict(werte)
    assert daten["objektivprofil"] is True
    gelesen = werteformat.aus_dict(daten)
    assert gelesen.objektivprofil is True
    assert gelesen.werte.objektivprofil == ()


@pytest.mark.parametrize("name, wert", [
    ("belichtung", "1"), ("belichtung", True), ("belichtung", None), ("belichtung", [1]),
    ("spiegeln", 1), ("drehung90", 4), ("drehung90", 1.0), ("drehung90", True),
    ("zuschnitt", [0.5, 0.5, 0.5, 0.9]), ("zuschnitt", [0, 0, 1]),
    ("kurve_hell", [[0.2, 0], [1, 1]]), ("kurve_hell", [[0, 0], [0.5, 1], [0.5, 1], [1, 1]]),
    ("kurve_hell", [[0, 0]] * 40), ("hsl_farbton", [0] * 7), ("film", "farbe"),
    ("film_maske", [0.5, 0.5]), ("film_umfang", [1, 2, 3]), ("anonym_art", "nichts"),
    ("anonym_flaechen", [["kreis", 0, 0, 1, 1]]), ("anonym_flaechen", "x"),
    ("angaben", [["pfad", "C:\\x"]]), ("angaben", [["bewertung", 9]]),
    ("angaben", [["titel", "a"], ["titel", "b"]]), ("angaben", [["datum", "gestern"]]),
    ("angaben", [[["titel"], "a"]]),
])
def test_ungueltiges_wird_verworfen(name, wert):
    gelesen = werteformat.aus_dict({name: wert})
    assert gelesen.verworfen == [name]
    assert getattr(gelesen.werte, name) == getattr(Einstellungen(), name)


def test_zahlen_werden_begrenzt():
    gelesen = werteformat.aus_dict({"belichtung": 1e300, "kontrast": -1e9, "temperatur": 50,
                                    "film_maske": [0, 1, 100]})
    assert gelesen.verworfen == []
    assert gelesen.werte.belichtung == 5.0
    assert gelesen.werte.kontrast == -100.0
    assert gelesen.werte.temperatur == 50.0
    assert gelesen.werte.film_maske == (werteformat.FILM_MASKE_BEREICH[0], 1.0, 16.0)


def test_unbekanntes_und_kein_dict():
    assert werteformat.aus_dict({"__class__": 1, "gibt_es_nicht": 2}).verworfen == []
    assert werteformat.aus_dict([1, 2]).verworfen == ["werte"]


def test_texte_ohne_steuerzeichen_und_gekuerzt():
    text = "A\x00B\x1b[31m\u202eC\nD" + "x" * 5000
    gelesen = werteformat.aus_dict({"angaben": [["titel", text]]})
    titel = dict(gelesen.werte.angaben)["titel"]
    assert titel.startswith("AB[31mC\nD")
    assert len(titel) <= werteformat.MAX_TEXT


def test_lut_wird_eingebettet_nie_als_pfad():
    gelesen = werteformat.aus_dict({"lut": "\\\\server\\freigabe\\x.cube"})
    assert gelesen.werte.lut == ""                 # ein Pfad in den Werten zaehlt nicht
    gelesen = werteformat.aus_dict({}, lut_daten={"name": "Look", "text": LUT_TEXT})
    assert gelesen.werte.lut.startswith(lut.EINGEBETTET)
    assert lut.laden(gelesen.werte.lut).groesse == 2
    assert werteformat.lut_als_dict(gelesen.werte) == {"name": "Look", "text": LUT_TEXT}


def test_kaputte_lut_wird_verworfen():
    for text in ("unsinn", "LUT_3D_SIZE 2\n" + "nan 0 0\n" * 8,
                 "LUT_3D_SIZE 2\n" + "-nan 0 0\n" * 8):
        gelesen = werteformat.aus_dict({}, lut_daten={"name": "x", "text": text})
        assert gelesen.verworfen == ["lut"]
        assert gelesen.werte.lut == ""


def test_nur_gewaehlte_felder():
    daten = werteformat.als_dict(_bearbeitet())
    basis = Einstellungen(kontrast=10.0)
    gelesen = werteformat.aus_dict(daten, basis, felder={"belichtung"})
    assert gelesen.werte == dataclasses.replace(basis, belichtung=1.25)
    assert gelesen.felder == ("belichtung",)
