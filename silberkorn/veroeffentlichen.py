"""
Fuer Veroeffentlichung speichern: verkleinern, Wasserzeichen, Rechteangaben

Fuer Bilder, die ins Netz gehen: verkleinert (nie vergroessert), mit sichtbarem
Wasserzeichen aus Text und/oder Logo und mit Urheber, Copyright und Webadresse
in den Metadaten - EXIF fuer Programme, die nur EXIF lesen, XMP nach IPTC fuer
alle anderen. Auf Wunsch steht dort auch, dass das Bild nicht fuer KI-Training
und Data-Mining verwendet werden darf (IPTC/PLUS "Data Mining"; Suchmaschinen
duerfen es weiter finden). Enthaelt das Bild von der KI erfundene Teile
(Erweitern, Objekte entfernen), wird das ebenfalls vermerkt (IPTC "Digital
Source Type"). Titel, Beschreibung und Stichwoerter aus der Metadaten-Karte
kommen mit; Ort, Aufnahmedatum und Bewertung nur, wenn die Kameradaten bleiben.

Alle Groessen des Wasserzeichens sind Anteile des Bildes. So sieht die kleine
Vorschau im Dialog genauso aus wie das gespeicherte Bild.

Gerechnet wird mit NumPy und Pillow auf dem Prozessor: Das Ergebnis ist klein,
und so bleibt der Grafikspeicher fuer die Bearbeitung frei.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import anonym, bilddatei, metadaten

GROESSEN_ART = ("kante", "prozent")
KANTEN = (1280, 1920, 2560)          # Schnellwahl der laengsten Kante
KANTE_MIN, KANTE_MAX = 64, 20000
POSITIONEN = ("unten_rechts", "unten_links", "oben_rechts", "oben_links", "mitte")
TEXTFARBEN = ("weiss", "schwarz")
FORMATE = (".jpg", ".png", ".webp")
QUALITAET = 90                       # JPEG und WebP: fuers Netz reicht das
RAND = 0.03                          # Abstand zum Bildrand: Anteil der kuerzeren Kante
MUSTER_WINKEL = 30                   # Grad, gegen den Uhrzeigersinn
SCHRIFT_PX = 160                     # Text wird so gross gezeichnet und dann skaliert
SCHRIFTEN = ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")

EXIF_KUENSTLER = 0x013B
EXIF_COPYRIGHT = 0x8298

# IPTC Photo Metadata 2023.1: Data Mining (Vokabular von PLUS) und Digital Source Type
DATA_MINING = "http://ns.useplus.org/ldf/vocab/DMI-PROHIBITED-EXCEPTSEARCHENGINEINDEXING"
KI_QUELLE = ("http://cv.iptc.org/newscodes/digitalsourcetype/"
             "compositeWithTrainedAlgorithmicMedia")
KI_VERBOT_TEXT = ("No use for training artificial intelligence or for text and data "
                  "mining without permission (search engine indexing is allowed).")


@dataclass
class Vorlage:
    """Die Einstellungen des Dialogs - als Vorlage in silberkorn.json gespeichert."""
    groesse_art: str = "kante"
    kante: int = 1920
    prozent: int = 50
    text: str = ""
    logo: str = ""                   # Pfad zu einem Bild, am besten PNG mit Transparenz
    position: str = "unten_rechts"
    wz_groesse: int = 20             # Breite des Wasserzeichens in % der Bildbreite
    deckkraft: int = 60              # %
    muster: bool = False             # ueber das ganze Bild wiederholt
    textfarbe: str = "weiss"
    urheber: str = ""
    copyright: str = ""
    webadresse: str = ""
    ki_training_verbieten: bool = True
    kameradaten_entfernen: bool = True
    format: str = ".jpg"

    @classmethod
    def aus_dict(cls, daten) -> Vorlage:
        """Aus der Einstellungsdatei - Unbekanntes und Ungueltiges faellt auf die Vorgabe."""
        vorlage = cls()
        if not isinstance(daten, dict):
            return vorlage
        for feld in dataclasses.fields(cls):
            wert = daten.get(feld.name)
            vorgabe = getattr(vorlage, feld.name)
            if type(wert) is type(vorgabe):           # bool ist hier kein int
                setattr(vorlage, feld.name, wert)
        return vorlage.begrenzt()

    def als_dict(self) -> dict:
        return dataclasses.asdict(self)

    def begrenzt(self) -> Vorlage:
        auswahl = {"groesse_art": GROESSEN_ART, "position": POSITIONEN,
                   "textfarbe": TEXTFARBEN, "format": FORMATE}
        for name, erlaubt in auswahl.items():
            if getattr(self, name) not in erlaubt:
                setattr(self, name, erlaubt[0])
        self.kante = min(max(self.kante, KANTE_MIN), KANTE_MAX)
        self.prozent = min(max(self.prozent, 1), 100)
        self.wz_groesse = min(max(self.wz_groesse, 5), 80)
        self.deckkraft = min(max(self.deckkraft, 10), 100)
        return self

    @property
    def mit_wasserzeichen(self) -> bool:
        return bool(self.text.strip() or self.logo)


# --------------------------------------------------------------------------
# Groesse
# --------------------------------------------------------------------------

def zielgroesse(hoehe: int, breite: int, vorlage: Vorlage) -> tuple[int, int]:
    """Hoehe und Breite des veroeffentlichten Bildes - nie groesser als das Original."""
    if vorlage.groesse_art == "prozent":
        faktor = vorlage.prozent / 100
    else:
        faktor = vorlage.kante / max(hoehe, breite)
    if faktor >= 1:
        return hoehe, breite
    return max(1, round(hoehe * faktor)), max(1, round(breite * faktor))


def verkleinern(ebenen: np.ndarray, hoehe: int, breite: int) -> np.ndarray:
    """Float32 (H, W) oder (H, W, K) 0..1 mit Lanczos auf die neue Groesse."""
    if ebenen.shape[:2] == (hoehe, breite):
        return ebenen
    einzeln = ebenen[..., None] if ebenen.ndim == 2 else ebenen
    kanaele = [np.asarray(Image.fromarray(np.ascontiguousarray(einzeln[..., k]), "F")
                          .resize((breite, hoehe), Image.LANCZOS, reducing_gap=3.0))
               for k in range(einzeln.shape[2])]
    ergebnis = np.clip(np.stack(kanaele, axis=-1), 0, 1)
    return ergebnis[..., 0] if ebenen.ndim == 2 else ergebnis


def als_float(pixel: np.ndarray) -> np.ndarray:
    hoechst = 65535.0 if pixel.dtype == np.uint16 else 255.0
    return pixel.astype(np.float32) / np.float32(hoechst)


def als_8bit(ebenen: np.ndarray) -> np.ndarray:
    return (np.clip(ebenen, 0, 1) * 255 + 0.5).astype(np.uint8)


# --------------------------------------------------------------------------
# Wasserzeichen
# --------------------------------------------------------------------------

def _schrift(groesse: int):
    for name in SCHRIFTEN:
        try:
            return ImageFont.truetype(name, groesse)
        except OSError:
            continue
    return ImageFont.load_default(groesse)


def _text_bild(text: str, farbe: str) -> Image.Image:
    """Der Text als RGBA mit weichem Schatten in der Gegenfarbe - lesbar auf jedem Grund."""
    schrift = _schrift(SCHRIFT_PX)
    links, oben, rechts, unten = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox(
        (0, 0), text, font=schrift)
    rand = SCHRIFT_PX // 6
    groesse = (rechts - links + 2 * rand, unten - oben + 2 * rand)
    ort = (rand - links, rand - oben)
    vorn, hinten = ((255, 255, 255), (0, 0, 0)) if farbe == "weiss" else \
        ((0, 0, 0), (255, 255, 255))

    schatten = Image.new("L", groesse, 0)
    versatz = max(1, SCHRIFT_PX // 40)
    ImageDraw.Draw(schatten).text((ort[0] + versatz, ort[1] + versatz), text, font=schrift,
                                  fill=150)
    schatten = schatten.filter(ImageFilter.GaussianBlur(SCHRIFT_PX / 30))
    bild = Image.new("RGBA", groesse, (*hinten, 0))
    bild.putalpha(schatten)
    schrift_ebene = Image.new("L", groesse, 0)
    ImageDraw.Draw(schrift_ebene).text(ort, text, font=schrift, fill=255)
    bild.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", groesse, vorn).split(),
                                              schrift_ebene)))
    return bild


def logo_laden(pfad: str) -> Image.Image | None:
    """Das Logo als RGBA - None, wenn die Datei fehlt oder kein Bild ist."""
    if not pfad or not os.path.isfile(pfad):
        return None
    try:
        with Image.open(pfad) as roh:
            return roh.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def zeichen_bild(vorlage: Vorlage, logo: Image.Image | None = None) -> Image.Image | None:
    """Logo und Text nebeneinander als ein RGBA-Bild in Zeichengroesse, None ohne beides."""
    text = vorlage.text.strip()
    teile = []
    if logo is not None:
        teile.append(logo)
    if text:
        teile.append(_text_bild(text, vorlage.textfarbe))
    if not teile:
        return None
    if len(teile) == 2:
        # Logo so hoch wie der Text samt Schattenrand
        hoehe = teile[1].height
        teile[0] = teile[0].resize((max(1, round(logo.width * hoehe / logo.height)), hoehe),
                                   Image.LANCZOS)
        abstand = SCHRIFT_PX // 6
        gesamt = Image.new("RGBA", (teile[0].width + abstand + teile[1].width, hoehe))
        gesamt.alpha_composite(teile[0], (0, 0))
        gesamt.alpha_composite(teile[1], (teile[0].width + abstand, 0))
        return gesamt
    return teile[0]


def _ebene(hoehe: int, breite: int, vorlage: Vorlage, zeichen: Image.Image) -> Image.Image:
    """RGBA-Ebene in Bildgroesse mit dem Wasserzeichen an seinem Platz."""
    ziel_b = max(4, round(breite * vorlage.wz_groesse / 100))
    ziel_h = max(1, round(zeichen.height * ziel_b / zeichen.width))
    marke = zeichen.resize((ziel_b, ziel_h), Image.LANCZOS)
    ebene = Image.new("RGBA", (breite, hoehe))
    if vorlage.muster:
        marke = marke.rotate(MUSTER_WINKEL, Image.BICUBIC, expand=True)
        schritt_x = max(8, round(marke.width * 1.5))
        schritt_y = max(8, round(marke.height * 1.3))
        for zeile, y in enumerate(range(-schritt_y // 2, hoehe, schritt_y)):
            x0 = -schritt_x // 2 + (schritt_x // 2 if zeile % 2 else 0)
            for x in range(x0, breite, schritt_x):
                ebene.alpha_composite(_beschnitten(marke, x, y, breite, hoehe),
                                      (max(x, 0), max(y, 0)))
        return ebene
    rand = round(min(hoehe, breite) * RAND)
    x = {"unten_rechts": breite - rand - marke.width, "oben_rechts": breite - rand - marke.width,
         "unten_links": rand, "oben_links": rand}.get(vorlage.position,
                                                     (breite - marke.width) // 2)
    y = {"unten_rechts": hoehe - rand - marke.height, "unten_links": hoehe - rand - marke.height,
         "oben_rechts": rand, "oben_links": rand}.get(vorlage.position,
                                                     (hoehe - marke.height) // 2)
    ebene.alpha_composite(_beschnitten(marke, x, y, breite, hoehe), (max(x, 0), max(y, 0)))
    return ebene


def _beschnitten(marke: Image.Image, x: int, y: int, breite: int, hoehe: int) -> Image.Image:
    """Den Teil der Marke, der bei (x, y) ins Bild faellt - alpha_composite will das so."""
    links, oben = max(0, -x), max(0, -y)
    rechts = min(marke.width, breite - x)
    unten = min(marke.height, hoehe - y)
    if rechts <= links or unten <= oben:
        return Image.new("RGBA", (1, 1))
    return marke.crop((links, oben, rechts, unten))


def wasserzeichen(rgb: np.ndarray, alpha: np.ndarray | None, vorlage: Vorlage,
                  zeichen: Image.Image | None) -> tuple[np.ndarray, np.ndarray | None]:
    """Wasserzeichen auf float32 (H, W, 3) 0..1 legen; ein Alphakanal wird mit gedeckt."""
    if zeichen is None:
        return rgb, alpha
    hoehe, breite = rgb.shape[:2]
    ebene = np.asarray(_ebene(hoehe, breite, vorlage, zeichen), dtype=np.float32) / 255
    deckung = ebene[..., 3:] * np.float32(vorlage.deckkraft / 100)
    rgb = rgb * (1 - deckung) + ebene[..., :3] * deckung
    if alpha is not None:
        alpha = alpha + deckung[..., 0] * (1 - alpha)
    return rgb, alpha


# --------------------------------------------------------------------------
# Metadaten
# --------------------------------------------------------------------------

def _rechte(vorlage: Vorlage, angaben: metadaten.Angaben | None) -> tuple[str, str]:
    """Urheber und Copyright: aus der Vorlage, sonst aus den Angaben des Bildes."""
    angaben = angaben or metadaten.Angaben()
    return (vorlage.urheber.strip() or angaben.urheber.strip(),
            vorlage.copyright.strip() or angaben.copyright.strip())


def exif_daten(exif: bytes, vorlage: Vorlage, angaben: metadaten.Angaben | None = None) -> bytes:
    """EXIF fuers Netz: ohne GPS und Seriennummern, auf Wunsch ganz ohne Kameradaten,
    dazu Urheber, Copyright und Beschreibung."""
    daten = Image.Exif()
    if exif and not vorlage.kameradaten_entfernen:
        daten = metadaten.exif_laden(anonym.metadaten_bereinigen(exif))
    urheber, rechte = _rechte(vorlage, angaben)
    if urheber:
        daten[EXIF_KUENSTLER] = metadaten.ascii_text(urheber)
    if rechte:
        daten[EXIF_COPYRIGHT] = metadaten.ascii_text(rechte)
    if angaben is not None and angaben.beschreibung:
        daten[metadaten.BESCHREIBUNG] = metadaten.ascii_text(angaben.beschreibung)
    return daten.tobytes() if len(daten) else b""


def xmp_daten(vorlage: Vorlage, ki_inhalt: bool = False,
              angaben: metadaten.Angaben | None = None) -> bytes:
    """XMP-Paket nach IPTC: Urheber, Rechte, Webadresse, KI-Trainingsverbot, KI-Inhalt
    und die Angaben des Bildes."""
    angaben = angaben or metadaten.Angaben()
    urheber, rechte = _rechte(vorlage, angaben)
    adresse = vorlage.webadresse.strip()
    felder = ["titel", "beschreibung", "stichwoerter"]
    if not vorlage.kameradaten_entfernen:
        felder += ["stadt", "region", "land", "datum", "bewertung"]
    angaben = dataclasses.replace(angaben, urheber="", copyright="")
    neu = {schluessel: element for schluessel, element
           in metadaten.angaben_eigenschaften(angaben, felder).items() if element is not None}
    e = metadaten.eigenschaft
    if urheber:
        neu[("dc", "creator")] = e("dc", "creator", urheber, "seq")
        neu[("photoshop", "Credit")] = e("photoshop", "Credit", urheber)
    if rechte:
        neu[("dc", "rights")] = e("dc", "rights", rechte, "alt")
        neu[("photoshop", "CopyrightFlag")] = e("photoshop", "CopyrightFlag", "True")
    if urheber or rechte:
        neu[("xmpRights", "Marked")] = e("xmpRights", "Marked", "True")
    if adresse:
        neu[("xmpRights", "WebStatement")] = e("xmpRights", "WebStatement", adresse)
        kontakt = e("Iptc4xmpCore", "CreatorContactInfo", "")
        kontakt.text = None
        kontakt.set(metadaten.RDF["parseType"], "Resource")
        kontakt.append(e("Iptc4xmpCore", "CiUrlWork", adresse))
        neu[("Iptc4xmpCore", "CreatorContactInfo")] = kontakt
    if vorlage.ki_training_verbieten:
        neu[("plus", "DataMining")] = e("plus", "DataMining", DATA_MINING)
        neu[("plus", "OtherConstraints")] = e("plus", "OtherConstraints", KI_VERBOT_TEXT, "alt")
    if ki_inhalt:
        neu[("Iptc4xmpExt", "DigitalSourceType")] = e("Iptc4xmpExt", "DigitalSourceType",
                                                      KI_QUELLE)
    return metadaten.xmp_aendern(b"", neu, weitergeben=False)


# --------------------------------------------------------------------------
# Alles zusammen
# --------------------------------------------------------------------------

def bearbeiten(rgb: np.ndarray, alpha: np.ndarray | None, vorlage: Vorlage,
               zeichen: Image.Image | None) -> tuple[np.ndarray, np.ndarray | None]:
    """sRGB uint8/uint16 -> verkleinert und mit Wasserzeichen, als uint8."""
    hoehe, breite = zielgroesse(*rgb.shape[:2], vorlage)
    bild = verkleinern(als_float(rgb), hoehe, breite)
    ebene = None if alpha is None else verkleinern(als_float(alpha), hoehe, breite)
    bild, ebene = wasserzeichen(bild, ebene, vorlage, zeichen)
    return als_8bit(bild), None if ebene is None else als_8bit(ebene)


def speichern(pfad: str, rgb: np.ndarray, alpha: np.ndarray | None, exif: bytes,
              vorlage: Vorlage, ki_inhalt: bool = False,
              angaben: metadaten.Angaben | None = None) -> tuple[int, int]:
    """Das fertige Bild fuers Netz speichern; Rueckgabe: Breite und Hoehe."""
    zeichen = zeichen_bild(vorlage, logo_laden(vorlage.logo))
    bild, ebene = bearbeiten(rgb, alpha, vorlage, zeichen)
    exif = metadaten.exif_groesse(exif, bild.shape[1], bild.shape[0])
    bilddatei.speichern(pfad, bild, ebene, exif_daten(exif, vorlage, angaben),
                        xmp=xmp_daten(vorlage, ki_inhalt, angaben), qualitaet=QUALITAET)
    return bild.shape[1], bild.shape[0]
