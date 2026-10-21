"""Gemerkter Zustand der Abschneide-Warnung in der Einstellungsdatei - mit echter Datei."""

from __future__ import annotations

import dataclasses
import json

import pytest

from silberkorn import einstellungen, filter


@pytest.fixture
def datei(tmp_path, monkeypatch):
    pfad = tmp_path / "silberkorn.json"
    monkeypatch.setattr(einstellungen, "config_path", lambda: str(pfad))
    return pfad


def test_fehlende_datei_und_schluessel(datei):
    assert einstellungen.warnung_gemerkt() == (False, False)
    datei.write_text("{}", encoding="utf-8")
    assert einstellungen.warnung_gemerkt() == (False, False)
    datei.write_text(json.dumps({"warnung_lichter": True}), encoding="utf-8")
    assert einstellungen.warnung_gemerkt() == (True, False)


@pytest.mark.parametrize("wert", ["true", 1, None, [True], {"a": 1}, 1.0, "ja"])
def test_nur_echtes_true_zaehlt(datei, wert):
    datei.write_text(json.dumps({"warnung_lichter": wert, "warnung_tiefen": wert}),
                     encoding="utf-8")
    assert einstellungen.warnung_gemerkt() == (False, False)


@pytest.mark.parametrize("inhalt", ["{kaputt", "", "[1, 2]", "null"])
def test_kaputte_datei(datei, inhalt):
    datei.write_text(inhalt, encoding="utf-8")
    assert einstellungen.warnung_gemerkt() == (False, False)
    assert einstellungen.warnung_merken(True, False)        # ueberschreibt, ohne Absturz
    assert einstellungen.warnung_gemerkt() == (True, False)


def test_rundlauf_und_andere_schluessel_bleiben(datei):
    datei.write_text(json.dumps({"sprache": "en", "begleitdateien": True}), encoding="utf-8")
    for wahl in ((True, True), (True, False), (False, True), (False, False)):
        assert einstellungen.warnung_merken(*wahl)
        assert einstellungen.warnung_gemerkt() == wahl
    einstellungen.warnung_merken(True, False)
    inhalt = json.loads(datei.read_text(encoding="utf-8"))
    assert inhalt == {"sprache": "en", "begleitdateien": True,
                      "warnung_lichter": True, "warnung_tiefen": False}


def test_warnung_ist_keine_bildeinstellung():
    """Die Warnung ist Anzeige: kein Feld in Einstellungen, also nicht in Rueckgaengig,
    Begleitdatei oder Voreinstellungen."""
    assert not [f.name for f in dataclasses.fields(filter.Einstellungen) if "warnung" in f.name]
