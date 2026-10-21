"""
Bewertung: Sterne und Ausschuss in einer kleinen XMP-Begleitdatei neben dem Bild

Neben foto.jpg liegt foto.jpg.xmp - dieselbe Namensform wie bei darktable. Silberkorn
schreibt nur das, was es selbst angelegt hat:

  xmp:Rating      0 bis 5 Sterne, -1 steht fuer Ausschuss (so kennt es XMP)
  xmp:CreatorTool "Silberkorn"
  sk:Kennung      Kennung von Silberkorn - daran erkennt es seine eigene Datei

Eine solche Datei kann von Dritten stammen oder von Silberkorn. Deshalb:

- Eigen ist sie nur, wenn sie genau so aussieht, wie Silberkorn sie schreibt: eine
  Beschreibung ohne Unterelemente, nur diese Attribute, mit der Kennung. Alles andere wird
  nie veraendert, ersetzt oder geloescht: "fremd" ist eine gueltige XMP-Datei eines anderen
  Programms (ihre Bewertung darf gelesen werden), "unlesbar" eine kaputte, zu grosse oder
  nicht lesbare Datei, eine Verknuepfung oder ein Ordner.
- Gelesen wird ueber den gehaerteten Leser der Metadaten (kein DOCTYPE, keine
  Entitaeten, begrenzte Groesse); die Groesse wird vorher geprueft. Der Wert muss genau
  -1 bis 5 sein, sonst gilt das Bild als unbewertet. Aus der Datei wird nichts
  uebernommen ausser dieser einen Zahl - insbesondere keine Pfade.
- Geschrieben wird eine feste Vorlage mit nur der Ganzzahl, erst in eine Datei
  daneben, die dann die alte ersetzt.
- Nichts in diesem Modul loescht oder verschiebt ein Bild; eine Datei wird nie geloescht.

Lightroom-Dateien (foto.xmp ohne die Bildendung) fasst Silberkorn nicht an und liest sie
nicht: Ihr Name sagt bei gleichnamigen Bildern in verschiedenen Formaten nicht, zu welchem
sie gehoeren.

Dieses Modul kennt kein Qt.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import os
import stat
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass

from . import metadaten

ENDUNG = ".xmp"
AUSSCHUSS = -1
STERNE_MAX = 5
LESE_MAX = 2 * 2**20            # darktable-Dateien mit langem Verlauf sind gross, aber kleiner
NAMENSRAUM = "urn:silberkorn:bewertung:1"
KENNUNG = "bewertung"
_RATING = metadaten._q("xmp", "Rating")
_WERKZEUG = metadaten._q("xmp", "CreatorTool")
_KENNUNG = f"{{{NAMENSRAUM}}}Kennung"
_EIGENE_ATTRIBUTE = {metadaten.RDF["about"], _RATING, _WERKZEUG, _KENNUNG}
_ZAHLEN = {"-1": -1, "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}

VORLAGE = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
    '  <rdf:Description rdf:about=""\n'
    '    xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
    f'    xmlns:sk="{NAMENSRAUM}"\n'
    '    xmp:CreatorTool="Silberkorn"\n'
    '    xmp:Rating="{wert}"\n'
    f'    sk:Kennung="{KENNUNG}"/>\n'
    ' </rdf:RDF>\n'
    '</x:xmpmeta>\n'
    '<?xpacket end="w"?>\n')


class BewertungFehler(Exception):
    """Die Bewertung laesst sich nicht schreiben - etwa in einem schreibgeschuetzten Ordner."""


class FremdeDatei(BewertungFehler):
    """Neben dem Bild liegt eine XMP-Datei, die nicht von Silberkorn stammt."""


class UnlesbareDatei(FremdeDatei):
    """Neben dem Bild liegt eine Datei, die sich nicht deuten laesst - sie bleibt unberuehrt."""


@dataclass(frozen=True)
class Stand:
    """Die Bewertung eines Bildes: wert -1 (Ausschuss) bis 5; art "keine", "eigen", "fremd"
    (gueltige XMP eines anderen Programms) oder "unlesbar" (nicht zu deuten)."""
    wert: int = 0
    art: str = "keine"

    @property
    def aenderbar(self) -> bool:
        return self.art in ("keine", "eigen")


KEINE = Stand()
_UNLESBAR = Stand(0, "unlesbar")   # da, aber nicht zu deuten: bleibt unangetastet


def pfad_fuer(bild: str) -> str:
    return bild + ENDUNG


def _deuten(daten: bytes) -> Stand:
    try:
        wurzel = metadaten._xmp_wurzel(daten)
        beschreibungen = [] if wurzel is None else metadaten._beschreibungen(wurzel)
    except (ET.ParseError, ValueError, RecursionError, MemoryError):
        return _UNLESBAR
    if not beschreibungen:
        return _UNLESBAR
    angaben = []
    for beschreibung in beschreibungen:
        if _RATING in beschreibung.attrib:
            angaben.append(beschreibung.get(_RATING))
        for element in beschreibung.findall(_RATING):
            angaben.append(None if len(element) else element.text or "")
    wert = _ZAHLEN.get(angaben[0].strip(), 0) if len(angaben) == 1 and angaben[0] is not None \
        else 0                                 # fehlt, mehrfach oder keine Zahl: unbewertet
    beschreibung = beschreibungen[0]
    eigen = (len(beschreibungen) == 1 and not len(beschreibung)
             and set(beschreibung.attrib) <= _EIGENE_ATTRIBUTE
             and beschreibung.get(_KENNUNG) == KENNUNG
             and beschreibung.get(_WERKZEUG) == "Silberkorn")
    return Stand(wert, "eigen" if eigen else "fremd")


def lesen(bild: str) -> Stand:
    """Die Bewertung neben dem Bild: ein stat, gelesen wird nur, wenn die Datei da ist."""
    ziel = pfad_fuer(bild)
    try:
        info = os.lstat(ziel)
    except FileNotFoundError:
        return KEINE
    except OSError:
        return _UNLESBAR
    if not stat.S_ISREG(info.st_mode) or info.st_size > LESE_MAX:
        return _UNLESBAR                       # Ordner, Verknuepfung oder zu gross
    try:
        with open(ziel, "rb") as datei:
            daten = datei.read(LESE_MAX + 1)
    except OSError:
        return _UNLESBAR
    return _deuten(daten) if len(daten) <= LESE_MAX else _UNLESBAR


def lesen_viele(pfade: list[str], weiter: Callable[[], bool] | None = None) -> dict[str, Stand]:
    """Die Bewertungen vieler Bilder. weiter() == False bricht ab (ein neuer Ordner)."""
    ergebnis = {}
    for pfad in pfade:
        if weiter is not None and not weiter():
            break
        try:
            stand = lesen(pfad)
        except Exception:                      # noqa: BLE001 - nur dieses Bild gilt als unlesbar
            stand = _UNLESBAR
        if stand.art != "keine":
            ergebnis[pfad] = stand
    return ergebnis


def _pruefen(bild: str, ziel: str):
    """Wirft FremdeDatei oder UnlesbareDatei, wenn dort etwas liegt, das nicht Silberkorns ist."""
    art = lesen(bild).art
    if art == "unlesbar":
        raise UnlesbareDatei(ziel)
    if art == "fremd":
        raise FremdeDatei(ziel)


def schreiben(bild: str, wert: int) -> None:
    """Die Bewertung neben das Bild schreiben (-1 bis 5). FremdeDatei (UnlesbareDatei), wenn
    dort eine fremde oder nicht lesbare Datei liegt - sie bleibt unberuehrt; BewertungFehler,
    wenn es nicht geht."""
    if isinstance(wert, bool) or not isinstance(wert, int) or not AUSSCHUSS <= wert <= STERNE_MAX:
        raise ValueError(f"Bewertung ausserhalb von -1 bis 5: {wert!r}")
    ziel = pfad_fuer(bild)
    _pruefen(bild, ziel)
    ordner = os.path.dirname(os.path.abspath(ziel))
    try:
        griff, zwischen = tempfile.mkstemp(prefix=".silberkorn-bewertung-", suffix=".tmp",
                                           dir=ordner)
    except OSError as fehler:
        raise BewertungFehler(str(fehler)) from fehler
    try:
        with os.fdopen(griff, "wb") as datei:
            datei.write(VORLAGE.format(wert=wert).encode("utf-8"))
        _pruefen(bild, ziel)                   # inzwischen von einem anderen Programm angelegt
        os.replace(zwischen, ziel)
    except BaseException as fehler:
        try:
            os.remove(zwischen)
        except OSError:
            pass
        if isinstance(fehler, OSError):
            raise BewertungFehler(str(fehler)) from fehler
        raise


def fuer_bearbeiten(stand: Stand) -> int | None:
    """Was das Feld „Bewertung“ im Reiter Bearbeiten aus der eigenen Datei bekommt: ihre
    Sterne 0 bis 5 (auch 0 - die eigene Datei geht vor), bei Ausschuss 0 (keine Sterne).
    None bei fremder, unlesbarer oder fehlender Datei - dann gilt, was im Bild steht."""
    if stand.art != "eigen":
        return None
    return max(stand.wert, 0)


def sortiert(pfade: list[str], art: str, name_schluessel: Callable[[str], object],
             staende: dict[str, Stand], zeiten: dict[str, float]) -> list[str]:
    """Die Bilder nach "name", "datum" (neueste zuerst) oder "sterne" (meiste zuerst), bei
    Gleichstand nach Name. Ausschuss steht in jeder Sortierung am Ende."""
    def schluessel(pfad):
        wert = staende.get(pfad, KEINE).wert
        name = name_schluessel(os.path.basename(pfad))
        if art == "datum":
            return (wert == AUSSCHUSS, -zeiten.get(pfad, 0.0), name)
        if art == "sterne":
            return (wert == AUSSCHUSS, -wert, name)
        return (wert == AUSSCHUSS, name)
    return sorted(pfade, key=schluessel)
