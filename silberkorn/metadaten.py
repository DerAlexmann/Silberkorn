"""
Metadaten: EXIF, IPTC und XMP lesen, anzeigen und die beschreibenden Angaben aendern

Gelesen wird alles, was die Datei mitbringt: EXIF (auch aus RAW), IPTC-IIM (der
alte Block aus Photoshop-Zeiten) und XMP. Daraus folgen die Angaben, die sich
in Silberkorn aendern lassen - Titel, Beschreibung, Stichwoerter, Urheber,
Copyright, Ort, Aufnahmedatum und Bewertung. Gibt es eine Angabe mehrfach, gilt
XMP vor IPTC vor EXIF, so wie es auch Lightroom und Bridge halten.

Technische Werte (Belichtung, Blende, ISO ...) bleiben unveraendert: sie
beschreiben die Aufnahme.

Geaendert wird nichts in der Datei, sondern in den Einstellungen der Sitzung:
dort stehen nur die Aenderungen gegenueber der Datei, als sortiertes Tupel aus
(Feld, Wert). So zaehlen sie als ungespeicherte Aenderung und fallen mit
„Zurücksetzen“ weg. Erst beim Speichern werden sie geschrieben - nach XMP (IPTC
Core) und, wo es ein Gegenstueck gibt, auch nach EXIF. IPTC-IIM schreibt
Silberkorn nicht mehr; was nur dort stand, wandert beim Speichern nach XMP.

Das XMP der Datei wird beim Speichern weitergegeben, aber bereinigt: Drehung
und Bildgroesse stimmen nach der Bearbeitung nicht mehr, und Entwicklungs-
einstellungen von Lightroom oder darktable wuerden dort ein zweites Mal
angewendet.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import dataclasses
import datetime
import mmap
import re
import struct
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from PIL import ExifTags, Image

# --------------------------------------------------------------------------
# Die Angaben
# --------------------------------------------------------------------------

FELDER = ("titel", "beschreibung", "stichwoerter", "urheber", "copyright", "stadt", "region",
          "land", "datum", "bewertung")
BEWERTUNG_MAX = 5


@dataclass(frozen=True)
class Angaben:
    """Die beschreibenden Angaben eines Bildes - leer heisst nicht vorhanden."""
    titel: str = ""
    beschreibung: str = ""
    stichwoerter: tuple[str, ...] = ()
    urheber: str = ""                 # mehrere durch Semikolon getrennt
    copyright: str = ""
    stadt: str = ""
    region: str = ""                  # Bundesland, Kanton, Provinz
    land: str = ""
    datum: str = ""                   # JJJJ, JJJJ-MM, JJJJ-MM-TT oder mit hh:mm[:ss]
    bewertung: int = 0                # 0 bis 5 Sterne


def mit(basis: Angaben, aenderungen: tuple) -> Angaben:
    """Die Angaben der Datei mit den Aenderungen der Sitzung."""
    return dataclasses.replace(basis, **dict(aenderungen)) if aenderungen else basis


def aendern(aenderungen: tuple, basis: Angaben, name: str, wert) -> tuple:
    """Aenderungen mit einem neuen Wert - gleicht er dem der Datei, entfaellt er."""
    neu = dict(aenderungen)
    if wert == getattr(basis, name):
        neu.pop(name, None)
    else:
        neu[name] = wert
    return tuple(sorted(neu.items()))


def stichwoerter_lesen(text: str) -> tuple[str, ...]:
    """„Berlin, Herbst; Familie“ -> ("Berlin", "Herbst", "Familie"), ohne Doppelte."""
    gesehen: dict[str, None] = {}
    for wort in re.split(r"[,;\n]", text):
        wort = " ".join(wort.split())
        if wort and wort.casefold() not in {g.casefold() for g in gesehen}:
            gesehen[wort] = None
    return tuple(gesehen)


_DATUM_ISO = re.compile(r"(\d{4})(?:[-:.](\d{1,2})(?:[-:.](\d{1,2})(?:[ T](\d{1,2}):(\d{2})"
                        r"(?::(\d{2}))?)?)?)?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_DATUM_DE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:,?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")


def datum_lesen(text: str) -> str | None:
    """Ein Datum in der Form der Angaben: "" fuer leer, None, wenn es keins ist.
    Versteht 2024-05-17 14:03, 2024:05:17 (EXIF), 17.05.2024 und auch nur 1965
    oder 1965-07 - alte Abzuege haben oft kein genaueres Datum."""
    text = " ".join(text.split())
    if not text:
        return ""
    treffer = _DATUM_ISO.fullmatch(text)
    if treffer:
        jahr, monat, tag, stunde, minute, sekunde = treffer.groups()
    else:
        treffer = _DATUM_DE.fullmatch(text)
        if not treffer:
            return None
        tag, monat, jahr, stunde, minute, sekunde = treffer.groups()
    try:
        datetime.datetime(int(jahr), int(monat or 1), int(tag or 1), int(stunde or 0),
                          int(minute or 0), int(sekunde or 0))
    except ValueError:
        return None
    if int(jahr) < 1800:
        return None
    ergebnis = jahr
    if monat:
        ergebnis += f"-{int(monat):02d}"
    if tag:
        ergebnis += f"-{int(tag):02d}"
    if stunde is not None:
        ergebnis += f" {int(stunde):02d}:{minute}"
        if sekunde is not None:
            ergebnis += f":{sekunde}"
    return ergebnis


def _datum_exif(datum: str) -> str:
    """Datum der Angaben -> EXIF "JJJJ:MM:TT hh:mm:ss"; "" ohne vollstaendigen Tag."""
    if len(datum) < 10:
        return ""
    zeit = datum[11:] if len(datum) > 10 else "00:00"
    if len(zeit) == 5:
        zeit += ":00"
    return datum[:10].replace("-", ":") + " " + zeit


# --------------------------------------------------------------------------
# EXIF
# --------------------------------------------------------------------------

EXIF_IFD, GPS_IFD, INTEROP_IFD = 0x8769, 0x8825, 0xA005
BESCHREIBUNG, HERSTELLER, MODELL, AUSRICHTUNG = 0x010E, 0x010F, 0x0110, 0x0112
KUENSTLER, COPYRIGHT, BEWERTUNG, BEWERTUNG_PROZENT = 0x013B, 0x8298, 0x4746, 0x4749
XP_TITEL, XP_KOMMENTAR, XP_AUTOR, XP_STICHWOERTER, XP_THEMA = (0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E,
                                                                0x9C9F)
AUFNAHMEZEIT, BREITE, HOEHE, MAKERNOTE = 0x9003, 0xA002, 0xA003, 0x927C
BELICHTUNGSZEIT, BLENDE, ISO, BRENNWEITE, BRENNWEITE_KB = 0x829A, 0x829D, 0x8827, 0x920A, 0xA405
OBJEKTIV, OBJEKTIV_HERSTELLER = 0xA434, 0xA433

# Was aus dem ersten Verzeichnis (IFD0) mitkommt. Alles andere beschreibt den
# Aufbau der Quelldatei - Streifen, Bittiefe, Vorschaubilder von RAW - und
# waere im gespeicherten Bild falsch.
IFD0_BEHALTEN = {BESCHREIBUNG, HERSTELLER, MODELL, AUSRICHTUNG, 0x011A, 0x011B, 0x0128,
                 0x0131, 0x0132, KUENSTLER, COPYRIGHT, BEWERTUNG, BEWERTUNG_PROZENT, XP_TITEL,
                 XP_KOMMENTAR, XP_AUTOR, XP_STICHWOERTER, XP_THEMA, EXIF_IFD, GPS_IFD}
# Kameras schreiben das statt einer Beschreibung
LEERE_BESCHREIBUNGEN = {"", "OLYMPUS DIGITAL CAMERA", "SONY DSC", "DIGITAL CAMERA", "DCIM",
                        "DEFAULT", "<NO COMMENT>", "LEVEL 1 DIGITAL CAMERA"}
JPEG_EXIF_MAX = 65000              # APP1 fasst 64 KB


def exif_laden(exif: bytes) -> Image.Exif:
    daten = Image.Exif()
    if exif:
        try:
            daten.load(exif[6:] if exif.startswith(b"Exif\x00\x00") else exif)
        except (OSError, ValueError, SyntaxError, struct.error):
            return Image.Exif()
    return daten


def _unterverzeichnis(daten: Image.Exif, tag: int) -> dict:
    try:
        return daten.get_ifd(tag)
    except (KeyError, ValueError, TypeError, OSError, SyntaxError, struct.error):
        return {}


def einlesen(daten: Image.Exif) -> Image.Exif:
    """Die Unterverzeichnisse lesen, solange die Datei offen ist - bei TIFF holt Pillow
    sie sonst erst spaeter aus der dann geschlossenen Datei."""
    for tag in (EXIF_IFD, GPS_IFD):
        if tag in daten:
            _unterverzeichnis(daten, tag)
    return daten


def saeubern(daten: Image.Exif, raw: bool = False) -> bytes:
    """EXIF fuer die Sitzung: Drehung schon angewendet, nur beschreibende Felder in IFD0.
    Aus RAW faellt zudem die Herstellernotiz weg - ihre Verweise zielen in die RAW-Datei."""
    if not len(daten):
        return b""
    for tag in list(daten):
        if tag not in IFD0_BEHALTEN:
            del daten[tag]
    if AUSRICHTUNG in daten:
        daten[AUSRICHTUNG] = 1
    unter = _unterverzeichnis(daten, EXIF_IFD) if EXIF_IFD in daten else {}
    unter.pop(INTEROP_IFD, None)                 # selten gebraucht, Verweis wuerde falsch
    if raw:
        unter.pop(MAKERNOTE, None)
    try:
        roh = daten.tobytes()
    except (OSError, ValueError, TypeError, struct.error):
        return b""
    if len(roh) > JPEG_EXIF_MAX and MAKERNOTE in unter:
        unter.pop(MAKERNOTE)
        roh = daten.tobytes()
    return roh if len(daten) else b""


def _text(wert) -> str:
    if isinstance(wert, tuple) and all(isinstance(z, int) for z in wert):
        wert = bytes(wert)
    if isinstance(wert, bytes):
        wert = wert.decode("utf-8", "replace")
    return " ".join(str(wert).replace("\x00", " ").split()) if wert is not None else ""


def _xp_text(wert) -> str:
    """Windows-Felder (XPTitle ...): UTF-16LE als Bytefolge."""
    if isinstance(wert, tuple):
        wert = bytes(wert)
    if not isinstance(wert, bytes):
        return _text(wert)
    return " ".join(wert.decode("utf-16-le", "replace").replace("\x00", " ").split())


def ascii_text(text: str) -> str:
    """EXIF-Texte sind ASCII: © wird (C), Umlaute verlieren die Punkte."""
    text = text.replace("©", "(C)").replace("ß", "ss")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _aus_exif(daten: Image.Exif) -> dict:
    unter = _unterverzeichnis(daten, EXIF_IFD)
    werte = {}
    beschreibung = _text(daten.get(BESCHREIBUNG))
    if beschreibung.upper() not in LEERE_BESCHREIBUNGEN:
        werte["beschreibung"] = beschreibung
    werte["titel"] = _xp_text(daten.get(XP_TITEL))
    werte["urheber"] = _text(daten.get(KUENSTLER)) or _xp_text(daten.get(XP_AUTOR))
    # Copyright kann "Fotograf\0Bearbeiter" sein
    werte["copyright"] = _text(str(daten.get(COPYRIGHT, "")).split("\x00")[0])
    werte["stichwoerter"] = stichwoerter_lesen(_xp_text(daten.get(XP_STICHWOERTER)))
    datum = datum_lesen(_text(unter.get(AUFNAHMEZEIT)))
    werte["datum"] = datum or ""
    try:
        werte["bewertung"] = min(max(int(daten.get(BEWERTUNG, 0)), 0), BEWERTUNG_MAX)
    except (TypeError, ValueError):
        pass
    return {name: wert for name, wert in werte.items() if wert}


def exif_schreiben(exif: bytes, angaben: Angaben, geaendert, breite: int = 0,
                   hoehe: int = 0) -> bytes:
    """EXIF fuers gespeicherte Bild: geaenderte Angaben eingetragen, Bildgroesse richtig."""
    daten = exif_laden(exif)
    # get_ifd legte ein fehlendes Verzeichnis leer an - und Pillow schriebe es mit
    unter = _unterverzeichnis(daten, EXIF_IFD) if EXIF_IFD in daten else {}
    if breite and hoehe and (BREITE in unter or HOEHE in unter):
        unter[BREITE], unter[HOEHE] = breite, hoehe

    def setzen(tag, wert, ziel=daten):
        if wert:
            ziel[tag] = wert
        elif tag in ziel:
            del ziel[tag]

    if "beschreibung" in geaendert:
        setzen(BESCHREIBUNG, ascii_text(angaben.beschreibung))
        setzen(XP_KOMMENTAR, None)
    if "urheber" in geaendert:
        setzen(KUENSTLER, ascii_text(angaben.urheber))
        setzen(XP_AUTOR, None)
    if "copyright" in geaendert:
        setzen(COPYRIGHT, ascii_text(angaben.copyright))
    if "titel" in geaendert:
        setzen(XP_TITEL, None)                   # Windows liest dann den Titel aus XMP
    if "stichwoerter" in geaendert:
        setzen(XP_STICHWOERTER, None)
    if "bewertung" in geaendert:
        setzen(BEWERTUNG, angaben.bewertung)
        prozent = (0, 1, 25, 50, 75, 99)[angaben.bewertung]
        setzen(BEWERTUNG_PROZENT, prozent)
    if "datum" in geaendert and (_datum_exif(angaben.datum) or AUFNAHMEZEIT in unter):
        unter = _unterverzeichnis(daten, EXIF_IFD)
        setzen(AUFNAHMEZEIT, _datum_exif(angaben.datum), unter)
    if not len(daten) and not unter:
        return b""
    return daten.tobytes()


def exif_groesse(exif: bytes, breite: int, hoehe: int) -> bytes:
    """Die Bildgroesse in EXIF nachtragen - nach Verkleinern oder Zuschnitt."""
    return exif_schreiben(exif, Angaben(), (), breite, hoehe) if exif else exif


# --------------------------------------------------------------------------
# IPTC-IIM
# --------------------------------------------------------------------------

IIM = {"titel": (2, 5), "beschreibung": (2, 120), "stichwoerter": (2, 25), "urheber": (2, 80),
       "copyright": (2, 116), "stadt": (2, 90), "region": (2, 95), "land": (2, 101)}
IIM_DATUM, IIM_ZEIT, IIM_ZEICHENSATZ = (2, 55), (2, 60), (1, 90)
IIM_NAMEN = {(1, 90): "CodedCharacterSet", (2, 0): "RecordVersion", (2, 5): "ObjectName",
             (2, 10): "Urgency", (2, 15): "Category", (2, 20): "SupplementalCategories",
             (2, 25): "Keywords", (2, 40): "SpecialInstructions", (2, 55): "DateCreated",
             (2, 60): "TimeCreated", (2, 62): "DigitalCreationDate",
             (2, 63): "DigitalCreationTime", (2, 65): "OriginatingProgram", (2, 80): "By-line",
             (2, 85): "By-lineTitle", (2, 90): "City", (2, 92): "Sub-location",
             (2, 95): "Province-State", (2, 100): "Country-PrimaryLocationCode",
             (2, 101): "Country-PrimaryLocationName", (2, 103): "OriginalTransmissionReference",
             (2, 105): "Headline", (2, 110): "Credit", (2, 115): "Source",
             (2, 116): "CopyrightNotice", (2, 118): "Contact", (2, 120): "Caption-Abstract",
             (2, 122): "Writer-Editor"}


def iim_lesen(bild: Image.Image) -> dict:
    """IPTC-IIM eines geoeffneten Bildes (JPEG, TIFF) als {(Satz, Feld): [Bytes, ...]}."""
    from PIL import IptcImagePlugin
    try:
        roh = IptcImagePlugin.getiptcinfo(bild) or {}
    except (OSError, ValueError, SyntaxError, IndexError, KeyError, TypeError):
        return {}
    return {schluessel: list(wert) if isinstance(wert, list) else [wert]
            for schluessel, wert in roh.items() if isinstance(schluessel, tuple)}


def _iim_text(iptc: dict, schluessel) -> list[str]:
    utf8 = b"\x1b%G" in b"".join(iptc.get(IIM_ZEICHENSATZ, []))
    texte = []
    for roh in iptc.get(schluessel, []):
        if not isinstance(roh, bytes):
            continue
        try:
            text = roh.decode("utf-8")
        except UnicodeDecodeError:
            text = roh.decode("cp1252" if not utf8 else "utf-8", "replace")
        text = " ".join(text.replace("\x00", " ").split())
        if text:
            texte.append(text)
    return texte


def _aus_iim(iptc: dict) -> dict:
    werte = {}
    for name, schluessel in IIM.items():
        texte = _iim_text(iptc, schluessel)
        if name == "stichwoerter":
            werte[name] = stichwoerter_lesen(";".join(texte))
        elif name == "urheber":
            werte[name] = "; ".join(texte)
        elif texte:
            werte[name] = texte[0]
    tag = "".join(_iim_text(iptc, IIM_DATUM))
    zeit = "".join(_iim_text(iptc, IIM_ZEIT))
    if re.fullmatch(r"\d{8}", tag):
        text = f"{tag[:4]}-{tag[4:6]}-{tag[6:]}"
        if re.match(r"\d{6}", zeit):
            text += f" {zeit[:2]}:{zeit[2:4]}:{zeit[4:6]}"
        werte["datum"] = datum_lesen(text) or ""
    return {name: wert for name, wert in werte.items() if wert}


# --------------------------------------------------------------------------
# XMP
# --------------------------------------------------------------------------

NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "xmpRights": "http://ns.adobe.com/xap/1.0/rights/",
    "xmpMM": "http://ns.adobe.com/xap/1.0/mm/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "Iptc4xmpCore": "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/",
    "Iptc4xmpExt": "http://iptc.org/std/Iptc4xmpExt/2008-02-29/",
    "plus": "http://ns.useplus.org/ldf/xmp/1.0/",
    "tiff": "http://ns.adobe.com/tiff/1.0/",
    "exif": "http://ns.adobe.com/exif/1.0/",
    "exifEX": "http://cipa.jp/exif/1.0/",
    "aux": "http://ns.adobe.com/exif/1.0/aux/",
    "crs": "http://ns.adobe.com/camera-raw-settings/1.0/",
    "darktable": "http://darktable.sf.net/",
    "lr": "http://ns.adobe.com/lightroom/1.0/",
}
PRAEFIX = {uri: name for name, uri in NS.items()}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
for _name, _uri in NS.items():
    ET.register_namespace(_name, _uri)


def _q(praefix: str, name: str) -> str:
    return f"{{{NS[praefix]}}}{name}"


RDF = {name: _q("rdf", name) for name in ("RDF", "Description", "Alt", "Seq", "Bag", "li",
                                          "about", "parseType", "resource", "value")}

# Feld -> (Praefix, Name, Art): Art "alt" (Sprachvarianten), "seq", "bag" oder None
EIGENSCHAFTEN = {
    "titel": ("dc", "title", "alt"),
    "beschreibung": ("dc", "description", "alt"),
    "stichwoerter": ("dc", "subject", "bag"),
    "urheber": ("dc", "creator", "seq"),
    "copyright": ("dc", "rights", "alt"),
    "stadt": ("photoshop", "City", None),
    "region": ("photoshop", "State", None),
    "land": ("photoshop", "Country", None),
    "datum": ("photoshop", "DateCreated", None),
    "bewertung": ("xmp", "Rating", None),
}
# Was beim Weitergeben immer wegfaellt: stimmt nach der Bearbeitung nicht mehr
VERALTET = [("tiff", "Orientation"), ("tiff", "ImageWidth"), ("tiff", "ImageLength"),
            ("exif", "PixelXDimension"), ("exif", "PixelYDimension"),
            ("tiff", "BitsPerSample"), ("tiff", "Compression"),
            ("tiff", "PhotometricInterpretation"), ("tiff", "SamplesPerPixel"),
            ("photoshop", "ColorMode"), ("photoshop", "ICCProfile"),
            ("xmp", "Thumbnails")]
# ... samt allen Entwicklungseinstellungen
ENTWICKLUNG = ("crs", "darktable")
# Ohne GPS und Seriennummern speichern: nur diese Namensraeume bleiben - auch
# verschachtelt. Eine Sperrliste liesse GPS in Herstellerfeldern durch, etwa
# drone-dji:GpsLatitude in Fotos von DJI-Drohnen.
BESCHREIBEND = ("rdf", "dc", "xmp", "xmpRights", "photoshop", "Iptc4xmpCore", "Iptc4xmpExt",
                "plus")
XMP_MAX = 8 * 2**20


def xmp_suchen(pfad: str) -> bytes:
    """Das XMP-Paket irgendwo in der Datei - fuer RAW, die keine Bibliothek zerlegt."""
    try:
        with open(pfad, "rb") as datei, mmap.mmap(datei.fileno(), 0,
                                                  access=mmap.ACCESS_READ) as inhalt:
            anfang = inhalt.find(b"<x:xmpmeta")
            if anfang < 0:
                return b""
            ende = inhalt.find(b"</x:xmpmeta>", anfang)
            if ende < 0 or ende - anfang > XMP_MAX:
                return b""
            return bytes(inhalt[anfang:ende + len(b"</x:xmpmeta>")])
    except (OSError, ValueError):
        return b""


def xmp_aus_bild(bild: Image.Image) -> bytes:
    """Das XMP eines mit Pillow geoeffneten Bildes (JPEG, PNG, TIFF, WebP, AVIF, HEIF)."""
    wert = bild.info.get("xmp") or bild.info.get("XML:com.adobe.xmp") or b""
    if isinstance(wert, tuple) and len(wert) == 1:
        wert = wert[0]
    if isinstance(wert, str):
        wert = wert.encode("utf-8")
    return bytes(wert) if isinstance(wert, (bytes, bytearray)) else b""


def _xmp_wurzel(xmp: bytes) -> ET.Element | None:
    """Der Baum des Pakets - None, wenn es fehlt oder sich nicht sicher lesen laesst."""
    if not xmp or b"<!DOCTYPE" in xmp or b"<!ENTITY" in xmp or len(xmp) > XMP_MAX:
        return None
    for anfang, ende in ((b"<x:xmpmeta", b"</x:xmpmeta>"), (b"<x:xapmeta", b"</x:xapmeta>"),
                         (b"<rdf:RDF", b"</rdf:RDF>")):
        a = xmp.find(anfang)
        e = xmp.rfind(ende)
        if a >= 0 and e > a:
            try:
                wurzel = ET.fromstring(xmp[a:e + len(ende)])
            except ET.ParseError:
                return None
            return wurzel if _rdf(wurzel) is not None else None
    return None


def _rdf(wurzel: ET.Element) -> ET.Element | None:
    return wurzel if wurzel.tag == RDF["RDF"] else wurzel.find(RDF["RDF"])


def _beschreibungen(wurzel: ET.Element) -> list[ET.Element]:
    return list(_rdf(wurzel).findall(RDF["Description"]))


def _werte(element: ET.Element) -> list[str]:
    """Inhalt einer Eigenschaft: Alt (x-default zuerst), Seq, Bag oder einfacher Text."""
    for art in ("Alt", "Seq", "Bag"):
        behaelter = element.find(RDF[art])
        if behaelter is not None:
            punkte = behaelter.findall(RDF["li"])
            if art == "Alt":
                punkte.sort(key=lambda li: li.get(XML_LANG) != "x-default")
                punkte = punkte[:1]
            return [" ".join((li.text or "").split()) for li in punkte if (li.text or "").strip()]
    text = element.get(RDF["resource"]) or element.text or ""
    return [" ".join(text.split())] if text.strip() else []


def _xmp_eigenschaft(wurzel: ET.Element, praefix: str, name: str) -> list[str] | None:
    schluessel = _q(praefix, name)
    for beschreibung in _beschreibungen(wurzel):
        if schluessel in beschreibung.attrib:
            return [beschreibung.get(schluessel)]
        element = beschreibung.find(schluessel)
        if element is not None:
            return _werte(element)
    return None


def _aus_xmp(wurzel: ET.Element | None) -> dict:
    if wurzel is None:
        return {}
    werte = {}
    for feld, (praefix, name, _art) in EIGENSCHAFTEN.items():
        inhalt = _xmp_eigenschaft(wurzel, praefix, name)
        if inhalt is None and feld == "datum":
            inhalt = _xmp_eigenschaft(wurzel, "exif", "DateTimeOriginal")
        if inhalt is None:
            continue
        if feld == "stichwoerter":
            werte[feld] = stichwoerter_lesen(";".join(inhalt))
        elif feld == "urheber":
            werte[feld] = "; ".join(inhalt)
        elif feld == "datum":
            werte[feld] = datum_lesen(inhalt[0]) if inhalt else ""
        elif feld == "bewertung":
            try:
                werte[feld] = min(max(int(float(inhalt[0])), 0), BEWERTUNG_MAX)
            except (ValueError, IndexError):
                pass
        elif inhalt:
            werte[feld] = inhalt[0]
    return {name: wert for name, wert in werte.items() if wert}


def eigenschaft(praefix: str, name: str, wert, art: str | None = None) -> ET.Element:
    """Eine XMP-Eigenschaft als Element; art wie in EIGENSCHAFTEN."""
    element = ET.Element(_q(praefix, name))
    if art is None:
        element.text = str(wert)
        return element
    behaelter = ET.SubElement(element, RDF[{"alt": "Alt", "seq": "Seq", "bag": "Bag"}[art]])
    for eintrag in (wert if isinstance(wert, (tuple, list)) else [wert]):
        li = ET.SubElement(behaelter, RDF["li"])
        li.text = str(eintrag)
        if art == "alt":
            li.set(XML_LANG, "x-default")
    return element


def angaben_eigenschaften(angaben: Angaben, felder) -> dict:
    """Die Angaben als XMP-Eigenschaften {(Praefix, Name): Element oder None (entfernen)}."""
    ergebnis = {}
    for feld in felder:
        praefix, name, art = EIGENSCHAFTEN[feld]
        wert = getattr(angaben, feld)
        if feld == "urheber":
            wert = tuple(teil.strip() for teil in wert.split(";") if teil.strip())
        elif feld == "datum":
            wert = wert.replace(" ", "T")
        ergebnis[(praefix, name)] = eigenschaft(praefix, name, wert, art) if wert else None
        if feld == "datum":
            # Lightroom traegt die Aufnahmezeit auch hier ein - sie soll nicht widersprechen
            voll = _datum_exif(angaben.datum)
            ergebnis[("exif", "DateTimeOriginal")] = (
                eigenschaft("exif", "DateTimeOriginal", angaben.datum.replace(" ", "T"))
                if voll else None)
    return ergebnis


def _entfernen(element: ET.Element, weg) -> None:
    """Eigenschaften (als Attribut oder Kindelement) in einem Element und darunter entfernen."""
    for schluessel in [s for s in element.attrib if weg(s)]:
        del element.attrib[schluessel]
    for kind in list(element):
        if weg(kind.tag):
            element.remove(kind)
        else:
            _entfernen(kind, weg)


def xmp_aendern(xmp: bytes, eigenschaften: dict, bereinigen: bool = False,
                weitergeben: bool = True) -> bytes:
    """XMP-Paket mit diesen Eigenschaften: das der Datei (bereinigt), sonst ein neues.

    eigenschaften: {(Praefix, Name): Element oder None} - None entfernt die Eigenschaft.
    bereinigen behaelt nur beschreibende Namensraeume (BESCHREIBEND) - ohne GPS,
    Seriennummern und Kameradaten in welchem Namensraum auch immer. Ohne Eigenschaften und ohne
    weitergebbares Paket: b""."""
    wurzel = _xmp_wurzel(xmp) if weitergeben else None
    if wurzel is None:
        wurzel = ET.Element(_q("x", "xmpmeta"))
        ET.SubElement(wurzel, RDF["RDF"])
    elif wurzel.tag == RDF["RDF"]:
        huelle = ET.Element(_q("x", "xmpmeta"))
        huelle.append(wurzel)
        wurzel = huelle
    rdf = _rdf(wurzel)
    beschreibungen = _beschreibungen(wurzel)
    if not beschreibungen:
        beschreibungen = [ET.SubElement(rdf, RDF["Description"], {RDF["about"]: ""})]

    veraltet = {_q(p, n) for p, n in VERALTET}
    namensraeume = tuple(f"{{{NS[p]}}}" for p in ENTWICKLUNG)
    erlaubt = tuple(f"{{{NS[p]}}}" for p in BESCHREIBEND) + ("{http://www.w3.org/XML/",)
    geaendert = {_q(p, n) for p, n in eigenschaften}

    def weg(schluessel: str) -> bool:
        if schluessel in veraltet or schluessel in geaendert or schluessel.startswith(
                namensraeume):
            return True
        return bereinigen and schluessel.startswith("{") and not schluessel.startswith(erlaubt)

    for beschreibung in beschreibungen:
        _entfernen(beschreibung, weg)
        if beschreibung is not beschreibungen[0] and not len(beschreibung) and all(
                s in (RDF["about"],) for s in beschreibung.attrib):
            rdf.remove(beschreibung)
    for element in eigenschaften.values():
        if element is not None:
            beschreibungen[0].append(element)
    if not any(len(b) or set(b.attrib) - {RDF["about"]} for b in _beschreibungen(wurzel)):
        return b""
    ET.indent(wurzel, space=" ")
    inhalt = ET.tostring(wurzel, encoding="unicode")
    return ('<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n' + inhalt
            + '\n<?xpacket end="w"?>').encode("utf-8")


def _felder_in_xmp(wurzel: ET.Element | None) -> set[str]:
    if wurzel is None:
        return set()
    return {feld for feld, (praefix, name, _art) in EIGENSCHAFTEN.items()
            if _xmp_eigenschaft(wurzel, praefix, name) is not None}


# --------------------------------------------------------------------------
# Lesen und Speichern
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Vorgefunden:
    """Die Angaben der Datei und woher jede stammt ("xmp", "iptc", "exif")."""
    angaben: Angaben
    herkunft: tuple                   # ((Feld, Quelle), ...)
    formate: tuple[str, ...]          # was die Datei enthaelt: "EXIF", "IPTC", "XMP"


def lesen(exif: bytes, xmp: bytes, iptc: dict) -> Vorgefunden:
    """Die Angaben aus allen drei Quellen - XMP vor IPTC vor EXIF."""
    wurzel = _xmp_wurzel(xmp)
    werte, herkunft = {}, {}
    for quelle, gefunden in (("exif", _aus_exif(exif_laden(exif))), ("iptc", _aus_iim(iptc)),
                             ("xmp", _aus_xmp(wurzel))):
        for name, wert in gefunden.items():
            werte[name] = wert
            herkunft[name] = quelle
    formate = tuple(name for name, da in (("EXIF", bool(exif)), ("IPTC", bool(iptc)),
                                          ("XMP", wurzel is not None)) if da)
    return Vorgefunden(Angaben(**werte), tuple(sorted(herkunft.items())), formate)


def fuer_speichern(exif: bytes, xmp: bytes, vorgefunden: Vorgefunden, aenderungen: tuple,
                   breite: int, hoehe: int, bereinigen: bool = False) -> tuple[bytes, bytes]:
    """EXIF und XMP fuers gespeicherte Bild.

    In EXIF und XMP kommen die geaenderten Angaben; ins XMP ausserdem, was nur im
    alten IPTC-Block stand - den schreibt Silberkorn nicht. bereinigen nimmt GPS und
    Seriennummern aus beidem."""
    from . import anonym
    angaben = mit(vorgefunden.angaben, aenderungen)
    geaendert = {name for name, _wert in aenderungen}
    exif_neu = exif_schreiben(exif, angaben, geaendert, breite, hoehe)
    if bereinigen:
        exif_neu = anonym.metadaten_bereinigen(exif_neu)
    in_xmp = _felder_in_xmp(_xmp_wurzel(xmp))
    nur_iptc = {name for name, quelle in vorgefunden.herkunft
                if quelle == "iptc" and name not in in_xmp}
    xmp_neu = xmp_aendern(xmp, angaben_eigenschaften(angaben, geaendert | nur_iptc), bereinigen)
    return exif_neu, xmp_neu


# --------------------------------------------------------------------------
# Anzeigen
# --------------------------------------------------------------------------

def _zahl(wert) -> float | None:
    try:
        zahl = float(wert)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return zahl if zahl == zahl and zahl not in (float("inf"), float("-inf")) else None


def _kurz(zahl: float) -> str:
    return f"{zahl:.1f}".rstrip("0").rstrip(".")


def ueberblick(exif: bytes) -> dict[str, str]:
    """Kamera, Objektiv und Belichtung in Kurzform - fuer die Karte."""
    daten = exif_laden(exif)
    unter = _unterverzeichnis(daten, EXIF_IFD)
    hersteller, modell = _text(daten.get(HERSTELLER)), _text(daten.get(MODELL))
    if hersteller and modell.lower().startswith(hersteller.split()[0].lower()):
        hersteller = ""                      # "Canon Canon EOS R5" vermeiden
    ergebnis = {"kamera": " ".join(teil for teil in (hersteller, modell) if teil),
                "objektiv": _text(unter.get(OBJEKTIV))}
    teile = []
    zeit = _zahl(unter.get(BELICHTUNGSZEIT))
    if zeit:
        teile.append(f"1/{_kurz(1 / zeit)} s" if zeit < 0.5 else f"{_kurz(zeit)} s")
    blende = _zahl(unter.get(BLENDE))
    if blende:
        teile.append(f"f/{_kurz(blende)}")
    iso = unter.get(ISO)
    if isinstance(iso, tuple):
        iso = iso[0] if iso else None
    if _zahl(iso):
        teile.append(f"ISO {int(_zahl(iso))}")
    brennweite = _zahl(unter.get(BRENNWEITE))
    if brennweite:
        teile.append(f"{_kurz(brennweite)} mm")
    ergebnis["belichtung"] = " · ".join(teile)
    return {name: wert for name, wert in ergebnis.items() if wert}


def _anzeige(wert) -> str:
    if isinstance(wert, bytes):
        if len(wert) > 96 or any(z < 9 for z in wert.rstrip(b"\x00")):
            return f"({len(wert)} Bytes)"
        return _text(wert)
    if isinstance(wert, tuple):
        if len(wert) > 16:
            return f"({len(wert)} Werte)"
        return ", ".join(_anzeige(teil) for teil in wert)
    zahl = _zahl(wert) if not isinstance(wert, (int, str)) else None
    if zahl is not None:
        return f"{zahl:.6g}"
    return _text(wert)


def _xmp_name(schluessel: str) -> str:
    if schluessel.startswith("{"):
        uri, name = schluessel[1:].split("}", 1)
        return f"{PRAEFIX.get(uri, uri.rstrip('/#').rsplit('/', 1)[-1])}:{name}"
    return schluessel


def _xmp_flach(element: ET.Element, vorne: str, liste: list) -> None:
    for schluessel, wert in element.attrib.items():
        if schluessel not in (RDF["about"], RDF["parseType"]):
            liste.append((vorne + _xmp_name(schluessel), " ".join(wert.split())))
    for kind in element:
        name = vorne + _xmp_name(kind.tag)
        behaelter = next((kind.find(RDF[a]) for a in ("Alt", "Seq", "Bag")
                          if kind.find(RDF[a]) is not None), None)
        if behaelter is not None:
            punkte = behaelter.findall(RDF["li"])
            if all(not len(li) for li in punkte):
                liste.append((name, "; ".join(" ".join((li.text or "").split())
                                              for li in punkte)))
                continue
            for nummer, li in enumerate(punkte, 1):
                _xmp_flach(li.find(RDF["Description"]) if li.find(RDF["Description"])
                           is not None else li, f"{name}[{nummer}]/", liste)
        elif len(kind):
            innen = kind.find(RDF["Description"])
            _xmp_flach(innen if innen is not None else kind, name + "/", liste)
        else:
            liste.append((name, " ".join((kind.text or kind.get(RDF["resource"], "")).split())))


def eintraege(exif: bytes, xmp: bytes, iptc: dict) -> list[tuple[str, str, str]]:
    """Alle Metadaten als (Gruppe, Name, Wert) - fuer die Anzeige, nur lesend."""
    liste = []
    daten = exif_laden(exif)
    for tag, wert in daten.items():
        if tag not in (EXIF_IFD, GPS_IFD):
            name = ExifTags.TAGS.get(tag, f"0x{tag:04X}")
            liste.append(("EXIF", name, _xp_text(wert) if 0x9C9B <= tag <= 0x9C9F
                          else _anzeige(wert)))
    for tag, wert in _unterverzeichnis(daten, EXIF_IFD).items():
        if tag != INTEROP_IFD:
            liste.append(("EXIF", ExifTags.TAGS.get(tag, f"0x{tag:04X}"), _anzeige(wert)))
    for tag, wert in _unterverzeichnis(daten, GPS_IFD).items():
        liste.append(("GPS", ExifTags.GPSTAGS.get(tag, f"0x{tag:04X}"), _anzeige(wert)))
    for schluessel in sorted(iptc):
        name = IIM_NAMEN.get(schluessel, f"{schluessel[0]}:{schluessel[1]}")
        texte = _iim_text(iptc, schluessel)
        liste.append(("IPTC", name, "; ".join(texte) if texte else _anzeige(
            b"".join(t for t in iptc[schluessel] if isinstance(t, bytes)))))
    wurzel = _xmp_wurzel(xmp)
    if wurzel is not None:
        xmp_liste: list = []
        for beschreibung in _beschreibungen(wurzel):
            _xmp_flach(beschreibung, "", xmp_liste)
        liste += [("XMP", name, wert) for name, wert in xmp_liste]
    return liste
