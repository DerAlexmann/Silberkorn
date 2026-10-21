"""
Einstellungen: eine JSON-Datei neben dem Programm

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import json
import locale
import os
import sys
import tempfile

from . import farben
from .uebersetzung import LANGUAGE_NAMES, SOURCE_LANGUAGE, TRANSLATIONS

CONFIG_NAME = "silberkorn.json"


def ist_eingefroren() -> bool:
    """Laeuft das Programm als gebuendelte EXE (PyInstaller & Co.)?"""
    return getattr(sys, "frozen", False)


def programm_ordner() -> str:
    """Ordner, in dem das Programm fuer den Anwender sichtbar liegt.

    Als PyInstaller-EXE zeigt __file__ in den Entpackordner, der den
    Programmlauf nicht ueberdauert. Alles Bleibende gehoert deshalb neben die
    EXE. Als Skript ist es der Ordner ueber dem Paket, also der, in dem
    Silberkorn.pyw liegt.
    """
    if ist_eingefroren():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def beschreibbar(ordner: str) -> bool:
    """Liesse sich in ordner schreiben? Ordner, die erst fuer die Probe entstehen,
    werden danach wieder entfernt - angelegt wird erst beim Herunterladen, also
    nach der Zustimmung des Anwenders."""
    neu = []
    pfad = os.path.abspath(ordner)
    while not os.path.isdir(pfad):
        neu.append(pfad)
        eltern = os.path.dirname(pfad)
        if eltern == pfad:
            break
        pfad = eltern
    try:
        os.makedirs(ordner, exist_ok=True)
        probe = os.path.join(ordner, ".schreibprobe")
        with open(probe, "w", encoding="ascii") as datei:
            datei.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False
    finally:
        for pfad in neu:
            try:
                os.rmdir(pfad)
            except OSError:
                pass


def config_path() -> str:
    return os.path.join(programm_ordner(), CONFIG_NAME)


class _Unvollstaendig(dict):
    """Ergebnis von load_config(), wenn die Datei da war, sich aber gerade nicht
    lesen liess (gesperrt, keine Rechte). save_config() schreibt so etwas nicht -
    sonst ersetzte ein einzelner geaenderter Schluessel alle uebrigen Einstellungen."""


def load_config() -> dict:
    try:
        with open(config_path(), encoding="utf-8") as datei:
            daten = json.load(datei)
    except FileNotFoundError:
        return {}
    except OSError:
        return _Unvollstaendig()
    except (ValueError, RecursionError):
        return {}                       # kaputt: save_config() legt sie vorher beiseite
    return daten if isinstance(daten, dict) else {}


def _defekte_beiseitelegen(pfad: str):
    """Eine vorhandene, aber kaputte Datei als .defekt aufheben statt sie zu
    ueberschreiben. OSError, wenn sie sich nicht pruefen laesst."""
    try:
        with open(pfad, encoding="utf-8") as datei:
            daten = json.load(datei)
        if isinstance(daten, dict):
            return
    except FileNotFoundError:
        return
    except (ValueError, RecursionError):
        pass
    os.replace(pfad, pfad + ".defekt")


def save_config(daten: dict) -> bool:
    """Atomar schreiben: erst daneben, dann ersetzen. False, wenn nichts gespeichert wurde."""
    if isinstance(daten, _Unvollstaendig):
        return False
    pfad = config_path()
    try:
        _defekte_beiseitelegen(pfad)
        griff, zwischen = tempfile.mkstemp(prefix=".silberkorn-json-", suffix=".tmp",
                                           dir=os.path.dirname(pfad))
    except OSError:
        return False
    try:
        with os.fdopen(griff, "w", encoding="utf-8") as datei:
            json.dump(daten, datei, indent=2)
        os.replace(zwischen, pfad)
        return True
    except BaseException as fehler:
        try:
            os.remove(zwischen)
        except OSError:
            pass
        if isinstance(fehler, OSError):
            return False
        raise


def detect_language() -> str:
    """Sprache des Betriebssystems, falls dafuer eine Tabelle vorliegt."""
    try:
        locale.setlocale(locale.LC_CTYPE, "")
        code = (locale.getlocale()[0] or "").lower()
    except (locale.Error, ValueError):
        code = ""
    bekannt = {SOURCE_LANGUAGE, *TRANSLATIONS}
    kurz = code.split("_")[0]
    if kurz in bekannt:
        return kurz
    for name, sprache in (("german", "de"), ("deutsch", "de"), ("english", "en")):
        if kurz.startswith(name) and sprache in bekannt:
            return sprache
    return SOURCE_LANGUAGE


def startup_language() -> str:
    """Gespeicherte Sprache, sonst die des Betriebssystems."""
    gespeichert = load_config().get("language")
    if gespeichert in LANGUAGE_NAMES and (gespeichert == SOURCE_LANGUAGE
                                          or gespeichert in TRANSLATIONS):
        return gespeichert
    return detect_language()


def raw_qualitaet() -> str:
    """Gespeicherte Wahl fuer die RAW-Entwicklung: "schnell" (GPU) oder "beste" (LibRaw)."""
    wert = load_config().get("raw_qualitaet")
    return wert if wert in ("schnell", "beste") else "schnell"


def startup_theme() -> str:
    """Gespeichertes Farbschema, sonst das helle."""
    gespeichert = load_config().get("theme")
    return gespeichert if gespeichert in farben.THEMES else farben.DEFAULT_THEME


def begleitdateien() -> bool | None:
    """Darf Silberkorn Begleitdateien neben die Bilder schreiben? None: noch nicht gefragt."""
    wert = load_config().get("begleitdateien")
    return wert if isinstance(wert, bool) else None


def begleitdateien_setzen(erlaubt: bool) -> bool:
    daten = load_config()
    daten["begleitdateien"] = bool(erlaubt)
    return save_config(daten)
