"""
Dialog zum Sichern einer Voreinstellung und zum Kopieren von Einstellungen:
welche Gruppen mitgehen, beim Film ob die gemessene Filmmaske mitgeht, und
beim Sichern der Name

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from . import voreinstellungen as vor
from .uebersetzung import _


def gruppen_titel(gruppe: str) -> str:
    return {
        "grundregler": _("Grundregler"),
        "kurven": _("Gradationskurve"),
        "hsl": _("Farbbereiche"),
        "schwarzweiss": _("Schwarzweiß & Tönung"),
        "lut": _("LUT"),
        "rauschen": _("Rauschminderung"),
        "korn": _("Filmkorn"),
        "film": _("Scan & Film"),
        "ki": _("KI-Stärken"),
        "hintergrund": _("Motiv & Hintergrund"),
        "tiefe": _("Tiefe & Bokeh"),
        "objektiv": _("Objektiv"),
        "geometrie": _("Geometrie"),
        "anonym": _("Anonymisieren"),
        "metadaten": _("Metadaten"),
        "lokal": _("Lokale Anpassungen"),
    }[gruppe]


def gruppen_tooltip(gruppe: str) -> str:
    return {
        "grundregler": _("Weißabgleich, Licht, Präsenz, Farbe und Details"),
        "film": _("Die Filmart – und auf Wunsch die gemessene Filmmaske"),
        "ki": _("Nur die Stärke von KI-Entrauschen, -Schärfen und -Kolorieren. Berechnet "
                "werden muss jedes Bild selbst."),
        "hintergrund": _("Die Regler für den Hintergrund – sie wirken erst mit einer Maske."),
        "tiefe": _("Bokeh, Fokus und Schärfentiefe – sie wirken erst mit einer Tiefe."),
        "objektiv": _("Verzeichnung, Vignette, Farbsäume und ob das Objektivprofil gilt"),
        "geometrie": _("Drehen, Spiegeln, Zuschnitt, Begradigen und Perspektive – meist nur für "
                       "ein bestimmtes Bild richtig"),
        "anonym": _("Die Flächen zum Anonymisieren – sie gehören zu einem bestimmten Bild"),
        "metadaten": _("Titel, Beschreibung, Urheber, Ort, Datum und Bewertung"),
        "lokal": _("Die Masken mit Verlauf und Radial und ihren Reglern – sie liegen "
                   "relativ zum Bild und passen meist nur zu ähnlichen Motiven"),
    }.get(gruppe, "")


class VoreinstellungDialog(QDialog):
    """mit_name: Sichern (mit Namen) statt Kopieren."""

    def __init__(self, eltern, auswahl: vor.Auswahl, mit_name: bool, name: str = ""):
        super().__init__(eltern)
        self.setWindowTitle(_("Voreinstellung sichern") if mit_name
                            else _("Einstellungen kopieren"))
        aufbau = QVBoxLayout(self)
        self.name = None
        if mit_name:
            aufbau.addWidget(QLabel(_("Name")))
            self.name = QLineEdit(name)
            self.name.setMaxLength(vor.MAX_NAME)
            self.name.setPlaceholderText(_("z. B. Kodak Portra"))
            self.name.textChanged.connect(lambda _t: self._pruefen())
            aufbau.addWidget(self.name)
        hinweis = QLabel(objectName="nebentext")
        hinweis.setWordWrap(True)
        hinweis.setText(_("Was mitgenommen wird:"))
        aufbau.addWidget(hinweis)
        gitter = QGridLayout()
        gitter.setHorizontalSpacing(16)
        self.boxen: dict[str, QCheckBox] = {}
        for nummer, gruppe in enumerate(vor.GRUPPEN):
            box = QCheckBox(gruppen_titel(gruppe))
            box.setToolTip(gruppen_tooltip(gruppe))
            box.setChecked(gruppe in auswahl.gruppen)
            box.toggled.connect(lambda _an: self._pruefen())
            gitter.addWidget(box, nummer // 2, nummer % 2)
            self.boxen[gruppe] = box
        aufbau.addLayout(gitter)
        self.film_messung = QCheckBox(_("Gemessene Filmmaske mitnehmen"))
        self.film_messung.setToolTip(_(
            "Für Bilder vom selben Filmstreifen. Sonst wird die Filmmaske an jedem Bild neu "
            "geschätzt."))
        self.film_messung.setChecked(auswahl.film_messung)
        aufbau.addWidget(self.film_messung)
        self.knoepfe = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.knoepfe.accepted.connect(self.accept)
        self.knoepfe.rejected.connect(self.reject)
        aufbau.addWidget(self.knoepfe)
        self._pruefen()

    def _pruefen(self):
        self.film_messung.setEnabled(self.boxen["film"].isChecked())
        ok = any(box.isChecked() for box in self.boxen.values())
        if self.name is not None:
            ok = ok and vor.name_pruefen(self.name.text()) is not None
        self.knoepfe.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def auswahl(self) -> vor.Auswahl:
        gruppen = tuple(g for g, box in self.boxen.items() if box.isChecked())
        return vor.Auswahl(gruppen, self.film_messung.isChecked() and "film" in gruppen)

    def gewaehlter_name(self) -> str:
        return vor.name_pruefen(self.name.text()) or "" if self.name is not None else ""
