"""Einstellungsdatei: atomar schreiben, unlesbare oder kaputte Dateien nicht still ersetzen."""

import builtins
import json
import os

import pytest

from silberkorn import einstellungen


@pytest.fixture(autouse=True)
def eigener_ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(einstellungen, "programm_ordner", lambda: str(tmp_path))
    return tmp_path


def _inhalt(ordner) -> str:
    return (ordner / einstellungen.CONFIG_NAME).read_text(encoding="utf-8")


def _reste(ordner) -> list[str]:
    return sorted(n for n in os.listdir(ordner) if n != einstellungen.CONFIG_NAME)


def test_rundreise_ohne_reste(eigener_ordner):
    werte = {"language": "en", "theme": "dunkel", "vorschau_cache_mb": 512}
    assert einstellungen.save_config(werte) is True
    assert einstellungen.load_config() == werte
    assert einstellungen.save_config({**werte, "theme": "hell"}) is True
    assert einstellungen.load_config()["theme"] == "hell"
    assert _reste(eigener_ordner) == []


def test_fehlende_datei_ist_leer():
    daten = einstellungen.load_config()
    assert daten == {}
    daten["language"] = "en"
    assert einstellungen.save_config(daten) is True


def test_abbruch_beim_schreiben_laesst_alte_datei_stehen(eigener_ordner):
    einstellungen.save_config({"language": "en"})
    vorher = _inhalt(eigener_ordner)
    with pytest.raises(TypeError):
        einstellungen.save_config({"language": "de", "kaputt": object()})
    assert _inhalt(eigener_ordner) == vorher
    assert _reste(eigener_ordner) == []


def test_fehler_beim_ersetzen_gibt_false(eigener_ordner, monkeypatch):
    einstellungen.save_config({"language": "en"})
    vorher = _inhalt(eigener_ordner)

    def gesperrt(*_args):
        raise PermissionError("gesperrt")

    monkeypatch.setattr(einstellungen.os, "replace", gesperrt)
    assert einstellungen.save_config({"language": "de"}) is False
    assert _inhalt(eigener_ordner) == vorher
    assert _reste(eigener_ordner) == []


def test_voller_datentraeger_gibt_false(eigener_ordner, monkeypatch):
    einstellungen.save_config({"language": "en"})
    vorher = _inhalt(eigener_ordner)

    def voll(*_args, **_kwargs):
        raise OSError(28, "Kein Platz mehr")

    monkeypatch.setattr(einstellungen.json, "dump", voll)
    assert einstellungen.save_config({"language": "de"}) is False
    assert _inhalt(eigener_ordner) == vorher
    assert _reste(eigener_ordner) == []


def test_ordner_nicht_beschreibbar_gibt_false(eigener_ordner, monkeypatch):
    einstellungen.save_config({"language": "en"})
    vorher = _inhalt(eigener_ordner)

    def verweigert(*_args, **_kwargs):
        raise PermissionError("schreibgeschuetzt")

    monkeypatch.setattr(einstellungen.tempfile, "mkstemp", verweigert)
    assert einstellungen.save_config({"language": "de"}) is False
    assert _inhalt(eigener_ordner) == vorher


def test_gesperrte_datei_wird_nicht_ueberschrieben(eigener_ordner, monkeypatch):
    einstellungen.save_config({"language": "en", "theme": "dunkel", "begleitdateien": True})
    vorher = _inhalt(eigener_ordner)
    echtes_open = builtins.open
    gesperrt = {"an": True}

    def open_mit_sperre(pfad, *args, **kwargs):
        if gesperrt["an"] and os.path.basename(pfad) == einstellungen.CONFIG_NAME:
            raise PermissionError("Datei gerade gesperrt")
        return echtes_open(pfad, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_mit_sperre)
    daten = einstellungen.load_config()
    assert isinstance(daten, einstellungen._Unvollstaendig)
    daten["ordner_ansicht"] = "C:/bilder"
    gesperrt["an"] = False                       # beim Schreiben schon wieder lesbar
    assert einstellungen.save_config(daten) is False
    assert _inhalt(eigener_ordner) == vorher
    assert einstellungen.begleitdateien_setzen(False) is True   # neu geladen: geht wieder
    assert einstellungen.load_config() == {"language": "en", "theme": "dunkel",
                                           "begleitdateien": False}


def test_unpruefbare_datei_wird_nicht_ueberschrieben(eigener_ordner, monkeypatch):
    einstellungen.save_config({"language": "en"})
    vorher = _inhalt(eigener_ordner)
    echtes_open = builtins.open

    def open_mit_sperre(pfad, *args, **kwargs):
        if os.path.basename(pfad) == einstellungen.CONFIG_NAME:
            raise PermissionError("Datei gerade gesperrt")
        return echtes_open(pfad, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_mit_sperre)
    assert einstellungen.save_config({"language": "de"}) is False   # Pruefung scheitert
    monkeypatch.setattr(builtins, "open", echtes_open)
    assert _inhalt(eigener_ordner) == vorher
    assert _reste(eigener_ordner) == []


@pytest.mark.parametrize("kaputt", ['{"language": "en", "the', "[1, 2]", "\xff\xfe", "",
                                    "[" * 100000],
                         ids=["abgeschnitten", "liste", "kein-utf8", "leer", "zu-tief"])
def test_kaputte_datei_wird_beiseitegelegt(eigener_ordner, kaputt):
    pfad = eigener_ordner / einstellungen.CONFIG_NAME
    pfad.write_bytes(kaputt.encode("latin-1"))
    daten = einstellungen.load_config()
    assert daten == {}
    daten["language"] = "de"
    assert einstellungen.save_config(daten) is True
    assert json.loads(_inhalt(eigener_ordner)) == {"language": "de"}
    assert _reste(eigener_ordner) == [einstellungen.CONFIG_NAME + ".defekt"]
    assert (eigener_ordner / (einstellungen.CONFIG_NAME + ".defekt")).read_bytes() \
        == kaputt.encode("latin-1")


def test_heile_datei_bleibt_ohne_sicherung(eigener_ordner):
    einstellungen.save_config({"language": "en"})
    einstellungen.save_config({"language": "de"})
    assert _reste(eigener_ordner) == []


def test_kaputte_datei_bleibt_wenn_sicherung_scheitert(eigener_ordner, monkeypatch):
    pfad = eigener_ordner / einstellungen.CONFIG_NAME
    pfad.write_text("{halb", encoding="utf-8")

    def gesperrt(*_args):
        raise PermissionError("gesperrt")

    monkeypatch.setattr(einstellungen.os, "replace", gesperrt)
    assert einstellungen.save_config({"language": "de"}) is False
    assert pfad.read_text(encoding="utf-8") == "{halb"
    assert _reste(eigener_ordner) == []
