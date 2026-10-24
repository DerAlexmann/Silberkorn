"""
Dialog "Kontaktbogen": Drucker oder PDF, Papier, Lage und Spalten mit Vorschau

Die Vorschau zeigt die Seiten mit den Kacheln der Ordneransicht - so schnell,
wie man blaettert. Gedruckt werden die Bilder danach in Zellaufloesung
(kontaktbogen.ausgeben).

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import bewertung, kontaktbogen
from .drucken_dialog import VORSCHAU, DruckerWahl, cm
from .kontaktbogen import Raster, Vorgaben
from .uebersetzung import _


def seite_text(nummer: int, anzahl: int) -> str:
    return _("Seite {nummer}/{anzahl}").format(nummer=nummer, anzahl=anzahl)


class Bogen(QWidget):
    """Eine Seite des Kontaktbogens, verkleinert."""

    def __init__(self, vorschau):
        super().__init__()
        self.setFixedSize(VORSCHAU, VORSCHAU)
        self._vorschau = vorschau                # Pfad -> QPixmap oder None
        self.groesse_mm = (210.0, 297.0)
        self.raster: Raster | None = None
        self.kopf = ""
        self.seite, self.seiten = 1, 1
        self.eintraege: list[tuple[str, bewertung.Stand]] = []

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
        if self.raster is not None:
            je = self.raster.je_seite
            teil = self.eintraege[(self.seite - 1) * je:self.seite * je]
            zellen = [(self._vorschau(pfad), kontaktbogen.beschriftung(os.path.basename(pfad),
                                                                       stand))
                      for pfad, stand in teil]
            maler.translate(ox, oy)
            kontaktbogen.seite_zeichnen(maler, je_mm, self.raster, self.kopf,
                                        seite_text(self.seite, self.seiten), zellen)
        maler.end()


class KontaktbogenDialog(QDialog):
    def __init__(self, eltern, eintraege: list[tuple[str, bewertung.Stand]], kopf: str,
                 vorgaben: Vorgaben, vorschau):
        """eintraege: (Pfad, Bewertung) in der Reihenfolge der Ordneransicht; kopf: der
        Ordner fuer die Kopfzeile; vorschau(Pfad): die Kachel als QPixmap oder None."""
        super().__init__(eltern)
        self.setWindowTitle(_("Kontaktbogen"))
        self._alle = list(eintraege)
        self._wahl = DruckerWahl(kontaktbogen.ist_a4, pdf=True)
        self._raster: Raster | None = None

        aufbau = QVBoxLayout(self)
        oben = QHBoxLayout()
        oben.setSpacing(12)
        links = QVBoxLayout()
        links.addWidget(self._einstellungen_karte())
        links.addStretch(1)
        oben.addLayout(links)
        rechts = QVBoxLayout()
        self.bogen = Bogen(vorschau)
        self.bogen.kopf = kopf
        rechts.addWidget(self.bogen)
        blaettern = QHBoxLayout()
        self.zurueck = QPushButton("◀", objectName="zoomsymbol")
        self.zurueck.setToolTip(_("Vorige Seite"))
        self.zurueck.setAccessibleName(_("Vorige Seite"))
        self.seite_info = QLabel(objectName="nebentext", alignment=Qt.AlignmentFlag.AlignCenter)
        self.vor = QPushButton("▶", objectName="zoomsymbol")
        self.vor.setToolTip(_("Nächste Seite"))
        self.vor.setAccessibleName(_("Nächste Seite"))
        self.zurueck.clicked.connect(lambda: self._blaettern(-1))
        self.vor.clicked.connect(lambda: self._blaettern(1))
        blaettern.addStretch(1)
        blaettern.addWidget(self.zurueck)
        blaettern.addWidget(self.seite_info)
        blaettern.addWidget(self.vor)
        blaettern.addStretch(1)
        rechts.addLayout(blaettern)
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
        self.los_knopf = QPushButton(objectName="hauptschalter")
        self.los_knopf.setDefault(True)
        self.los_knopf.clicked.connect(self.accept)
        knoepfe.addWidget(abbrechen)
        knoepfe.addWidget(self.los_knopf)
        aufbau.addLayout(knoepfe)

        self._setzen(vorgaben)
        self._verbinden()
        self._aktualisieren()

    def _einstellungen_karte(self) -> QFrame:
        karte = QFrame(objectName="karte")
        innen = QVBoxLayout(karte)
        innen.setContentsMargins(16, 12, 16, 14)
        innen.addWidget(QLabel(_("Kontaktbogen"), objectName="kartentitel"))
        gitter = QGridLayout()
        gitter.setColumnStretch(1, 1)
        gitter.setVerticalSpacing(6)
        self.drucker_wahl, self.papier_wahl = self._wahl.drucker_wahl, self._wahl.papier_wahl
        zeilen = [(_("Drucker"), self.drucker_wahl), (_("Papier"), self.papier_wahl)]
        self.lage = QComboBox()
        self.lage.addItem(_("Hochformat"), False)
        self.lage.addItem(_("Querformat"), True)
        zeilen.append((_("Lage"), self.lage))
        self.spalten = QSpinBox()
        self.spalten.setRange(kontaktbogen.SPALTEN_MIN, kontaktbogen.SPALTEN_MAX)
        self.spalten.setToolTip(_("Wie viele Bilder nebeneinander stehen – mehr Spalten, "
                                  "kleinere Bilder, weniger Seiten."))
        zeilen.append((_("Spalten"), self.spalten))
        for nummer, (text, feld) in enumerate(zeilen):
            beschriftung = QLabel(text)
            beschriftung.setBuddy(feld)
            feld.setAccessibleName(text)
            gitter.addWidget(beschriftung, nummer, 0)
            gitter.addWidget(feld, nummer, 1)
        innen.addLayout(gitter)
        self.ausschuss = QCheckBox(_("Ausschuss weglassen"))
        self.ausschuss.setToolTip(_("Bilder, die in der Ordneransicht als Ausschuss markiert "
                                    "sind, kommen nicht auf den Bogen."))
        innen.addWidget(self.ausschuss)
        karte.setMinimumWidth(300)
        return karte

    # ------------------------------------------------------------------

    def _setzen(self, vorgaben: Vorgaben):
        self._wahl.setzen(vorgaben.drucker, vorgaben.papier)
        self.lage.setCurrentIndex(1 if vorgaben.quer else 0)
        self.spalten.setValue(vorgaben.spalten)
        self.ausschuss.setChecked(vorgaben.ausschuss_weglassen)
        hat_ausschuss = any(stand.wert == bewertung.AUSSCHUSS for _pfad, stand in self._alle)
        self.ausschuss.setEnabled(hat_ausschuss)

    def vorgaben(self) -> Vorgaben:
        return Vorgaben(drucker=self.drucker_wahl.currentData() or "",
                        papier=self.papier_wahl.currentText(),
                        quer=bool(self.lage.currentData()), spalten=self.spalten.value(),
                        ausschuss_weglassen=self.ausschuss.isChecked()).begrenzt()

    def _verbinden(self):
        self.drucker_wahl.currentIndexChanged.connect(self._drucker_gewechselt)
        for feld in (self.papier_wahl, self.lage):
            feld.currentIndexChanged.connect(self._aktualisieren)
        self.spalten.valueChanged.connect(self._aktualisieren)
        self.ausschuss.toggled.connect(self._aktualisieren)

    def _drucker_gewechselt(self, *_args):
        self._wahl.papiere_fuellen(self.papier_wahl.currentText())
        self._aktualisieren()

    def ist_pdf(self) -> bool:
        return self._wahl.ist_pdf()

    def drucker(self) -> QPrinter | None:
        """Der eingerichtete Drucker (bei PDF ohne Dateinamen) - None ohne Drucker."""
        drucker = self._wahl.drucker()
        if drucker is not None:
            self._wahl.einrichten(drucker, bool(self.lage.currentData()))
        return drucker

    def raster(self) -> Raster:
        return self._raster

    def eintraege(self) -> list[tuple[str, bewertung.Stand]]:
        """Was auf den Bogen kommt - ohne Ausschuss, wenn das gewaehlt ist."""
        return kontaktbogen.auswahl(self._alle, self.ausschuss.isChecked()
                                    and self.ausschuss.isEnabled())

    # ------------------------------------------------------------------

    def _blaettern(self, schritt: int):
        self.bogen.seite = min(max(self.bogen.seite + schritt, 1), self.bogen.seiten)
        self._seite_anzeigen()

    def _seite_anzeigen(self):
        self.seite_info.setText(seite_text(self.bogen.seite, self.bogen.seiten))
        self.zurueck.setEnabled(self.bogen.seite > 1)
        self.vor.setEnabled(self.bogen.seite < self.bogen.seiten)
        self.bogen.update()

    def _aktualisieren(self, *_args):
        groesse_mm, bedruckbar = self._wahl.blatt(self.drucker(), bool(self.lage.currentData()))
        self._raster = kontaktbogen.raster(bedruckbar, self.spalten.value())
        eintraege = self.eintraege()
        seiten = self._raster.seiten(len(eintraege))
        self.bogen.groesse_mm, self.bogen.raster = groesse_mm, self._raster
        self.bogen.eintraege, self.bogen.seiten = eintraege, seiten
        self.bogen.seite = min(self.bogen.seite, seiten)
        self._seite_anzeigen()
        anzahl = len(eintraege)
        bilder = _("1 Bild") if anzahl == 1 else _("{anzahl} Bilder").format(anzahl=anzahl)
        self.info.setText(_("{bilder} auf {seiten} · je Bild bis {kante}").format(
            bilder=bilder, seiten=seite_anzahl(seiten), kante=cm(self._raster.kante)))
        self.los_knopf.setText(_("Als PDF speichern …") if self.ist_pdf() else _("Drucken"))
        self.los_knopf.setEnabled(anzahl > 0 and self.drucker_wahl.count() > 0)


def seite_anzahl(seiten: int) -> str:
    return _("1 Seite") if seiten == 1 else _("{seiten} Seiten").format(seiten=seiten)
