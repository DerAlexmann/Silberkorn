"""
Reglerwerte als JSON: schreiben und - streng geprueft - wieder lesen

Begleitdateien (begleitdatei.py) und Voreinstellungen (voreinstellungen.py)
halten die Werte einer Bearbeitung als JSON. Beide koennen von Dritten stammen
- ein Ordner aus dem Netz, eine weitergegebene Voreinstellung. Gelesen wird
deshalb nichts ungeprueft:

- Nur Felder, die Einstellungen kennt; Unbekanntes wird uebergangen.
- Jeder Wert muss den erwarteten Typ haben (ein bool ist keine Zahl), endlich
  sein und wird auf den Bereich seines Reglers begrenzt. Was nicht passt,
  behaelt seine Vorgabe und wird als verworfen gemeldet.
- Listen haben eine Hoechstlaenge, Texte eine Hoechstlaenge ohne
  Steuerzeichen.
- Pfade stehen nie darin: Eine LUT kommt als Text mit (lut.einbetten), das
  Objektivprofil nur als "an" - die Terme sucht Silberkorn selbst in lensfun.

Dieses Modul kennt weder Qt noch die Grafikkarte.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import dataclasses
import math
import unicodedata
from dataclasses import dataclass, field

from . import anonym, film, filter, kurven, lokal, lut, metadaten
from .filter import Einstellungen

MAX_TEXT = 2000                 # Zeichen je Angabe (Titel, Beschreibung ...)
MAX_STICHWOERTER = 200
MAX_FLAECHEN = 2000             # Flaechen zum Anonymisieren
FILM_MASKE_BEREICH = (film.KLEINSTE, 16.0)
FILM_UMFANG_BEREICH = (-10.0, 10.0)

# Felder, die nicht einfach Zahl oder Schalter sind - jedes hat unten seinen eigenen Leser
_SCHALTER = ("spiegeln", "maske_umkehren", "freistellen", "bokeh_motiv", "metadaten_entfernen",
             "sw")
_BESONDERE = ("film", "film_maske", "film_umfang", *filter.KURVEN, *filter.HSL, "sw_mischer",
              "lut", "drehung90", "zuschnitt", "objektivprofil", "anonym_flaechen", "anonym_art",
              "anonym_bloecke", "angaben", "masken")


@dataclass
class Gelesen:
    """Was aus einer Datei uebernommen wurde."""
    werte: Einstellungen
    felder: tuple[str, ...]                    # die Felder, die in der Datei standen
    verworfen: list[str] = field(default_factory=list)
    objektivprofil: bool = False               # Profil einschalten, wenn eins gefunden wird
    lut: tuple[str, str] | None = None         # (Text, Name)


# --------------------------------------------------------------------------
# Schreiben
# --------------------------------------------------------------------------

def als_dict(werte: Einstellungen, felder=None) -> dict:
    """Die Werte als JSON-taugliches dict - nur die genannten Felder, ohne LUT (siehe
    lut_als_dict) und mit dem Objektivprofil nur als an oder aus."""
    daten = {}
    for feld in dataclasses.fields(werte):
        name = feld.name
        if (felder is not None and name not in felder) or name == "lut":
            continue
        wert = getattr(werte, name)
        if name == "objektivprofil":
            daten[name] = bool(wert)
        elif name in filter.KURVEN:
            daten[name] = [[float(x), float(y)] for x, y in wert]
        elif name == "anonym_flaechen":
            daten[name] = [[f[0], *(float(z) for z in f[1:])] for f in wert]
        elif name == "angaben":
            daten[name] = [[n, list(w) if isinstance(w, tuple) else w] for n, w in wert]
        elif name == "masken":
            daten[name] = [_maske_als_dict(maske) for maske in wert]
        elif isinstance(wert, tuple):
            daten[name] = [float(z) for z in wert]
        else:
            daten[name] = wert
    return daten


def _maske_als_dict(maske: lokal.Maske) -> dict:
    return {"name": maske.name, "an": maske.an,
            "werte": [float(w) for w in maske.werte],
            "teile": [{"art": t.art, "modus": t.modus, "umkehren": t.umkehren,
                       "daten": [float(z) for z in t.daten]} for t in maske.teile]}


def lut_als_dict(werte: Einstellungen) -> dict | None:
    """Die LUT der Werte als {"name", "text"} - oder None ohne LUT. LutFehler, wenn sich
    die Datei nicht mehr lesen laesst."""
    if not werte.lut:
        return None
    text, name = lut.text_von(werte.lut)
    return {"name": name, "text": text}


# --------------------------------------------------------------------------
# Lesen
# --------------------------------------------------------------------------

def _zahl(wert) -> float | None:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    wert = float(wert)
    return wert if math.isfinite(wert) else None


def _begrenzt(wert, unten: float, oben: float) -> float | None:
    zahl = _zahl(wert)
    return None if zahl is None else min(max(zahl, unten), oben)


def _zahlen(wert, laengen, unten: float, oben: float) -> tuple[float, ...] | None:
    if not isinstance(wert, list) or len(wert) not in laengen:
        return None
    zahlen = [_begrenzt(z, unten, oben) for z in wert]
    return None if None in zahlen else tuple(zahlen)


def text_saeubern(wert, laenge: int = MAX_TEXT) -> str | None:
    """Ein Text ohne Steuerzeichen (Zeilenumbruch und Tab duerfen bleiben), gekuerzt."""
    if not isinstance(wert, str):
        return None
    return "".join(z for z in wert[:laenge]
                   if z in "\n\t" or unicodedata.category(z)[0] != "C")


def _kurve(wert) -> kurven.Punkte | None:
    if not isinstance(wert, list) or not 2 <= len(wert) <= kurven.MAX_PUNKTE:
        return None
    punkte = []
    for punkt in wert:
        paar = _zahlen(punkt, (2,), 0.0, 1.0)
        if paar is None:
            return None
        punkte.append(paar)
    xs = [x for x, _y in punkte]
    if xs[0] != 0.0 or xs[-1] != 1.0 or any(b <= a for a, b in zip(xs, xs[1:], strict=False)):
        return None
    return tuple(punkte)


def _flaechen(wert) -> tuple | None:
    if not isinstance(wert, list) or len(wert) > MAX_FLAECHEN:
        return None
    flaechen = []
    for teil in wert:
        if not isinstance(teil, list) or len(teil) != 5 or teil[0] not in anonym.FORMEN:
            return None
        ecken = _zahlen(teil[1:], (4,), -1.0, 2.0)
        if ecken is None:
            return None
        flaeche = anonym.flaeche_begrenzen((teil[0], *ecken))
        if flaeche is not None:
            flaechen.append(flaeche)
    return tuple(flaechen)


def _angabe(name: str, wert):
    if name == "bewertung":
        if isinstance(wert, bool) or not isinstance(wert, int):
            return None
        return wert if 0 <= wert <= metadaten.BEWERTUNG_MAX else None
    if name == "stichwoerter":
        if not isinstance(wert, list) or len(wert) > MAX_STICHWOERTER:
            return None
        woerter = [text_saeubern(w, 200) for w in wert]
        return None if None in woerter else metadaten.stichwoerter_lesen(", ".join(woerter))
    text = text_saeubern(wert)
    if text is None:
        return None
    if name == "datum":
        return metadaten.datum_lesen(text)
    return text


def _angaben(wert) -> tuple | None:
    if not isinstance(wert, list) or len(wert) > len(metadaten.FELDER):
        return None
    angaben = {}
    for teil in wert:
        if (not isinstance(teil, list) or len(teil) != 2 or not isinstance(teil[0], str)
                or teil[0] not in metadaten.FELDER or teil[0] in angaben):
            return None
        angabe = _angabe(teil[0], teil[1])
        if angabe is None:
            return None
        angaben[teil[0]] = angabe
    return tuple(sorted(angaben.items()))


def _teil(wert) -> lokal.Teil | None:
    if not isinstance(wert, dict) or set(wert) - {"art", "modus", "umkehren", "daten"}:
        return None
    art, modus = wert.get("art"), wert.get("modus", "dazu")
    umkehren = wert.get("umkehren", False)
    if (not isinstance(art, str) or art not in lokal.ARTEN or not isinstance(modus, str)
            or modus not in lokal.MODI or not isinstance(umkehren, bool)):
        return None
    grenzen = lokal.DATEN[art]
    daten = wert.get("daten")
    if not isinstance(daten, list) or len(daten) != len(grenzen):
        return None
    zahlen = [_begrenzt(z, unten, oben) for z, (_n, unten, oben) in zip(daten, grenzen,
                                                                         strict=True)]
    if None in zahlen:
        return None
    return lokal.Teil(art, tuple(zahlen), modus, umkehren)


def _maske(wert) -> lokal.Maske | None:
    if not isinstance(wert, dict) or set(wert) - {"name", "an", "werte", "teile"}:
        return None
    name = text_saeubern(wert.get("name", ""), lokal.MAX_NAME)
    an = wert.get("an", True)
    teile = wert.get("teile", [])
    zahlen = wert.get("werte")
    if (name is None or not isinstance(an, bool) or not isinstance(teile, list)
            or len(teile) > lokal.MAX_TEILE or not isinstance(zahlen, list)
            or len(zahlen) != len(lokal.REGLER)):
        return None
    name = " ".join(name.split())             # ein Name ist eine Zeile
    werte = [_begrenzt(z, r.minimum, r.maximum) for z, r in zip(zahlen, lokal.REGLER,
                                                                 strict=True)]
    gelesen = [_teil(t) for t in teile]
    if None in werte or None in gelesen:
        return None
    return lokal.Maske(name, tuple(gelesen), tuple(werte), an)


def _masken(wert) -> tuple | None:
    if not isinstance(wert, list) or len(wert) > lokal.MAX_MASKEN:
        return None
    masken = [_maske(m) for m in wert]
    return None if None in masken else tuple(masken)


def _feld_lesen(name: str, wert):
    """Der gepruefte Wert eines Feldes - oder None, wenn er nicht taugt."""
    regler = filter.REGLER_NACH_NAME.get(name)
    if regler is not None:
        return _begrenzt(wert, regler.minimum, regler.maximum)
    if name in _SCHALTER:
        return wert if isinstance(wert, bool) else None
    if name in filter.KURVEN:
        return _kurve(wert)
    if name in filter.HSL or name == "sw_mischer":
        return _zahlen(wert, (len(filter.FARBBEREICHE),), -100.0, 100.0)
    if name == "film":
        return wert if isinstance(wert, str) and wert in film.ARTEN else None
    if name == "film_maske":
        return _zahlen(wert, (0, 3), *FILM_MASKE_BEREICH)
    if name == "film_umfang":
        return _zahlen(wert, (0, 6), *FILM_UMFANG_BEREICH)
    if name == "drehung90":
        ok = isinstance(wert, int) and not isinstance(wert, bool) and 0 <= wert <= 3
        return wert if ok else None
    if name == "zuschnitt":
        ecken = _zahlen(wert, (4,), 0.0, 1.0)
        if ecken is None or ecken[2] - ecken[0] < 1e-3 or ecken[3] - ecken[1] < 1e-3:
            return None
        return ecken
    if name == "anonym_flaechen":
        return _flaechen(wert)
    if name == "anonym_art":
        return wert if isinstance(wert, str) and wert in anonym.ARTEN else None
    if name == "anonym_bloecke":
        return _begrenzt(wert, anonym.BLOECKE_MIN, anonym.BLOECKE_MAX)
    if name == "angaben":
        return _angaben(wert)
    if name == "masken":
        return _masken(wert)
    return None


def aus_dict(daten, basis: Einstellungen | None = None, felder=None,
             lut_daten=None) -> Gelesen:
    """Werte aus einem dict (aus JSON) - gesetzt werden nur gepruefte Felder auf basis.

    felder: nur diese Felder uebernehmen (None: alle). lut_daten: {"name", "text"} oder
    None; eine lesbare LUT wird eingebettet (lut.einbetten), eine kaputte verworfen."""
    werte = dataclasses.replace(basis) if basis is not None else Einstellungen()
    gelesen = Gelesen(werte, ())
    if not isinstance(daten, dict):
        gelesen.verworfen.append("werte")
        return gelesen
    bekannt = {f.name for f in dataclasses.fields(Einstellungen)}
    vorhanden = []
    for name, wert in daten.items():
        if name not in bekannt or name == "lut" or (felder is not None and name not in felder):
            continue
        vorhanden.append(name)
        if name == "objektivprofil":
            if isinstance(wert, bool):
                gelesen.objektivprofil = wert
                werte.objektivprofil = ()
            else:
                gelesen.verworfen.append(name)
            continue
        geprueft = _feld_lesen(name, wert)
        if geprueft is None:
            gelesen.verworfen.append(name)
        else:
            setattr(werte, name, geprueft)
    if lut_daten is not None and (felder is None or "lut" in felder):
        vorhanden.append("lut")
        text = lut_daten.get("text") if isinstance(lut_daten, dict) else None
        name = text_saeubern(lut_daten.get("name"), 200) if isinstance(lut_daten, dict) else None
        try:
            if not isinstance(text, str) or name is None:
                raise lut.LutFehler("unvollständig")
            werte.lut = lut.einbetten(text, name)
            gelesen.lut = (text, name)
        except lut.LutFehler:
            gelesen.verworfen.append("lut")
    gelesen.felder = tuple(vorhanden)
    return gelesen


def alle_felder_bekannt() -> bool:
    """Hat jedes Feld der Einstellungen einen Leser? Fuer einen Test - ein neues Feld
    ohne Leser wuerde sonst still nie aus einer Datei gelesen."""
    namen = {f.name for f in dataclasses.fields(Einstellungen)}
    gelesen = set(filter.REGLER_NACH_NAME) | set(_SCHALTER) | set(_BESONDERE)
    return namen == gelesen
