"""
Voreinstellungen: Werte unter einem Namen sichern und auf andere Bilder legen

Eine Voreinstellung haelt nur die Gruppen von Werten, die beim Sichern gewaehlt
waren - etwa Grundregler und Kurven, aber nicht den Zuschnitt, der zu einem
bestimmten Bild gehoert. Dieselbe Form dient zum Kopieren und Einfuegen von
Einstellungen zwischen zwei Bildern.

Beim Film entscheidet der Anwender: Die gemessene Filmmaske mitnehmen - fuer
Bilder vom selben Filmstreifen - oder nur die Filmart, und Silberkorn schaetzt
Maske und Umfang an jedem Bild neu.

Voreinstellungen liegen als JSON im Ordner "voreinstellungen" neben dem
Programm, wie silberkorn.json - Silberkorn bleibt so tragbar. Eine LUT steht
als Text darin (werteformat.py). Eine fremde Voreinstellung (Importieren) wird
genauso streng gelesen wie eine Begleitdatei; ihr Name wird zum Dateinamen
erst, nachdem er geprueft ist - ohne Pfadteile, ohne Geraetenamen wie CON.

Dieses Modul kennt weder Qt noch die Grafikkarte.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import unicodedata

from . import einstellungen, filter, lokal, werteformat
from .filter import Einstellungen

KENNUNG = "silberkorn-voreinstellung"
FORMAT = 1
ORDNER = "voreinstellungen"
ENDUNG = ".json"
MAX_DATEI = 70 * 2**20           # eine LUT darf bis 64 MB gross sein
MAX_NAME = 60
VERBOTEN = set('<>:"/\\|?*')
GERAETE = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
           *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10)),
           *(f"COM{z}" for z in "¹²³"), *(f"LPT{z}" for z in "¹²³")}

# Gruppe -> Felder, in der Reihenfolge des Dialogs; dazu, ob sie anfangs gewaehlt ist
_GRUNDREGLER = ("temperatur", "toenung", "belichtung", "kontrast", "lichter", "tiefen",
                "klarheit", "dunst", "dynamik", "saettigung", "schaerfe", "schaerfe_radius")
GRUPPEN: dict[str, tuple[str, ...]] = {
    "grundregler": _GRUNDREGLER,
    "kurven": filter.KURVEN,
    "hsl": filter.HSL,
    "schwarzweiss": (*filter.SW_FELDER, *filter.TONUNG),
    "lut": ("lut", "lut_staerke"),
    "rauschen": ("rauschen_luminanz", "rauschen_farbe"),
    "korn": ("korn", "korn_groesse", "korn_rauheit"),
    "film": tuple(filter.FILM_FELDER),
    "ki": ("ki_rauschen", "ki_schaerfe", "ki_farbe"),
    "hintergrund": (*filter.HINTERGRUND, "maske_kante", "maske_verschieben", "maske_umkehren",
                    "freistellen"),
    "tiefe": ("bokeh", "fokus", "schaerfentiefe", "bokeh_motiv"),
    "objektiv": ("verzeichnung", "vignette", "ca_rot", "ca_blau", "objektivprofil"),
    "geometrie": ("drehung90", "spiegeln", "zuschnitt", "begradigen", "perspektive_v",
                  "perspektive_h"),
    "anonym": tuple(filter.ANONYM_FELDER),
    "metadaten": tuple(filter.METADATEN_FELDER),
    "lokal": tuple(filter.LOKAL_FELDER),
}
VORGABE = ("grundregler", "kurven", "hsl", "schwarzweiss", "lut", "rauschen", "korn", "film")


class VoreinstellungFehler(Exception):
    """Die Voreinstellung laesst sich nicht lesen oder sichern."""


@dataclasses.dataclass(frozen=True)
class Auswahl:
    """Was mitgenommen wird."""
    gruppen: tuple[str, ...] = VORGABE
    film_messung: bool = False       # Filmmaske und Umfang mitnehmen statt neu schaetzen


def felder(auswahl: Auswahl) -> set[str]:
    namen = set()
    for gruppe in auswahl.gruppen:
        namen |= set(GRUPPEN.get(gruppe, ()))
    if not auswahl.film_messung:
        namen -= {"film_maske", "film_umfang"}
    return namen


def als_dict(werte: Einstellungen, auswahl: Auswahl, programm: str = "") -> dict:
    """Die gewaehlten Gruppen der Werte als JSON-taugliches dict. LutFehler, wenn die
    LUT gewaehlt ist, sich aber nicht mehr lesen laesst."""
    namen = felder(auswahl)
    if "masken" in namen:
        # Pinselstriche gehoeren zu diesem Bild - mit ihnen kaeme etwas Fremdes aufs naechste
        werte = dataclasses.replace(werte, masken=lokal.uebertragbar(werte.masken))
    daten = {"kennung": KENNUNG, "format": FORMAT, "programm": programm,
             "gruppen": list(auswahl.gruppen), "film_messung": auswahl.film_messung,
             "werte": werteformat.als_dict(werte, namen), "lut": None}
    if "lut" in namen:
        daten["lut"] = werteformat.lut_als_dict(werte)
    return daten


@dataclasses.dataclass
class Gelesen:
    auswahl: Auswahl
    ergebnis: werteformat.Gelesen
    film_schaetzen: bool             # Filmart gesetzt, Maske und Umfang neu schaetzen


def anwenden(daten: dict, basis: Einstellungen) -> Gelesen:
    """Eine Voreinstellung (dict aus als_dict oder einer Datei) auf die Werte basis legen -
    streng geprueft. VoreinstellungFehler, wenn sie keine ist."""
    if not isinstance(daten, dict) or daten.get("kennung") != KENNUNG:
        raise VoreinstellungFehler("keine Voreinstellung")
    if daten.get("format") != FORMAT:
        raise VoreinstellungFehler("unbekanntes Format")
    gruppen = daten.get("gruppen")
    if not isinstance(gruppen, list):
        raise VoreinstellungFehler("gruppen")
    auswahl = Auswahl(tuple(g for g in GRUPPEN if g in gruppen),
                      daten.get("film_messung") is True)
    namen = felder(auswahl)
    lut_daten = daten.get("lut")
    ergebnis = werteformat.aus_dict(daten.get("werte"), basis, namen,
                                    lut_daten if isinstance(lut_daten, dict) else None)
    werte = ergebnis.werte
    if "lut" in namen and lut_daten is None:
        werte.lut = ""                              # die Voreinstellung hatte keine LUT
    film_schaetzen = False
    if "film" in auswahl.gruppen and not auswahl.film_messung:
        werte.film_maske, werte.film_umfang = (), ()
        film_schaetzen = werte.film in ("farbnegativ", "sw_negativ")
    return Gelesen(auswahl, ergebnis, film_schaetzen)


# --------------------------------------------------------------------------
# Ablage
# --------------------------------------------------------------------------

def ordner() -> str:
    return os.path.join(einstellungen.programm_ordner(), ORDNER)


def name_pruefen(text: str) -> str | None:
    """Ein Name, der als Dateiname taugt - oder None. Keine Pfadteile, keine
    Steuerzeichen, kein Geraetename, nicht mit Punkt oder Leerzeichen am Ende."""
    if not isinstance(text, str):
        return None
    name = " ".join(text.split())
    if not 0 < len(name) <= MAX_NAME or name.endswith("."):
        return None
    if any(z in VERBOTEN or unicodedata.category(z)[0] == "C" for z in name):
        return None
    if name in (".", "..") or name.split(".")[0].strip().upper() in GERAETE:
        return None
    return name


def _pfad(name: str) -> str:
    geprueft = name_pruefen(name)
    if geprueft is None or geprueft != name:
        raise VoreinstellungFehler("ungültiger Name")
    basis = os.path.abspath(ordner())
    pfad = os.path.abspath(os.path.join(basis, name + ENDUNG))
    if os.path.dirname(pfad) != basis:
        raise VoreinstellungFehler("ungültiger Name")
    return pfad


def namen() -> list[str]:
    """Alle Voreinstellungen, nach Namen sortiert."""
    try:
        dateien = os.listdir(ordner())
    except OSError:
        return []
    gefunden = []
    for datei in dateien:
        stamm, endung = os.path.splitext(datei)
        if endung.lower() == ENDUNG and name_pruefen(stamm) == stamm:
            gefunden.append(stamm)
    return sorted(gefunden, key=str.casefold)


def datei_lesen(pfad: str) -> dict:
    """Den Inhalt einer Voreinstellungsdatei - nur auf Form geprueft, die Werte prueft
    anwenden()."""
    try:
        with open(pfad, "rb") as datei:
            roh = datei.read(MAX_DATEI + 1)
    except OSError as fehler:
        raise VoreinstellungFehler(str(fehler)) from fehler
    if len(roh) > MAX_DATEI:
        raise VoreinstellungFehler("Datei zu groß")

    def konstante(wert):
        raise VoreinstellungFehler(f"ungültiger Wert {wert}")
    try:
        daten = json.loads(roh.decode("utf-8"), parse_constant=konstante)
    except (UnicodeDecodeError, ValueError, RecursionError) as fehler:
        raise VoreinstellungFehler(str(fehler)) from fehler
    anwenden(daten, Einstellungen())                # wirft, wenn es keine ist
    return daten


def laden(name: str) -> dict:
    return datei_lesen(_pfad(name))


def datei_schreiben(pfad: str, daten: dict):
    """Atomar schreiben: erst daneben, dann ersetzen."""
    zielordner = os.path.dirname(os.path.abspath(pfad))
    try:
        os.makedirs(zielordner, exist_ok=True)
        griff, zwischen = tempfile.mkstemp(prefix=".voreinstellung-", suffix=".tmp",
                                           dir=zielordner)
    except OSError as fehler:
        raise VoreinstellungFehler(str(fehler)) from fehler
    try:
        with os.fdopen(griff, "w", encoding="utf-8") as datei:
            json.dump(daten, datei, ensure_ascii=False, allow_nan=False, indent=1)
        os.replace(zwischen, pfad)
    except (OSError, ValueError) as fehler:
        try:
            os.remove(zwischen)
        except OSError:
            pass
        raise VoreinstellungFehler(str(fehler)) from fehler


def sichern(name: str, daten: dict):
    datei_schreiben(_pfad(name), daten)


def loeschen(name: str):
    try:
        os.remove(_pfad(name))
    except OSError as fehler:
        raise VoreinstellungFehler(str(fehler)) from fehler


def vorhanden(name: str) -> bool:
    return os.path.isfile(_pfad(name))


def importieren(pfad: str, name: str) -> dict:
    """Eine fremde Datei pruefen und als Voreinstellung name ablegen; Rueckgabe: der
    Inhalt. Abgelegt wird, was gelesen wurde - neu geschrieben, nicht kopiert."""
    daten = datei_lesen(pfad)
    sichern(name, daten)
    return daten


def vorgeschlagener_name(pfad: str) -> str:
    """Ein Name fuer eine importierte Datei - aus ihrem Dateinamen, gesaeubert."""
    stamm = os.path.splitext(os.path.basename(pfad))[0]
    sauber = "".join(z for z in stamm if z not in VERBOTEN
                     and unicodedata.category(z)[0] != "C")
    sauber = " ".join(sauber.split())[:MAX_NAME].rstrip(". ")
    return name_pruefen(sauber) or "Voreinstellung"
