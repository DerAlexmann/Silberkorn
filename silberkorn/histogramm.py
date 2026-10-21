"""
Histogramm-Feld: Rot, Gruen, Blau und Helligkeit des Bildes, dazu die Warnungen vor
abgeschnittenen Tiefen und Lichtern

Zwei kleine Dreiecke oben links (Tiefen) und oben rechts (Lichter) schalten die
Warnung ein und aus; sie sind gefuellt, sobald im Bild wirklich Pixel am Anschlag
sind - auch bei ausgeschalteter Warnung. Die Markierung im Bild zeichnet die Sitzung
(abschneiden.py), nicht dieses Feld.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

from . import farben
from .uebersetzung import _

HOEHE = 70
DREIECK = 11                 # Kantenlaenge der Dreiecke
DREIECK_RAND = 4             # Abstand zur Ecke des Feldes
TREFFER = 8                  # so weit um ein Dreieck herum zaehlt der Klick noch

# Rot, Gruen und Blau: Farbrolle im Farbschema (wie bei den Kurven) und Deckkraft
KANALFARBE = (("DANGER", 105), ("OK", 105), ("ACCENT", 105))


class HistogrammFeld(QWidget):
    warnung_geaendert = Signal(bool, bool)       # Lichter, Tiefen

    def __init__(self, breite: int):
        super().__init__()
        self.setObjectName("histogramm")
        self.setFixedSize(breite, HOEHE)
        self.setMouseTracking(True)
        self.histogramm: np.ndarray | None = None
        self.abgeschnitten: tuple[int, int] = (0, 0)     # Pixel (Lichter, Tiefen)
        self.lichter = False
        self.tiefen = False

    # ------------------------------------------------------------------
    # Zustand
    # ------------------------------------------------------------------

    def daten_setzen(self, histogramm: np.ndarray | None,
                     abgeschnitten: tuple[int, int] | None = None):
        self.histogramm = histogramm
        self.abgeschnitten = ((0, 0) if histogramm is None or abgeschnitten is None
                              else abgeschnitten)
        self.update()

    def warnung_setzen(self, lichter: bool, tiefen: bool, melden: bool = False):
        if (lichter, tiefen) == (self.lichter, self.tiefen):
            return
        self.lichter, self.tiefen = lichter, tiefen
        self.update()
        if melden:
            self.warnung_geaendert.emit(lichter, tiefen)

    def beide_umschalten(self):
        """Beide an, wenn nicht beide an sind, sonst beide aus (Taste J)."""
        an = not (self.lichter and self.tiefen)
        self.warnung_setzen(an, an, melden=True)

    # ------------------------------------------------------------------
    # Dreiecke
    # ------------------------------------------------------------------

    def _dreieck(self, tiefen: bool) -> QPolygonF:
        """Die Spitze zeigt in die Ecke des Feldes - links fuer die Tiefen, rechts fuer
        die Lichter."""
        rand, d = DREIECK_RAND, DREIECK
        if tiefen:
            punkte = [(rand, rand), (rand + d, rand), (rand, rand + d)]
        else:
            rechts = self.width() - rand
            punkte = [(rechts, rand), (rechts - d, rand), (rechts, rand + d)]
        return QPolygonF([QPointF(x, y) for x, y in punkte])

    def _dreieck_bei(self, position: QPointF) -> str | None:
        for name, tiefen in (("tiefen", True), ("lichter", False)):
            feld = self._dreieck(tiefen).boundingRect().adjusted(
                -TREFFER, -TREFFER, TREFFER, TREFFER)
            if feld.contains(position):
                return name
        return None

    def mousePressEvent(self, ereignis):             # noqa: N802 - Qt-Name
        if ereignis.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            return
        ziel = self._dreieck_bei(ereignis.position())
        if ziel == "tiefen":
            self.warnung_setzen(self.lichter, not self.tiefen, melden=True)
        elif ziel == "lichter":
            self.warnung_setzen(not self.lichter, self.tiefen, melden=True)

    def mouseMoveEvent(self, ereignis):              # noqa: N802 - Qt-Name
        ueber = self.isEnabled() and self._dreieck_bei(ereignis.position()) is not None
        self.setCursor(Qt.CursorShape.PointingHandCursor if ueber
                       else Qt.CursorShape.ArrowCursor)

    def event(self, ereignis):
        # Jedes Dreieck hat seinen eigenen Hinweis; der Text entsteht erst jetzt, damit er
        # zur gerade gewaehlten Sprache passt
        if ereignis.type() == QEvent.Type.ToolTip:
            ziel = self._dreieck_bei(QPointF(ereignis.pos()))
            if ziel is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(ereignis.globalPos(), self.hinweis(ziel), self)
            return True
        return super().event(ereignis)

    def hinweis(self, ziel: str) -> str:
        if ziel == "tiefen":
            return str(_("Warnung vor abgeschnittenen Tiefen: färbt sie im Bild blau "
                         "(Taste J schaltet beide Warnungen)"))
        return str(_("Warnung vor abgeschnittenen Lichtern: färbt sie im Bild rot "
                     "(Taste J schaltet beide Warnungen)"))

    # ------------------------------------------------------------------
    # Zeichnen
    # ------------------------------------------------------------------

    def paintEvent(self, ereignis):                  # noqa: N802 - Qt-Name
        rollen = farben.THEMES[farben.CURRENT_THEME]
        maler = QPainter(self)
        maler.setRenderHint(QPainter.RenderHint.Antialiasing)
        feld = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        maler.fillRect(feld, QColor(rollen["CARD_ALT"]))

        daten = self.histogramm
        if daten is not None and daten.shape == (4, 256) and daten.max() > 0:
            # Wurzel statt linear, wie bei der Gradationskurve: sonst schluckt ein Berg
            # alles andere. Alle Linien teilen einen Massstab, damit sie vergleichbar sind.
            hoehen = np.sqrt(daten / daten.max())
            for kanal, (rolle, deckung) in enumerate(KANALFARBE):
                farbe = QColor(rollen[rolle])
                farbe.setAlpha(deckung)
                maler.fillPath(self._pfad(hoehen[kanal], feld, schliessen=True), farbe)
            linie = QColor(rollen["TEXT"])
            linie.setAlpha(210)
            maler.setPen(QPen(linie, 1.2))
            maler.setBrush(Qt.BrushStyle.NoBrush)
            maler.drawPath(self._pfad(hoehen[3], feld, schliessen=False))

        maler.setPen(QPen(QColor(rollen["BORDER"]), 1))
        maler.setBrush(Qt.BrushStyle.NoBrush)
        maler.drawRect(feld)

        lichter, tiefen = self.abgeschnitten
        for ist_tiefen, an, anzahl, rolle in ((True, self.tiefen, tiefen, "ACCENT"),
                                              (False, self.lichter, lichter, "DANGER")):
            if not self.isEnabled():
                kontur, fuellung = QColor(rollen["BTN_DISABLED"]), None
            elif anzahl:
                kontur = QColor(rollen["TEXT"] if an else rollen[rolle])
                fuellung = QColor(rollen[rolle])
            else:
                kontur = QColor(rollen["TEXT"] if an else rollen["MUTED"])
                fuellung = QColor(rollen["TEXT"]) if an else None
            # Aktiv: kraeftige Kontur; so ist die Warnung auch am gefuellten Dreieck zu sehen
            maler.setPen(QPen(kontur, 1.8 if an and self.isEnabled() else 1.0))
            maler.setBrush(fuellung if fuellung is not None else Qt.BrushStyle.NoBrush)
            maler.drawPolygon(self._dreieck(ist_tiefen))
        maler.end()

    @staticmethod
    def _pfad(hoehen, feld: QRectF, schliessen: bool) -> QPainterPath:
        pfad = QPainterPath()
        unten, nutz = feld.bottom(), feld.height() * 0.92
        spanne = len(hoehen)
        if schliessen:
            pfad.moveTo(feld.left(), unten)
        for i, h in enumerate(hoehen):
            x = feld.left() + (i + 0.5) / spanne * feld.width()
            y = unten - float(h) * nutz
            if i == 0 and not schliessen:
                pfad.moveTo(x, y)
            else:
                pfad.lineTo(x, y)
        if schliessen:
            pfad.lineTo(feld.right(), unten)
            pfad.closeSubpath()
        return pfad
