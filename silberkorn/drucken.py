"""
Drucken: wo das Bild auf dem Blatt liegt und wie es zum Drucker kommt

Gerechnet wird in Millimetern auf dem ganzen Blatt, von der linken oberen
Ecke aus. Das Bild bekommt eine Flaeche - das bedruckbare Blatt abzueglich
eines Randes, oder ein festes Format wie 10 x 15 cm darin. Hoch- oder
Querformat folgt dem Bild. "Ganz zeigen" passt das Bild in die Flaeche ein,
"Flaeche fuellen" fuellt sie und beschneidet, was uebersteht, gleichmaessig.

Zum Drucker geht das Bild als sRGB mit 8 Bit, vorher genau auf die
Druckgroesse gebracht - mit hoechstens 300 Pixeln je Zoll: Das ist, was
Fotodrucker tatsaechlich aufloesen; feiner gerechnet wuerde nur der Auftrag
groesser. Den Farbabgleich mit Drucker und Papier uebernimmt der Treiber.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np

MM_JE_ZOLL = 25.4
DRUCK_DPI = 300                # so fein wird das Bild fuer den Drucker gerechnet, hoechstens
KNAPP_DPI = 200                # darunter kann der Druck weich wirken
PAPIER_VORGABE_MM = (101.6, 152.4)   # 10 x 15 cm, im Handel 4 x 6 Zoll
PAPIER_TOLERANZ_MM = 2.0
RAND_MAX_MM = 50

# Bildgroessen: Schluessel und (kurze, lange Seite) in mm; None ist die ganze Flaeche
FORMATE = {"seite": None, "9x13": (89.0, 127.0), "10x15": (101.6, 152.4),
           "13x18": (127.0, 178.0), "20x30": (203.0, 305.0), "eigen": None}
EIGEN_MIN_CM, EIGEN_MAX_CM = 2.0, 120.0


@dataclass
class Vorgaben:
    """Was der Druckdialog sich merkt."""
    drucker: str = ""              # leer: der Standarddrucker von Windows
    papier: str = ""               # Name beim Drucker; leer: 10 x 15 cm, wenn er es kann
    groesse: str = "seite"
    eigen_breite: float = 10.0     # cm, fuer „Eigene Größe“
    eigen_hoehe: float = 15.0
    fuellen: bool = False          # Flaeche fuellen und beschneiden statt ganz zeigen
    rand: float = 0.0              # mm zusaetzlich zum Rand, den der Drucker braucht
    randlos: bool = False

    @classmethod
    def aus_dict(cls, daten) -> Vorgaben:
        """Aus der Einstellungsdatei - Unbekanntes und Ungueltiges faellt auf die Vorgabe."""
        vorgaben = cls()
        if not isinstance(daten, dict):
            return vorgaben
        for feld in dataclasses.fields(cls):
            wert = daten.get(feld.name)
            vorgabe = getattr(vorgaben, feld.name)
            if isinstance(vorgabe, float) and type(wert) is int:
                wert = float(wert)
            if type(wert) is type(vorgabe):           # bool ist hier kein int
                setattr(vorgaben, feld.name, wert)
        return vorgaben.begrenzt()

    def als_dict(self) -> dict:
        return dataclasses.asdict(self)

    def begrenzt(self) -> Vorgaben:
        if self.groesse not in FORMATE:
            self.groesse = "seite"
        self.eigen_breite = min(max(self.eigen_breite, EIGEN_MIN_CM), EIGEN_MAX_CM)
        self.eigen_hoehe = min(max(self.eigen_hoehe, EIGEN_MIN_CM), EIGEN_MAX_CM)
        self.rand = min(max(self.rand, 0.0), float(RAND_MAX_MM))
        return self

    def format_mm(self) -> tuple[float, float] | None:
        """(Breite, Hoehe) der Bildgroesse in mm - None fuer die ganze Flaeche."""
        if self.groesse == "eigen":
            return self.eigen_breite * 10, self.eigen_hoehe * 10
        return FORMATE[self.groesse]


@dataclass(frozen=True)
class Platz:
    """Wo das Bild auf dem Blatt liegt."""
    ziel: tuple[float, float, float, float]      # x, y, Breite, Hoehe in mm auf dem Blatt
    ausschnitt: tuple[int, int, int, int]        # x0, y0, x1, y1 des Bildes, das gedruckt wird
    dpi: float                                   # Bildpixel je Zoll auf dem Papier
    verkleinert: bool = False                    # das Format passte nicht aufs Papier

    @property
    def knapp(self) -> bool:
        return self.dpi < KNAPP_DPI


def flaeche(blatt: tuple[float, float, float, float], rand: float) -> tuple[float, ...]:
    """Bedruckbarer Bereich (x, y, Breite, Hoehe in mm) abzueglich eines Randes."""
    x, y, breite, hoehe = blatt
    rand = min(rand, breite / 2 - 1, hoehe / 2 - 1)
    return x + rand, y + rand, breite - 2 * rand, hoehe - 2 * rand


def platzieren(bild_breite: int, bild_hoehe: int, flaeche_mm: tuple[float, ...],
               format_mm: tuple[float, float] | None = None, fuellen: bool = False) -> Platz:
    """Lage des Bildes (Pixel) in der Flaeche (x, y, Breite, Hoehe in mm).

    format_mm ist eine feste Bildgroesse; sie wird so gedreht, dass sie zum Bild
    passt, und verkleinert, wenn sie nicht in die Flaeche passt.
    """
    fx, fy, fb, fh = flaeche_mm
    kasten_b, kasten_h = fb, fh
    verkleinert = False
    if format_mm is not None:
        kurz, lang = sorted(format_mm)
        kasten_b, kasten_h = (lang, kurz) if bild_breite > bild_hoehe else (kurz, lang)
        faktor = min(1.0, fb / kasten_b, fh / kasten_h)
        if faktor < 0.999:
            verkleinert = True
            kasten_b, kasten_h = kasten_b * faktor, kasten_h * faktor
    x0, y0, x1, y1 = 0, 0, bild_breite, bild_hoehe
    if fuellen:
        # Den Kasten ganz fuellen: was uebersteht, faellt auf beiden Seiten gleich weg
        if bild_breite / bild_hoehe > kasten_b / kasten_h:
            breite = max(1, round(bild_hoehe * kasten_b / kasten_h))
            x0 = (bild_breite - breite) // 2
            x1 = x0 + breite
        else:
            hoehe = max(1, round(bild_breite * kasten_h / kasten_b))
            y0 = (bild_hoehe - hoehe) // 2
            y1 = y0 + hoehe
        ziel_b, ziel_h = kasten_b, kasten_h
    else:
        faktor = min(kasten_b / bild_breite, kasten_h / bild_hoehe)
        ziel_b, ziel_h = bild_breite * faktor, bild_hoehe * faktor
    ziel = (fx + (fb - ziel_b) / 2, fy + (fh - ziel_h) / 2, ziel_b, ziel_h)
    dpi = (x1 - x0) / (ziel_b / MM_JE_ZOLL)
    return Platz(ziel, (x0, y0, x1, y1), dpi, verkleinert)


def ki_faktor(platz: Platz) -> int:
    """Mit welchem Faktor KI-Hochskalieren das Bild auf KNAPP_DPI braechte (2 oder 4);
    0, wenn es ohne genuegt."""
    if not platz.knapp:
        return 0
    return 2 if platz.dpi * 2 >= KNAPP_DPI - 0.5 else 4


def passt_zur_vorgabe(breite_mm: float, hoehe_mm: float) -> bool:
    """Ist eine Papiergroesse 10 x 15 cm (in beiden Lagen)?"""
    kurz, lang = sorted((breite_mm, hoehe_mm))
    return (abs(kurz - PAPIER_VORGABE_MM[0]) <= PAPIER_TOLERANZ_MM
            and abs(lang - PAPIER_VORGABE_MM[1]) <= PAPIER_TOLERANZ_MM)


def druckpixel(platz: Platz, drucker_dpi: float) -> tuple[int, int]:
    """Breite und Hoehe, auf die das Bild fuer den Drucker gebracht wird."""
    dpi = min(drucker_dpi, DRUCK_DPI)
    _x, _y, breite, hoehe = platz.ziel
    return (max(1, round(breite / MM_JE_ZOLL * dpi)), max(1, round(hoehe / MM_JE_ZOLL * dpi)))


def vorbereiten(rgb: np.ndarray, platz: Platz, groesse: tuple[int, int],
                faktor: int = 1) -> np.ndarray:
    """Den Ausschnitt (bei KI-Vergroesserung um faktor groesser) auf groesse (B, H)
    bringen - Lanczos, auch beim Vergroessern."""
    from PIL import Image
    x0, y0, x1, y1 = (wert * faktor for wert in platz.ausschnitt)
    teil = np.ascontiguousarray(rgb[y0:y1, x0:x1])
    bild = Image.fromarray(teil, "RGB")
    if bild.size != groesse:
        bild = bild.resize(groesse, Image.Resampling.LANCZOS)
    return np.asarray(bild)


def drucken(drucker, rgb: np.ndarray, platz: Platz, faktor: int = 1):
    """Das Bild (sRGB, 8 Bit, H x W x 3) auf einen eingerichteten QPrinter drucken.
    Der Drucker muss mit setFullPage(True) eingerichtet sein - gerechnet wird ab der
    Ecke des Blattes."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColorSpace, QImage, QPainter

    groesse = druckpixel(platz, drucker.resolution())
    fertig = vorbereiten(rgb, platz, groesse, faktor)
    breite, hoehe = groesse
    bild = QImage(fertig.data, breite, hoehe, 3 * breite, QImage.Format.Format_RGB888).copy()
    bild.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    je_mm = drucker.resolution() / MM_JE_ZOLL
    x, y, b, h = platz.ziel
    maler = QPainter()
    if not maler.begin(drucker):
        raise OSError("Der Drucker hat den Auftrag nicht angenommen.")
    try:
        maler.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        maler.drawImage(QRectF(x * je_mm, y * je_mm, b * je_mm, h * je_mm), bild)
    finally:
        maler.end()
