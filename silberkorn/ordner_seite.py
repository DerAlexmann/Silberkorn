"""
Reiter "Ordner": die Bilder eines Ordners als Kacheln, Doppelklick oeffnet

Die Vorschaubilder entstehen in einem Hintergrund-Thread, nur fuer die Kacheln,
die gerade zu sehen sind - das fragt die Liste selbst an, wenn sie eine Kachel
zeichnet. Woher ein Vorschaubild kommt, steht in vorschaubilder.py; teure
landen im verschluesselten Vorschau-Cache (vorschau_cache.py), dessen Groesse
und Ort der Anwender bestimmt. Der Thread besitzt den Cache allein - SQLite
teilt Verbindungen nicht zwischen Threads.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import collections
import math
import os
import re
import stat
import tempfile
import threading

import numpy as np
from PySide6.QtCore import (
    QAbstractListModel,
    QDir,
    QEvent,
    QObject,
    QPointF,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from . import (
    anzeigeprofil,
    bewertung,
    einstellungen,
    farben,
    voreinstellungen,
    vorschau_cache,
    vorschaubilder,
)
from .stapel import Auftrag, Stapel, StapelAbbruch
from .stapel_dialog import StapelDialog, bericht_text
from .uebersetzung import _

KACHEL = 160                  # Kantenlaenge einer Kachel auf dem Bildschirm
IM_SPEICHER = 3000            # so viele Vorschaubilder haelt die Ansicht im Arbeitsspeicher
AUFRAEUMEN_S = 1.0            # so lange raeumt der Cache je Leerlauf auf
BEARBEITET_ROLLE = Qt.ItemDataRole.UserRole + 1
PFAD_ROLLE = Qt.ItemDataRole.UserRole + 2
ZUSTAND_ROLLE = Qt.ItemDataRole.UserRole + 3     # "ordner", "laedt", "fehlt" oder "bild"
BEWERTUNG_ROLLE = Qt.ItemDataRole.UserRole + 4   # bewertung.Stand eines Bildes
RAND = 6                      # Luft um den Inhalt einer Kachel
# Sterne und Papierkorb in der Kachel: Felder, die auch mit dem Finger zu treffen sind
STERN_B, FELD_H, KORB_B, FELD_LUECKE = 20, 24, 24, 6


def _natuerlich(name: str):
    """Sortierschluessel: Bild2 vor Bild10."""
    # isdecimal statt isdigit: "²" ist eine Ziffer, aber int() kennt sie nicht
    return [int(t) if t.isdecimal() else t.casefold() for t in re.split(r"(\d+)", name)]


def _versteckt(eintrag: os.DirEntry) -> bool:
    """Unter Windows als versteckt oder System markiert - etwa AppData oder die alten
    Verweise wie "Anwendungsdaten", die sich nicht oeffnen lassen."""
    if os.name != "nt":
        return False
    try:
        merkmale = eintrag.stat(follow_symlinks=False).st_file_attributes
    except OSError:
        return True
    return bool(merkmale & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))


def _durchsuchen(ordner: str):
    """Unterordner, Bilddateien (unsortiert) und deren Aenderungszeiten - ohne versteckte."""
    try:
        eintraege = list(os.scandir(ordner))
    except OSError:
        return [], [], {}
    unterordner, bilder, zeiten = [], [], {}
    for eintrag in eintraege:
        if eintrag.name.startswith(".") or _versteckt(eintrag):
            continue
        try:
            if eintrag.is_dir():
                unterordner.append(eintrag.path)
            elif vorschaubilder.ist_bild(eintrag.name) and eintrag.is_file():
                bilder.append(eintrag.path)
                zeiten[eintrag.path] = eintrag.stat().st_mtime    # unter Windows ohne Zugriff
        except OSError:
            continue
    return unterordner, bilder, zeiten


def _nach_name(pfad: str):
    return _natuerlich(os.path.basename(pfad))


def ordner_inhalt(ordner: str) -> tuple[list[str], list[str], dict[str, float]]:
    """Wie eintraege_im_ordner, dazu die Aenderungszeit jedes Bildes (fuer die Sortierung)."""
    unterordner, bilder, zeiten = _durchsuchen(ordner)
    return sorted(unterordner, key=_nach_name), sorted(bilder, key=_nach_name), zeiten


def eintraege_im_ordner(ordner: str) -> tuple[list[str], list[str]]:
    """Unterordner und Bilddateien eines Ordners, je natuerlich sortiert - ohne versteckte.
    Unterordner werden nicht durchsucht; hinein geht es erst per Doppelklick."""
    return ordner_inhalt(ordner)[:2]


def bilder_im_ordner(ordner: str) -> list[str]:
    """Die Bilddateien eines Ordners, ohne Unterordner und versteckte Dateien."""
    return eintraege_im_ordner(ordner)[1]


# --------------------------------------------------------------------------
# Einstellungen des Caches
# --------------------------------------------------------------------------

def cache_mb() -> int | None:
    """Die gewaehlte Groesse in MB, 0 fuer aus - None, solange nicht gefragt wurde."""
    wert = einstellungen.load_config().get("vorschau_cache_mb")
    if isinstance(wert, bool) or not isinstance(wert, int):
        return None
    return wert if wert == 0 or vorschau_cache.MIN_MB <= wert <= vorschau_cache.MAX_MB else None


def cache_ordner() -> str:
    wert = einstellungen.load_config().get("vorschau_cache_ort")
    return wert if isinstance(wert, str) and wert else vorschau_cache.standard_ordner()


def ausgenommene_ordner() -> list[str]:
    wert = einstellungen.load_config().get("vorschau_ausgenommen")
    if not isinstance(wert, list):
        return []
    return [o for o in wert if isinstance(o, str) and o]


def _speichern(**werte):
    daten = einstellungen.load_config()
    daten.update(werte)
    einstellungen.save_config(daten)


# --------------------------------------------------------------------------
# Hintergrund: Vorschaubilder und Cache
# --------------------------------------------------------------------------

class VorschauDienst(QObject):
    """Ein Thread fuer alle Vorschaubilder. Auftraege fuer Kacheln werden zuletzt-zuerst
    erledigt - die zuletzt angefragten sind die, die gerade zu sehen sind."""

    fertig = Signal(int, str, QImage, bool)       # Durchgang, Pfad, Bild, bearbeitet
    fehlt = Signal(int, str)                      # kein Vorschaubild moeglich
    cache_stand = Signal(object)                  # (belegt, Dateigroesse, Anzahl) oder None
    meldung = Signal(str)

    def __init__(self):
        super().__init__()
        self._bedingung = threading.Condition()
        self._kacheln: collections.OrderedDict[str, int] = collections.OrderedDict()
        self._befehle: collections.deque = collections.deque()
        self._ausgenommen: list[str] = []
        self._ende = False
        self._cache: vorschau_cache.VorschauCache | None = None
        self._aufraeumen_ab: int | None = None
        self._thread = threading.Thread(target=self._schleife, name="Vorschaubilder",
                                        daemon=True)
        self._thread.start()

    # Aus dem Hauptthread ------------------------------------------------

    def anfordern(self, durchgang: int, pfad: str):
        with self._bedingung:
            self._kacheln.pop(pfad, None)
            self._kacheln[pfad] = durchgang
            self._bedingung.notify()

    def verwerfen(self):
        """Ein neuer Ordner: offene Kacheln des alten nicht mehr rechnen."""
        with self._bedingung:
            self._kacheln.clear()

    def befehl(self, *befehl):
        with self._bedingung:
            self._befehle.append(befehl)
            self._bedingung.notify()

    def ausnehmen(self, ordner: list[str]):
        with self._bedingung:
            self._ausgenommen = list(ordner)

    def beenden(self):
        with self._bedingung:
            self._ende = True
            self._bedingung.notify()
        self._thread.join(timeout=5)

    # Im Thread ----------------------------------------------------------

    def _schleife(self):
        while True:
            with self._bedingung:
                while (not self._ende and not self._befehle and not self._kacheln
                       and self._aufraeumen_ab is None):
                    self._bedingung.wait()
                if self._ende:
                    break
                befehl = self._befehle.popleft() if self._befehle else None
                kachel = None
                if befehl is None and self._kacheln:
                    kachel = self._kacheln.popitem(last=True)
                ausgenommen = list(self._ausgenommen)
            try:
                if befehl is not None:
                    self._ausfuehren(befehl)
                elif kachel is not None:
                    self._kachel(*kachel, ausgenommen)
                else:
                    self._aufraeumen()
            except Exception as fehler:          # noqa: BLE001 - der Thread darf nie sterben
                self.meldung.emit(str(fehler))
        if self._cache is not None:
            self._cache.schliessen()

    def _ausfuehren(self, befehl):
        art = befehl[0]
        if art == "oeffnen":
            _art, pfad, groesse = befehl
            self._schliessen()
            try:
                self._cache = vorschau_cache.anlegen(pfad, groesse)
                self._aufraeumen_ab = 0
            except vorschau_cache.CacheFehler as fehler:
                self.meldung.emit(_("Der Vorschau-Cache lässt sich nicht anlegen: {grund}")
                                  .format(grund=str(fehler)))
        elif art == "entfernen":
            self._schliessen()
            try:
                vorschau_cache.entfernen(befehl[1])
            except vorschau_cache.CacheFehler as fehler:
                self.meldung.emit(str(fehler))
        elif art == "leeren" and self._cache is not None:
            self._cache.leeren()
        elif art == "vergessen" and self._cache is not None:
            self._cache.vergessen(befehl[1])
        self._stand_melden()                           # auch fuer den Befehl "stand"

    def _schliessen(self):
        if self._cache is not None:
            self._cache.schliessen()
            self._cache = None
        self._aufraeumen_ab = None

    def _stand_melden(self):
        if self._cache is None:
            self.cache_stand.emit(None)
        else:
            self.cache_stand.emit((self._cache.belegt(), self._cache.dateigroesse(),
                                   self._cache.anzahl()))

    def _aufraeumen(self):
        if self._cache is None:
            self._aufraeumen_ab = None
            return
        weiter = self._cache.aufraeumen(AUFRAEUMEN_S, self._aufraeumen_ab or 0)
        self._aufraeumen_ab = weiter or None

    def _kachel(self, pfad: str, durchgang: int, ausgenommen: list[str]):
        bearbeitet = vorschaubilder.aus_begleitdatei(pfad)
        if bearbeitet is not None:
            # Die Begleitdatei zeigt das bearbeitete - etwa anonymisierte - Bild; eine
            # Vorschau des Originals soll es daneben nicht geben
            if self._cache is not None:
                self._cache.vergessen(pfad)
            self.fertig.emit(durchgang, pfad, _qimage(bearbeitet), True)
            return
        darf = self._cache is not None and not vorschau_cache.ausgenommen(pfad, ausgenommen)
        if darf:
            daten = self._cache.holen(pfad)
            if daten is not None:
                try:
                    self.fertig.emit(durchgang, pfad,
                                     _qimage(vorschaubilder.dekodieren(daten)), False)
                    return
                except vorschaubilder.VorschauFehler:
                    self._cache.vergessen(pfad)
        try:
            vorschau = vorschaubilder.erzeugen(pfad)
        except vorschaubilder.VorschauFehler:
            self.fehlt.emit(durchgang, pfad)
            return
        if darf and vorschau.teuer:
            self._cache.ablegen(pfad, vorschaubilder.kodieren(vorschau.bild))
        elif self._cache is not None and not darf:
            self._cache.vergessen(pfad)            # ein ausgenommener Ordner
        self.fertig.emit(durchgang, pfad, _qimage(vorschau.bild), False)


class BewertungsDienst(QObject):
    """Liest die Bewertungsdateien eines Ordners im Hintergrund - ein stat je Bild, gelesen
    wird nur, wo eine Datei liegt. Die Kacheln erscheinen sofort, die Sterne kommen danach."""

    fertig = Signal(int, object)                  # Durchgang, {Pfad: bewertung.Stand}
    meldung = Signal(str)

    def __init__(self):
        super().__init__()
        self._aktuell = 0

    def laden(self, durchgang: int, pfade: list[str]):
        self._aktuell = durchgang                 # ein laufender, aelterer Durchgang bricht ab
        threading.Thread(target=self._lesen, args=(durchgang, list(pfade)), daemon=True,
                         name="Bewertungen").start()

    def abbrechen(self):
        """Ein laufendes Lesen gibt auf, sein Ergebnis wird nicht mehr abgeliefert."""
        self._aktuell = -1

    def _lesen(self, durchgang: int, pfade: list[str]):
        try:
            try:
                staende = bewertung.lesen_viele(pfade, lambda: self._aktuell == durchgang)
            except Exception as fehler:          # noqa: BLE001 - der Thread soll nie still sterben
                if self._aktuell == durchgang:
                    self.meldung.emit(_("Die Bewertungen ließen sich nicht lesen: {grund}")
                                      .format(grund=str(fehler)))
                return
            if self._aktuell == durchgang:
                self.fertig.emit(durchgang, staende)
        except RuntimeError:
            pass                                 # das Fenster ist schon zu: nichts mehr zu melden


def _qimage(bild) -> QImage:
    rgb = np.ascontiguousarray(anzeigeprofil.umrechnen(np.asarray(bild.convert("RGB"))))
    hoehe, breite = rgb.shape[:2]
    return QImage(rgb.data, breite, hoehe, breite * 3, QImage.Format.Format_RGB888).copy()


# --------------------------------------------------------------------------
# Liste der Kacheln
# --------------------------------------------------------------------------

class KachelModell(QAbstractListModel):
    def __init__(self, dienst: VorschauDienst):
        super().__init__()
        self.dienst = dienst
        self.pfade: list[str] = []
        self.durchgang = 0
        # Eigener Zaehler der Kacheln: ein neues Monitorprofil laedt die Bilder neu, die
        # gerade gelesenen Bewertungen desselben Ordners sollen dabei nicht verfallen
        self._kachelstand = 0
        self._bilder: collections.OrderedDict[str, tuple[QPixmap, bool]] = \
            collections.OrderedDict()
        self._angefragt: set[str] = set()
        self._fehlend: set[str] = set()
        self.unterordner: set[str] = set()
        self.bewertungen: dict[str, bewertung.Stand] = {}     # getrennt vom Bild-Cache
        self._ordner_symbol = QApplication.style().standardIcon(
            QStyle.StandardPixmap.SP_DirIcon).pixmap(KACHEL * 3 // 4, KACHEL * 3 // 4)
        dienst.fertig.connect(self._fertig)
        dienst.fehlt.connect(self._fehlt)

    def setzen(self, pfade: list[str], unterordner: list[str] = ()):
        self.beginResetModel()
        self.durchgang += 1
        self._kachelstand += 1
        self.dienst.verwerfen()
        self.pfade = [*unterordner, *pfade]
        self.unterordner = set(unterordner)
        self.bewertungen = {}
        self._angefragt.clear()
        self._fehlend.clear()
        self.endResetModel()

    def umordnen(self, pfade: list[str], unterordner: list[str]):
        """Dieselben Eintraege in neuer Reihenfolge; die Auswahl bleibt, wo sie war."""
        neu = [*unterordner, *pfade]
        if neu == self.pfade:
            return
        self.layoutAboutToBeChanged.emit()
        alt = self.persistentIndexList()
        namen = [self.pfade[i.row()] for i in alt]
        stellen = {p: z for z, p in enumerate(neu)}
        self.pfade = neu
        self.changePersistentIndexList(alt, [self.index(stellen[n]) for n in namen])
        self.layoutChanged.emit()

    def _zeile(self, pfad: str) -> int:
        """Die Zeile eines Pfades, auch wenn er anders geschrieben ist (Schraegstriche,
        Gross- und Kleinschreibung); -1, wenn er nicht in der Liste steht."""
        schluessel = os.path.normcase(os.path.normpath(pfad))
        for zeile, eintrag in enumerate(self.pfade):
            if os.path.normcase(os.path.normpath(eintrag)) == schluessel:
                return zeile
        return -1

    def stand_setzen(self, pfad: str, stand: bewertung.Stand):
        """Die Bewertung eines Bildes hat sich geaendert. Die Reihenfolge bleibt - die Kachel
        soll nicht unter der Maus wegspringen."""
        zeile = self._zeile(pfad)
        if zeile < 0 or self.pfade[zeile] in self.unterordner:
            return
        self.bewertungen[self.pfade[zeile]] = stand
        self.dataChanged.emit(self.index(zeile), self.index(zeile))

    def staende_laden(self, durchgang: int, staende: dict) -> bool:
        """Die im Hintergrund gelesenen Bewertungen; False, wenn der Ordner inzwischen ein
        anderer ist."""
        if durchgang != self.durchgang:
            return False
        for pfad, stand in staende.items():
            self.bewertungen.setdefault(pfad, stand)      # ein Klick seither gilt mehr
        if self.pfade:
            self.dataChanged.emit(self.index(0), self.index(len(self.pfade) - 1))
        return True

    def neu_laden(self, pfad: str):
        """Ein Bild hat sich geaendert (etwa seine Begleitdatei): neu anfragen."""
        self._bilder.pop(pfad, None)
        self._angefragt.discard(pfad)
        self._fehlend.discard(pfad)
        if pfad in self.pfade:
            stelle = self.index(self.pfade.index(pfad))
            self.dataChanged.emit(stelle, stelle)

    def alle_neu_laden(self):
        """Die Anzeige hat sich geaendert (Monitorprofil): alle Kacheln neu anfragen. Ein
        neuer Kachelstand verwirft, was noch mit dem alten Profil unterwegs ist."""
        self._kachelstand += 1
        self.dienst.verwerfen()
        self._bilder.clear()
        self._angefragt.clear()
        self._fehlend.clear()
        if self.pfade:
            self.dataChanged.emit(self.index(0), self.index(len(self.pfade) - 1))

    def rowCount(self, eltern=None):                   # noqa: N802 - Qt-Name
        return 0 if eltern is not None and eltern.isValid() else len(self.pfade)

    def data(self, index, rolle=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        pfad = self.pfade[index.row()]
        if rolle == Qt.ItemDataRole.DisplayRole:
            return os.path.basename(pfad)
        if rolle == Qt.ItemDataRole.ToolTipRole:
            return os.path.basename(pfad)
        if rolle == PFAD_ROLLE:
            return pfad
        if rolle == BEWERTUNG_ROLLE:
            return None if pfad in self.unterordner else self.bewertungen.get(pfad,
                                                                              bewertung.KEINE)
        if pfad in self.unterordner:
            return {Qt.ItemDataRole.DecorationRole: self._ordner_symbol,
                    ZUSTAND_ROLLE: "ordner", BEARBEITET_ROLLE: False}.get(rolle)
        if rolle in (Qt.ItemDataRole.DecorationRole, BEARBEITET_ROLLE, ZUSTAND_ROLLE):
            if pfad in self._bilder:
                self._bilder.move_to_end(pfad)
                bild, bearbeitet = self._bilder[pfad]
                return {Qt.ItemDataRole.DecorationRole: bild, BEARBEITET_ROLLE: bearbeitet,
                        ZUSTAND_ROLLE: "bild"}[rolle]
            if pfad in self._fehlend:
                return {ZUSTAND_ROLLE: "fehlt", BEARBEITET_ROLLE: False}.get(rolle)
            if pfad not in self._angefragt:
                self._angefragt.add(pfad)
                self.dienst.anfordern(self._kachelstand, pfad)
            return {ZUSTAND_ROLLE: "laedt", BEARBEITET_ROLLE: False}.get(rolle)
        return None

    def _fertig(self, stand: int, pfad: str, bild: QImage, bearbeitet: bool):
        if stand != self._kachelstand or pfad not in self.pfade:
            return
        self._bilder[pfad] = (QPixmap.fromImage(bild), bearbeitet)
        while len(self._bilder) > IM_SPEICHER:
            alt, _bild = self._bilder.popitem(last=False)
            self._angefragt.discard(alt)
        self._angefragt.discard(pfad)
        stelle = self.index(self.pfade.index(pfad))
        self.dataChanged.emit(stelle, stelle)

    def _fehlt(self, stand: int, pfad: str):
        if stand == self._kachelstand and pfad in self.pfade:
            self._fehlend.add(pfad)
            self._angefragt.discard(pfad)
            stelle = self.index(self.pfade.index(pfad))
            self.dataChanged.emit(stelle, stelle)


def zwei_zeilen(metrik, text: str, breite: int) -> list[str]:
    """Ein Name in hoechstens zwei Zeilen, umgebrochen an Leerzeichen, Unter- und
    Bindestrichen wie im Explorer; was nicht passt, endet in "…"."""
    if metrik.horizontalAdvance(text) <= breite:
        return [text]
    trenner = [i + 1 for i, z in enumerate(text) if z in " _-." and i + 1 < len(text)]
    erste = ""
    for stelle in trenner:                         # so viel wie moeglich in die erste Zeile
        if metrik.horizontalAdvance(text[:stelle].rstrip()) <= breite:
            erste = text[:stelle]
    if not erste:                                  # kein Trenner passt: hart umbrechen
        stelle = len(text)
        while stelle > 1 and metrik.horizontalAdvance(text[:stelle]) > breite:
            stelle -= 1
        erste = text[:stelle]
    rest = text[len(erste):]
    return [erste.rstrip(), metrik.elidedText(rest, Qt.TextElideMode.ElideRight, breite)]


def bild_flaeche(kachel: QRect) -> QRect:
    """Das Quadrat, in dem das Vorschaubild unten buendig sitzt."""
    rahmen = kachel.adjusted(2, 2, -2, -2)
    return QRect(rahmen.left() + (rahmen.width() - KACHEL) // 2, rahmen.top() + RAND,
                 KACHEL, KACHEL)


def gesperrt_text(stand: bewertung.Stand) -> str:
    """Warum sich eine Bewertung nicht aendern laesst."""
    if stand.art == "unlesbar":
        return _("Die Bewertungsdatei neben dem Bild lässt sich nicht lesen und bleibt "
                 "unverändert.")
    return _("Bewertung stammt aus einer fremden XMP-Datei und wird nicht verändert")


def bewertung_felder(flaeche: QRect) -> tuple[list[QRect], QRect]:
    """Die fuenf Sternfelder und das Papierkorbfeld, unten im Bild. Dieselben Rechtecke
    zeichnet der Zeichner und trifft die Liste beim Klicken."""
    gesamt = 5 * STERN_B + FELD_LUECKE + KORB_B
    x = flaeche.left() + (KACHEL - gesamt) // 2
    y = flaeche.bottom() + 1 - FELD_H - 5
    sterne = [QRect(x + i * STERN_B, y, STERN_B, FELD_H) for i in range(5)]
    return sterne, QRect(x + 5 * STERN_B + FELD_LUECKE, y, KORB_B, FELD_H)


def bewertung_ziel(flaeche: QRect, ort) -> tuple | None:
    """Was liegt unter dem Mauszeiger: ("stern", 1 bis 5), ("korb",) oder nichts."""
    sterne, korb = bewertung_felder(flaeche)
    for nummer, feld in enumerate(sterne, 1):
        if feld.contains(ort):
            return ("stern", nummer)
    return ("korb",) if korb.contains(ort) else None


def _stern(feld: QRect) -> QPolygonF:
    mitte = QPointF(feld.center().x() + 0.5, feld.center().y() + 1.0)
    kante = min(feld.width(), feld.height())
    punkte = []
    for ecke in range(10):
        winkel = math.pi * (ecke / 5 - 0.5)
        radius = kante * (0.42 if ecke % 2 == 0 else 0.18)
        punkte.append(QPointF(mitte.x() + radius * math.cos(winkel),
                              mitte.y() + radius * math.sin(winkel)))
    return QPolygonF(punkte)


def _korb(feld: QRect) -> tuple[QPainterPath, QPainterPath]:
    """Papierkorb als Umriss: (Deckel mit Griff, Eimer)."""
    x, y = feld.center().x() + 0.5, feld.center().y() + 0.5
    deckel, eimer = QPainterPath(), QPainterPath()
    deckel.moveTo(x - 7, y - 5)
    deckel.lineTo(x + 7, y - 5)
    deckel.moveTo(x - 2.5, y - 5)
    deckel.lineTo(x - 2.5, y - 8)
    deckel.lineTo(x + 2.5, y - 8)
    deckel.lineTo(x + 2.5, y - 5)
    eimer.moveTo(x - 5.5, y - 3)
    eimer.lineTo(x - 4.5, y + 8)
    eimer.lineTo(x + 4.5, y + 8)
    eimer.lineTo(x + 5.5, y - 3)
    eimer.closeSubpath()
    return deckel, eimer


class KachelZeichner(QStyledItemDelegate):
    """Bild oder Ordnersymbol unten buendig, der Name direkt darunter - wie im Explorer.
    Ein Punkt oben rechts markiert eine Begleitdatei. Solange ein Bild laedt, steht dort
    eine graue Flaeche, ohne moegliche Vorschau ein Fragezeichen. Beim Darueberfahren
    erscheinen fuenf Sterne und ein Papierkorb im Bild; gesetzte Sterne bleiben stehen,
    Ausschuss blendet die Kachel ab."""

    RAND = RAND

    def __init__(self, eltern=None):
        super().__init__(eltern)
        self.hover_zeile = -1                      # die Kachel unter der Maus
        self.hover_ziel = None                     # und was in ihr: ("stern", n) oder ("korb",)

    def sizeHint(self, option, _index):                   # noqa: N802 - Qt-Name
        zeilen = 2 * option.fontMetrics.lineSpacing()
        return QSize(KACHEL + 2 * self.RAND + 8, KACHEL + zeilen + 2 * self.RAND + 6)

    def paint(self, maler: QPainter, option, index):
        maler.save()
        maler.setRenderHint(QPainter.RenderHint.Antialiasing)
        rahmen = option.rect.adjusted(2, 2, -2, -2)
        # Farben aus dem Schema von Silberkorn - die Palette waere die von Windows, im
        # dunklen Windows dunkle Schrift auf dunklem Grund
        schema = farben.THEMES[farben.CURRENT_THEME]
        if option.state & option.state.State_Selected:
            auswahl = QColor(schema["ACCENT"])
            auswahl.setAlpha(50)
            maler.setPen(Qt.PenStyle.NoPen)
            maler.setBrush(auswahl)
            maler.drawRoundedRect(rahmen, 6, 6)
        flaeche = bild_flaeche(option.rect)
        unten = flaeche.bottom()                   # Unterkante des Bildes - darunter der Name
        zustand = index.data(ZUSTAND_ROLLE)
        bild = index.data(Qt.ItemDataRole.DecorationRole)
        stand = index.data(BEWERTUNG_ROLLE)
        if stand is not None and stand.wert == bewertung.AUSSCHUSS:
            maler.setOpacity(0.4)                  # Ausschuss: abgeblendet samt Namen
        if zustand in ("laedt", "fehlt"):
            leer = QRect(flaeche.left() + KACHEL // 8, flaeche.top() + KACHEL // 4,
                         KACHEL * 3 // 4, KACHEL * 3 // 4)
            maler.setPen(Qt.PenStyle.NoPen)
            maler.setBrush(QColor(schema["BTN_BG"]))
            maler.drawRoundedRect(leer, 6, 6)
            if zustand == "fehlt":
                maler.setPen(QColor(schema["MUTED"]))
                schrift = maler.font()
                schrift.setPointSize(schrift.pointSize() * 2)
                maler.setFont(schrift)
                maler.drawText(leer, Qt.AlignmentFlag.AlignCenter, "?")
                maler.setFont(option.font)
        elif isinstance(bild, QPixmap) and not bild.isNull():
            passend = bild                         # nur verkleinern, nie unscharf vergroessern
            if bild.width() > KACHEL or bild.height() > KACHEL:
                passend = bild.scaled(flaeche.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
            groesse = passend.deviceIndependentSize()
            breite, hoehe = round(groesse.width()), round(groesse.height())
            x = flaeche.left() + (KACHEL - breite) // 2
            y = flaeche.bottom() + 1 - hoehe
            maler.drawPixmap(x, y, passend)
            if index.data(BEARBEITET_ROLLE):
                maler.setPen(Qt.PenStyle.NoPen)
                maler.setBrush(QColor(schema["ACCENT"]))
                maler.drawEllipse(x + breite - 16, y + 6, 10, 10)
        metrik = option.fontMetrics
        breite = rahmen.width() - 2 * self.RAND
        maler.setPen(QColor(schema["TEXT"]))
        for nummer, zeile in enumerate(zwei_zeilen(metrik, index.data(), breite)):
            ort = QRect(rahmen.left() + self.RAND, unten + 6 + nummer * metrik.lineSpacing(),
                        breite, metrik.lineSpacing())
            maler.drawText(ort, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, zeile)
        maler.setOpacity(1.0)
        if stand is not None:
            self._bewertung_malen(maler, flaeche, stand, index.row() == self.hover_zeile,
                                  schema)
        maler.restore()

    def _bewertung_malen(self, maler: QPainter, flaeche: QRect, stand, darueber: bool, schema):
        """Beim Darueberfahren fuenf leere Sterne und der Papierkorb; gesetzte Sterne und
        Ausschuss bleiben auch ohne Maus sichtbar. Fremde Bewertungen sind ausgegraut."""
        ausschuss = stand.wert == bewertung.AUSSCHUSS
        sterne = max(stand.wert, 0)
        if not darueber and not sterne and not ausschuss:
            return
        felder, korb = bewertung_felder(flaeche)
        gesperrt = not stand.aenderbar
        ziel = self.hover_ziel if darueber and not gesperrt else None
        if darueber:
            traeger = felder[0].united(korb)
        elif ausschuss:
            traeger = korb
        else:
            traeger = felder[0].united(felder[sterne - 1])
        maler.setPen(Qt.PenStyle.NoPen)
        maler.setBrush(QColor(schema["PLAKETTE"]))
        maler.drawRoundedRect(traeger.adjusted(-3, 1, 3, -1), 7, 7)

        umriss = QColor(schema["PLAKETTE_TEXT"])
        gold = QColor(schema["STERN"])
        if gesperrt:
            umriss.setAlpha(110)
            gold = QColor(schema["MUTED"])
        voll = sterne
        if ziel is not None and ziel[0] == "stern":
            voll = ziel[1]                         # Vorschau: bis zum Stern unter der Maus
        for nummer, feld in enumerate(felder, 1):
            if not darueber and nummer > sterne:
                break
            gefuellt = nummer <= voll
            farbe = gold if gefuellt else umriss
            maler.setPen(QPen(farbe, 1.2))
            maler.setBrush(farbe if gefuellt else Qt.BrushStyle.NoBrush)
            maler.drawPolygon(_stern(feld))
        if darueber or ausschuss:
            if ausschuss:
                farbe = QColor(schema["DANGER"])
            elif ziel == ("korb",):
                farbe = QColor(schema["ACCENT"])
            else:
                farbe = umriss
            deckel, eimer = _korb(korb)
            maler.setPen(QPen(farbe, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                              Qt.PenJoinStyle.RoundJoin))
            fuellung = QColor(farbe)
            fuellung.setAlpha(110)
            maler.setBrush(fuellung if ausschuss else Qt.BrushStyle.NoBrush)
            maler.drawPath(eimer)
            maler.setBrush(Qt.BrushStyle.NoBrush)
            maler.drawPath(deckel)


class KachelListe(QListView):
    """Die Liste der Kacheln. Sterne und Papierkorb in einer Kachel nimmt sie selbst an -
    ein Klick darauf waehlt die Kachel nicht und oeffnet sie nicht."""

    bewertung_gewaehlt = Signal(str, int)         # Pfad, neuer Wert (-1 Ausschuss, 0 bis 5)
    bewertung_gesperrt = Signal(str)              # Klick auf eine fremde Bewertung

    def __init__(self):
        super().__init__()
        self.setObjectName("kacheln")
        self.setMouseTracking(True)
        self.zeichner = KachelZeichner(self)
        self.setItemDelegate(self.zeichner)
        self._verbraucht = False                   # der Druck galt den Sternen
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def setModel(self, modell):                    # noqa: N802 - Qt-Name
        super().setModel(modell)
        modell.modelReset.connect(lambda: self._darueber(-1, None))
        modell.layoutChanged.connect(lambda: self._darueber(-1, None))

    # Wo ist die Maus ---------------------------------------------------

    def ziel_bei(self, ort) -> tuple[int, tuple | None]:
        """(Zeile, Ziel) unter diesem Punkt: -1 ausserhalb von Bildkacheln."""
        index = self.indexAt(ort)
        if not index.isValid() or self.model().pfade[index.row()] in self.model().unterordner:
            return -1, None
        return index.row(), bewertung_ziel(bild_flaeche(self.visualRect(index)), ort)

    def _darueber(self, zeile: int, ziel):
        if (zeile, ziel) == (self.zeichner.hover_zeile, self.zeichner.hover_ziel):
            return
        alt = self.zeichner.hover_zeile
        self.zeichner.hover_zeile, self.zeichner.hover_ziel = zeile, ziel
        modell = self.model()
        for nummer in (alt, zeile):
            if modell is not None and 0 <= nummer < modell.rowCount():
                self.viewport().update(self.visualRect(modell.index(nummer)))

    def tooltip_fuer(self, zeile: int, ziel: tuple) -> str:
        """Der Hinweistext zu einem Stern oder zum Papierkorb."""
        stand = self.model().data(self.model().index(zeile), BEWERTUNG_ROLLE)
        if not stand.aenderbar:
            return gesperrt_text(stand)
        if ziel[0] == "korb":
            if stand.wert == bewertung.AUSSCHUSS:
                return _("Ausschuss aufheben")
            return _("Als Ausschuss markieren – löscht nichts")
        if ziel[1] == stand.wert:
            return _("Bewertung entfernen")
        return _("1 Stern") if ziel[1] == 1 else _("{n} Sterne").format(n=ziel[1])

    # Ereignisse ---------------------------------------------------------

    def mouseMoveEvent(self, ereignis):            # noqa: N802 - Qt-Name
        if self._verbraucht:
            # Der Klick auf einen Stern gehoert uns: Qt kennt dafuer keine Druckposition und
            # zoege sonst ein Gummiband ab dem vorigen Klick (oder startete ein Ziehen)
            ereignis.accept()
        else:
            super().mouseMoveEvent(ereignis)
        self._darueber(*self.ziel_bei(ereignis.position().toPoint()))

    def leaveEvent(self, ereignis):                # noqa: N802 - Qt-Name
        super().leaveEvent(ereignis)
        self._darueber(-1, None)

    def scrollContentsBy(self, dx, dy):            # noqa: N802 - Qt-Name
        super().scrollContentsBy(dx, dy)
        ort = self.viewport().mapFromGlobal(QCursor.pos())
        self._darueber(*(self.ziel_bei(ort) if self.viewport().rect().contains(ort)
                         else (-1, None)))

    def viewportEvent(self, ereignis):             # noqa: N802 - Qt-Name
        if ereignis.type() == QEvent.Type.ToolTip:
            zeile, ziel = self.ziel_bei(ereignis.pos())
            if ziel is not None:
                QToolTip.showText(ereignis.globalPos(), self.tooltip_fuer(zeile, ziel),
                                  self.viewport())
                return True
        return super().viewportEvent(ereignis)

    def mousePressEvent(self, ereignis):           # noqa: N802 - Qt-Name
        self._verbraucht = False
        if ereignis.button() == Qt.MouseButton.LeftButton:
            zeile, ziel = self.ziel_bei(ereignis.position().toPoint())
            if ziel is not None:
                self._verbraucht = True            # keine Auswahl, kein Oeffnen
                self._angeklickt(zeile, ziel)
                ereignis.accept()
                return
        super().mousePressEvent(ereignis)

    def mouseDoubleClickEvent(self, ereignis):     # noqa: N802 - Qt-Name
        # Der zweite Klick eines schnellen Paares auf einen Stern zaehlt nicht noch einmal
        # (er nahme die Bewertung gleich wieder zurueck) und oeffnet das Bild nicht
        if self.ziel_bei(ereignis.position().toPoint())[1] is not None:
            self._verbraucht = True
            ereignis.accept()
            return
        super().mouseDoubleClickEvent(ereignis)

    def mouseReleaseEvent(self, ereignis):         # noqa: N802 - Qt-Name
        if self._verbraucht:
            self._verbraucht = False
            ereignis.accept()
            return
        super().mouseReleaseEvent(ereignis)

    def _angeklickt(self, zeile: int, ziel: tuple):
        modell = self.model()
        pfad = modell.pfade[zeile]
        stand = modell.data(modell.index(zeile), BEWERTUNG_ROLLE)
        if not stand.aenderbar:
            self.bewertung_gesperrt.emit(pfad)
        elif ziel[0] == "korb":
            self.bewertung_gewaehlt.emit(
                pfad, 0 if stand.wert == bewertung.AUSSCHUSS else bewertung.AUSSCHUSS)
        else:
            self.bewertung_gewaehlt.emit(pfad, 0 if ziel[1] == stand.wert else ziel[1])


# --------------------------------------------------------------------------
# Dialog: Vorschau-Cache
# --------------------------------------------------------------------------

def ordner_dialog(eltern, titel: str, start: str) -> str:
    """Einen Ordner waehlen - auch in versteckten Ordnern wie AppData. Der Ordnerdialog von
    Windows springt sonst nicht hinein und beginnt im Benutzerordner."""
    while start and not os.path.isdir(start):
        oben = os.path.dirname(start)
        start = "" if oben == start else oben
    dialog = QFileDialog(eltern, titel, start)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dialog.setFilter(dialog.filter() | QDir.Filter.Hidden)
    if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selectedFiles():
        return ""
    return os.path.normpath(dialog.selectedFiles()[0])


class CacheDialog(QDialog):
    def __init__(self, eltern, stand, erstmals: bool):
        super().__init__(eltern)
        self.setWindowTitle(_("Vorschau-Cache"))
        aufbau = QVBoxLayout(self)
        hinweis = QLabel(objectName="nebentext")
        hinweis.setWordWrap(True)
        hinweis.setTextFormat(Qt.TextFormat.PlainText)
        hinweis.setText(_(
            "Vorschaubilder großer Dateien – etwa Scans – kosten Zeit. Silberkorn kann sie "
            "in einer Datei mit fester Größe sichern, verschlüsselt für die eigene "
            "Windows-Anmeldung. Der Platz wird gleich belegt, damit es später keine "
            "Überraschung gibt. 0 MB: kein Cache."))
        if erstmals:
            self.setWindowTitle(_("Vorschau-Cache einrichten"))
        aufbau.addWidget(hinweis)

        zeile = QHBoxLayout()
        zeile.addWidget(QLabel(_("Größe")))
        self.groesse = QSpinBox()
        self.groesse.setRange(0, vorschau_cache.MAX_MB)
        self.groesse.setSuffix(" MB")
        self.groesse.setSingleStep(50)
        mb = cache_mb()
        self.groesse.setValue(vorschau_cache.VORSCHLAG_MB if mb is None else mb)
        zeile.addWidget(self.groesse)
        zeile.addStretch(1)
        aufbau.addLayout(zeile)

        self.stand = QLabel(objectName="nebentext")
        self.stand.setTextFormat(Qt.TextFormat.PlainText)
        if stand is not None:
            belegt, groesse, anzahl = stand
            self.stand.setText(_("Belegt: {belegt} von {groesse} MB, {anzahl} Vorschaubilder")
                               .format(belegt=f"{belegt / 2**20:.0f}",
                                       groesse=f"{groesse / 2**20:.0f}", anzahl=anzahl))
        aufbau.addWidget(self.stand)

        zeile = QHBoxLayout()
        zeile.addWidget(QLabel(_("Ort")))
        self.ort = QLabel()
        self.ort.setTextFormat(Qt.TextFormat.PlainText)
        self.ort.setWordWrap(True)
        self._ort = cache_ordner()
        self.ort.setText(self._ort)
        zeile.addWidget(self.ort, 1)
        knopf = QPushButton(_("Ändern …"))
        knopf.clicked.connect(self._ort_waehlen)
        zeile.addWidget(knopf)
        aufbau.addLayout(zeile)

        aufbau.addWidget(QLabel(_("Nie in den Cache (Ordner und alles darunter):")))
        self.ausnahmen = QListWidget()
        self.ausnahmen.addItems(ausgenommene_ordner())
        self.ausnahmen.setMaximumHeight(110)
        aufbau.addWidget(self.ausnahmen)
        zeile = QHBoxLayout()
        dazu = QPushButton(_("Ordner hinzufügen …"))
        dazu.clicked.connect(self._ausnahme_dazu)
        weg = QPushButton(_("Entfernen"))
        weg.clicked.connect(lambda: self.ausnahmen.takeItem(self.ausnahmen.currentRow()))
        zeile.addWidget(dazu)
        zeile.addWidget(weg)
        zeile.addStretch(1)
        aufbau.addLayout(zeile)

        self.leeren = QCheckBox(_("Cache jetzt leeren"))
        self.leeren.setVisible(stand is not None)
        aufbau.addWidget(self.leeren)

        knoepfe = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        knoepfe.accepted.connect(self._pruefen)
        knoepfe.rejected.connect(self.reject)
        aufbau.addWidget(knoepfe)

    def _ort_waehlen(self):
        ordner = ordner_dialog(self, _("Ort des Vorschau-Caches"), self._ort)
        if ordner:
            self._ort = ordner
            self.ort.setText(self._ort)

    def _ausnahme_dazu(self):
        ordner = ordner_dialog(self, _("Ordner ausnehmen"), os.path.expanduser("~"))
        if ordner:
            self.ausnahmen.addItem(ordner)

    def _pruefen(self):
        """Reicht der Platz? Sonst den groessten moeglichen Wert vorschlagen."""
        mb = self.groesse.value()
        if mb and mb < vorschau_cache.MIN_MB:
            self.groesse.setValue(vorschau_cache.MIN_MB)
            return
        datei = os.path.join(self._ort, vorschau_cache.DATEINAME)
        vorhanden = os.path.getsize(datei) if os.path.isfile(datei) else 0
        frei = vorschau_cache.platz_frei(self._ort) + vorhanden
        if mb * 2**20 > frei:
            hoechstens = frei // 2**20
            QMessageBox.warning(self, self.windowTitle(), _(
                "Dort ist nicht genug Platz frei. Möglich sind höchstens {mb} MB.").format(
                mb=hoechstens))
            self.groesse.setValue(max(0, hoechstens))
            return
        self.accept()

    def ergebnis(self) -> tuple[int, str, list[str], bool]:
        ausnahmen = [self.ausnahmen.item(i).text() for i in range(self.ausnahmen.count())]
        return self.groesse.value(), self._ort, ausnahmen, self.leeren.isChecked()


# --------------------------------------------------------------------------
# Der Reiter
# --------------------------------------------------------------------------

class OrdnerSeite(QWidget):
    def __init__(self, fenster):
        super().__init__()
        self.fenster = fenster
        self.ordner = ""
        self._cache_stand = None
        self.dienst = VorschauDienst()
        self.dienst.cache_stand.connect(self._cache_stand_merken)
        self.dienst.meldung.connect(lambda text: fenster.melden(text, fehler=True))
        self.dienst.ausnehmen(ausgenommene_ordner())
        self.bewertungen = BewertungsDienst()
        self.bewertungen.fertig.connect(self._bewertungen_da)
        self.bewertungen.meldung.connect(lambda text: fenster.melden(text, fehler=True))
        self._unterordner: list[str] = []
        self._bilder: list[str] = []               # nach Name sortiert, die Grundlage
        self._zeiten: dict[str, float] = {}

        aufbau = QVBoxLayout(self)
        aufbau.setContentsMargins(0, 12, 0, 0)
        leiste = QHBoxLayout()
        leiste.setSpacing(6)
        self.waehlen_knopf = QPushButton()
        fenster.beschriften(self.waehlen_knopf.setText, _("Ordner wählen …"))
        self.waehlen_knopf.clicked.connect(self.ordner_waehlen)
        self.hoch_knopf = QPushButton("↑", objectName="zoomsymbol")
        fenster.beschriften(self.hoch_knopf.setToolTip, _("Übergeordneter Ordner"))
        self.hoch_knopf.clicked.connect(self.ordner_hoch)
        self.neu_knopf = QPushButton("↻", objectName="zoomsymbol")
        fenster.beschriften(self.neu_knopf.setToolTip, _("Ordner neu einlesen"))
        self.neu_knopf.clicked.connect(lambda: self.ordner_zeigen(self.ordner))
        self.ort = QLabel(objectName="nebentext")
        self.ort.setTextFormat(Qt.TextFormat.PlainText)
        self.sortierung = QComboBox()
        for art in einstellungen.ORDNER_SORTIERUNGEN:
            self.sortierung.addItem("", art)
        for nummer, text in enumerate((_("Nach Name"), _("Nach Datum"), _("Nach Sternen"))):
            fenster.beschriften(lambda t, i=nummer: self.sortierung.setItemText(i, t), text)
        fenster.beschriften(self.sortierung.setToolTip, _(
            "Reihenfolge der Bilder: nach Name, nach Änderungsdatum (neueste zuerst) oder nach "
            "Sternen (meiste zuerst). Ausschuss steht immer am Ende, Unterordner vorn."))
        self.sortierung.setCurrentIndex(
            max(0, self.sortierung.findData(einstellungen.ordner_sortierung())))
        self.sortierung.currentIndexChanged.connect(self._sortierung_gewaehlt)
        self.stapel_knopf = QPushButton()
        fenster.beschriften(self.stapel_knopf.setText, _("Stapel …"))
        fenster.beschriften(self.stapel_knopf.setToolTip, _(
            "Die gewählten Bilder auf einmal bearbeiten: eine Voreinstellung darauflegen, "
            "Staub entfernen, als Begleitdatei sichern oder ausgeben. Mehrere Bilder wählen "
            "mit Strg oder Umschalt."))
        self.stapel_knopf.clicked.connect(self.stapel_starten)
        self.stapel_knopf.setEnabled(False)
        self.bogen_knopf = QPushButton("🖶", objectName="zoomsymbol")
        fenster.beschriften(self.bogen_knopf.setToolTip, _(
            "Kontaktbogen: die gewählten Bilder – sonst alle des Ordners – als Raster mit "
            "Dateinamen und Sternen drucken oder als PDF speichern."))
        fenster.beschriften(self.bogen_knopf.setAccessibleName, _("Kontaktbogen"))
        self.bogen_knopf.clicked.connect(self.kontaktbogen_starten)
        self.bogen_knopf.setEnabled(False)
        self.vergleich_knopf = QPushButton("⇆", objectName="zoomsymbol")
        fenster.beschriften(self.vergleich_knopf.setToolTip, _(
            "Vergleichen: zwei oder mehr gewählte Bilder nebeneinander, gemeinsam gezoomt – "
            "mit Bearbeitung, Sternen und Ausschuss. Mehrere Bilder wählen mit Strg oder "
            "Umschalt."))
        fenster.beschriften(self.vergleich_knopf.setAccessibleName, _("Bilder vergleichen"))
        self.vergleich_knopf.clicked.connect(self.vergleich_starten)
        self.vergleich_knopf.setEnabled(False)
        self.cache_knopf = QPushButton()
        fenster.beschriften(self.cache_knopf.setText, _("Vorschau-Cache …"))
        fenster.beschriften(self.cache_knopf.setToolTip, _(
            "Größe, Ort und Ausnahmen des verschlüsselten Caches für Vorschaubilder"))
        self.cache_knopf.clicked.connect(lambda: self.cache_einstellen(False))
        leiste.addWidget(self.waehlen_knopf)
        leiste.addWidget(self.hoch_knopf)
        leiste.addWidget(self.neu_knopf)
        leiste.addWidget(self.ort, 1)
        leiste.addWidget(self.sortierung)
        leiste.addWidget(self.stapel_knopf)
        leiste.addWidget(self.vergleich_knopf)
        leiste.addWidget(self.bogen_knopf)
        leiste.addWidget(self.cache_knopf)
        aufbau.addLayout(leiste)

        self.modell = KachelModell(self.dienst)
        self.liste = KachelListe()
        self.liste.setModel(self.modell)
        self.liste.doubleClicked.connect(self._doppelklick)
        self.liste.bewertung_gewaehlt.connect(self._bewertung_gewaehlt)
        self.liste.bewertung_gesperrt.connect(self._bewertung_gesperrt)
        self.liste.selectionModel().selectionChanged.connect(self._auswahl_geaendert)
        aufbau.addWidget(self.liste, 1)
        self.leer = QLabel(objectName="nebentext")
        self.leer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fenster.beschriften(self.leer.setText, _("Einen Ordner wählen, um seine Bilder zu sehen."))
        aufbau.addWidget(self.leer)

        mb = cache_mb()
        if mb:
            self.dienst.befehl("oeffnen", os.path.join(cache_ordner(), vorschau_cache.DATEINAME),
                               mb * 2**20)
        zuletzt = einstellungen.load_config().get("ordner_ansicht")
        self.ordner_zeigen(zuletzt if isinstance(zuletzt, str) and os.path.isdir(zuletzt)
                           else "", melden=False)

    # ------------------------------------------------------------------

    def ordner_waehlen(self):
        if cache_mb() is None:
            self.cache_einstellen(True)
        daten = einstellungen.load_config()
        start = self.ordner
        for gemerkt in (daten.get("ordner_ansicht"), daten.get("letzter_ordner")):
            if not start and isinstance(gemerkt, str) and os.path.isdir(gemerkt):
                start = gemerkt
        ordner = ordner_dialog(self, _("Ordner wählen"), start or os.path.expanduser("~"))
        if ordner:
            self.ordner_wechseln(ordner)

    def ordner_wechseln(self, ordner: str):
        self.ordner_zeigen(os.path.normpath(ordner))
        _speichern(ordner_ansicht=self.ordner)

    def ordner_hoch(self):
        oben = os.path.dirname(self.ordner)
        if self.ordner and oben and oben != self.ordner:
            self.ordner_wechseln(oben)

    def ordner_zeigen(self, ordner: str, melden: bool = True):
        self.ordner = ordner
        unterordner, pfade, zeiten = ordner_inhalt(ordner) if ordner else ([], [], {})
        self._unterordner, self._bilder, self._zeiten = unterordner, pfade, zeiten
        self.modell.setzen(self._geordnet(), unterordner)
        if pfade:
            self.bewertungen.laden(self.modell.durchgang, pfade)
        else:
            self.bewertungen.abbrechen()           # sonst käme das Ergebnis des alten Ordners
        self.ort.setText(ordner)
        self.liste.setVisible(bool(ordner))
        self.leer.setVisible(not ordner)
        self.neu_knopf.setEnabled(bool(ordner))
        self.bogen_knopf.setEnabled(bool(pfade))
        self._auswahl_geaendert()
        self.hoch_knopf.setEnabled(bool(ordner) and os.path.dirname(ordner) != ordner)
        if ordner and melden:
            text = _("1 Bild in {ordner}") if len(pfade) == 1 else _("{anzahl} Bilder in {ordner}")
            self.fenster.melden(text.format(
                anzahl=len(pfade), ordner=os.path.basename(ordner) or ordner))

    def _geordnet(self) -> list[str]:
        """Die Bilder in der gewaehlten Reihenfolge; Ausschuss zuletzt, Gleichstand nach Name."""
        return bewertung.sortiert(self._bilder, self.sortierung.currentData(), _nach_name,
                                  self.modell.bewertungen, self._zeiten)

    def _sortierung_gewaehlt(self, _nummer: int):
        einstellungen.ordner_sortierung_setzen(self.sortierung.currentData())
        self.modell.umordnen(self._geordnet(), self._unterordner)

    def _bewertungen_da(self, durchgang: int, staende: dict):
        """Die Sterne sind gelesen: zeigen und einsortieren (Ausschuss ans Ende, bei
        „Nach Sternen“ die Reihenfolge)."""
        if self.modell.staende_laden(durchgang, staende):
            self.modell.umordnen(self._geordnet(), self._unterordner)
            unlesbar = sum(1 for stand in staende.values() if stand.art == "unlesbar")
            if unlesbar:
                text = (_("1 Bewertungsdatei ließ sich nicht lesen und bleibt unverändert.")
                        if unlesbar == 1 else
                        _("{anzahl} Bewertungsdateien ließen sich nicht lesen und bleiben "
                          "unverändert.").format(anzahl=unlesbar))
                self.fenster.melden(text)

    def _bewertung_gewaehlt(self, pfad: str, wert: int):
        if not bewertung_setzen(self.fenster, pfad, wert):
            return
        text = bewertung_text(pfad, wert)
        if self._neu_einsortieren(wert):
            text += " " + _("Mit ↻ lässt sich neu einsortieren.")
        self.fenster.melden(text)

    def _neu_einsortieren(self, wert: int) -> bool:
        """Stimmt die Reihenfolge nach dieser Bewertung womoeglich nicht mehr?"""
        return wert == bewertung.AUSSCHUSS or self.sortierung.currentData() == "sterne"

    def _bewertung_gesperrt(self, pfad: str):
        stand = self.modell.bewertungen.get(pfad, bewertung.KEINE)
        self.fenster.melden(gesperrt_text(stand))

    def _doppelklick(self, index):
        pfad = index.data(PFAD_ROLLE)
        if pfad and pfad in self.modell.unterordner:
            self.ordner_wechseln(pfad)
        elif pfad:
            self.fenster.reiter.setCurrentWidget(self.fenster.bearbeiten)
            self.fenster.bearbeiten.oeffnen(pfad)

    def _auswahl_geaendert(self, *_args):
        anzahl = len(self.gewaehlte_bilder())
        self.stapel_knopf.setEnabled(anzahl > 0)
        self.vergleich_knopf.setEnabled(anzahl >= 2)

    def gewaehlte_bilder(self) -> list[str]:
        """Die gewaehlten Bilder in der Reihenfolge der Liste - ohne Ordner."""
        zeilen = sorted(i.row() for i in self.liste.selectionModel().selectedIndexes())
        pfade = [self.modell.pfade[z] for z in zeilen if z < len(self.modell.pfade)]
        return [p for p in pfade if p not in self.modell.unterordner]

    def stapel_starten(self):
        from .bearbeiten_seite import speicherformate
        pfade = self.gewaehlte_bilder()
        if not pfade:
            return
        bearbeiten = self.fenster.bearbeiten
        faktor = bearbeiten.ki_faktor.currentData()
        dialog = StapelDialog(self, len(pfade), self.ordner, speicherformate(),
                              bearbeiten._zwischenablage, einstellungen.begleitdateien() is True,
                              f"{faktor}×" if faktor else "")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            auftrag = dialog.auftrag()
        except voreinstellungen.VoreinstellungFehler as fehler:
            QMessageBox.warning(self, _("Stapel"), _("Die Voreinstellung lässt sich nicht "
                                                     "lesen.") + "\n" + str(fehler))
            return
        # Das offene Bild zuerst sichern und schliessen - zwei Bilder auf einmal haetten im
        # Grafikspeicher oft keinen Platz, und der Stapel koennte es selbst bearbeiten
        if not bearbeiten.aenderungen_verwerfen_ok():
            return
        offen = bearbeiten.sitzung.daten.pfad if bearbeiten.sitzung is not None else None
        if offen is not None:
            bearbeiten.schliessen()
            bearbeiten._knoepfe_freischalten()
            bearbeiten._alles_anzeigen()
            bearbeiten.zeichnen_anfordern()
        ergebnisse, abgebrochen = self._stapel_rechnen(bearbeiten, auftrag, pfade)
        for ergebnis in ergebnisse:
            self.bild_geaendert(ergebnis.pfad)
        self.ordner_zeigen(self.ordner, melden=False)      # neue Dateien zeigen
        self._bericht(ergebnisse, len(pfade), abgebrochen)
        if offen is not None and os.path.isfile(offen):
            bearbeiten.oeffnen(offen)
            self.fenster.reiter.setCurrentWidget(self)

    # ------------------------------------------------------------------
    # Vergleichen
    # ------------------------------------------------------------------

    def vergleich_starten(self):
        import functools

        from . import bildvergleich
        from .bildvergleich_dialog import VergleichDialog
        pfade = self.gewaehlte_bilder()
        if len(pfade) < 2:
            return
        vorher = {p: self.modell.bewertungen.get(p, bewertung.KEINE) for p in pfade}
        laden = functools.partial(bildvergleich.laden, raw_qualitaet=einstellungen.raw_qualitaet())
        dialog = VergleichDialog(self, pfade, vorher, self._vergleich_bewerten, gesperrt_text,
                                 laden)
        dialog.exec()
        geaendert = [s for p, s in dialog.staende.items() if s != vorher[p]]
        if geaendert:
            text = _("Bewertungen aus dem Vergleich gesichert.")
            if any(self._neu_einsortieren(stand.wert) for stand in geaendert):
                text += " " + _("Mit ↻ lässt sich neu einsortieren.")
            self.fenster.melden(text)
        if dialog.zu_bearbeiten:
            # oeffnen() meldet selbst, was es tut - die Bewertung steht dann in der Kachel
            self.fenster.reiter.setCurrentWidget(self.fenster.bearbeiten)
            self.fenster.bearbeiten.oeffnen(dialog.zu_bearbeiten)

    def _vergleich_bewerten(self, pfad: str, wert: int, melden) -> bool:
        if not bewertung_setzen(self.fenster, pfad, wert, melden=melden):
            return False
        melden(bewertung_text(pfad, wert))
        return True

    # ------------------------------------------------------------------
    # Kontaktbogen
    # ------------------------------------------------------------------

    def _kachel(self, pfad: str) -> QPixmap | None:
        """Die Kachel eines Bildes fuer die Vorschau des Kontaktbogens; fragt sie an, wenn
        sie noch fehlt."""
        zeile = self.modell._zeile(pfad)
        if zeile < 0:
            return None
        bild = self.modell.data(self.modell.index(zeile), Qt.ItemDataRole.DecorationRole)
        return bild if isinstance(bild, QPixmap) else None

    def kontaktbogen_starten(self):
        from . import kontaktbogen
        from .kontaktbogen_dialog import KontaktbogenDialog, seite_anzahl, seite_text
        pfade = self.gewaehlte_bilder() or [p for p in self.modell.pfade
                                            if p not in self.modell.unterordner]
        if not pfade:
            return
        eintraege = [(p, self.modell.bewertungen.get(p, bewertung.KEINE)) for p in pfade]
        vorgaben = kontaktbogen.Vorgaben.aus_dict(einstellungen.load_config().get("kontaktbogen"))
        dialog = KontaktbogenDialog(self, eintraege, self.ordner, vorgaben, self._kachel)
        # Kacheln, die waehrend des Dialogs ankommen, erscheinen in der Vorschau
        self.modell.dataChanged.connect(dialog.bogen.update)
        try:
            angenommen = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self.modell.dataChanged.disconnect(dialog.bogen.update)
        if not angenommen:
            return
        _speichern(kontaktbogen=dialog.vorgaben().als_dict())
        drucker, gitter, eintraege = dialog.drucker(), dialog.raster(), dialog.eintraege()
        ziel = zwischen = None
        if dialog.ist_pdf():
            name = os.path.basename(self.ordner) or "Silberkorn"
            ziel, _filter = QFileDialog.getSaveFileName(
                self, _("Kontaktbogen speichern"),
                os.path.join(self.ordner, _("Kontaktbogen {ordner}.pdf").format(ordner=name)),
                "PDF (*.pdf)")
            if not ziel:
                return
            if not ziel.lower().endswith(".pdf"):
                ziel += ".pdf"
            # Erst fertig, dann unter dem gewaehlten Namen: ein Abbruch laesst eine vorhandene
            # Datei unberuehrt
            try:
                griff, zwischen = tempfile.mkstemp(".teil", ".kontaktbogen-",
                                                   os.path.dirname(ziel))
            except OSError as fehler:
                self.fenster.melden(_("Der Kontaktbogen ließ sich nicht ausgeben: {grund}")
                                    .format(grund=str(fehler)), fehler=True)
                return
            os.close(griff)
            drucker.setOutputFileName(zwischen)
        try:
            fehlt = self._kontaktbogen_rechnen(drucker, gitter, eintraege, seite_text)
            if zwischen is not None:
                if os.path.getsize(zwischen) == 0:
                    raise OSError(_("Die PDF-Datei blieb leer."))
                os.replace(zwischen, ziel)
                zwischen = None
        except kontaktbogen.Abbruch:
            self.fenster.melden(_("Kontaktbogen abgebrochen – nichts ausgegeben."))
            return
        except Exception as fehler:             # noqa: BLE001 - jeder Fehler gehoert gemeldet
            self.fenster.melden(_("Der Kontaktbogen ließ sich nicht ausgeben: {grund}").format(
                grund=str(fehler) or type(fehler).__name__), fehler=True)
            return
        finally:
            if zwischen is not None:
                try:
                    os.remove(zwischen)           # nur die eigene, unfertige Zwischendatei
                except OSError:
                    pass                          # gesperrt: der eigentliche Fehler zaehlt mehr
        seiten = seite_anzahl(gitter.seiten(len(eintraege)))
        if fehlt:
            self.fenster.melden(_("Kontaktbogen mit {seiten} ausgegeben; nicht zu laden und "
                                  "darum grau: {namen} ({grund})").format(
                seiten=seiten, namen=", ".join(os.path.basename(p) for p, _g in fehlt),
                grund=fehlt[0][1]), fehler=True)
        elif ziel is not None:
            self.fenster.melden(_("Kontaktbogen mit {seiten} gespeichert: {datei}").format(
                seiten=seiten, datei=os.path.basename(ziel)))
        else:
            self.fenster.melden(_("Kontaktbogen mit {seiten} an den Drucker geschickt.").format(
                seiten=seiten))

    def _kontaktbogen_rechnen(self, drucker, gitter, eintraege, seite_text
                              ) -> list[tuple[str, str]]:
        from . import kontaktbogen
        anzeige = QProgressDialog("", _("Abbrechen"), 0, 1000, self)
        anzeige.setWindowTitle(_("Kontaktbogen"))
        anzeige.setWindowModality(Qt.WindowModality.WindowModal)
        anzeige.setMinimumDuration(0)
        anzeige.setMinimumWidth(420)

        def fortschritt(name: str, anteil: float) -> bool:
            anzeige.setLabelText(_("Lege {name} auf …").format(name=name))
            anzeige.setValue(min(999, round(anteil * 1000)))
            QApplication.processEvents()
            return not anzeige.wasCanceled()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return kontaktbogen.ausgeben(drucker, gitter, eintraege, self.ordner, seite_text,
                                         fortschritt)
        finally:
            QApplication.restoreOverrideCursor()
            anzeige.close()

    def _stapel_rechnen(self, bearbeiten, auftrag: Auftrag, pfade: list[str]):
        anzeige = QProgressDialog("", _("Abbrechen"), 0, 1000, self)
        anzeige.setWindowTitle(_("Stapel"))
        anzeige.setWindowModality(Qt.WindowModality.WindowModal)
        anzeige.setMinimumDuration(0)
        anzeige.setMinimumWidth(420)

        def fortschritt(name: str, anteil: float) -> bool:
            anzeige.setLabelText(_("Bearbeite {name} …").format(name=name))
            anzeige.setValue(min(999, round(anteil * 1000)))
            QApplication.processEvents()
            return not anzeige.wasCanceled()

        stapel = Stapel(bearbeiten, auftrag, fortschritt)
        ergebnisse, abgebrochen = [], False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for nummer, pfad in enumerate(pfade):
                ergebnisse.append(stapel.bearbeiten(pfad, nummer, len(pfade)))
        except StapelAbbruch:
            abgebrochen = True
        finally:
            stapel.freigeben()
            QApplication.restoreOverrideCursor()
            anzeige.close()
        return ergebnisse, abgebrochen

    def _bericht(self, ergebnisse, anzahl: int, abgebrochen: bool):
        fertig = sum(1 for e in ergebnisse if e.ok)
        text = _("{fertig} von {anzahl} Bildern fertig.").format(fertig=fertig, anzahl=anzahl)
        if abgebrochen:
            text += " " + _("Abgebrochen.")
        zeilen = []
        for ergebnis in ergebnisse:
            teile = [bericht_text(h) for h in ergebnis.hinweise]
            if ergebnis.ausgabe:
                teile.append("→ " + os.path.basename(ergebnis.ausgabe))
            if teile or not ergebnis.ok:
                zeichen = "" if ergebnis.ok else "✗ "
                zeilen.append(f"{zeichen}{os.path.basename(ergebnis.pfad)}: {'; '.join(teile)}")
        box = QMessageBox(QMessageBox.Icon.Information if fertig == anzahl
                          else QMessageBox.Icon.Warning, _("Stapel"), text,
                          QMessageBox.StandardButton.Ok, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        if zeilen:
            box.setDetailedText("\n".join(zeilen))
        box.exec()
        self.fenster.melden(text, fehler=fertig != anzahl)

    def bild_geaendert(self, pfad: str):
        """Die Begleitdatei eines Bildes ist neu oder weg: Kachel neu, Cache vergessen."""
        self.dienst.befehl("vergessen", pfad)
        self.modell.neu_laden(pfad)

    def anzeige_geaendert(self):
        """Ein anderes Monitorprofil: die Kacheln neu zeichnen."""
        self.modell.alle_neu_laden()

    def _cache_stand_merken(self, stand):
        self._cache_stand = stand

    def cache_einstellen(self, erstmals: bool):
        dialog = CacheDialog(self, self._cache_stand, erstmals)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if erstmals and cache_mb() is None:
                _speichern(vorschau_cache_mb=0)         # gefragt ist gefragt: kein Cache
            return
        mb, ort, ausnahmen, leeren = dialog.ergebnis()
        alt_ort, alt_mb = cache_ordner(), cache_mb()
        _speichern(vorschau_cache_mb=mb, vorschau_ausgenommen=ausnahmen,
                   vorschau_cache_ort="" if ort == vorschau_cache.standard_ordner() else ort)
        self.dienst.ausnehmen(ausnahmen)
        alt = os.path.join(alt_ort, vorschau_cache.DATEINAME)
        neu = os.path.join(ort, vorschau_cache.DATEINAME)
        if os.path.normcase(alt) != os.path.normcase(neu) or mb == 0:
            self.dienst.befehl("entfernen", alt)
        if mb and (mb != alt_mb or os.path.normcase(alt) != os.path.normcase(neu)
                   or self._cache_stand is None):
            self.dienst.befehl("oeffnen", neu, mb * 2**20)
        if leeren:
            self.dienst.befehl("leeren")
        for ordner in ausnahmen:                       # was schon drin ist, faellt beim
            for pfad in self.modell.pfade:             # naechsten Aufraeumen ohnehin weg
                if vorschau_cache.ausgenommen(pfad, [ordner]):
                    self.dienst.befehl("vergessen", pfad)

    def beenden(self):
        self.dienst.beenden()
        self.bewertungen.abbrechen()


def begleitdatei_geaendert(fenster, pfad: str):
    """Fuer die Bearbeiten-Seite: nach dem Schreiben oder Loeschen einer Begleitdatei."""
    seite = getattr(fenster, "ordner", None)
    if seite is not None and os.path.dirname(os.path.normcase(pfad)) == \
            os.path.normcase(seite.ordner):
        seite.bild_geaendert(pfad)
    elif seite is not None:
        seite.dienst.befehl("vergessen", pfad)


def bewertung_text(pfad: str, wert: int) -> str:
    """Was nach dem Bewerten in der Statuszeile steht."""
    name = os.path.basename(pfad)
    if wert > 0:
        return _("{name}: {sterne}").format(name=name, sterne="★" * wert)
    if wert == 0:
        return _("{name}: Bewertung entfernt").format(name=name)
    return _("{name} als Ausschuss markiert – die Datei bleibt unverändert").format(name=name)


def bewertung_setzen(fenster, pfad: str, wert: int, von_bearbeiten: bool = False,
                     melden=None) -> bool:
    """Die Bewertung (-1 Ausschuss, 0 bis 5) neben das Bild schreiben - nur mit der Erlaubnis
    fuer Begleitdateien und nie in eine fremde XMP-Datei. Es wird nichts geloescht, auch bei
    Ausschuss nicht. Rueckgabe: ob geschrieben wurde; sonst steht der Grund in der Statuszeile
    (oder geht an melden(text, fehler))."""
    melden = melden or fenster.melden
    bearbeiten = fenster.bearbeiten
    if not bearbeiten.bewertung_erlaubt(pfad):
        melden(_("Ohne Erlaubnis für Begleitdateien werden Bewertungen nicht gespeichert."),
               fehler=True)
        return False
    try:
        bewertung.schreiben(pfad, wert)
    except bewertung.FremdeDatei as fehler:        # auch UnlesbareDatei
        melden(gesperrt_text(bewertung.Stand(
            0, "unlesbar" if isinstance(fehler, bewertung.UnlesbareDatei) else "fremd")),
            fehler=True)
        return False
    except bewertung.BewertungFehler as fehler:
        melden(_("Die Bewertung ließ sich nicht neben dem Bild sichern: {grund}")
               .format(grund=str(fehler)), fehler=True)
        return False
    stand = bewertung.Stand(wert, "eigen")
    seite = getattr(fenster, "ordner", None)
    if seite is not None:
        seite.modell.stand_setzen(pfad, stand)
    sitzung = bearbeiten.sitzung
    if (not von_bearbeiten and sitzung is not None
            and os.path.normcase(os.path.normpath(sitzung.daten.pfad))
            == os.path.normcase(os.path.normpath(pfad))):
        bearbeiten.bewertung_von_aussen(stand)     # das offene Bild bekommt die Sterne auch
    return True
