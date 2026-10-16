"""
Begleitdatei: die Bearbeitung neben dem Bild sichern

Neben foto.jpg liegt foto.jpg.silberkorn - ein ZIP mit fest benannten Teilen:

  begleitdatei.json   Kennung, Format, Fingerabdruck des Originals, Reglerwerte
                      (werteformat.py) und was an KI-Ergebnissen dabei ist
  lut.cube            die LUT als Text, falls eine gesetzt ist
  vorschau.webp       das bearbeitete Bild klein, fuer die Ordneransicht
  maske.npy           Maske des Motivs (uint8)
  tiefe.npy           Tiefe, verkleinert (float16)
  flicken-N-*.npy     entfernte Objekte: Deckkraft und Fuellung (float16)
  staub-*.npy         gefuellter Staub: Stellen und Werte
  erweiterung.npy     Leinwand der KI-Erweiterung (sRGB, uint16)

Gespeichert wird, was sich nicht in Sekunden gleich wiederholen laesst: Maske,
Tiefe, entfernte Objekte, Staub und Erweiterung. KI-Entrauschen, -Schaerfen und
-Kolorieren liefern fuer dasselbe Bild dasselbe; sie in voller Groesse zu
speichern, kostete Hunderte MB. Ihre Staerke steht in den Werten, berechnet
werden sie nach dem Oeffnen neu.

Eine Begleitdatei kann von Dritten stammen. Gelesen wird deshalb so:

- Nichts wird entpackt, gelesen werden nur die erwarteten Namen; andere Namen
  oder zu viele Eintraege machen die Datei ungueltig.
- Kein pickle: Arrays werden ueber ihren Kopf (np.lib.format, nur Version 1.0)
  gelesen; Typ und Form muessen genau passen - auch zur Groesse des Bildes -,
  bevor ein Byte der Daten gelesen wird. Gelesen wird dann genau so viel, wie
  die Form verlangt: Eine ZIP-Bombe kann nicht mehr auspacken als ein
  passendes Array.
- Zahlen muessen endlich sein; Lagen und Groessen muessen ins Bild passen.
- Die Werte prueft werteformat.py.

Geschrieben wird erst in eine Datei daneben, die dann die alte ersetzt - ein
Absturz mittendrin hinterlaesst nie eine halbe Begleitdatei.

Dieses Modul kennt weder Qt noch die Grafikkarte.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import zipfile
from dataclasses import dataclass, field

import numpy as np

from . import lut, werteformat
from .filter import Einstellungen

ENDUNG = ".silberkorn"
KENNUNG = "silberkorn-begleitdatei"
FORMAT = 1
JSON_NAME = "begleitdatei.json"
LUT_NAME = "lut.cube"
VORSCHAU_NAME = "vorschau.webp"
MAX_JSON = 4 * 2**20
MAX_LUT = 64 * 2**20
MAX_VORSCHAU = 2 * 2**20
MAX_FLICKEN = 500
MAX_TIEFE_KANTE = 8192
MAX_LEINWAND = 9                 # die Leinwand hat hoechstens so viele Pixel wie 9 Originale
FINGER_BYTES = 2**20             # so viel vom Anfang und vom Ende geht in den Fingerabdruck
VERHAELTNIS_BEREICH = (0.05, 20.0)


class BegleitFehler(Exception):
    """Die Begleitdatei laesst sich nicht lesen oder schreiben."""


@dataclass
class Flicken:
    y0: int
    y1: int
    x0: int
    x1: int
    deckkraft: np.ndarray            # (h, w) float16, 0..1
    fuellung: np.ndarray             # (h, w, 3) float16, linear und mit der Deckkraft malgenommen


@dataclass
class Staub:
    stellen: np.ndarray              # (n,) int64, aufsteigend, im flachen Bild H * W
    werte: np.ndarray                # (n, 3) float32, linear
    anzahl: int


@dataclass
class Erweiterung:
    x: int
    y: int
    seed: int
    verhaeltnis: float
    rand: np.ndarray                 # (H, W, 3) uint16, sRGB


@dataclass
class Inhalt:
    """Eine Bearbeitung, wie sie in der Begleitdatei steht."""
    werte: Einstellungen
    objektivprofil: bool = False
    maske: np.ndarray | None = None  # (h, w) uint8
    maske_per_klick: bool = False
    tiefe: np.ndarray | None = None  # (th, tw) float16, 0..1
    flicken: list[Flicken] = field(default_factory=list)
    staub: Staub | None = None
    erweiterung: Erweiterung | None = None
    vorschau: bytes | None = None    # WebP
    # Nur beim Lesen
    verworfen: list[str] = field(default_factory=list)
    passt: bool = True               # gehoert zum Original (Fingerabdruck stimmt)


def pfad_fuer(bild: str) -> str:
    return bild + ENDUNG


def fingerabdruck(pfad: str) -> dict:
    """Groesse und SHA-256 ueber Anfang und Ende - erkennt ein anderes oder geaendertes
    Bild, ohne bei jedem Oeffnen die ganze Datei zu lesen."""
    try:
        groesse = os.path.getsize(pfad)
        summe = hashlib.sha256(groesse.to_bytes(8, "little"))
        with open(pfad, "rb") as datei:
            summe.update(datei.read(FINGER_BYTES))
            if groesse > FINGER_BYTES:
                datei.seek(max(FINGER_BYTES, groesse - FINGER_BYTES))
                summe.update(datei.read(FINGER_BYTES))
    except OSError as fehler:
        raise BegleitFehler(str(fehler)) from fehler
    return {"groesse": groesse, "sha256": summe.hexdigest()}


# --------------------------------------------------------------------------
# Schreiben
# --------------------------------------------------------------------------

def _npy(archiv: zipfile.ZipFile, name: str, array: np.ndarray):
    with archiv.open(name, "w", force_zip64=True) as ziel:
        np.lib.format.write_array(ziel, np.ascontiguousarray(array), version=(1, 0),
                                  allow_pickle=False)


def schreiben(bild: str, inhalt: Inhalt, finger: dict, programm: str = ""):
    """Die Bearbeitung neben das Bild schreiben. BegleitFehler, wenn es nicht geht -
    etwa in einem schreibgeschuetzten Ordner. LutFehler wird zu BegleitFehler."""
    try:
        lut_daten = werteformat.lut_als_dict(inhalt.werte)
    except lut.LutFehler as fehler:
        raise BegleitFehler(str(fehler)) from fehler
    kopf = {
        "kennung": KENNUNG, "format": FORMAT, "programm": programm, "original": finger,
        "werte": werteformat.als_dict(inhalt.werte),
        "lut": None if lut_daten is None else {"name": lut_daten["name"]},
        "maske": None if inhalt.maske is None else {"per_klick": bool(inhalt.maske_per_klick)},
        "tiefe": inhalt.tiefe is not None,
        "flicken": [[f.y0, f.y1, f.x0, f.x1] for f in inhalt.flicken],
        "staub": None if inhalt.staub is None else {"anzahl": int(inhalt.staub.anzahl)},
        "erweiterung": None if inhalt.erweiterung is None else {
            "x": inhalt.erweiterung.x, "y": inhalt.erweiterung.y,
            "seed": inhalt.erweiterung.seed, "verhaeltnis": inhalt.erweiterung.verhaeltnis},
        "vorschau": inhalt.vorschau is not None,
    }
    ziel = pfad_fuer(bild)
    ordner = os.path.dirname(os.path.abspath(ziel))
    try:
        griff, zwischen = tempfile.mkstemp(prefix=".silberkorn-", suffix=".tmp", dir=ordner)
    except OSError as fehler:
        raise BegleitFehler(str(fehler)) from fehler
    try:
        with os.fdopen(griff, "wb") as datei, \
                zipfile.ZipFile(datei, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archiv:
            archiv.writestr(JSON_NAME, json.dumps(kopf, ensure_ascii=False, allow_nan=False))
            if lut_daten is not None:
                archiv.writestr(LUT_NAME, lut_daten["text"])
            if inhalt.vorschau is not None:
                archiv.writestr(VORSCHAU_NAME, inhalt.vorschau, zipfile.ZIP_STORED)
            if inhalt.maske is not None:
                _npy(archiv, "maske.npy", inhalt.maske.astype(np.uint8))
            if inhalt.tiefe is not None:
                _npy(archiv, "tiefe.npy", inhalt.tiefe.astype(np.float16))
            for nummer, flicken in enumerate(inhalt.flicken):
                _npy(archiv, f"flicken-{nummer}-deckkraft.npy", flicken.deckkraft.astype("<f2"))
                _npy(archiv, f"flicken-{nummer}-fuellung.npy", flicken.fuellung.astype("<f2"))
            if inhalt.staub is not None:
                _npy(archiv, "staub-stellen.npy", inhalt.staub.stellen.astype("<i8"))
                _npy(archiv, "staub-werte.npy", inhalt.staub.werte.astype("<f4"))
            if inhalt.erweiterung is not None:
                _npy(archiv, "erweiterung.npy", inhalt.erweiterung.rand.astype("<u2"))
        os.replace(zwischen, ziel)
    except (OSError, ValueError, zipfile.BadZipFile) as fehler:
        try:
            os.remove(zwischen)
        except OSError:
            pass
        raise BegleitFehler(str(fehler)) from fehler


def entfernen(bild: str) -> bool:
    """Die Begleitdatei loeschen - etwa wenn alles zurueckgesetzt ist. Nur eine
    gewoehnliche Datei, nie ein Ordner oder eine Verknuepfung."""
    ziel = pfad_fuer(bild)
    try:
        if os.path.islink(ziel) or not os.path.isfile(ziel):
            return False
        os.remove(ziel)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# Lesen
# --------------------------------------------------------------------------

def _ganz(wert, unten: int, oben: int) -> int:
    if isinstance(wert, bool) or not isinstance(wert, int) or not unten <= wert <= oben:
        raise BegleitFehler("ungültige Zahl")
    return wert


def _json_konstante(name: str):
    raise BegleitFehler(f"ungültiger Wert {name}")


class _Archiv:
    """Liest nur erwartete Teile, jeden hoechstens einmal, mit begrenzter Groesse."""

    def __init__(self, archiv: zipfile.ZipFile, erlaubt: set[str]):
        eintraege = archiv.infolist()
        namen = [e.filename for e in eintraege]
        if len(namen) != len(set(namen)) or not set(namen) <= erlaubt:
            raise BegleitFehler("unerwarteter Inhalt")
        self.archiv = archiv
        self.namen = set(namen)

    def bytes(self, name: str, hoechstens: int) -> bytes:
        if name not in self.namen:
            raise BegleitFehler(f"{name} fehlt")
        with self.archiv.open(name) as quelle:
            daten = quelle.read(hoechstens + 1)
        if len(daten) > hoechstens:
            raise BegleitFehler(f"{name} zu groß")
        return daten

    def array(self, name: str, typ: str, form_ok) -> np.ndarray:
        """Ein Array, wenn Typ und Form passen; form_ok(shape) -> bool. Gelesen werden
        genau die Bytes, die diese Form braucht."""
        if name not in self.namen:
            raise BegleitFehler(f"{name} fehlt")
        typ = np.dtype(typ)
        with self.archiv.open(name) as quelle:
            try:
                if np.lib.format.read_magic(quelle) != (1, 0):
                    raise BegleitFehler(f"{name}: unbekannte Fassung")
                form, fortran, gelesen_typ = np.lib.format.read_array_header_1_0(quelle)
            except ValueError as fehler:
                raise BegleitFehler(f"{name}: {fehler}") from fehler
            if (fortran or gelesen_typ != typ or not isinstance(form, tuple)
                    or not all(isinstance(z, int) and z >= 0 for z in form)
                    or not form_ok(form)):
                raise BegleitFehler(f"{name}: Typ oder Form passt nicht")
            anzahl = math.prod(form) * typ.itemsize
            daten = quelle.read(anzahl + 1)
        if len(daten) != anzahl:
            raise BegleitFehler(f"{name}: Länge passt nicht")
        array = np.frombuffer(daten, dtype=typ).reshape(form)
        if typ.kind == "f" and not np.isfinite(array).all():
            raise BegleitFehler(f"{name}: ungültige Zahlen")
        return array


def _erlaubte_namen() -> set[str]:
    namen = {JSON_NAME, LUT_NAME, VORSCHAU_NAME, "maske.npy", "tiefe.npy", "staub-stellen.npy",
             "staub-werte.npy", "erweiterung.npy"}
    for nummer in range(MAX_FLICKEN):
        namen |= {f"flicken-{nummer}-deckkraft.npy", f"flicken-{nummer}-fuellung.npy"}
    return namen


_ERLAUBT = _erlaubte_namen()


def kopf_lesen(pfad: str) -> dict:
    """Nur den JSON-Teil - etwa fuer die Vorschau in einer Ordneransicht."""
    try:
        with zipfile.ZipFile(pfad) as archiv:
            return _kopf(_Archiv(archiv, _ERLAUBT))
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as fehler:
        raise BegleitFehler(str(fehler)) from fehler


def _kopf(archiv: _Archiv) -> dict:
    try:
        kopf = json.loads(archiv.bytes(JSON_NAME, MAX_JSON).decode("utf-8"),
                          parse_constant=_json_konstante)
    except (UnicodeDecodeError, ValueError, RecursionError) as fehler:
        raise BegleitFehler(str(fehler)) from fehler
    if not isinstance(kopf, dict) or kopf.get("kennung") != KENNUNG:
        raise BegleitFehler("keine Begleitdatei")
    if kopf.get("format") != FORMAT:
        raise BegleitFehler("unbekanntes Format")
    return kopf


def vorschau_lesen(pfad: str) -> bytes | None:
    """Das kleine Vorschaubild (WebP) oder None."""
    try:
        with zipfile.ZipFile(pfad) as archiv:
            gelesen = _Archiv(archiv, _ERLAUBT)
            _kopf(gelesen)
            if VORSCHAU_NAME not in gelesen.namen:
                return None
            return gelesen.bytes(VORSCHAU_NAME, MAX_VORSCHAU)
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as fehler:
        raise BegleitFehler(str(fehler)) from fehler


def lesen(bild: str, hoehe: int, breite: int, basis: Einstellungen | None = None) -> Inhalt:
    """Die Begleitdatei zum Bild (hoehe x breite Pixel) lesen. BegleitFehler, wenn sie
    fehlt oder ungueltig ist. Passt der Fingerabdruck nicht, kommen nur die Werte
    zurueck (passt=False) - die KI-Ergebnisse gehoerten zu einem anderen Bild."""
    pfad = pfad_fuer(bild)
    try:
        with zipfile.ZipFile(pfad) as archiv:
            return _lesen(_Archiv(archiv, _ERLAUBT), bild, hoehe, breite, basis)
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError,
            KeyError) as fehler:
        raise BegleitFehler(str(fehler)) from fehler


def _lesen(archiv: _Archiv, bild: str, hoehe: int, breite: int,
           basis: Einstellungen | None) -> Inhalt:
    kopf = _kopf(archiv)
    lut_daten = None
    if kopf.get("lut") is not None:
        lut_kopf = kopf["lut"]
        if not isinstance(lut_kopf, dict):
            raise BegleitFehler("lut")
        try:
            text = archiv.bytes(LUT_NAME, MAX_LUT).decode("utf-8")
        except UnicodeDecodeError as fehler:
            raise BegleitFehler(str(fehler)) from fehler
        lut_daten = {"name": lut_kopf.get("name"), "text": text}
    gelesen = werteformat.aus_dict(kopf.get("werte"), basis, lut_daten=lut_daten)
    inhalt = Inhalt(gelesen.werte, gelesen.objektivprofil, verworfen=gelesen.verworfen)
    inhalt.passt = kopf.get("original") == fingerabdruck(bild)
    if not inhalt.passt:
        return inhalt

    if kopf.get("maske") is not None:
        maske = kopf["maske"]
        if not isinstance(maske, dict) or not isinstance(maske.get("per_klick"), bool):
            raise BegleitFehler("maske")
        inhalt.maske = archiv.array("maske.npy", "|u1", lambda f: f == (hoehe, breite))
        inhalt.maske_per_klick = maske["per_klick"]
    if kopf.get("tiefe") is True:
        def tiefe_ok(f):
            return (len(f) == 2 and 1 <= f[0] <= min(hoehe, MAX_TIEFE_KANTE)
                    and 1 <= f[1] <= min(breite, MAX_TIEFE_KANTE))
        inhalt.tiefe = np.clip(archiv.array("tiefe.npy", "<f2", tiefe_ok), 0, 1)

    lagen = kopf.get("flicken", [])
    if not isinstance(lagen, list) or len(lagen) > MAX_FLICKEN:
        raise BegleitFehler("flicken")
    flaeche = 0
    for nummer, lage in enumerate(lagen):
        if not isinstance(lage, list) or len(lage) != 4:
            raise BegleitFehler("flicken")
        y0, y1 = _ganz(lage[0], 0, hoehe), _ganz(lage[1], 0, hoehe)
        x0, x1 = _ganz(lage[2], 0, breite), _ganz(lage[3], 0, breite)
        if y1 <= y0 or x1 <= x0:
            raise BegleitFehler("flicken")
        flaeche += (y1 - y0) * (x1 - x0)
        if flaeche > 4 * hoehe * breite:
            raise BegleitFehler("flicken zu groß")
        h, w = y1 - y0, x1 - x0
        deckkraft = archiv.array(f"flicken-{nummer}-deckkraft.npy", "<f2",
                                 lambda f, h=h, w=w: f == (h, w))
        fuellung = archiv.array(f"flicken-{nummer}-fuellung.npy", "<f2",
                                lambda f, h=h, w=w: f == (h, w, 3))
        inhalt.flicken.append(Flicken(y0, y1, x0, x1, np.clip(deckkraft, 0, 1), fuellung))

    if kopf.get("staub") is not None:
        staub = kopf["staub"]
        if not isinstance(staub, dict):
            raise BegleitFehler("staub")
        anzahl = _ganz(staub.get("anzahl"), 0, hoehe * breite)
        stellen = archiv.array("staub-stellen.npy", "<i8",
                               lambda f: len(f) == 1 and f[0] <= hoehe * breite)
        n = stellen.shape[0]
        if n and (stellen[0] < 0 or stellen[-1] >= hoehe * breite
                  or not (np.diff(stellen) > 0).all()):
            raise BegleitFehler("staub: Stellen")
        werte = archiv.array("staub-werte.npy", "<f4", lambda f: f == (n, 3))
        inhalt.staub = Staub(stellen, werte, anzahl)

    if kopf.get("erweiterung") is not None:
        teil = kopf["erweiterung"]
        if not isinstance(teil, dict):
            raise BegleitFehler("erweiterung")
        verhaeltnis = teil.get("verhaeltnis")
        if (isinstance(verhaeltnis, bool) or not isinstance(verhaeltnis, (int, float))
                or not VERHAELTNIS_BEREICH[0] <= verhaeltnis <= VERHAELTNIS_BEREICH[1]):
            raise BegleitFehler("erweiterung")
        seed = _ganz(teil.get("seed"), 0, 2**63 - 1)

        def leinwand_ok(f):
            return (len(f) == 3 and f[2] == 3 and f[0] >= hoehe and f[1] >= breite
                    and f[0] * f[1] <= MAX_LEINWAND * hoehe * breite)
        rand = archiv.array("erweiterung.npy", "<u2", leinwand_ok)
        x = _ganz(teil.get("x"), 0, rand.shape[1] - breite)
        y = _ganz(teil.get("y"), 0, rand.shape[0] - hoehe)
        inhalt.erweiterung = Erweiterung(x, y, seed, float(verhaeltnis), rand)

    if kopf.get("vorschau") is True and VORSCHAU_NAME in archiv.namen:
        inhalt.vorschau = archiv.bytes(VORSCHAU_NAME, MAX_VORSCHAU)
    return inhalt
