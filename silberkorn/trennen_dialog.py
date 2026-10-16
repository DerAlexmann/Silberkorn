"""
Dialog "Fotos trennen": die gefundenen Fotos zum Abwaehlen, Ordner, Name und
Format der Dateien und welches Foto danach zum Bearbeiten geoeffnet wird

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from .uebersetzung import _

KACHEL = 150                  # Vorschaubilder hoechstens so gross
SPALTEN = 4
FORMATE = ((".tif", "TIFF"), (".png", "PNG"), (".jpg", "JPEG"))
KEINES = -1                   # „Danach öffnen: Keines“


def format_vorgabe(pfad: str) -> str:
    """Das Format des Scans, wenn es eines der angebotenen ist - sonst TIFF."""
    endung = os.path.splitext(pfad)[1].lower()
    endung = {".tiff": ".tif", ".jpeg": ".jpg"}.get(endung, endung)
    return endung if endung in dict(FORMATE) else ".tif"


def _pixmap(rgb: np.ndarray) -> QPixmap:
    rgb = np.ascontiguousarray(rgb)
    bild = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0],
                  QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(bild).scaled(KACHEL, KACHEL, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)


class TrennenDialog(QDialog):
    def __init__(self, eltern, vorschauen: list[np.ndarray], scan_pfad: str):
        super().__init__(eltern)
        self.setWindowTitle(_("Fotos trennen"))
        aufbau = QVBoxLayout(self)
        hinweis = QLabel(objectName="nebentext")
        hinweis.setWordWrap(True)
        hinweis.setText(_(
            "{n} Fotos gefunden, gerade gerichtet und auf ihren Rand beschnitten. Gespeichert "
            "wird jedes gewählte Foto als eigene Datei – ausgeschnitten aus dem unbearbeiteten "
            "Scan.").format(n=len(vorschauen)))
        aufbau.addWidget(hinweis)

        gitter = QGridLayout()
        gitter.setSpacing(8)
        self.kacheln: list[QToolButton] = []
        for nummer, rgb in enumerate(vorschauen):
            kachel = QToolButton(objectName="fotokachel")
            kachel.setCheckable(True)
            kachel.setChecked(True)
            kachel.setIcon(QIcon(_pixmap(rgb)))
            kachel.setIconSize(QSize(KACHEL, KACHEL))
            kachel.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            kachel.setText(_("Foto {n}").format(n=nummer + 1))
            kachel.setToolTip(_("Anklicken, um dieses Foto nicht zu speichern."))
            kachel.toggled.connect(lambda _an: self._auswahl_geaendert())
            gitter.addWidget(kachel, nummer // SPALTEN, nummer % SPALTEN)
            self.kacheln.append(kachel)
        aufbau.addLayout(gitter)

        felder = QGridLayout()
        felder.setColumnStretch(1, 1)
        felder.addWidget(QLabel(_("Ordner")), 0, 0)
        self.ordner_feld = QLineEdit(os.path.dirname(os.path.abspath(scan_pfad)))
        felder.addWidget(self.ordner_feld, 0, 1)
        aendern = QPushButton(_("Ändern …"))
        aendern.clicked.connect(self._ordner_waehlen)
        felder.addWidget(aendern, 0, 2)
        felder.addWidget(QLabel(_("Name")), 1, 0)
        self.name_feld = QLineEdit(os.path.splitext(os.path.basename(scan_pfad))[0])
        self.name_feld.setToolTip(_("Die Dateien heißen Name-01, Name-02 … – vorhandene "
                                    "Dateien werden nie überschrieben."))
        felder.addWidget(self.name_feld, 1, 1, 1, 2)
        felder.addWidget(QLabel(_("Format")), 2, 0)
        self.format_wahl = QComboBox()
        for endung, titel in FORMATE:
            self.format_wahl.addItem(titel, endung)
        self.format_wahl.setCurrentIndex(self.format_wahl.findData(format_vorgabe(scan_pfad)))
        felder.addWidget(self.format_wahl, 2, 1, 1, 2)
        felder.addWidget(QLabel(_("Danach öffnen")), 3, 0)
        self.oeffnen_wahl = QComboBox()
        self.oeffnen_wahl.setToolTip(_("Dieses Foto wird nach dem Speichern zum Bearbeiten "
                                       "geöffnet."))
        felder.addWidget(self.oeffnen_wahl, 3, 1, 1, 2)
        aufbau.addLayout(felder)

        knoepfe = QHBoxLayout()
        knoepfe.addStretch(1)
        self.speichern_knopf = QPushButton(_("Speichern"), objectName="hauptschalter")
        self.speichern_knopf.setDefault(True)
        self.speichern_knopf.clicked.connect(self.accept)
        abbrechen = QPushButton(_("Abbrechen"))
        abbrechen.clicked.connect(self.reject)
        knoepfe.addWidget(self.speichern_knopf)
        knoepfe.addWidget(abbrechen)
        aufbau.addLayout(knoepfe)
        self._auswahl_geaendert()

    def _ordner_waehlen(self):
        ordner = QFileDialog.getExistingDirectory(self, _("Ordner wählen"),
                                                  self.ordner_feld.text())
        if ordner:
            self.ordner_feld.setText(ordner)

    def _auswahl_geaendert(self):
        """Nur gewaehlte Fotos lassen sich danach oeffnen; die Wahl bleibt, wenn moeglich."""
        vorher = self.oeffnen_wahl.currentData()
        self.oeffnen_wahl.clear()
        self.oeffnen_wahl.addItem(_("Keines"), KEINES)
        for nummer in self.gewaehlt():
            self.oeffnen_wahl.addItem(_("Foto {n}").format(n=nummer + 1), nummer)
        gewaehlt = self.gewaehlt()
        ziel = vorher if vorher in gewaehlt or vorher == KEINES else (
            gewaehlt[0] if gewaehlt else KEINES)
        self.oeffnen_wahl.setCurrentIndex(max(0, self.oeffnen_wahl.findData(ziel)))
        self.speichern_knopf.setEnabled(bool(gewaehlt))

    def gewaehlt(self) -> list[int]:
        return [i for i, kachel in enumerate(self.kacheln) if kachel.isChecked()]

    def ordner(self) -> str:
        return self.ordner_feld.text().strip()

    def name(self) -> str:
        return self.name_feld.text().strip()

    def endung(self) -> str:
        return self.format_wahl.currentData()

    def danach_oeffnen(self) -> int | None:
        """Nummer des Fotos (unter allen gefundenen), das danach geoeffnet wird."""
        nummer = self.oeffnen_wahl.currentData()
        return None if nummer in (None, KEINES) else nummer
