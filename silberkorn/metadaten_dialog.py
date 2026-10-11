"""
Dialog "Alle Metadaten": was die Datei an EXIF, GPS, IPTC und XMP mitbringt - nur lesend

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

from html import escape

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from . import metadaten
from .uebersetzung import _


def gruppen_titel() -> dict[str, str]:
    return {"EXIF": _("EXIF – Kamera und Aufnahme"), "GPS": _("GPS – Standort"),
            "IPTC": _("IPTC (IIM) – ältere Beschreibung"), "XMP": _("XMP – Beschreibung")}


class MetadatenDialog(QDialog):
    def __init__(self, eltern, name: str, exif: bytes, xmp: bytes, iptc: dict):
        super().__init__(eltern)
        self.setWindowTitle(_("Metadaten von {name}").format(name=name))
        self.resize(720, 620)
        aufbau = QVBoxLayout(self)
        hinweis = QLabel(objectName="nebentext")
        hinweis.setWordWrap(True)
        hinweis.setText(_("So steht es in der Datei. Titel, Beschreibung, Stichwörter, Urheber, "
                          "Copyright, Ort, Datum und Bewertung lassen sich in der Karte "
                          "„Metadaten“ ändern; geschrieben wird erst beim Speichern."))
        aufbau.addWidget(hinweis)
        self.suche = QLineEdit(placeholderText=_("Filtern …"), clearButtonEnabled=True)
        self.suche.textChanged.connect(self._filtern)
        aufbau.addWidget(self.suche)

        self.baum = QTreeWidget()
        self.baum.setColumnCount(2)
        self.baum.setHeaderLabels([_("Feld"), _("Wert")])
        self.baum.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.baum.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.baum.setUniformRowHeights(True)
        self.baum.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.baum.header().setStretchLastSection(True)
        titel = gruppen_titel()
        gruppen: dict[str, QTreeWidgetItem] = {}
        for gruppe, feld, wert in metadaten.eintraege(exif, xmp, iptc):
            if gruppe not in gruppen:
                gruppen[gruppe] = QTreeWidgetItem(self.baum, [titel.get(gruppe, gruppe), ""])
                gruppen[gruppe].setFirstColumnSpanned(True)
            eintrag = QTreeWidgetItem(gruppen[gruppe], [feld, wert])
            # Tooltips deuten HTML - Werte aus der Datei nur als Text zeigen
            eintrag.setToolTip(1, f"<p>{escape(wert)}</p>")
        if not gruppen:
            QTreeWidgetItem(self.baum, [_("Die Datei enthält keine Metadaten."), ""])
        self.baum.expandAll()
        self.baum.setColumnWidth(0, 260)
        aufbau.addWidget(self.baum, 1)

        knoepfe = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        knoepfe.button(QDialogButtonBox.StandardButton.Close).setText(_("Schließen"))
        knoepfe.rejected.connect(self.reject)
        aufbau.addWidget(knoepfe)

    def _filtern(self, text: str):
        text = text.casefold().strip()
        for nummer in range(self.baum.topLevelItemCount()):
            gruppe = self.baum.topLevelItem(nummer)
            sichtbar = 0
            for k in range(gruppe.childCount()):
                eintrag = gruppe.child(k)
                passt = not text or text in eintrag.text(0).casefold() \
                    or text in eintrag.text(1).casefold()
                eintrag.setHidden(not passt)
                sichtbar += passt
            gruppe.setHidden(gruppe.childCount() > 0 and not sichtbar)
