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
import os
import re
import stat
import threading

from PySide6.QtCore import (
    QAbstractListModel,
    QDir,
    QObject,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
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
    QVBoxLayout,
    QWidget,
)

from . import einstellungen, farben, voreinstellungen, vorschau_cache, vorschaubilder
from .stapel import Auftrag, Stapel, StapelAbbruch
from .stapel_dialog import StapelDialog, bericht_text
from .uebersetzung import _

KACHEL = 160                  # Kantenlaenge einer Kachel auf dem Bildschirm
IM_SPEICHER = 3000            # so viele Vorschaubilder haelt die Ansicht im Arbeitsspeicher
AUFRAEUMEN_S = 1.0            # so lange raeumt der Cache je Leerlauf auf
BEARBEITET_ROLLE = Qt.ItemDataRole.UserRole + 1
PFAD_ROLLE = Qt.ItemDataRole.UserRole + 2
ZUSTAND_ROLLE = Qt.ItemDataRole.UserRole + 3     # "ordner", "laedt", "fehlt" oder "bild"


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


def eintraege_im_ordner(ordner: str) -> tuple[list[str], list[str]]:
    """Unterordner und Bilddateien eines Ordners, je natuerlich sortiert - ohne versteckte.
    Unterordner werden nicht durchsucht; hinein geht es erst per Doppelklick."""
    try:
        eintraege = list(os.scandir(ordner))
    except OSError:
        return [], []
    unterordner, bilder = [], []
    for eintrag in eintraege:
        if eintrag.name.startswith(".") or _versteckt(eintrag):
            continue
        try:
            if eintrag.is_dir():
                unterordner.append(eintrag.path)
            elif vorschaubilder.ist_bild(eintrag.name) and eintrag.is_file():
                bilder.append(eintrag.path)
        except OSError:
            continue

    def schluessel(pfad):
        return _natuerlich(os.path.basename(pfad))
    return sorted(unterordner, key=schluessel), sorted(bilder, key=schluessel)


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


def _qimage(bild) -> QImage:
    rgb = bild.convert("RGB")
    daten = rgb.tobytes()
    return QImage(daten, rgb.width, rgb.height, rgb.width * 3,
                  QImage.Format.Format_RGB888).copy()


# --------------------------------------------------------------------------
# Liste der Kacheln
# --------------------------------------------------------------------------

class KachelModell(QAbstractListModel):
    def __init__(self, dienst: VorschauDienst):
        super().__init__()
        self.dienst = dienst
        self.pfade: list[str] = []
        self.durchgang = 0
        self._bilder: collections.OrderedDict[str, tuple[QPixmap, bool]] = \
            collections.OrderedDict()
        self._angefragt: set[str] = set()
        self._fehlend: set[str] = set()
        self.unterordner: set[str] = set()
        self._ordner_symbol = QApplication.style().standardIcon(
            QStyle.StandardPixmap.SP_DirIcon).pixmap(KACHEL * 3 // 4, KACHEL * 3 // 4)
        dienst.fertig.connect(self._fertig)
        dienst.fehlt.connect(self._fehlt)

    def setzen(self, pfade: list[str], unterordner: list[str] = ()):
        self.beginResetModel()
        self.durchgang += 1
        self.dienst.verwerfen()
        self.pfade = [*unterordner, *pfade]
        self.unterordner = set(unterordner)
        self._angefragt.clear()
        self._fehlend.clear()
        self.endResetModel()

    def neu_laden(self, pfad: str):
        """Ein Bild hat sich geaendert (etwa seine Begleitdatei): neu anfragen."""
        self._bilder.pop(pfad, None)
        self._angefragt.discard(pfad)
        self._fehlend.discard(pfad)
        if pfad in self.pfade:
            stelle = self.index(self.pfade.index(pfad))
            self.dataChanged.emit(stelle, stelle)

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
                self.dienst.anfordern(self.durchgang, pfad)
            return {ZUSTAND_ROLLE: "laedt", BEARBEITET_ROLLE: False}.get(rolle)
        return None

    def _fertig(self, durchgang: int, pfad: str, bild: QImage, bearbeitet: bool):
        if durchgang != self.durchgang or pfad not in self.pfade:
            return
        self._bilder[pfad] = (QPixmap.fromImage(bild), bearbeitet)
        while len(self._bilder) > IM_SPEICHER:
            alt, _bild = self._bilder.popitem(last=False)
            self._angefragt.discard(alt)
        self._angefragt.discard(pfad)
        stelle = self.index(self.pfade.index(pfad))
        self.dataChanged.emit(stelle, stelle)

    def _fehlt(self, durchgang: int, pfad: str):
        if durchgang == self.durchgang and pfad in self.pfade:
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


class KachelZeichner(QStyledItemDelegate):
    """Bild oder Ordnersymbol unten buendig, der Name direkt darunter - wie im Explorer.
    Ein Punkt oben rechts markiert eine Begleitdatei. Solange ein Bild laedt, steht dort
    eine graue Flaeche, ohne moegliche Vorschau ein Fragezeichen."""

    RAND = 6                                       # Luft um den Inhalt einer Kachel

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
        flaeche = QRect(rahmen.left() + (rahmen.width() - KACHEL) // 2,
                        rahmen.top() + self.RAND, KACHEL, KACHEL)
        unten = flaeche.bottom()                   # Unterkante des Bildes - darunter der Name
        zustand = index.data(ZUSTAND_ROLLE)
        bild = index.data(Qt.ItemDataRole.DecorationRole)
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
        maler.restore()


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
        self.stapel_knopf = QPushButton()
        fenster.beschriften(self.stapel_knopf.setText, _("Stapel …"))
        fenster.beschriften(self.stapel_knopf.setToolTip, _(
            "Die gewählten Bilder auf einmal bearbeiten: eine Voreinstellung darauflegen, "
            "Staub entfernen, als Begleitdatei sichern oder ausgeben. Mehrere Bilder wählen "
            "mit Strg oder Umschalt."))
        self.stapel_knopf.clicked.connect(self.stapel_starten)
        self.stapel_knopf.setEnabled(False)
        self.cache_knopf = QPushButton()
        fenster.beschriften(self.cache_knopf.setText, _("Vorschau-Cache …"))
        fenster.beschriften(self.cache_knopf.setToolTip, _(
            "Größe, Ort und Ausnahmen des verschlüsselten Caches für Vorschaubilder"))
        self.cache_knopf.clicked.connect(lambda: self.cache_einstellen(False))
        leiste.addWidget(self.waehlen_knopf)
        leiste.addWidget(self.hoch_knopf)
        leiste.addWidget(self.neu_knopf)
        leiste.addWidget(self.ort, 1)
        leiste.addWidget(self.stapel_knopf)
        leiste.addWidget(self.cache_knopf)
        aufbau.addLayout(leiste)

        self.modell = KachelModell(self.dienst)
        self.liste = QListView(objectName="kacheln")
        self.liste.setViewMode(QListView.ViewMode.IconMode)
        self.liste.setResizeMode(QListView.ResizeMode.Adjust)
        self.liste.setMovement(QListView.Movement.Static)
        self.liste.setUniformItemSizes(True)
        self.liste.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.liste.setItemDelegate(KachelZeichner(self.liste))
        self.liste.setModel(self.modell)
        self.liste.doubleClicked.connect(self._doppelklick)
        self.liste.selectionModel().selectionChanged.connect(
            lambda *_a: self.stapel_knopf.setEnabled(bool(self.gewaehlte_bilder())))
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
        unterordner, pfade = eintraege_im_ordner(ordner) if ordner else ([], [])
        self.modell.setzen(pfade, unterordner)
        self.ort.setText(ordner)
        self.liste.setVisible(bool(ordner))
        self.leer.setVisible(not ordner)
        self.neu_knopf.setEnabled(bool(ordner))
        self.hoch_knopf.setEnabled(bool(ordner) and os.path.dirname(ordner) != ordner)
        if ordner and melden:
            text = _("1 Bild in {ordner}") if len(pfade) == 1 else _("{anzahl} Bilder in {ordner}")
            self.fenster.melden(text.format(
                anzahl=len(pfade), ordner=os.path.basename(ordner) or ordner))

    def _doppelklick(self, index):
        pfad = index.data(PFAD_ROLLE)
        if pfad and pfad in self.modell.unterordner:
            self.ordner_wechseln(pfad)
        elif pfad:
            self.fenster.reiter.setCurrentWidget(self.fenster.bearbeiten)
            self.fenster.bearbeiten.oeffnen(pfad)

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


def begleitdatei_geaendert(fenster, pfad: str):
    """Fuer die Bearbeiten-Seite: nach dem Schreiben oder Loeschen einer Begleitdatei."""
    seite = getattr(fenster, "ordner", None)
    if seite is not None and os.path.dirname(os.path.normcase(pfad)) == \
            os.path.normcase(seite.ordner):
        seite.bild_geaendert(pfad)
    elif seite is not None:
        seite.dienst.befehl("vergessen", pfad)
