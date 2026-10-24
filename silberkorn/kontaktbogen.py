"""
Kontaktbogen: viele Bilder als Raster auf Papier oder in eine PDF-Datei

Wie der Kontaktabzug aus der Dunkelkammer - eine Uebersicht ueber einen
Ordner. Jedes Bild steht ganz in einer quadratischen Zelle, darunter
Dateiname und Sterne; oben auf jeder Seite der Ordner und "Seite n/m".

Gerechnet wird in Millimetern auf dem Blatt wie beim Drucken. Die Bilder
kommen mit ihrer Bearbeitung aus der Begleitdatei (ohne KI-Ergebnisse, die
stehen dort nicht), so gross gerechnet, wie die Zelle bei 300 dpi braucht -
mehr loest kein Drucker auf.

Ausgegeben wird Seite fuer Seite: Ein ganzer Ordner in Druckaufloesung passte
nicht in den Speicher. Bricht der Anwender ab, verwirft der Drucker den
Auftrag; eine PDF entsteht zuerst unter einem Zwischennamen und ersetzt die
Zieldatei erst, wenn sie fertig ist.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

from . import bewertung
from .drucken import DRUCK_DPI, MM_JE_ZOLL

SPALTEN_MIN, SPALTEN_MAX = 2, 8
RAND_MM = 5.0                 # zusaetzlich zum Rand, den der Drucker braucht
KOPF_MM = 9.0                 # Kopfzeile mit Ordner und Seitenzahl
KOPF_SCHRIFT_MM = 3.5
ABSTAND_MM = 3.0              # zwischen den Zellen
TEXT_MM = 4.0                 # Zeile unter dem Bild
TEXT_SCHRIFT_MM = 2.4         # etwa 7 Punkt
PLATZHALTER = (225, 225, 225)   # Zelle eines Bildes, das sich nicht laden liess


class Abbruch(Exception):
    """Der Anwender hat abgebrochen."""


@dataclass
class Vorgaben:
    """Was der Kontaktbogen sich merkt (Schluessel "kontaktbogen" der Einstellungen)."""
    drucker: str = ""              # leer: der Standarddrucker; drucken_dialog.PDF: PDF-Datei
    papier: str = ""               # leer: A4, wenn der Drucker es kann
    quer: bool = False
    spalten: int = 4
    ausschuss_weglassen: bool = True

    @classmethod
    def aus_dict(cls, daten) -> Vorgaben:
        """Aus der Einstellungsdatei - Unbekanntes und Ungueltiges faellt auf die Vorgabe."""
        vorgaben = cls()
        if not isinstance(daten, dict):
            return vorgaben
        for feld in dataclasses.fields(cls):
            wert = daten.get(feld.name)
            if type(wert) is type(getattr(vorgaben, feld.name)):   # bool ist hier kein int
                setattr(vorgaben, feld.name, wert)
        return vorgaben.begrenzt()

    def als_dict(self) -> dict:
        return dataclasses.asdict(self)

    def begrenzt(self) -> Vorgaben:
        self.spalten = min(max(self.spalten, SPALTEN_MIN), SPALTEN_MAX)
        return self


def ist_a4(breite_mm: float, hoehe_mm: float) -> bool:
    kurz, lang = sorted((breite_mm, hoehe_mm))
    return abs(kurz - 210.0) <= 2.0 and abs(lang - 297.0) <= 2.0


@dataclass(frozen=True)
class Raster:
    """Lage der Zellen auf einer Seite, alles in mm ab der Ecke des Blattes."""
    flaeche: tuple[float, float, float, float]   # x, y, Breite, Hoehe ohne Kopfzeile
    kopf: tuple[float, float, float, float]
    spalten: int
    zeilen: int
    kante: float                                 # Seite des quadratischen Bildfelds

    @property
    def je_seite(self) -> int:
        return self.spalten * self.zeilen

    def seiten(self, anzahl: int) -> int:
        return max(1, math.ceil(anzahl / self.je_seite))

    def kante_px(self) -> int:
        """So viele Pixel braucht das Bildfeld bei 300 dpi."""
        return max(64, round(self.kante / MM_JE_ZOLL * DRUCK_DPI))

    def zelle(self, stelle: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """Bildfeld und Textzeile (x, y, Breite, Hoehe) der Zelle an dieser Stelle der
        Seite, zeilenweise von links oben."""
        zeile, spalte = divmod(stelle, self.spalten)
        x0, y0 = self.flaeche[:2]
        x = x0 + spalte * (self.kante + ABSTAND_MM)
        y = y0 + zeile * (self.kante + TEXT_MM + ABSTAND_MM)
        return (x, y, self.kante, self.kante), (x, y + self.kante, self.kante, TEXT_MM)


def raster(bedruckbar: tuple[float, float, float, float], spalten: int) -> Raster:
    """Das Raster im bedruckbaren Bereich (x, y, Breite, Hoehe in mm)."""
    x, y, breite, hoehe = bedruckbar
    rand = min(RAND_MM, breite / 4, hoehe / 4)
    x, y, breite, hoehe = x + rand, y + rand, breite - 2 * rand, hoehe - 2 * rand
    spalten = min(max(spalten, SPALTEN_MIN), SPALTEN_MAX)
    kante = max(1.0, (breite - (spalten - 1) * ABSTAND_MM) / spalten)
    frei = hoehe - KOPF_MM
    zeilen = max(1, math.floor((frei + ABSTAND_MM) / (kante + TEXT_MM + ABSTAND_MM)))
    # Passt bei sehr breitem Papier keine ganze Zeile, wird das Bildfeld kleiner
    kante = min(kante, max(1.0, frei - TEXT_MM))
    return Raster((x, y + KOPF_MM, breite, frei), (x, y, breite, KOPF_MM - 2.0),
                  spalten, zeilen, kante)


def beschriftung(name: str, stand: bewertung.Stand) -> str:
    if stand.wert == bewertung.AUSSCHUSS:
        return f"{name}  ✕"
    return f"{name}  {'★' * stand.wert}" if stand.wert > 0 else name


def auswahl(eintraege: list[tuple[str, bewertung.Stand]], ausschuss_weglassen: bool
            ) -> list[tuple[str, bewertung.Stand]]:
    if not ausschuss_weglassen:
        return list(eintraege)
    return [(pfad, stand) for pfad, stand in eintraege if stand.wert != bewertung.AUSSCHUSS]


# --------------------------------------------------------------------------
# Zeichnen - fuer die Vorschau und fuer den Drucker dasselbe
# --------------------------------------------------------------------------

def seite_zeichnen(maler, je_mm: float, gitter: Raster, kopf_links: str, kopf_rechts: str,
                   zellen: list[tuple[object, str]]):
    """Eine Seite: Kopfzeile und je Zelle (QImage, QPixmap oder None, Text).
    je_mm: Geraetepixel je Millimeter."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPen, QPixmap

    def rechteck(x, y, b, h):
        return QRectF(x * je_mm, y * je_mm, b * je_mm, h * je_mm)

    def schrift(mm: float, fett: bool = False) -> QFont:
        font = QFont(maler.font())
        font.setPixelSize(max(1, round(mm * je_mm)))
        font.setBold(fett)
        return font

    maler.save()
    maler.setPen(QPen(QColor(0, 0, 0)))
    kopf = rechteck(*gitter.kopf)
    maler.setFont(schrift(KOPF_SCHRIFT_MM, True))
    links = QFontMetricsF(maler.font()).elidedText(kopf_links, Qt.TextElideMode.ElideMiddle,
                                                  kopf.width() * 0.75)
    maler.drawText(kopf, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, links)
    maler.setFont(schrift(KOPF_SCHRIFT_MM))
    maler.drawText(kopf, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   kopf_rechts)

    maler.setFont(schrift(TEXT_SCHRIFT_MM))
    masse = QFontMetricsF(maler.font())
    for stelle, (bild, text) in enumerate(zellen):
        feld, zeile = gitter.zelle(stelle)
        ziel = rechteck(*feld)
        if bild is None or bild.isNull():
            maler.fillRect(ziel, QColor(*PLATZHALTER))
        else:
            faktor = min(ziel.width() / bild.width(), ziel.height() / bild.height())
            b, h = bild.width() * faktor, bild.height() * faktor
            # Unten buendig: der Name steht direkt unter jedem Bild, auch unter Querformaten
            platz = QRectF(ziel.x() + (ziel.width() - b) / 2, ziel.bottom() - h, b, h)
            if isinstance(bild, QPixmap):
                maler.drawPixmap(platz, bild, QRectF(bild.rect()))
            else:
                maler.drawImage(platz, bild)
        unten = rechteck(*zeile)
        maler.drawText(unten, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                       masse.elidedText(text, Qt.TextElideMode.ElideMiddle, unten.width()))
    maler.restore()


def zellbild(pfad: str, kante: int):
    """Das Bild mit seiner Bearbeitung aus der Begleitdatei, die laengste Kante etwa
    `kante` Pixel - als QImage in sRGB. Wirft die Fehler des Ladens."""
    import numpy as np
    from PySide6.QtGui import QColorSpace, QImage

    from . import bilddatei
    from .bearbeitung import Sitzung
    from .cuda import cupy as cp
    from .stapel import Ergebnis, Stapel

    sitzung = Sitzung(bilddatei.laden(pfad), kante)
    try:
        Stapel._begleitdatei_uebernehmen(sitzung, Ergebnis(pfad))
        rgb, _ms, _histogramm = sitzung.vorschau()
    finally:
        sitzung.schliessen()
        cp.get_default_memory_pool().free_all_blocks()
    rgb = np.ascontiguousarray(rgb[..., :3])
    hoehe, breite = rgb.shape[:2]
    bild = QImage(rgb.data, breite, hoehe, 3 * breite, QImage.Format.Format_RGB888).copy()
    bild.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    return bild


def ausgeben(drucker, gitter: Raster, eintraege: list[tuple[str, bewertung.Stand]],
             kopf_links: str, seite_text, fortschritt, laden=zellbild
             ) -> list[tuple[str, str]]:
    """Alle Seiten auf einen eingerichteten QPrinter (setFullPage(True)). seite_text(n, m)
    ergibt den Text oben rechts, fortschritt(name, anteil) -> False bricht ab (Abbruch).
    Rueckgabe: (Pfad, Grund) der Bilder, die sich nicht laden liessen - sie bleiben grau.
    Bei jedem Fehler und beim Abbruch verwirft der Drucker den Auftrag."""
    import os

    from PySide6.QtGui import QPainter

    from . import begleitdatei, bilddatei
    from .cuda import cupy as cp

    fehler = (bilddatei.BildFehler, begleitdatei.BegleitFehler, OSError, ValueError,
              MemoryError)
    if cp is not None:
        fehler += (cp.cuda.memory.OutOfMemoryError, cp.cuda.runtime.CUDARuntimeError)
    je_mm = drucker.resolution() / MM_JE_ZOLL
    kante = gitter.kante_px()
    seiten = gitter.seiten(len(eintraege))
    fehlt: list[tuple[str, str]] = []
    maler = QPainter()
    if not maler.begin(drucker):
        raise OSError("Der Drucker hat den Auftrag nicht angenommen.")
    try:
        maler.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        maler.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        maler.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        for seite in range(seiten):
            if seite > 0 and not drucker.newPage():
                raise OSError("Der Drucker hat keine neue Seite angenommen.")
            teil = eintraege[seite * gitter.je_seite:(seite + 1) * gitter.je_seite]
            zellen = []
            for nummer, (pfad, stand) in enumerate(teil, seite * gitter.je_seite):
                name = os.path.basename(pfad)
                if not fortschritt(name, nummer / max(1, len(eintraege))):
                    raise Abbruch
                try:
                    bild = laden(pfad, kante)
                except fehler as grund:
                    bild = None
                    fehlt.append((pfad, str(grund) or type(grund).__name__))
                zellen.append((bild, beschriftung(name, stand)))
            seite_zeichnen(maler, je_mm, gitter, kopf_links, seite_text(seite + 1, seiten),
                           zellen)
            del zellen
    except BaseException:
        drucker.abort()                    # nichts Halbfertiges drucken
        maler.end()
        raise
    maler.end()
    if drucker.printerState() == drucker.PrinterState.Error:
        raise OSError("Der Drucker meldet einen Fehler.")
    return fehlt
