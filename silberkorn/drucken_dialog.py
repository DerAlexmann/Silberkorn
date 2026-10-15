"""
Dialog "Drucken": Drucker, Papier und Bildgröße mit Vorschau auf dem Blatt

Die Vorschau zeigt das Blatt mit dem Bild darauf, so wie es aus dem Drucker
kommt: Lage, Ränder und - bei "Fläche füllen" - der Beschnitt. Gedruckt wird
danach das Bild in voller Auflösung (bearbeitung.Sitzung.druckbild).

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPen
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import drucken
from .drucken import Platz, Vorgaben
from .uebersetzung import _

VORSCHAU = 380                 # Kante der Vorschau des Blattes in Pixeln


def format_titel() -> list[tuple[str, str]]:
    return [("seite", _("Seite füllen")), ("9x13", "9 × 13 cm"), ("10x15", "10 × 15 cm"),
            ("13x18", "13 × 18 cm"), ("20x30", "20 × 30 cm"), ("eigen", _("Eigene Größe"))]


def cm(wert_mm: float) -> str:
    text = f"{wert_mm / 10:.1f}"
    return f"{text.replace('.', ',') if _.language == 'de' else text} cm"


class Blatt(QWidget):
    """Das Blatt mit dem Bild darauf, verkleinert."""

    def __init__(self, vorschau: np.ndarray):
        super().__init__()
        self.setFixedSize(VORSCHAU, VORSCHAU)
        hoehe, breite = vorschau.shape[:2]
        rgb = np.ascontiguousarray(vorschau[..., :3])
        self._bild = QImage(rgb.data, breite, hoehe, 3 * breite,
                            QImage.Format.Format_RGB888).copy()
        self.groesse_mm = (101.6, 152.4)
        self.bedruckbar: tuple[float, ...] = (0.0, 0.0, 101.6, 152.4)
        self.platz: Platz | None = None
        self.volle_breite = breite              # Platz.ausschnitt ist in Pixeln des Vollbildes

    def paintEvent(self, _ereignis):             # noqa: N802 - Qt-Name
        breite_mm, hoehe_mm = self.groesse_mm
        je_mm = (VORSCHAU - 24) / max(breite_mm, hoehe_mm)
        b, h = breite_mm * je_mm, hoehe_mm * je_mm
        ox, oy = (VORSCHAU - b) / 2, (VORSCHAU - h) / 2
        maler = QPainter(self)
        maler.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        maler.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        maler.setPen(Qt.PenStyle.NoPen)
        maler.setBrush(QColor(0, 0, 0, 40))
        maler.drawRect(QRectF(ox + 3, oy + 3, b, h))         # Schatten
        maler.setBrush(QColor(255, 255, 255))
        maler.setPen(QPen(QColor(0, 0, 0, 90), 1))
        maler.drawRect(QRectF(ox, oy, b, h))
        x, y, bb, bh = self.bedruckbar
        maler.setBrush(Qt.BrushStyle.NoBrush)
        maler.setPen(QPen(QColor(0, 0, 0, 60), 1, Qt.PenStyle.DashLine))
        maler.drawRect(QRectF(ox + x * je_mm, oy + y * je_mm, bb * je_mm, bh * je_mm))
        if self.platz is not None:
            x, y, zb, zh = self.platz.ziel
            m = self._bild.width() / self.volle_breite
            x0, y0, x1, y1 = self.platz.ausschnitt
            quelle = QRectF(x0 * m, y0 * m, (x1 - x0) * m, (y1 - y0) * m)
            maler.drawImage(QRectF(ox + x * je_mm, oy + y * je_mm, zb * je_mm, zh * je_mm),
                            self._bild, quelle)
        maler.end()


class DruckenDialog(QDialog):
    def __init__(self, eltern, vorschau: np.ndarray, volle_form: tuple[int, int],
                 vorgaben: Vorgaben, ki_moeglich: bool = False):
        super().__init__(eltern)
        self.setWindowTitle(_("Drucken"))
        self._hoehe, self._breite = volle_form
        self._ki_moeglich = ki_moeglich
        self._drucker: QPrinter | None = None
        self._drucker_name = None
        self._platz: Platz | None = None

        aufbau = QVBoxLayout(self)
        oben = QHBoxLayout()
        oben.setSpacing(12)
        links = QVBoxLayout()
        links.addWidget(self._einstellungen_karte())
        links.addStretch(1)
        oben.addLayout(links)
        rechts = QVBoxLayout()
        self.blatt = Blatt(vorschau)
        self.blatt.volle_breite = self._breite
        rechts.addWidget(self.blatt)
        self.info = QLabel(objectName="nebentext", alignment=Qt.AlignmentFlag.AlignCenter)
        self.info.setWordWrap(True)
        rechts.addWidget(self.info)
        rechts.addStretch(1)
        oben.addLayout(rechts, 1)
        aufbau.addLayout(oben, 1)

        knoepfe = QHBoxLayout()
        knoepfe.addStretch(1)
        abbrechen = QPushButton(_("Abbrechen"))
        abbrechen.clicked.connect(self.reject)
        self.drucken_knopf = QPushButton(_("Drucken"), objectName="hauptschalter")
        self.drucken_knopf.setDefault(True)
        self.drucken_knopf.clicked.connect(self.accept)
        knoepfe.addWidget(abbrechen)
        knoepfe.addWidget(self.drucken_knopf)
        aufbau.addLayout(knoepfe)

        self._setzen(vorgaben)
        self._verbinden()
        self._aktualisieren()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------

    def _einstellungen_karte(self) -> QFrame:
        karte = QFrame(objectName="karte")
        innen = QVBoxLayout(karte)
        innen.setContentsMargins(16, 12, 16, 14)
        innen.addWidget(QLabel(_("Drucken"), objectName="kartentitel"))
        gitter = QGridLayout()
        gitter.setColumnStretch(1, 1)
        gitter.setVerticalSpacing(6)

        self.drucker_wahl = QComboBox()
        for name in QPrinterInfo.availablePrinterNames():
            self.drucker_wahl.addItem(name, name)
        gitter.addWidget(QLabel(_("Drucker")), 0, 0)
        gitter.addWidget(self.drucker_wahl, 0, 1, 1, 2)
        self.papier_wahl = QComboBox()
        gitter.addWidget(QLabel(_("Papier")), 1, 0)
        gitter.addWidget(self.papier_wahl, 1, 1, 1, 2)

        self.groesse_wahl = QComboBox()
        for wert, titel in format_titel():
            self.groesse_wahl.addItem(titel, wert)
        gitter.addWidget(QLabel(_("Bildgröße")), 2, 0)
        gitter.addWidget(self.groesse_wahl, 2, 1, 1, 2)
        self.eigen_zeile = QWidget()
        zeile = QHBoxLayout(self.eigen_zeile)
        zeile.setContentsMargins(0, 0, 0, 0)
        self.eigen_breite, self.eigen_hoehe = (self._cm_feld(), self._cm_feld())
        zeile.addWidget(self.eigen_breite)
        zeile.addWidget(QLabel("×"))
        zeile.addWidget(self.eigen_hoehe)
        zeile.addStretch(1)
        gitter.addWidget(self.eigen_zeile, 3, 1, 1, 2)

        self.anordnung = QComboBox()
        self.anordnung.addItem(_("Ganz zeigen"), False)
        self.anordnung.addItem(_("Fläche füllen (beschneidet)"), True)
        gitter.addWidget(QLabel(_("Bild")), 4, 0)
        gitter.addWidget(self.anordnung, 4, 1, 1, 2)

        self.rand = QSpinBox(suffix=" mm")
        self.rand.setRange(0, drucken.RAND_MAX_MM)
        self.rand.setToolTip(_("Weißer Rand zusätzlich zu dem, den der Drucker braucht."))
        self.randlos = QCheckBox(_("Randlos"))
        self.randlos.setToolTip(_("Bis an die Kante drucken – nur, wenn Drucker und Papier "
                                  "das können. Sonst fehlt am Rand etwas."))
        gitter.addWidget(QLabel(_("Rand")), 5, 0)
        gitter.addWidget(self.rand, 5, 1)
        gitter.addWidget(self.randlos, 5, 2)

        self.exemplare = QSpinBox()
        self.exemplare.setRange(1, 99)
        gitter.addWidget(QLabel(_("Exemplare")), 6, 0)
        gitter.addWidget(self.exemplare, 6, 1)
        innen.addLayout(gitter)

        self.ki_box = QCheckBox()
        self.ki_box.setToolTip(_("Rechnet das Bild vor dem Drucken mit dem Modell aus der "
                                 "Karte „KI-Hochskalieren“ größer – feine Details wirken "
                                 "dann schärfer."))
        innen.addWidget(self.ki_box)
        self.hinweis = QLabel(objectName="nebentext")
        self.hinweis.setWordWrap(True)
        innen.addWidget(self.hinweis)
        karte.setMinimumWidth(330)
        return karte

    @staticmethod
    def _cm_feld() -> QDoubleSpinBox:
        feld = QDoubleSpinBox(suffix=" cm", decimals=1)
        feld.setRange(drucken.EIGEN_MIN_CM, drucken.EIGEN_MAX_CM)
        feld.setSingleStep(0.5)
        return feld

    # ------------------------------------------------------------------
    # Werte
    # ------------------------------------------------------------------

    def _setzen(self, vorgaben: Vorgaben):
        nummer = self.drucker_wahl.findData(vorgaben.drucker)
        if nummer < 0:
            nummer = self.drucker_wahl.findData(QPrinterInfo.defaultPrinterName())
        self.drucker_wahl.setCurrentIndex(max(0, nummer))
        self._papiere_fuellen(vorgaben.papier)
        self.groesse_wahl.setCurrentIndex(max(0, self.groesse_wahl.findData(vorgaben.groesse)))
        self.eigen_breite.setValue(vorgaben.eigen_breite)
        self.eigen_hoehe.setValue(vorgaben.eigen_hoehe)
        self.anordnung.setCurrentIndex(1 if vorgaben.fuellen else 0)
        self.rand.setValue(round(vorgaben.rand))
        self.randlos.setChecked(vorgaben.randlos)

    def vorgaben(self) -> Vorgaben:
        return Vorgaben(
            drucker=self.drucker_wahl.currentData() or "",
            papier=self.papier_wahl.currentText(),
            groesse=self.groesse_wahl.currentData(),
            eigen_breite=self.eigen_breite.value(),
            eigen_hoehe=self.eigen_hoehe.value(),
            fuellen=bool(self.anordnung.currentData()),
            rand=float(self.rand.value()),
            randlos=self.randlos.isChecked(),
        ).begrenzt()

    def _verbinden(self):
        self.drucker_wahl.currentIndexChanged.connect(self._drucker_gewechselt)
        for feld in (self.papier_wahl, self.groesse_wahl, self.anordnung):
            feld.currentIndexChanged.connect(self._aktualisieren)
        for feld in (self.eigen_breite, self.eigen_hoehe, self.rand):
            feld.valueChanged.connect(self._aktualisieren)
        for box in (self.randlos, self.ki_box):
            box.toggled.connect(self._aktualisieren)

    def _drucker_gewechselt(self, *_args):
        self._papiere_fuellen(self.papier_wahl.currentText())
        self._aktualisieren()

    def _papiere_fuellen(self, gewuenscht: str):
        """Papiergroessen des Druckers - gewaehlt das gewuenschte, sonst 10 x 15 cm, sonst
        das des Druckers."""
        info = QPrinterInfo.printerInfo(self.drucker_wahl.currentData() or "")
        groessen = info.supportedPageSizes() if not info.isNull() else []
        if not groessen:
            groessen = [QPageSize(QPageSize.PageSizeId.A4)]
        self.papier_wahl.blockSignals(True)
        self.papier_wahl.clear()
        for groesse in groessen:
            self.papier_wahl.addItem(groesse.name(), groesse)
        nummer = self.papier_wahl.findText(gewuenscht) if gewuenscht else -1
        if nummer < 0:
            nummer = next((i for i, g in enumerate(groessen)
                           if drucken.passt_zur_vorgabe(*self._mm(g))), -1)
        if nummer < 0 and not info.isNull():
            nummer = self.papier_wahl.findText(info.defaultPageSize().name())
        self.papier_wahl.setCurrentIndex(max(0, nummer))
        self.papier_wahl.blockSignals(False)

    @staticmethod
    def _mm(groesse: QPageSize) -> tuple[float, float]:
        mass = groesse.size(QPageSize.Unit.Millimeter)
        return mass.width(), mass.height()

    # ------------------------------------------------------------------
    # Drucker und Lage
    # ------------------------------------------------------------------

    def drucker(self) -> QPrinter | None:
        """Der eingerichtete Drucker: Papier, Lage passend zum Bild, Raender, Exemplare."""
        name = self.drucker_wahl.currentData()
        if not name:
            return None
        if self._drucker is None or self._drucker_name != name:
            self._drucker = QPrinter(QPrinterInfo.printerInfo(name),
                                     QPrinter.PrinterMode.HighResolution)
            self._drucker_name = name
        self._einrichten(self._drucker)
        return self._drucker

    def _einrichten(self, drucker: QPrinter):
        drucker.setFullPage(True)                 # gerechnet wird ab der Ecke des Blattes
        groesse = self.papier_wahl.currentData()
        if groesse is not None:
            drucker.setPageSize(groesse)
        quer = self._breite > self._hoehe
        drucker.setPageOrientation(QPageLayout.Orientation.Landscape if quer else
                                   QPageLayout.Orientation.Portrait)
        lage = drucker.pageLayout()
        if self.randlos.isChecked():
            lage.setMode(QPageLayout.Mode.FullPageMode)
            lage.setMargins(QMarginsF(0, 0, 0, 0))
        else:
            lage.setMode(QPageLayout.Mode.StandardMode)
            lage.setMargins(lage.minimumMargins())   # so knapp, wie der Drucker kann
        drucker.setPageLayout(lage)
        drucker.setCopyCount(self.exemplare.value())

    def _blatt(self) -> tuple[tuple[float, float], tuple[float, ...]]:
        """Groesse des Blattes und sein bedruckbarer Bereich in mm."""
        drucker = self.drucker()
        if drucker is not None:
            lage = drucker.pageLayout()
        else:
            # Ohne Drucker: das gewaehlte Papier ohne Rand - nur fuer die Vorschau
            quer = self._breite > self._hoehe
            lage = QPageLayout(self.papier_wahl.currentData() or QPageSize(QPageSize.PageSizeId.A4),
                               QPageLayout.Orientation.Landscape if quer else
                               QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0))
        voll = lage.fullRect(QPageLayout.Unit.Millimeter)
        innen = lage.paintRect(QPageLayout.Unit.Millimeter)
        return ((voll.width(), voll.height()),
                (innen.x(), innen.y(), innen.width(), innen.height()))

    def platz(self) -> Platz:
        return self._platz

    def ki_faktor(self) -> int:
        """2 oder 4, wenn vorher mit KI hochskaliert werden soll, sonst 0."""
        faktor = drucken.ki_faktor(self._platz)
        return faktor if self._ki_moeglich and self.ki_box.isChecked() else 0

    # ------------------------------------------------------------------
    # Anzeige
    # ------------------------------------------------------------------

    def _aktualisieren(self, *_args):
        vorgaben = self.vorgaben()
        self.eigen_zeile.setVisible(vorgaben.groesse == "eigen")
        self.rand.setEnabled(not vorgaben.randlos)
        groesse_mm, bedruckbar = self._blatt()
        flaeche = drucken.flaeche(bedruckbar, 0.0 if vorgaben.randlos else vorgaben.rand)
        self._platz = drucken.platzieren(self._breite, self._hoehe, flaeche,
                                         vorgaben.format_mm(), vorgaben.fuellen)
        self.blatt.groesse_mm, self.blatt.bedruckbar = groesse_mm, bedruckbar
        self.blatt.platz = self._platz
        self.blatt.update()

        platz = self._platz
        faktor = drucken.ki_faktor(platz)
        self.ki_box.setVisible(faktor > 0)
        self.ki_box.setEnabled(self._ki_moeglich)
        self.ki_box.setText(_("Vorher mit KI hochskalieren ({faktor} ×)").format(faktor=faktor))
        dpi = platz.dpi * (self.ki_faktor() or 1)
        _x, _y, breite, hoehe = platz.ziel
        self.info.setText(_("Auf dem Papier: {breite} × {hoehe} · {dpi} dpi").format(
            breite=cm(breite), hoehe=cm(hoehe), dpi=f"{dpi:.0f}"))
        hinweise = []
        if self.drucker_wahl.count() == 0:
            hinweise.append(_("Kein Drucker gefunden."))
        if platz.verkleinert:
            hinweise.append(_("Die Bildgröße passt nicht aufs Papier – verkleinert."))
        if platz.knapp and not self.ki_faktor():
            hinweise.append(_("Für diese Größe hat das Bild wenig Pixel – der Druck kann "
                              "weich wirken."))
            if not self._ki_moeglich:
                hinweise.append(_("Mit einem geladenen Modell der Karte „KI-Hochskalieren“ "
                                  "ließe es sich vorher vergrößern."))
        self.hinweis.setText(" ".join(hinweise))
        self.hinweis.setVisible(bool(hinweise))
        self.drucken_knopf.setEnabled(self.drucker_wahl.count() > 0)
