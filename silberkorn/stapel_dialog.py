"""
Dialog "Stapel": was mit den gewaehlten Bildern geschieht

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from . import voreinstellungen
from .stapel import Auftrag, zusatz_pruefen
from .uebersetzung import _

KEINE = ""                     # Auswahl "nur die vorhandene Bearbeitung"
KOPIERT = "\x00kopiert"        # Auswahl "kopierte Einstellungen" - kein gueltiger Name


class StapelDialog(QDialog):
    def __init__(self, eltern, anzahl: int, ordner: str, formate, zwischenablage: dict | None,
                 begleitdateien: bool, hochskalieren: str):
        """formate: [(Beschriftung, Endung, Bits)]; hochskalieren: Text wie "2×" oder "",
        wenn die Karte KI-Hochskalieren aus ist."""
        super().__init__(eltern)
        self.setWindowTitle(_("Stapel: {anzahl} Bilder").format(anzahl=anzahl))
        self._zwischenablage = zwischenablage
        aufbau = QVBoxLayout(self)

        zeile = QHBoxLayout()
        zeile.addWidget(QLabel(_("Einstellungen")))
        self.wahl = QComboBox()
        self.wahl.addItem(_("Keine – nur die vorhandene Bearbeitung"), KEINE)
        if zwischenablage is not None:
            self.wahl.addItem(_("Kopierte Einstellungen"), KOPIERT)
        for name in voreinstellungen.namen():
            self.wahl.addItem(name, name)
        zeile.addWidget(self.wahl, 1)
        aufbau.addLayout(zeile)

        self.staub = QCheckBox(_("Staub über den Infrarotkanal entfernen, wo es einen gibt"))
        aufbau.addWidget(self.staub)
        self.begleit = QCheckBox(_("Bearbeitung als Begleitdatei neben jedem Bild sichern"))
        self.begleit.setChecked(begleitdateien)
        aufbau.addWidget(self.begleit)

        self.ausgeben = QGroupBox(_("Bilder ausgeben"))
        self.ausgeben.setCheckable(True)
        self.ausgeben.setChecked(not begleitdateien)
        gitter = QGridLayout(self.ausgeben)
        gitter.addWidget(QLabel(_("Ordner")), 0, 0)
        self.ziel = QLineEdit(os.path.join(ordner, _("bearbeitet")))
        gitter.addWidget(self.ziel, 0, 1)
        waehlen = QPushButton(_("Ändern …"))
        waehlen.clicked.connect(self._ziel_waehlen)
        gitter.addWidget(waehlen, 0, 2)
        gitter.addWidget(QLabel(_("Format")), 1, 0)
        self.format = QComboBox()
        for beschriftung, endung, bits in formate:
            self.format.addItem(beschriftung.split(" (")[0], (endung, bits))
        gitter.addWidget(self.format, 1, 1, 1, 2)
        gitter.addWidget(QLabel(_("Namenszusatz")), 2, 0)
        self.zusatz = QLineEdit("-bearbeitet")
        self.zusatz.textChanged.connect(lambda _t: self._pruefen())
        gitter.addWidget(self.zusatz, 2, 1, 1, 2)
        self.ki = QCheckBox(_("KI-Entrauschen, -Schärfen und -Kolorieren rechnen, wo eingestellt"))
        self.ki.setChecked(True)
        gitter.addWidget(self.ki, 3, 0, 1, 3)
        self.hoch = QCheckBox(_("Mit KI-Hochskalieren ({faktor}, wie in der Karte eingestellt)")
                              .format(faktor=hochskalieren or "–"))
        self.hoch.setEnabled(bool(hochskalieren))
        gitter.addWidget(self.hoch, 4, 0, 1, 3)
        hinweis = QLabel(_("Vorhandene Dateien werden nie überschrieben – dann heißt die neue "
                           "Datei etwa „Name-bearbeitet-2“."), objectName="nebentext")
        hinweis.setWordWrap(True)
        gitter.addWidget(hinweis, 5, 0, 1, 3)
        self.ausgeben.toggled.connect(lambda _an: self._pruefen())
        self.begleit.toggled.connect(lambda _an: self._pruefen())
        aufbau.addWidget(self.ausgeben)

        self.knoepfe = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.knoepfe.button(QDialogButtonBox.StandardButton.Ok).setText(_("Starten"))
        self.knoepfe.accepted.connect(self.accept)
        self.knoepfe.rejected.connect(self.reject)
        aufbau.addWidget(self.knoepfe)
        self._pruefen()

    def _ziel_waehlen(self):
        from .ordner_seite import ordner_dialog
        ordner = ordner_dialog(self, _("Ordner für die Ausgabe"), self.ziel.text())
        if ordner:
            self.ziel.setText(ordner)

    def _pruefen(self):
        ok = self.begleit.isChecked() or self.ausgeben.isChecked()
        if self.ausgeben.isChecked():
            ok = ok and zusatz_pruefen(self.zusatz.text()) is not None and bool(
                self.ziel.text().strip())
        self.knoepfe.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def auftrag(self) -> Auftrag:
        wahl = self.wahl.currentData()
        if wahl == KOPIERT:
            voreinstellung = self._zwischenablage
        elif wahl:
            voreinstellung = voreinstellungen.laden(wahl)
        else:
            voreinstellung = None
        endung, bits = self.format.currentData()
        return Auftrag(voreinstellung=voreinstellung, staub=self.staub.isChecked(),
                       ki=self.ki.isChecked(), begleitdatei=self.begleit.isChecked(),
                       ausgeben=self.ausgeben.isChecked(),
                       ziel=os.path.normpath(self.ziel.text().strip() or "."),
                       endung=endung, bits=bits,
                       zusatz=zusatz_pruefen(self.zusatz.text()) or "",
                       hochskalieren=self.hoch.isChecked() and self.hoch.isEnabled())


def bericht_text(hinweis: str) -> str:
    """Ein Hinweis aus stapel.Ergebnis in Worten."""
    if hinweis == "veraltet":
        return _("Begleitdatei passte nicht mehr – nur die Reglerwerte übernommen")
    if hinweis == "verworfen":
        return _("ungültige Werte übergangen")
    if hinweis.startswith("ohne "):
        return _("KI-Schritt ausgelassen – Modell nicht geladen")
    if hinweis == "Grafikspeicher":
        return _("Für dieses Bild reicht der Grafikspeicher nicht.")
    return hinweis

