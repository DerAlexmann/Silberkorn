"""
Dialog "Bilder vergleichen": zwei Bilder nebeneinander, gemeinsam gezoomt

Links der Favorit, rechts ein Kandidat (bildvergleich.Reihe). Einpassen, 100 %, Mausrad,
Doppelklick und Verschieben wirken auf beide Seiten, solange die Ansicht gekoppelt ist -
bei verschieden grossen Bildern an dieselbe Stelle im Verhaeltnis. Unter jedem Bild
stehen Name, Pixel, Datum und Aufnahmedaten, die Bewertung und "Bearbeiten".

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import os
import traceback

from PySide6.QtCore import QEventLoop, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import bewertung, bildvergleich
from .bildvergleich import Vergleichsbild
from .leinwand import Leinwand
from .uebersetzung import _


def sterne_text(anzahl: int) -> str:
    return _("1 Stern") if anzahl == 1 else _("{n} Sterne").format(n=anzahl)


def angaben_text(bild: Vergleichsbild) -> str:
    """Pixel, Datum, Kamera und Belichtung - eine Zeile je Gruppe, Leeres faellt weg."""
    zeilen = []
    if bild.form is not None:
        hoehe, breite = bild.form
        pixel = f"{breite} × {hoehe} px"
        if bild.verkleinert:
            pixel += " " + _("(verkleinert – zu wenig Speicher)")
        zeilen.append(pixel)
    if bild.datum:
        zeilen.append((_("Aufnahme {datum}") if bild.datum_aufnahme
                       else _("Geändert {datum}")).format(datum=bild.datum))
    geraet = " · ".join(bild.aufnahme[name] for name in ("kamera", "objektiv")
                        if name in bild.aufnahme)
    for zeile in (geraet, bild.aufnahme.get("belichtung", "")):
        if zeile:
            zeilen.append(zeile)
    if bild.veraltet:
        zeilen.append(_("Die Begleitdatei passt nicht ganz zum Bild."))
    elif bild.bearbeitet:
        zeilen.append(_("Mit der Bearbeitung aus der Begleitdatei"))
    if bild.verworfen:
        zeilen.append(_("Ungültige Werte der Begleitdatei übergangen."))
    return "\n".join(zeilen)


class BewertungsLeiste(QWidget):
    """Fuenf Sterne und "Ausschuss" - wie in der Kachel: ein Klick auf den gesetzten Stern
    nimmt die Bewertung weg. Gezeigt wird, was in der Datei steht (setzen)."""

    gewaehlt = Signal(int)                       # -1 Ausschuss, 0 bis 5

    def __init__(self, gesperrt_text):
        super().__init__()
        self._gesperrt_text = gesperrt_text
        self.stand = bewertung.KEINE
        aufbau = QHBoxLayout(self)
        aufbau.setContentsMargins(0, 0, 0, 0)
        aufbau.setSpacing(0)
        self.sterne: list[QPushButton] = []
        for anzahl in range(1, 6):
            knopf = QPushButton("☆", objectName="stern")
            knopf.setAccessibleName(sterne_text(anzahl))
            knopf.clicked.connect(lambda _an=False, n=anzahl: self._stern(n))
            aufbau.addWidget(knopf)
            self.sterne.append(knopf)
        aufbau.addSpacing(8)
        self.ausschuss = QPushButton(_("Ausschuss"), checkable=True)
        self.ausschuss.setAccessibleName(_("Ausschuss"))
        self.ausschuss.clicked.connect(self._ausschuss)
        aufbau.addWidget(self.ausschuss)
        self.setzen(bewertung.KEINE, False)

    def setzen(self, stand: bewertung.Stand, offen: bool = True):
        """offen=False: kein Bild - alles gesperrt."""
        self.stand = stand
        frei = offen and stand.aenderbar
        gesperrt = "" if not offen or stand.aenderbar else self._gesperrt_text(stand)
        for anzahl, knopf in enumerate(self.sterne, 1):
            knopf.setText("★" if anzahl <= max(stand.wert, 0) else "☆")
            knopf.setEnabled(frei)
            knopf.setToolTip(gesperrt or (_("Bewertung entfernen") if anzahl == stand.wert
                                          else sterne_text(anzahl)))
        ausschuss = stand.wert == bewertung.AUSSCHUSS
        self.ausschuss.setChecked(ausschuss)
        self.ausschuss.setEnabled(frei)
        self.ausschuss.setToolTip(gesperrt or (_("Ausschuss aufheben") if ausschuss else
                                               _("Als Ausschuss markieren – löscht nichts")))

    def _stern(self, anzahl: int):
        self.gewaehlt.emit(0 if anzahl == self.stand.wert else anzahl)

    def _ausschuss(self):
        ausschuss = self.stand.wert == bewertung.AUSSCHUSS
        self.ausschuss.setChecked(ausschuss)          # erst, wenn es in der Datei steht
        self.gewaehlt.emit(0 if ausschuss else bewertung.AUSSCHUSS)


class Seite(QFrame):
    """Eine Haelfte: Ueberschrift, Leinwand, Angaben, Bewertung und "Bearbeiten"."""

    bearbeiten = Signal()

    def __init__(self, gesperrt_text):
        super().__init__(objectName="karte")
        self.bild: Vergleichsbild | None = None
        innen = QVBoxLayout(self)
        innen.setContentsMargins(12, 10, 12, 12)
        innen.setSpacing(6)
        self.titel = QLabel(objectName="kartentitel")
        innen.addWidget(self.titel)
        self.leinwand = Leinwand()
        self.leinwand.setAcceptDrops(False)
        for zeile in (self.leinwand.leer, self.leinwand.hinweis):
            zeile.setTextFormat(Qt.TextFormat.PlainText)    # Fehlertexte nennen Dateien
        innen.addWidget(self.leinwand, 1)
        self.name = QLabel()
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        innen.addWidget(self.name)
        self.angaben = QLabel(objectName="nebentext")
        self.angaben.setTextFormat(Qt.TextFormat.PlainText)
        self.angaben.setWordWrap(True)
        innen.addWidget(self.angaben)
        leiste = QHBoxLayout()
        self.bewertung = BewertungsLeiste(gesperrt_text)
        leiste.addWidget(self.bewertung)
        leiste.addStretch(1)
        self.bearbeiten_knopf = QPushButton(_("Bearbeiten"))
        self.bearbeiten_knopf.setToolTip(_("Schließt den Vergleich und öffnet dieses Bild im "
                                           "Reiter Bearbeiten."))
        self.bearbeiten_knopf.clicked.connect(self.bearbeiten.emit)
        leiste.addWidget(self.bearbeiten_knopf)
        innen.addLayout(leiste)
        self.zeigen(None, bewertung.KEINE)

    def rechnen_zeigen(self, pfad: str):
        """Solange das Bild gerechnet wird."""
        self.name.setText(os.path.basename(pfad))
        self.angaben.setText("")
        self.leinwand.leer.setText(_("Wird gerechnet …"))
        self.leinwand.hinweis.setText("")
        self.leinwand.zeigen(None)

    def zeigen(self, bild: Vergleichsbild | None, stand: bewertung.Stand):
        """Name, Angaben und Bewertung; das Bild selbst setzt der Dialog."""
        self.bild = bild
        self.name.setText("" if bild is None else os.path.basename(bild.pfad))
        self.name.setToolTip("" if bild is None else bild.pfad)
        if bild is not None and bild.fehler:
            self.leinwand.leer.setText(_("Lässt sich nicht laden"))
            self.leinwand.hinweis.setText(bild.fehler)
            self.angaben.setText("")
        else:
            self.leinwand.leer.setText("")
            self.leinwand.hinweis.setText("")
            self.angaben.setText("" if bild is None else angaben_text(bild))
        self.bewertung.setzen(stand, bild is not None)
        self.bearbeiten_knopf.setEnabled(bild is not None)


class VergleichDialog(QDialog):
    def __init__(self, eltern, pfade: list[str], staende: dict[str, bewertung.Stand],
                 bewerten, gesperrt_text, laden=bildvergleich.laden):
        """pfade: mindestens zwei, in der Reihenfolge der Ordneransicht; staende: ihre
        Bewertungen. bewerten(pfad, wert, melden) -> bool schreibt eine Bewertung und meldet
        mit melden(text, fehler), was geschah; gesperrt_text(stand) sagt, warum eine
        Bewertung fest ist. laden(pfad) -> Vergleichsbild rechnet ein Bild."""
        super().__init__(eltern)
        self.setWindowTitle(_("Bilder vergleichen"))
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.reihe = bildvergleich.Reihe(pfade)
        self.staende = dict(staende)
        self._bewerten = bewerten
        self._speicher = bildvergleich.Speicher(laden)
        self._koppelt = False
        self._gezeigt = False
        self.zu_bearbeiten: str | None = None
        self.bewertet = False                      # mindestens eine Bewertung geschrieben

        aufbau = QVBoxLayout(self)
        aufbau.setSpacing(8)
        aufbau.addLayout(self._leiste())
        seiten = QHBoxLayout()
        seiten.setSpacing(8)
        self.links, self.rechts = Seite(gesperrt_text), Seite(gesperrt_text)
        for seite in (self.links, self.rechts):
            seite.leinwand.ansicht_geaendert.connect(lambda s=seite: self._ansicht_geaendert(s))
            seite.bewertung.gewaehlt.connect(lambda wert, s=seite: self._bewerten_auf(s, wert))
            seite.bearbeiten.connect(lambda s=seite: self._bearbeiten(s))
            seiten.addWidget(seite, 1)
        aufbau.addLayout(seiten, 1)
        unten = QHBoxLayout()
        self.meldung = QLabel(objectName="nebentext")
        self.meldung.setTextFormat(Qt.TextFormat.PlainText)
        unten.addWidget(self.meldung, 1)
        schliessen = QPushButton(_("Schließen"))
        schliessen.clicked.connect(self.reject)
        unten.addWidget(schliessen)
        aufbau.addLayout(unten)

        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self.blaettern(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self.blaettern(1))
        self.setMinimumSize(900, 560)
        bildschirm = QGuiApplication.primaryScreen()
        if bildschirm is not None:
            frei = bildschirm.availableGeometry()
            self.resize(max(900, int(frei.width() * 0.9)), max(560, int(frei.height() * 0.85)))
        self._knoepfe()

    def _leiste(self) -> QHBoxLayout:
        leiste = QHBoxLayout()
        leiste.setSpacing(6)
        self.einpassen_knopf = QPushButton(_("Einpassen"), objectName="zoom")
        self.einpassen_knopf.setToolTip(_("Beide Bilder ganz zeigen"))
        self.einpassen_knopf.clicked.connect(lambda: self.zoomen(None))
        self.voll_knopf = QPushButton("100 %", objectName="zoom")
        self.voll_knopf.setToolTip(_("Ein Bildpixel auf einem Bildschirmpixel – Mausrad und "
                                     "Doppelklick zoomen, Ziehen verschiebt."))
        self.voll_knopf.setAccessibleName(_("100 Prozent"))
        self.voll_knopf.clicked.connect(lambda: self.zoomen(1.0))
        self.koppeln_knopf = QPushButton("🔗", objectName="zoomsymbol", checkable=True)
        self.koppeln_knopf.setChecked(True)
        self.koppeln_knopf.setAccessibleName(_("Ansicht koppeln"))
        self.koppeln_knopf.setToolTip(_(
            "Beide Seiten gemeinsam zoomen und verschieben – bei verschieden großen Bildern "
            "an dieselbe Stelle im Verhältnis."))
        self.koppeln_knopf.toggled.connect(self._koppeln_umgeschaltet)
        self.zurueck_knopf = QPushButton("◀", objectName="zoomsymbol")
        self.zurueck_knopf.setToolTip(_("Voriger Kandidat (←)"))
        self.zurueck_knopf.setAccessibleName(_("Voriger Kandidat"))
        self.zurueck_knopf.clicked.connect(lambda: self.blaettern(-1))
        self.stelle = QLabel(objectName="nebentext", alignment=Qt.AlignmentFlag.AlignCenter)
        self.vor_knopf = QPushButton("▶", objectName="zoomsymbol")
        self.vor_knopf.setToolTip(_("Nächster Kandidat (→)"))
        self.vor_knopf.setAccessibleName(_("Nächster Kandidat"))
        self.vor_knopf.clicked.connect(lambda: self.blaettern(1))
        self.tauschen_knopf = QPushButton(_("⇆ Tauschen"))
        self.tauschen_knopf.setAccessibleName(_("Tauschen"))
        self.tauschen_knopf.setToolTip(
            _("Den Kandidaten zum Favoriten machen – der bisherige Favorit wird Kandidat.")
            if self.reihe.blaetterbar else _("Die beiden Seiten tauschen."))
        self.tauschen_knopf.clicked.connect(self.tauschen)
        for knopf in (self.einpassen_knopf, self.voll_knopf, self.koppeln_knopf):
            leiste.addWidget(knopf)
        leiste.addStretch(1)
        for teil in (self.zurueck_knopf, self.stelle, self.vor_knopf, self.tauschen_knopf):
            leiste.addWidget(teil)
        return leiste

    # ------------------------------------------------------------------
    # Bilder
    # ------------------------------------------------------------------

    def showEvent(self, ereignis):                    # noqa: N802 - Qt-Name
        super().showEvent(ereignis)
        if not self._gezeigt:
            self._gezeigt = True
            QTimer.singleShot(0, self.anzeigen)      # erst das Fenster, dann das Rechnen

    def anzeigen(self):
        """Favorit und Kandidat zeigen - was nicht im Speicher ist, wird jetzt gerechnet."""
        for seite, pfad in ((self.links, self.reihe.links), (self.rechts, self.reihe.rechts)):
            if self._speicher.da(pfad):
                bild = self._speicher.holen(pfad)        # zuletzt gebraucht: bleibt im Speicher
            else:
                seite.rechnen_zeigen(pfad)
                QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                bild = self._rechnen(pfad)
            if seite.bild is not bild:
                self._seite_setzen(seite, bild)
        self._knoepfe()

    def _rechnen(self, pfad: str) -> Vergleichsbild:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return self._speicher.holen(pfad)
        except Exception as grund:                  # noqa: BLE001 - die Seite soll nie haengen
            traceback.print_exc()
            return Vergleichsbild(pfad, fehler=f"{type(grund).__name__}: {grund}")
        finally:
            QApplication.restoreOverrideCursor()

    def _seite_setzen(self, seite: Seite, bild: Vergleichsbild):
        """Ein anderes Bild auf eine Seite - Zoom und Lage im Verhaeltnis bleiben. Gekoppelt
        gelten die der anderen Seite, wenn sie ein Bild zeigt (die eigene stand vielleicht
        auf einem Bild, das sich nicht laden liess)."""
        leinwand = seite.leinwand
        alt_form = leinwand.voll_form if seite.bild is not None else None
        seite.zeigen(bild, self.staende.get(bild.pfad, bewertung.KEINE))
        leinwand.voll_form = bild.form
        if bild.form is None:
            leinwand.zoom = None
            leinwand.zeigen(None)
            return
        hoehe, breite = bild.form
        vorbild = self._andere(seite).leinwand
        if self.koppeln_knopf.isChecked() and vorbild.voll_form is not None:
            zoom = vorbild.zoom
            mitte = bildvergleich.mitte_uebertragen(vorbild.mitte, vorbild.voll_form, bild.form)
        else:
            zoom = leinwand.zoom
            mitte = (bildvergleich.mitte_uebertragen(leinwand.mitte, alt_form, bild.form)
                     if alt_form is not None else (breite / 2, hoehe / 2))
        leinwand.ansicht_uebernehmen(zoom, mitte)      # zeichnet ueber _ansicht_geaendert

    def _bild_zeigen(self, seite: Seite):
        """Eingepasst die Vorschau, vergroessert der sichtbare Ausschnitt des vollen Bildes."""
        bild, leinwand = seite.bild, seite.leinwand
        if bild is None or bild.voll is None:
            leinwand.zeigen(None)
        elif leinwand.zoom is None:
            leinwand.zeigen(bild.vorschau)
        else:
            bereich = leinwand.sichtbarer_bereich()
            if bereich is not None:
                leinwand.zeigen_ausschnitt(bildvergleich.ausschnitt(bild.voll, bereich),
                                           *bereich[:2])

    def _andere(self, seite: Seite) -> Seite:
        return self.rechts if seite is self.links else self.links

    def _ansicht_geaendert(self, seite: Seite):
        self._bild_zeigen(seite)
        if self.koppeln_knopf.isChecked() and not self._koppelt:
            self._folgen(seite, self._andere(seite))

    def _folgen(self, von: Seite, nach: Seite):
        """nach bekommt Zoom und Lage von von - im Verhaeltnis der Bildgroessen."""
        quelle, ziel = von.leinwand, nach.leinwand
        if quelle.voll_form is None or ziel.voll_form is None:
            return
        self._koppelt = True
        try:
            ziel.ansicht_uebernehmen(quelle.zoom, bildvergleich.mitte_uebertragen(
                quelle.mitte, quelle.voll_form, ziel.voll_form))
        finally:
            self._koppelt = False

    def _koppeln_umgeschaltet(self, an: bool):
        if an:
            self._folgen(self.links, self.rechts)

    def zoomen(self, zoom: float | None):
        for seite in (self.links, self.rechts):
            seite.leinwand.zoom_setzen(zoom)

    def blaettern(self, schritt: int):
        if self.reihe.blaetterbar:
            self.reihe.blaettern(schritt)
            self.anzeigen()

    def tauschen(self):
        self.reihe.tauschen()
        self.anzeigen()

    def _knoepfe(self):
        blaetterbar = self.reihe.blaetterbar
        for teil in (self.zurueck_knopf, self.stelle, self.vor_knopf):
            teil.setVisible(blaetterbar)
        nummer, anzahl = self.reihe.stelle()
        self.stelle.setText(_("Kandidat {nummer}/{anzahl}").format(nummer=nummer,
                                                                   anzahl=anzahl))
        self.links.titel.setText(_("Favorit"))
        self.rechts.titel.setText(_("Kandidat"))

    # ------------------------------------------------------------------
    # Bewerten und Bearbeiten
    # ------------------------------------------------------------------

    def melden(self, text: str, fehler: bool = False):
        self.meldung.setObjectName("warnung" if fehler else "nebentext")
        self.meldung.style().unpolish(self.meldung)
        self.meldung.style().polish(self.meldung)
        self.meldung.setText(str(text))

    def _bewerten_auf(self, seite: Seite, wert: int):
        if seite.bild is None:
            return
        pfad = seite.bild.pfad
        try:
            geschrieben = self._bewerten(pfad, wert, self.melden)
        except Exception as grund:                  # noqa: BLE001 - sonst nur auf stderr
            self.melden(_("Die Bewertung ließ sich nicht neben dem Bild sichern: {grund}")
                        .format(grund=f"{type(grund).__name__}: {grund}"), True)
            return
        if not geschrieben:
            return
        stand = bewertung.Stand(wert, "eigen")
        self.staende[pfad] = stand
        self.bewertet = True
        for beide in (self.links, self.rechts):
            if beide.bild is not None and beide.bild.pfad == pfad:
                beide.bewertung.setzen(stand)

    def _bearbeiten(self, seite: Seite):
        if seite.bild is not None:
            self.zu_bearbeiten = seite.bild.pfad
            self.accept()

    def done(self, ergebnis):
        self._speicher.leeren()                    # die vollen Bilder nicht laenger halten
        for seite in (self.links, self.rechts):
            seite.bild = None
            seite.leinwand.zeigen(None)
        super().done(ergebnis)
