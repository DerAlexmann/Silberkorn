"""
Reiter "Bearbeiten": Leinwand, Werkzeugleiste und Reglerleiste

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import contextlib
import dataclasses
import math
import os
import random
import time
from concurrent.futures import wait
from html import escape

import numpy as np
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from . import (
    VERSION,
    anonym,
    begleitdatei,
    bilddatei,
    drucken,
    einstellungen,
    film,
    filter,
    geometrie,
    ki,
    lokal,
    lut,
    metadaten,
    objektivprofile,
    ordner_seite,
    staub,
    trennen,
    verlauf,
    veroeffentlichen,
    voreinstellungen,
)
from .bearbeitung import Sitzung
from .cuda import cupy as cp
from .drucken_dialog import DruckenDialog
from .geometrie import VOLLER_ZUSCHNITT
from .kurveneditor import KurvenEditor
from .leinwand import Leinwand, rahmen_mit_verhaeltnis
from .metadaten_dialog import MetadatenDialog
from .trennen_dialog import TrennenDialog
from .uebersetzung import _
from .veroeffentlichen_dialog import VeroeffentlichenDialog
from .voreinstellung_dialog import VoreinstellungDialog

REGLERLEISTE_BREITE = 340
KARTE_SPRUNG_MS = 200        # so lange rollt die Liste zur gewaehlten Karte
KARTE_MARKIERT_MS = 900      # so lange ist die angesprungene Karte hervorgehoben
KARTENWAHL_LUFT_PX = 6       # Luft je Eintrag der Kartenauswahl ueber der Schrifthoehe
KARTE_OBEN_PX = 8            # so weit unter dem oberen Rand gilt eine Karte noch als oben
VERBOTEN = '<>:"/\\|?*'       # Zeichen, die Windows in Dateinamen nicht erlaubt
STAUB_PAUSE_MS = 200         # so lange ruht der Regler, dann wird nach Staub gesucht
VERLAUF_PAUSE_MS = 400        # so lange ohne Aenderung, dann wird der Stand festgehalten
VERLAUF_ANTEIL = 0.2          # so viel Grafikspeicher darf der Verlauf zusaetzlich belegen
VERLAUF_MINDESTENS = 256 * 2**20


class Reglerleiste(QScrollArea):
    """Senkrecht rollende Leiste, deren Inhalt immer genau so breit ist wie sichtbar.

    Ein QScrollArea macht seinen Inhalt sonst mindestens so breit, wie das
    breiteste Element es verlangt - eine etwas breitere Schrift oder ein langer
    Text schoebe dann alle Karten nach rechts aus dem Bild. So wird stattdessen
    nur das zu breite Element enger, Rahmen und Regler bleiben sichtbar.
    """

    def viewportEvent(self, ereignis):
        # auch wenn der Rollbalken erscheint oder verschwindet
        if ereignis.type() == QEvent.Type.Resize:
            self._breite_anpassen()
        return super().viewportEvent(ereignis)

    def _breite_anpassen(self):
        if self.widget() is not None:
            self.widget().setFixedWidth(self.viewport().width())

    def setWidget(self, inhalt):
        super().setWidget(inhalt)
        self._breite_anpassen()


def _datum(zeitstempel: int) -> str:
    return time.strftime(_("%d.%m.%Y"), time.localtime(zeitstempel))


def gruppen_titel(gruppe: str) -> str:
    return {
        "weissabgleich": _("Weißabgleich"),
        "licht": _("Licht"),
        "praesenz": _("Präsenz"),
        "farbe": _("Farbe"),
        "rauschen": _("Rauschminderung"),
        "details": _("Details"),
        "geometrie": _("Geometrie"),
        "objektiv": _("Objektiv"),
        "lut": _("LUT"),
        "ki_rauschen": _("KI-Entrauschen"),
        "ki_schaerfe": _("KI-Schärfen"),
        "ki_farbe": _("KI-Kolorieren"),
        "maske": _("Motiv & Hintergrund"),
        "tiefe": _("Tiefe & Bokeh"),
        "korn": _("Filmkorn"),
    }[gruppe]


@contextlib.contextmanager
def _sanduhr():
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


def farbbereich_titel(nummer: int) -> str:
    return (_("Rot"), _("Orange"), _("Gelb"), _("Grün"), _("Aqua"), _("Blau"), _("Lila"),
            _("Magenta"))[nummer]


# Regler der Farbbereichskarte - je nach gewaehlter Eigenschaft zeigen sie
# Farbton, Saettigung oder Luminanz desselben Bereichs
HSL_REGLER = tuple(filter.Regler(f"hsl_{i}", "hsl", -100, 100)
                   for i in range(len(filter.FARBBEREICHE)))
# Regler des Schwarzweiss-Mischers: wie hell jeder Farbbereich als Grau wird
SW_REGLER = tuple(filter.Regler(f"sw_{i}", "schwarzweiss", -100, 100)
                  for i in range(len(filter.FARBBEREICHE)))


def lokal_art_titel(art: str) -> str:
    return {"verlauf": _("Verlauf"), "radial": _("Radial"), "pinsel": _("Pinsel")}[art]


def lokal_modus_titel(modus: str) -> str:
    return {"dazu": _("Hinzufügen"), "weg": _("Abziehen"), "schnitt": _("Schneiden")}[modus]


def lokal_teil_text(teil: lokal.Teil) -> str:
    """Ein Teil in der Liste, etwa „Radial – abgezogen, umgekehrt“."""
    zusatz = [{"dazu": "", "weg": _("abgezogen"), "schnitt": _("geschnitten")}[teil.modus]]
    if teil.umkehren:
        zusatz.append(_("umgekehrt"))
    zusatz = [z for z in zusatz if z]
    titel = lokal_art_titel(teil.art)
    return f"{titel} – {', '.join(zusatz)}" if zusatz else titel


# Regler der gewaehlten Maske - sie zeigen deren Werte
LOKAL_REGLER = tuple(filter.Regler(f"lokal_{r.name}", "lokal", r.minimum, r.maximum,
                                   schritt=r.schritt, nachkomma=r.nachkomma)
                     for r in lokal.REGLER)
LOKAL_WEICH = filter.Regler("lokal_weich", "lokal", 0, 100, vorgabe=lokal.RADIAL_WEICH)
LOKAL_LISTE_ZEILEN = 4          # so viele Masken zeigt die Liste ohne Rollen
# Pinsel einer Maske: Groesse 100 % ist ein Radius von MALEN_GROESSTER der langen Kante
MALEN_GROESSTER = 0.1
MALEN_REGLER = (filter.Regler("malen_groesse", "malen", 1, 100, vorgabe=20),
                filter.Regler("malen_weich", "malen", 0, 100, vorgabe=50),
                filter.Regler("malen_deckkraft", "malen", 1, 100, vorgabe=100))
MALEN_SCHRITT = 1.25            # [ und ] aendern die Groesse um diesen Faktor


def sw_filter_titel(name: str) -> str:
    return {"rot": _("Rotfilter"), "orange": _("Orangefilter"), "gelb": _("Gelbfilter"),
            "gruen": _("Grünfilter"), "blau": _("Blaufilter")}[name]


def tonung_titel(name: str) -> str:
    return {"sepia": _("Sepia"), "selen": _("Selen"), "cyanotypie": _("Cyanotypie"),
            "warm_kalt": _("Lichter warm, Schatten kalt")}[name]


def farbton_farbe(winkel: float) -> str:
    """Eine mittelhelle, bunte Farbe zum Farbton (OkLCh-Winkel) als #rrggbb."""
    bogen = math.radians(winkel)
    lab = np.array([[[0.72, 0.12 * math.cos(bogen), 0.12 * math.sin(bogen)]]], dtype=np.float32)
    rgb = filter.linear_zu_srgb(np.clip(filter.von_oklab(lab), 0, 1))[0, 0]
    return "#" + "".join(f"{round(float(k) * 255):02x}" for k in rgb)


def regler_titel(name: str) -> str:
    return {
        "temperatur": _("Temperatur"),
        "toenung": _("Tönung"),
        "belichtung": _("Belichtung"),
        "kontrast": _("Kontrast"),
        "lichter": _("Lichter"),
        "tiefen": _("Tiefen"),
        "klarheit": _("Klarheit"),
        "dunst": _("Dunst entfernen"),
        "dynamik": _("Dynamik"),
        "saettigung": _("Sättigung"),
        "schaerfe": _("Schärfen"),
        "schaerfe_radius": _("Radius"),
        "rauschen_luminanz": _("Luminanz"),
        "rauschen_farbe": _("Farbe"),
        "lut_staerke": _("Stärke"),
        "begradigen": _("Begradigen"),
        "perspektive_v": _("Perspektive senkrecht"),
        "perspektive_h": _("Perspektive waagrecht"),
        "verzeichnung": _("Verzeichnung"),
        "vignette": _("Vignette"),
        "ca_rot": _("Farbsaum Rot/Cyan"),
        "ca_blau": _("Farbsaum Blau/Gelb"),
        "ki_entrauschen": _("Entrauschen"),
        "ki_rauschen": _("Stärke"),
        "ki_schaerfe": _("Stärke"),
        "ki_farbe": _("Stärke"),
        "hg_belichtung": _("Belichtung"),
        "hg_kontrast": _("Kontrast"),
        "hg_saettigung": _("Sättigung"),
        "hg_temperatur": _("Temperatur"),
        "hg_unschaerfe": _("Unschärfe"),
        "maske_kante": _("Kante weicher"),
        "maske_verschieben": _("Kante verschieben"),
        "bokeh": _("Unschärfe"),
        "fokus": _("Fokus (fern – nah)"),
        "schaerfentiefe": _("Schärfentiefe"),
        "ton_lichter_farbton": _("Lichter: Farbton"),
        "ton_lichter_saettigung": _("Lichter: Sättigung"),
        "ton_schatten_farbton": _("Schatten: Farbton"),
        "ton_schatten_saettigung": _("Schatten: Sättigung"),
        "ton_balance": _("Balance"),
        "malen_groesse": _("Größe"),
        "malen_weich": _("Weicher Rand"),
        "malen_deckkraft": _("Deckkraft"),
        "korn": _("Stärke"),
        "korn_groesse": _("Größe"),
        "korn_rauheit": _("Rauheit"),
    }[name] if not name.startswith(("hsl_", "sw_", "lokal_")) else (
        farbbereich_titel(int(name.split("_")[1])) if not name.startswith("lokal_") else
        _("Weicher Rand") if name == "lokal_weich" else
        _("Schärfe") if name == "lokal_schaerfe" else regler_titel(name[6:]))


def speicherformate() -> list[tuple[str, str, int]]:
    """Dateifilter fuer den Speichern-Dialog: (Beschriftung, Endung, Bits)."""
    return [
        ("JPEG (*.jpg *.jpeg)", ".jpg", 8),
        (f"PNG {_('8 Bit')} (*.png)", ".png", 8),
        (f"PNG {_('16 Bit')} (*.png)", ".png", 16),
        (f"TIFF {_('8 Bit')} (*.tif *.tiff)", ".tif", 8),
        (f"TIFF {_('16 Bit')} (*.tif *.tiff)", ".tif", 16),
        ("WebP (*.webp)", ".webp", 8),
        ("AVIF (*.avif)", ".avif", 8),
    ]


def veroeffentlichen_formate() -> list[tuple[str, str]]:
    """Dateifilter fuer „Für Veröffentlichung“: (Beschriftung, Endung) - nur 8 Bit."""
    return [("JPEG (*.jpg *.jpeg)", ".jpg"), ("PNG (*.png)", ".png"), ("WebP (*.webp)", ".webp"),
            ("AVIF (*.avif)", ".avif")]


def ziel_bestimmen(pfad: str, gewaehlt: str) -> tuple[str, int]:
    """Endung ergaenzen und Bittiefe aus dem gewaehlten Filter ablesen.

    Hat der Anwender eine Endung getippt, die nicht zum Filter passt, gilt die
    Endung; 16 Bit gibt es dann nur, wenn das Format sie kann.
    """
    formate = {beschriftung: (endung, bits) for beschriftung, endung, bits in speicherformate()}
    endung_filter, bits = formate.get(gewaehlt, (".jpg", 8))
    endung = os.path.splitext(pfad)[1].lower()
    if endung not in bilddatei.SCHREIBBAR:
        return pfad + endung_filter, bits
    if endung_filter == endung or (endung, endung_filter) in ((".jpeg", ".jpg"),
                                                             (".tiff", ".tif")):
        return pfad, bits
    return pfad, 16 if bits == 16 and bilddatei.SCHREIBBAR[endung][2] else 8


def art_anzeige(daten: bilddatei.Bilddaten) -> str:
    if daten.raw:
        return "RAW"
    art = _("16 Bit") if daten.bits == 16 else _("8 Bit")
    if daten.infrarot is not None:
        art = _("{art} mit Infrarotkanal").format(art=art)
    return art


KI_ENTRAUSCHEN = filter.Regler("ki_entrauschen", "ki", 0, 100, vorgabe=50)


def seitenverhaeltnisse() -> list[tuple[str, float | None]]:
    """Auswahl fuer den Zuschnitt: Beschriftung und Breite/Hoehe; None heisst frei."""
    return [(_("Frei"), None), (_("Original"), -1.0), ("1:1", 1.0), ("3:2", 3 / 2),
            ("2:3", 2 / 3), ("4:3", 4 / 3), ("3:4", 3 / 4), ("5:4", 5 / 4),
            ("4:5", 4 / 5), ("16:9", 16 / 9), ("9:16", 9 / 16)]


def _ueberlappung(a, b) -> float:
    """Wie sehr sich zwei Flaechen decken: Schnitt durch die kleinere (0..1)."""
    _fa, ax0, ay0, ax1, ay1 = a
    _fb, bx0, by0, bx1, by1 = b
    schnitt = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
    kleiner = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0))
    return schnitt / kleiner if kleiner > 0 else 0.0


def zuschnitt_drehen(rahmen, richtung: int):
    """Zuschnitt mitdrehen: +1 im Uhrzeigersinn, -1 dagegen (normierte Rahmenkoordinaten)."""
    x0, y0, x1, y1 = rahmen
    if richtung > 0:
        return (1 - y1, x0, 1 - y0, x1)
    return (y0, 1 - x1, y1, 1 - x0)


def zuschnitt_spiegeln(rahmen):
    x0, y0, x1, y1 = rahmen
    return (1 - x1, y0, 1 - x0, y1)


def wert_anzeige(regler: filter.Regler, wert: float) -> str:
    text = f"{wert:.{regler.nachkomma}f}"
    if regler.minimum < 0 and wert > 0:
        text = "+" + text
    text = text.replace("-", "−")
    if regler.name in ("belichtung", "hg_belichtung", "lokal_belichtung"):
        text += " EV"
    elif regler.name == "schaerfe_radius":
        text += " px"
    elif regler.name in ("lut_staerke", "ki_entrauschen", "ki_rauschen", "ki_schaerfe",
                         "ki_farbe"):
        text += " %"
    elif regler.name in ("begradigen", "ton_lichter_farbton", "ton_schatten_farbton"):
        text += "°"
    elif regler.name in ("ton_lichter_saettigung", "ton_schatten_saettigung", "lokal_weich",
                         "malen_weich", "malen_deckkraft", "malen_groesse"):
        text += " %"
    return text


class Doppelklick(QObject):
    """Setzt einen Regler per Doppelklick auf seine Vorgabe zurueck."""

    def __init__(self, zuruecksetzen):
        super().__init__()
        self._zuruecksetzen = zuruecksetzen

    def eventFilter(self, objekt, ereignis):        # noqa: N802 - Qt-Name
        if ereignis.type() == QEvent.Type.MouseButtonDblClick:
            self._zuruecksetzen()
            return True
        return False


class KompakteEintraege(QStyledItemDelegate):
    """Eintraege einer Auswahlliste, nur so hoch wie die Schrift und etwas Luft - damit alle
    Karten auch auf 768 Pixel hohen Bildschirmen auf einmal in die Liste passen."""

    def sizeHint(self, option, index):            # noqa: N802 - Qt-Name
        groesse = super().sizeHint(option, index)
        groesse.setHeight(option.fontMetrics.height() + KARTENWAHL_LUFT_PX)
        return groesse


class ReglerZeile:
    """Beschriftung, Wertanzeige und Schieberegler fuer einen Filterwert."""

    def __init__(self, seite: BearbeitenSeite, regler: filter.Regler, gitter: QGridLayout,
                 zeile: int):
        self.regler = regler
        self.seite = seite
        self.stufen = round((regler.maximum - regler.minimum) / regler.schritt)

        self.titel = QLabel()
        seite.fenster.beschriften(self.titel.setText, regler_titel(regler.name))
        self.anzeige = QLabel(objectName="wert")
        self.anzeige.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.schieber = QSlider(Qt.Orientation.Horizontal)
        self.schieber.setRange(0, self.stufen)
        self.schieber.setPageStep(max(1, self.stufen // 20))
        self._filter = Doppelklick(self.zuruecksetzen)
        for widget in (self.titel, self.anzeige, self.schieber):
            widget.installEventFilter(self._filter)
            seite.fenster.beschriften(widget.setToolTip,
                                      _("Doppelklick setzt den Regler zurück."))

        gitter.addWidget(self.titel, zeile, 0)
        gitter.addWidget(self.anzeige, zeile, 1)
        gitter.addWidget(self.schieber, zeile + 1, 0, 1, 2)
        self.setzen(regler.vorgabe)
        self.schieber.valueChanged.connect(self._bewegt)

    def wert(self) -> float:
        roh = self.regler.minimum + self.schieber.value() * self.regler.schritt
        return round(roh, self.regler.nachkomma)

    def setzen(self, wert: float):
        stufe = round((wert - self.regler.minimum) / self.regler.schritt)
        self.schieber.blockSignals(True)
        self.schieber.setValue(stufe)
        self.schieber.blockSignals(False)
        self._anzeigen()

    def zuruecksetzen(self):
        self.setzen(self.regler.vorgabe)
        self._bewegt()

    def _anzeigen(self):
        self.anzeige.setText(wert_anzeige(self.regler, self.wert()))

    def _bewegt(self, *_args):
        self._anzeigen()
        self.seite.wert_geaendert(self.regler.name, self.wert())


class FarbtonZeile(ReglerZeile):
    """Ein Farbtonregler, der die Farbe als Feld vor dem Wert zeigt."""

    def __init__(self, *args):
        super().__init__(*args)
        self.anzeige.setTextFormat(Qt.TextFormat.RichText)
        self._anzeigen()

    def _anzeigen(self):
        # Nur Zahlen und eine selbst berechnete Farbe - nichts von aussen im Rich Text
        self.anzeige.setText(f'<span style="color:{farbton_farbe(self.wert())}">■</span> '
                             f"{wert_anzeige(self.regler, self.wert())}")


class BearbeitenSeite(QWidget):
    def __init__(self, fenster):
        super().__init__(objectName="seite")
        self.fenster = fenster
        self.sitzung: Sitzung | None = None
        self._vorher = False
        self._zeichnen_angefordert = False
        self._zuschnitt_vorher = None         # Zuschnitt beim Betreten des Zuschnittmodus
        self._auswaehler: ki.Auswaehler | None = None   # SAM, solange der Klickmodus laeuft
        self._klick_ziel: str | None = None   # "maske" oder "entfernen" im Klickmodus
        self._klick_marken: dict[str, list] = {"maske": [], "entfernen": []}   # im fertigen Bild
        self._klick_geo: dict = {}            # Geometrie, in der je Ziel geklickt wurde
        self._maske_zeigen_vorher = False
        self._entferner: ki.Entferner | None = None
        self._pinsel_letzter = None           # letzter Pinselpunkt im Original
        self.verlauf = verlauf.Verlauf(0)
        self._schritt_name = ""               # benennt die naechste Aenderung, wenn noetig
        self._zwischenablage: dict | None = None   # kopierte Einstellungen (voreinstellungen.py)
        # Eine Aenderung wird erst festgehalten, wenn eine Weile nichts mehr kommt - ein
        # Zug am Regler ist ein Schritt, nicht hundert
        self._verlauf_uhr = QTimer(self, singleShot=True, interval=VERLAUF_PAUSE_MS)
        self._verlauf_uhr.timeout.connect(self._festhalten)

        # Raster: oben Werkzeugleiste und Kartenauswahl, darunter Leinwand und Karten -
        # so beginnen Leinwand und erste Karte auf derselben Hoehe
        aufbau = QGridLayout(self)
        aufbau.setContentsMargins(0, 12, 0, 0)
        aufbau.setHorizontalSpacing(12)
        aufbau.setVerticalSpacing(8)
        aufbau.setColumnStretch(0, 1)
        aufbau.setRowStretch(1, 1)
        aufbau.addLayout(self._werkzeugleiste(), 0, 0)
        self.leinwand = Leinwand()
        fenster.beschriften(self.leinwand.leer.setText, _("Noch kein Bild geöffnet."))
        fenster.beschriften(self.leinwand.hinweis.setText,
                            _("Bild hierher ziehen oder „Öffnen …“ wählen."))
        self.leinwand.datei_abgelegt.connect(self.oeffnen)
        self.leinwand.ansicht_geaendert.connect(self._ansicht_geaendert)
        self.leinwand.bild_geklickt.connect(self._bild_geklickt)
        self.leinwand.pinsel_gezogen.connect(self._pinsel_gezogen)
        self.leinwand.lokal_gezogen.connect(self._lokal_gezogen)
        self.leinwand.lokal_loeschen.connect(self.lokal_teil_loeschen)
        self.leinwand.lokal_gemalt.connect(self._lokal_gemalt)
        aufbau.addWidget(self.leinwand, 1, 0)
        aufbau.addWidget(self._reglerleiste(), 1, 1)
        self.kartenwahl = self._kartenwahl()
        aufbau.addWidget(self.kartenwahl, 0, 1)

        QShortcut(QKeySequence.StandardKey.Open, self, self.oeffnen_dialog)
        QShortcut(QKeySequence.StandardKey.Save, self, self.speichern_dialog)
        QShortcut(QKeySequence.StandardKey.Print, self, self.drucken_dialog)
        QShortcut(QKeySequence("Ctrl+0"), self, lambda: self.leinwand.zoom_setzen(None))
        QShortcut(QKeySequence("Ctrl+1"), self, lambda: self.leinwand.zoom_setzen(1.0))
        QShortcut(QKeySequence(Qt.Key.Key_Return), self, lambda: self.zuschneiden(False))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._abbrechen)
        QShortcut(QKeySequence.StandardKey.Undo, self, self._strg_z)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.wiederholen)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.wiederholen)
        QShortcut(QKeySequence(Qt.Key.Key_O), self, self._lokal_zeigen_taste)
        QShortcut(QKeySequence(Qt.Key.Key_BracketLeft), self,
                  lambda: self._malen_groesse_schritt(-1))
        QShortcut(QKeySequence(Qt.Key.Key_BracketRight), self,
                  lambda: self._malen_groesse_schritt(1))
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self.einstellungen_kopieren)
        QShortcut(QKeySequence("Ctrl+Shift+V"), self, self.einstellungen_einfuegen)
        self._knoepfe_freischalten()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------

    def _knopf(self, text, aktion, name=None) -> QPushButton:
        knopf = QPushButton()
        if name:
            knopf.setObjectName(name)
        self.fenster.beschriften(knopf.setText, text)
        if aktion:
            knopf.clicked.connect(aktion)
        return knopf

    def _modell_tooltip(self, knopf: QPushButton, modell: ki.Modell, aktion=None):
        """Tooltip eines Knopfs, der ohne Modell erst laedt: solange das Modell
        fehlt, der Hinweis auf den Download - danach, was der Knopf tut."""
        if not ki.vorhanden(modell):
            text = _("Lädt zuerst das KI-Modell ({mb} MB) aus den Releases von Silberkorn "
                     "auf GitHub – nach einer Rückfrage mit Quelle, Größe und Lizenz.").format(
                mb=f"{ki.download_groesse(modell) / 2**20:.0f}")
        else:
            text = aktion if aktion is not None else ""
        self.fenster.beschriften(knopf.setToolTip, text)

    def _eintrag(self, auswahl: QComboBox, text, wert):
        """Eintrag einer Auswahlliste, der den Sprachwechsel mitmacht."""
        auswahl.addItem("", wert)
        nummer = auswahl.count() - 1
        self.fenster.beschriften(lambda t: auswahl.setItemText(nummer, t), text)

    def _werkzeugleiste(self) -> QHBoxLayout:
        leiste = QHBoxLayout()
        leiste.setSpacing(8)
        leiste.addWidget(self._knopf(_("Öffnen …"), self.oeffnen_dialog, "hauptschalter"))
        self.speichern_knopf = self._knopf(_("Speichern …"), self.speichern_dialog)
        self.fenster.beschriften(self.speichern_knopf.setToolTip, _(
            "Speichert das bearbeitete Bild unter einem neuen Namen (Strg+S) – das Original "
            "wird nie überschrieben."))
        leiste.addWidget(self.speichern_knopf)
        # Kurze Beschriftungen, damit das Fenster auch auf Bildschirmen um 1100 Pixel
        # Breite passt - die Tooltips sagen, was genau geschieht
        self.veroeffentlichen_knopf = self._knopf(_("Fürs Netz …"), self.veroeffentlichen_dialog)
        self.fenster.beschriften(self.veroeffentlichen_knopf.setToolTip, _(
            "Verkleinert, mit Wasserzeichen und Rechteangaben speichern – etwa für Bilder "
            "im Netz. Das Original bleibt unverändert."))
        leiste.addWidget(self.veroeffentlichen_knopf)
        self.drucken_knopf = self._knopf("🖶", self.drucken_dialog, "zoomsymbol")
        self.fenster.beschriften(self.drucken_knopf.setToolTip, _(
            "Drucken (Strg+P): Drucker, Papier und Bildgröße wählen, mit Vorschau auf dem "
            "Blatt. Gedruckt wird das bearbeitete Bild in voller Auflösung."))
        leiste.addWidget(self.drucken_knopf)
        leiste.addStretch(1)
        self.einpassen_knopf = self._knopf("⤢", lambda: self.leinwand.zoom_setzen(None),
                                           "zoomsymbol")
        self.zoom100_knopf = self._knopf("1:1", lambda: self.leinwand.zoom_setzen(1.0), "zoom")
        self.fenster.beschriften(self.einpassen_knopf.setToolTip,
                                 _("Einpassen: das ganze Bild zeigen (Strg+0)"))
        self.fenster.beschriften(self.zoom100_knopf.setToolTip, _(
            "100 %: ein Bildpixel je Bildschirmpixel (Strg+1). Mausrad zoomt, Ziehen "
            "verschiebt, Doppelklick wechselt."))
        leiste.addWidget(self.einpassen_knopf)
        leiste.addWidget(self.zoom100_knopf)
        leiste.addSpacing(6)
        self.vorher_knopf = self._knopf(_("Vorher"), None)
        self.fenster.beschriften(self.vorher_knopf.setToolTip,
                                 _("Gedrückt halten, um das unbearbeitete Bild zu sehen."))
        self.vorher_knopf.pressed.connect(lambda: self._vorher_zeigen(True))
        self.vorher_knopf.released.connect(lambda: self._vorher_zeigen(False))
        leiste.addWidget(self.vorher_knopf)
        self.zuruecksetzen_knopf = self._knopf(_("Zurücksetzen"), self.alles_zuruecksetzen)
        self.fenster.beschriften(self.zuruecksetzen_knopf.setToolTip, _(
            "Setzt alle Regler, Drehung, Zuschnitt und geänderte Metadaten zurück, holt "
            "entfernte Objekte zurück und verwirft eine KI-Erweiterung. Lässt sich mit "
            "„Rückgängig“ zurücknehmen."))
        self.rueckgaengig_knopf = self._knopf("↶", self.rueckgaengig, "verlauf")
        self.wiederholen_knopf = self._knopf("↷", self.wiederholen, "verlauf")
        leiste.addWidget(self.zuruecksetzen_knopf)
        paar = QHBoxLayout()
        paar.setSpacing(2)
        paar.addWidget(self.rueckgaengig_knopf)
        paar.addWidget(self.wiederholen_knopf)
        leiste.addLayout(paar)
        return leiste

    def _reglerleiste(self) -> QScrollArea:
        flaeche = Reglerleiste()
        flaeche.setWidgetResizable(True)
        flaeche.setFixedWidth(REGLERLEISTE_BREITE)
        flaeche.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inhalt = QWidget(objectName="seite")
        spalte = QVBoxLayout(inhalt)
        spalte.setContentsMargins(0, 0, 4, 0)
        spalte.setSpacing(12)

        self.zeilen: dict[str, ReglerZeile] = {}
        self._karten_titel: dict[QFrame, str] = {}
        self._ki_bild_teile: dict[str, tuple[QLabel, QPushButton]] = {}
        gruppen: dict[str, QGridLayout] = {}
        karten: dict[str, QFrame] = {}
        zaehler: dict[str, int] = {}
        for regler in filter.REGLER:
            if regler.gruppe == "tonung":
                continue                    # steht auf der Karte Schwarzweiß & Tönung
            if regler.gruppe not in gruppen:
                karte, innen = self._karte(gruppen_titel(regler.gruppe))
                if regler.gruppe == "lut":
                    self._lut_bedienung(innen)
                if regler.gruppe == "geometrie":
                    self._geometrie_bedienung(innen)
                if regler.gruppe == "objektiv":
                    self._objektiv_bedienung(innen)
                if regler.gruppe in ("ki_rauschen", "ki_schaerfe", "ki_farbe"):
                    self._ki_bild_bedienung(regler.gruppe, innen)
                if regler.gruppe == "maske":
                    self._masken_bedienung(innen)
                if regler.gruppe == "tiefe":
                    self._tiefe_bedienung(innen)
                gitter = QGridLayout()
                gitter.setVerticalSpacing(2)
                gitter.setColumnStretch(0, 1)
                innen.addLayout(gitter)
                if regler.gruppe in ("rauschen", "korn"):
                    hinweis = QLabel(objectName="nebentext")
                    hinweis.setWordWrap(True)
                    self.fenster.beschriften(hinweis.setText, _(
                        "Die Vorschau ist verkleinert und zeigt Rauschen schwächer als das "
                        "gespeicherte Bild.") if regler.gruppe == "rauschen" else _(
                        "Das Korn wächst mit dem Bild. Die verkleinerte Vorschau zeigt es "
                        "schwächer – beurteilen lässt es sich in der 100-%-Ansicht."))
                    innen.addWidget(hinweis)
                spalte.addWidget(karte)
                karten[regler.gruppe] = karte
                gruppen[regler.gruppe] = gitter
                zaehler[regler.gruppe] = 0
            self.zeilen[regler.name] = ReglerZeile(self, regler, gruppen[regler.gruppe],
                                                   zaehler[regler.gruppe])
            zaehler[regler.gruppe] += 2
        # Gradationskurve hinter die Tonwerte, Farbbereiche hinter Dynamik und Saettigung
        spalte.insertWidget(spalte.indexOf(karten["licht"]) + 1, self._kurvenkarte())
        spalte.insertWidget(spalte.indexOf(karten["farbe"]) + 1, self._hsl_karte())
        spalte.insertWidget(spalte.indexOf(karten["farbe"]) + 2, self._sw_karte())
        spalte.insertWidget(spalte.indexOf(karten["farbe"]) + 3, self._lokal_karte())
        spalte.insertWidget(spalte.indexOf(karten["maske"]) + 1, self._entfern_karte())
        spalte.insertWidget(spalte.indexOf(karten["maske"]) + 2, self._anonym_karte())
        spalte.insertWidget(spalte.indexOf(karten["maske"]) + 3, self._metadaten_karte())
        spalte.insertWidget(spalte.indexOf(karten["maske"]), self._film_karte())
        spalte.addWidget(self._ki_karte())
        spalte.insertWidget(0, self._voreinstellungen_karte())
        spalte.addStretch(1)
        flaeche.setWidget(inhalt)
        self.reglerleiste = flaeche
        # Die Karten in der Reihenfolge der Leiste - fuer die Auswahl darueber
        self.karten = [karte for karte in (spalte.itemAt(i).widget()
                                           for i in range(spalte.count()))
                       if karte in self._karten_titel]
        return flaeche

    def _kartenwahl(self) -> QComboBox:
        """Auswahl ueber den Karten: springt zur gewaehlten Karte und zeigt beim Rollen,
        welche oben steht."""
        wahl = QComboBox(objectName="kartenwahl")
        wahl.setItemDelegate(KompakteEintraege(wahl))
        for nummer, karte in enumerate(self.karten):
            self._eintrag(wahl, self._karten_titel[karte], nummer)
        wahl.setMaxVisibleItems(len(self.karten))    # alle auf einmal, ohne Rollen
        wahl.setFixedWidth(REGLERLEISTE_BREITE)
        wahl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.fenster.beschriften(wahl.setToolTip, _("Zu einer Karte springen"))
        wahl.activated.connect(self.zu_karte)
        self._sprung = QPropertyAnimation(self.reglerleiste.verticalScrollBar(), b"value", self)
        self._sprung.setDuration(KARTE_SPRUNG_MS)
        self._sprung.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._sprung.finished.connect(self._sprung_fertig)
        self._sprung_ziel: int | None = None
        self.reglerleiste.verticalScrollBar().valueChanged.connect(self._karte_oben_zeigen)
        return wahl

    def zu_karte(self, nummer: int, weich: bool = True):
        """Die Liste so rollen, dass die Karte oben steht, und sie kurz hervorheben."""
        balken = self.reglerleiste.verticalScrollBar()
        ziel = min(self.karten[nummer].y(), balken.maximum())
        self._sprung.stop()
        self._sprung_ziel = nummer
        if weich and ziel != balken.value():
            self._sprung.setStartValue(balken.value())
            self._sprung.setEndValue(ziel)
            self._sprung.start()
        else:
            balken.setValue(ziel)
            self._sprung_fertig()

    def _sprung_fertig(self):
        nummer, self._sprung_ziel = self._sprung_ziel, None
        if nummer is None:
            return
        # Am Ende der Liste steht die Karte nicht ganz oben - gewaehlt bleibt sie trotzdem
        self.kartenwahl.setCurrentIndex(nummer)
        karte = self.karten[nummer]
        self._markieren(karte, True)
        QTimer.singleShot(KARTE_MARKIERT_MS, lambda: self._markieren(karte, False))

    @staticmethod
    def _markieren(karte: QFrame, an: bool):
        karte.setProperty("markiert", an)
        karte.style().unpolish(karte)
        karte.style().polish(karte)

    def _karte_oben_zeigen(self, wert: int):
        """Beim Rollen: die oberste sichtbare Karte im Auswahlfeld zeigen."""
        if self._sprung_ziel is not None:
            return                                # waehrend eines Sprungs gilt das Ziel
        nummer = 0
        for i, karte in enumerate(self.karten):
            if karte.isVisible() and karte.y() <= wert + KARTE_OBEN_PX:
                nummer = i
        if nummer != self.kartenwahl.currentIndex():
            self.kartenwahl.setCurrentIndex(nummer)

    def _karte(self, titeltext) -> tuple[QFrame, QVBoxLayout]:
        karte = QFrame(objectName="karte")
        self._karten_titel[karte] = titeltext     # fuer die Auswahl ueber den Karten
        innen = QVBoxLayout(karte)
        innen.setContentsMargins(16, 12, 16, 14)
        titel = QLabel(objectName="kartentitel")
        self.fenster.beschriften(titel.setText, titeltext)
        innen.addWidget(titel)
        return karte, innen

    def _geometrie_bedienung(self, innen: QVBoxLayout):
        """Drehen, Spiegeln und Zuschneiden - ueber den Reglern der Geometriekarte."""
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.links_knopf = self._knopf(_("↺ Links"), lambda: self.drehen(-1), "kanal")
        self.rechts_knopf = self._knopf(_("↻ Rechts"), lambda: self.drehen(1), "kanal")
        self.spiegeln_knopf = self._knopf(_("⇋ Spiegeln"), self.spiegeln, "kanal")
        for knopf in (self.links_knopf, self.rechts_knopf, self.spiegeln_knopf):
            leiste.addWidget(knopf)
        leiste.addStretch(1)
        innen.addLayout(leiste)

        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.zuschneiden_knopf = self._knopf(_("Zuschneiden"), None, "kanal")
        self.zuschneiden_knopf.setCheckable(True)
        self.zuschneiden_knopf.toggled.connect(self.zuschneiden)
        self.fenster.beschriften(self.zuschneiden_knopf.setToolTip, _(
            "Rahmen auf dem Bild ziehen; Eingabetaste übernimmt, Esc bricht ab."))
        self.verhaeltnis_wahl = QComboBox()
        for text, wert in seitenverhaeltnisse():
            self._eintrag(self.verhaeltnis_wahl, text, wert)
        self.verhaeltnis_wahl.currentIndexChanged.connect(self._verhaeltnis_gewaehlt)
        self.zuschnitt_weg_knopf = self._knopf(_("Voll"), self.zuschnitt_zuruecksetzen, "kanal")
        self.fenster.beschriften(self.zuschnitt_weg_knopf.setToolTip,
                                 _("Zuschnitt zurücksetzen"))
        leiste.addWidget(self.zuschneiden_knopf)
        leiste.addWidget(self.verhaeltnis_wahl, 1)
        leiste.addWidget(self.zuschnitt_weg_knopf)
        innen.addLayout(leiste)

        # KI-Erweitern: statt auf das Seitenverhaeltnis zuzuschneiden, Raender erfinden
        self.erweitern_box = QCheckBox()
        self.fenster.beschriften(self.erweitern_box.setText,
                                 _("Mit KI erweitern statt beschneiden"))
        self.erweitern_box.toggled.connect(self._erweitern_umgeschaltet)
        innen.addWidget(self.erweitern_box)
        self.erweitern_hinweis = QLabel(objectName="nebentext")
        self.erweitern_hinweis.setWordWrap(True)
        innen.addWidget(self.erweitern_hinweis)
        self.erweitern_knopf = self._knopf("", self.erweitern, "kanal")
        innen.addWidget(self.erweitern_knopf)

    # ------------------------------------------------------------------
    # Objektivprofil (lensfun)
    # ------------------------------------------------------------------

    def _objektiv_bedienung(self, innen: QVBoxLayout):
        """Profil an/aus, was erkannt wurde, Datenbank laden und aktualisieren."""
        self.profil_box = QCheckBox()
        self.fenster.beschriften(self.profil_box.setText, _("Objektivprofil anwenden"))
        self.fenster.beschriften(self.profil_box.setToolTip, _(
            "Gleicht Verzeichnung, Farbsäume und Vignette nach der Objektivdatenbank "
            "lensfun aus. Die Regler darunter wirken zusätzlich."))
        self.profil_box.toggled.connect(self._profil_umgeschaltet)
        innen.addWidget(self.profil_box)
        self.profil_hinweis = QLabel(objectName="nebentext")
        self.profil_hinweis.setWordWrap(True)
        innen.addWidget(self.profil_hinweis)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.profil_laden_knopf = self._knopf("", self.objektiv_datenbank_laden, "kanal")
        self.fenster.beschriften(self.profil_laden_knopf.setText,
                                 _("Objektivdatenbank laden"))
        self.profil_pruefen_knopf = self._knopf("", self.objektiv_datenbank_pruefen, "kanal")
        self.fenster.beschriften(self.profil_pruefen_knopf.setText,
                                 _("Nach neuer Datenbank suchen"))
        self.fenster.beschriften(self.profil_pruefen_knopf.setToolTip, _(
            "Fragt bei lensfun nach, ob es eine neuere Objektivdatenbank gibt. Silberkorn "
            "fragt nie von selbst."))
        leiste.addWidget(self.profil_laden_knopf)
        leiste.addWidget(self.profil_pruefen_knopf)
        leiste.addStretch(1)
        innen.addLayout(leiste)

    def _objektiv_anzeigen(self):
        offen = self.sitzung is not None
        suche = self.sitzung.objektiv if offen else None
        db_stand = objektivprofile.stand()
        profil = suche.profil if suche is not None else None
        self.profil_box.blockSignals(True)
        self.profil_box.setChecked(offen and bool(self.sitzung.werte.objektivprofil))
        self.profil_box.blockSignals(False)
        self.profil_box.setEnabled(profil is not None)
        self.profil_laden_knopf.setVisible(db_stand is None)
        self.profil_pruefen_knopf.setVisible(db_stand is not None)
        if db_stand is None:
            text = _("Die Objektivdatenbank ist noch nicht geladen (etwa 0,5 MB).")
        elif not offen:
            text = _("Objektivdatenbank vom {datum}.").format(
                datum=_datum(db_stand["zeitstempel"]))
        elif suche.aufnahme is None or not suche.aufnahme.objektiv:
            text = _("Die Datei nennt kein Objektiv.")
        elif profil is None:
            text = _("Kein Profil für „{objektiv}“ gefunden.").format(
                objektiv=suche.aufnahme.objektiv)
        else:
            aufnahme = suche.aufnahme
            teile = [profil.objektiv]
            if aufnahme.brennweite > 0:
                teile.append(f"{aufnahme.brennweite:g} mm")
            if aufnahme.blende > 0:
                teile.append(f"f/{round(aufnahme.blende, 1):g}")
            namen = {"verzeichnung": _("Verzeichnung"), "farbsaum": _("Farbsäume"),
                     "vignette": _("Vignette")}
            text = " · ".join(teile) + "\n" + _("Profil für: {arten}").format(
                arten=", ".join(namen[art] for art in profil.arten))
            if not self.sitzung.daten.raw:
                text += "\n" + _("Kamera-JPEGs sind oft schon in der Kamera korrigiert – "
                                 "deshalb hier nicht automatisch.")
        self.profil_hinweis.setText(text)

    def _profil_umgeschaltet(self, an: bool):
        if self.sitzung is None:
            return
        self.sitzung.werte.objektivprofil = self.sitzung.objektiv_terme() if an else ()
        self.zeichnen_anfordern()

    def objektiv_datenbank_laden(self, nachfragen: bool = True) -> bool:
        """Die lensfun-Datenbank laden - erst nach Rueckfrage mit Quelle, Lizenz und Ablage."""
        if nachfragen:
            frage = _(
                "Silberkorn lädt die Objektivdatenbank (etwa 0,5 MB) von:\n{quelle}\n\n"
                "Sie stammt vom Projekt {herkunft}.\n\n"
                "Ablage: {ordner}\n\nJetzt herunterladen?").format(
                    quelle=objektivprofile.QUELLE + objektivprofile.ARCHIV,
                    herkunft=objektivprofile.HERKUNFT,
                    ordner=objektivprofile.ziel_ordner())
            antwort = QMessageBox.question(self, _("Objektivdatenbank laden"), frage,
                                           QMessageBox.StandardButton.Yes
                                           | QMessageBox.StandardButton.No,
                                           QMessageBox.StandardButton.No)
            if antwort != QMessageBox.StandardButton.Yes:
                return False
        anzeige = QProgressDialog(_("Objektivdatenbank wird geladen …"), _("Abbrechen"),
                                  0, 100, self)
        anzeige.setWindowTitle(self.fenster.windowTitle())
        anzeige.setWindowModality(Qt.WindowModality.WindowModal)
        anzeige.setMinimumDuration(0)

        def fortschritt(geladen, gesamt):
            anzeige.setValue(round(100 * geladen / gesamt) if gesamt else 0)
            QApplication.processEvents()
            return not anzeige.wasCanceled()

        try:
            ordner = objektivprofile.herunterladen(fortschritt)
        except objektivprofile.Abbruch:
            self.fenster.melden(_("Herunterladen abgebrochen."))
            return False
        except objektivprofile.DatenbankFehler as fehler:
            self._fehler(_("Die Objektivdatenbank ließ sich nicht laden."), str(fehler))
            return False
        finally:
            anzeige.close()
        if self.sitzung is not None:
            self.sitzung.objektiv_suchen()
            self.zeichnen_anfordern()
        self._objektiv_anzeigen()
        self.fenster.melden(_("Objektivdatenbank geladen: {ordner}").format(ordner=ordner))
        return True

    def objektiv_datenbank_pruefen(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            neu = objektivprofile.aktualisierung()
        except objektivprofile.DatenbankFehler as fehler:
            self._fehler(_("Ob es eine neuere Objektivdatenbank gibt, ließ sich nicht "
                           "feststellen."), str(fehler))
            return
        finally:
            QApplication.restoreOverrideCursor()
        if neu is None:
            stand = objektivprofile.stand()
            QMessageBox.information(self, _("Objektivdatenbank"), _(
                "Die Objektivdatenbank ist aktuell (Stand {datum}).").format(
                    datum=_datum(stand["zeitstempel"]) if stand else "?"))
            return
        antwort = QMessageBox.question(
            self, _("Objektivdatenbank"),
            _("Es gibt eine neuere Objektivdatenbank vom {datum} (etwa 0,5 MB, von {quelle})."
              "\n\nJetzt laden?").format(datum=_datum(neu), quelle=objektivprofile.QUELLE),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if antwort == QMessageBox.StandardButton.Yes:
            self.objektiv_datenbank_laden(nachfragen=False)

    # ------------------------------------------------------------------
    # Geometrie: Drehen, Spiegeln, Zuschneiden
    # ------------------------------------------------------------------

    def drehen(self, richtung: int):
        if self.sitzung is None:
            return
        werte = self.sitzung.werte
        # Gespiegelt kehrt sich die Drehrichtung der Quelle um - die sichtbare
        # Drehung soll aber immer der Pfeilrichtung folgen.
        werte.drehung90 = (werte.drehung90 + (-richtung if werte.spiegeln else richtung)) % 4
        werte.zuschnitt = zuschnitt_drehen(werte.zuschnitt, richtung)
        self._geometrie_geaendert()

    def spiegeln(self):
        if self.sitzung is None:
            return
        werte = self.sitzung.werte
        werte.spiegeln = not werte.spiegeln
        werte.zuschnitt = zuschnitt_spiegeln(werte.zuschnitt)
        self._geometrie_geaendert()

    def _geometrie_geaendert(self):
        if self.leinwand.zuschnitt is not None:
            self.leinwand.zuschnitt = self.sitzung.werte.zuschnitt
        self.zeichnen_anfordern()

    def zuschneiden(self, an: bool):
        """Zuschnittmodus ein- oder ausschalten; beim Ausschalten wird der Rahmen uebernommen."""
        if self.sitzung is None or an == (self.leinwand.zuschnitt is not None):
            return
        if an:
            self.auswahl_beenden()
            self.pinsel_beenden()
            self._zuschnitt_vorher = self.sitzung.werte.zuschnitt
            self.leinwand.zoom_setzen(None)
            self.leinwand.zuschnitt = self.sitzung.werte.zuschnitt
            self.leinwand.seitenverhaeltnis = self._verhaeltnis()
        else:
            self.sitzung.werte.zuschnitt = tuple(self.leinwand.zuschnitt)
            self.leinwand.zuschnitt = None
        self.zuschneiden_knopf.blockSignals(True)
        self.zuschneiden_knopf.setChecked(an)
        self.zuschneiden_knopf.blockSignals(False)
        self.zeichnen_anfordern()

    def _abbrechen(self):
        """Esc: Zuschnitt verwerfen oder Klick- und Pinselmodus verlassen."""
        if self.leinwand.zuschnitt is not None:
            self.zuschnitt_abbrechen()
        else:
            self.auswahl_beenden()
            self.pinsel_beenden()

    def zuschnitt_abbrechen(self):
        if self.leinwand.zuschnitt is None:
            return
        self.leinwand.zuschnitt = self._zuschnitt_vorher
        self.zuschneiden(False)

    def zuschnitt_zuruecksetzen(self):
        if self.sitzung is None:
            return
        if self.leinwand.zuschnitt is not None:
            self.leinwand.zuschnitt = VOLLER_ZUSCHNITT
            self.leinwand.update()
        else:
            self.sitzung.werte.zuschnitt = VOLLER_ZUSCHNITT
            self.zeichnen_anfordern()

    def _verhaeltnis(self) -> float | None:
        wert = self.verhaeltnis_wahl.currentData()
        if wert is None or self.sitzung is None:
            return wert
        if wert < 0:                              # "Original": Verhaeltnis des ganzen Rahmens
            hoehe, breite = self.sitzung.ausgabe_form(
                dataclasses.replace(self.sitzung.werte, zuschnitt=VOLLER_ZUSCHNITT))
            return breite / hoehe
        return wert

    def _verhaeltnis_gewaehlt(self, *_args):
        if self.sitzung is None:
            return
        if self.erweitern_box.isChecked() and self.leinwand.zuschnitt is None:
            self._erweitern_anzeigen()             # erweitert wird erst auf Knopfdruck
            return
        verhaeltnis = self._verhaeltnis()
        if self.leinwand.zuschnitt is not None:
            self.leinwand.seitenverhaeltnis_setzen(verhaeltnis)
        elif verhaeltnis is not None:
            rahmen_form = self.sitzung.ausgabe_form(
                dataclasses.replace(self.sitzung.werte, zuschnitt=VOLLER_ZUSCHNITT))
            self.sitzung.werte.zuschnitt = rahmen_mit_verhaeltnis(
                self.sitzung.werte.zuschnitt, verhaeltnis, rahmen_form)
            self.zeichnen_anfordern()

    # ------------------------------------------------------------------
    # KI-Erweitern (Outpainting)
    # ------------------------------------------------------------------

    def _erweitern_modell(self) -> ki.Modell:
        return ki.ERWEITER_MODELLE["outpaint"]

    def _vram(self) -> int:
        karte = self.fenster.befund.karte
        return karte.vram_bytes if karte else 0

    def _erweitern_verhaeltnis(self) -> float | None:
        """Gewaehltes Seitenverhaeltnis, umgerechnet auf das Original vor dem Drehen -
        None bei „Frei“ und „Original“."""
        wert = self.verhaeltnis_wahl.currentData()
        if wert is None or wert < 0 or self.sitzung is None:
            return None
        return 1 / wert if self.sitzung.werte.drehung90 % 2 else wert

    def _erweitern_anzeigen(self):
        if not hasattr(self, "erweitern_knopf"):
            return
        modell = self._erweitern_modell()
        offen = self.sitzung is not None
        nutzbar = (ki.angeboten(modell, self._ki_stufe())
                   and ki.genug_vram(modell, self._vram()))
        an = self.erweitern_box.isChecked()
        # Abwaehlen bleibt immer moeglich - es verwirft eine Erweiterung
        self.erweitern_box.setEnabled((offen and nutzbar) or an)
        self._modell_tooltip(self.erweitern_box, modell, _(
            "Statt das Bild auf das Seitenverhältnis zuzuschneiden, erfindet die KI die "
            "fehlenden Ränder dazu. Das Original bleibt unverändert."))
        verhaeltnis = self._erweitern_verhaeltnis()
        plan = self.sitzung.erweiterung_planen(verhaeltnis) if offen and verhaeltnis else None
        hoehe, breite = self.sitzung.original.shape[:2] if offen else (0, 0)
        schon = plan is not None and plan[:2] == (breite, hoehe)
        if not nutzbar:
            text = _("KI-Erweitern braucht mindestens 8 GB Grafikspeicher.")
        elif not an:
            text = ""
        elif not ki.vorhanden(modell):
            text = _("Dieses Modell ist noch nicht geladen.")
        elif plan is None:
            text = _("Ein Seitenverhältnis wählen – die KI erfindet, was dafür fehlt.")
        elif schon:
            text = _("Das Bild hat dieses Seitenverhältnis schon.")
        else:
            gross_b, gross_h = plan[:2]
            if self.sitzung.werte.drehung90 % 2:
                gross_b, gross_h = gross_h, gross_b
            text = _("Neue Größe: {breite} × {hoehe} px. Die KI rechnet rund eine halbe "
                     "Minute.").format(breite=gross_b, hoehe=gross_h)
            if ki.grosser_rand(breite, hoehe, *plan):
                text += " " + _("Über 25 % je Seite erfindet die KI mehr, als sie sieht – "
                                "das Ergebnis kann unstimmig werden.")
        self.fenster.beschriften(self.erweitern_hinweis.setText, text)
        self.erweitern_hinweis.setVisible(bool(text))
        self.erweitern_knopf.setVisible(an and nutzbar)
        if not ki.vorhanden(modell):
            self.fenster.beschriften(self.erweitern_knopf.setText, _("Erweitern · {mb} MB").format(
                mb=f"{ki.download_groesse(modell) / 2**20:.0f}"))
            self.erweitern_knopf.setEnabled(True)
            self._modell_tooltip(self.erweitern_knopf, modell)
            return
        neu = offen and plan is not None and self.sitzung.erweitert_auf(verhaeltnis)
        if neu:
            self.fenster.beschriften(self.erweitern_knopf.setText, _("Neu erzeugen"))
            self._modell_tooltip(self.erweitern_knopf, modell, _(
                "Erfindet die Ränder noch einmal, mit anderem Zufall."))
        else:
            self.fenster.beschriften(self.erweitern_knopf.setText, _("Erweitern"))
            self._modell_tooltip(self.erweitern_knopf, modell, _(
                "Erfindet die fehlenden Ränder für das gewählte Seitenverhältnis. Das "
                "Original bleibt unverändert."))
        self.erweitern_knopf.setEnabled(offen and plan is not None and not schon)

    def _erweitern_umgeschaltet(self, an: bool):
        if an:
            self.zuschneiden(False)
            if self.sitzung is not None and self.sitzung.werte.zuschnitt != VOLLER_ZUSCHNITT:
                self.sitzung.werte.zuschnitt = VOLLER_ZUSCHNITT
                self.zeichnen_anfordern()
        elif self.sitzung is not None and self.sitzung.erweiterung_verwerfen():
            self._klick_marken = {"maske": [], "entfernen": []}
            self.fenster.melden(_("Erweiterung verworfen."))
            self.zeichnen_anfordern()
        self._erweitern_anzeigen()

    def erweitern(self):
        """Raender fuer das gewaehlte Seitenverhaeltnis erfinden - jedes Mal mit neuem
        Zufall, so erzeugt derselbe Knopf auch neu."""
        modell = self._erweitern_modell()
        if not ki.vorhanden(modell):
            self.ki_modell_laden(modell)
            self._erweitern_anzeigen()
            return
        verhaeltnis = self._erweitern_verhaeltnis()
        if self.sitzung is None or verhaeltnis is None:
            return
        self.auswahl_beenden()
        self.pinsel_beenden()
        self.zuschneiden(False)
        anzeige = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # Nicht aufheben: Der Transformer allein belegt gut 4 GB Grafikspeicher
            netz = ki.Erweiterer(modell)
            anzeige = QProgressDialog(_("KI erweitert das Bild …"), _("Abbrechen"), 0, 100, self)
            anzeige.setWindowTitle(self.fenster.windowTitle())
            anzeige.setWindowModality(Qt.WindowModality.WindowModal)
            anzeige.setMinimumDuration(0)

            def fortschritt(nummer, anzahl):
                anzeige.setValue(round(100 * nummer / anzahl))
                QApplication.processEvents()
                return not anzeige.wasCanceled()

            ms = self.sitzung.ki_erweitern(netz, verhaeltnis, random.randrange(1 << 31),
                                           fortschritt)
            del netz
        except ki.KiAbbruch:
            self.fenster.melden(_("KI-Erweitern abgebrochen."))
            return
        except ki.KiFehler as fehler:
            self._fehler(_("Das KI-Erweitern ist fehlgeschlagen."), str(fehler))
            return
        except cp.cuda.memory.OutOfMemoryError:
            self._fehler(_("Für dieses Bild reicht der Grafikspeicher nicht."), "")
            return
        finally:
            QApplication.restoreOverrideCursor()
            if anzeige is not None:
                anzeige.close()
            cp.get_default_memory_pool().free_all_blocks()
            self._erweitern_anzeigen()
        # Der Rahmen galt dem alten Bild, die Klickmarken lagen im alten Format
        self.sitzung.werte.zuschnitt = VOLLER_ZUSCHNITT
        self._klick_marken = {"maske": [], "entfernen": []}
        self.fenster.melden(_("KI-Erweitern fertig ({s} s)").format(s=f"{ms / 1000:.1f}"))
        self.zeichnen_anfordern()

    def _ansicht_geaendert(self):
        if self.leinwand.zoom is None and self.sitzung is not None:
            self.sitzung.vollbild_vergessen()     # Grafikspeicher des Vollbildes freigeben
        self.zeichnen_anfordern()

    # ------------------------------------------------------------------
    # KI-Hochskalieren
    # ------------------------------------------------------------------

    def _ki_karte(self) -> QFrame:
        karte, innen = self._karte(_("KI-Hochskalieren"))
        self._ki_hochskalierer = None            # (Schluessel, Entrauschen, Hochskalierer)
        zeile = QHBoxLayout()
        self.ki_faktor = QComboBox()
        for text, wert in ((_("Aus"), 0), ("2 ×", 2), ("4 ×", 4)):
            self._eintrag(self.ki_faktor, text, wert)
        self.ki_modell = QComboBox()
        self._eintrag(self.ki_modell, _("Schnell"), "schnell")
        self._eintrag(self.ki_modell, _("Hohe Qualität"), "qualitaet")
        zeile.addWidget(self.ki_faktor)
        zeile.addWidget(self.ki_modell, 1)
        innen.addLayout(zeile)
        gitter = QGridLayout()
        gitter.setVerticalSpacing(2)
        gitter.setColumnStretch(0, 1)
        innen.addLayout(gitter)
        self.ki_entrauschen = ReglerZeile(self, KI_ENTRAUSCHEN, gitter, 0)
        self.ki_ergebnis = QLabel(objectName="wert")
        innen.addWidget(self.ki_ergebnis)
        self.ki_hinweis = QLabel(objectName="nebentext")
        self.ki_hinweis.setWordWrap(True)
        innen.addWidget(self.ki_hinweis)
        self.ki_laden_knopf = QPushButton()
        self.ki_laden_knopf.clicked.connect(lambda: self.ki_modell_laden(self._ki_modell()))
        innen.addWidget(self.ki_laden_knopf)
        self.ki_faktor.currentIndexChanged.connect(self._ki_anzeigen)
        self.ki_modell.currentIndexChanged.connect(self._ki_anzeigen)
        self._ki_anzeigen()
        return karte

    def _ki_stufe(self) -> str:
        return self.fenster.befund.stufe

    def _ki_modell(self) -> ki.Modell:
        return ki.MODELLE[self.ki_modell.currentData()]

    def _ki_anzeigen(self, *_args):
        """Bedienbarkeit, Ergebnisgroesse und Hinweis der KI-Karte aufraeumen."""
        offen = self.sitzung is not None
        stufe = self._ki_stufe()
        nutzbar = stufe in ki.STUFEN
        modell = self._ki_modell()
        an = self.ki_faktor.currentData() > 0
        self.ki_faktor.setEnabled(nutzbar)
        self.ki_modell.setEnabled(nutzbar)
        self.ki_entrauschen.schieber.setEnabled(offen and nutzbar and modell.mischung is not None)
        if not nutzbar:
            text = _("KI-Funktionen brauchen mindestens 4 GB Grafikspeicher.")
        elif not ki.angeboten(modell, stufe):
            text = _("Dieses Modell braucht mindestens Funktionsstufe {stufe}.").format(
                stufe=modell.mindeststufe)
        elif not ki.vorhanden(modell):
            text = _("Dieses Modell ist noch nicht geladen.")
        else:
            text = _("Wird beim Speichern angewendet. KI ergänzt Details, die im Original "
                     "nicht vorhanden waren.")
        self.fenster.beschriften(self.ki_hinweis.setText, text)
        laden = nutzbar and ki.angeboten(modell, stufe) and not ki.vorhanden(modell)
        self.ki_laden_knopf.setVisible(laden)
        if laden:
            self.fenster.beschriften(self.ki_laden_knopf.setText, _(
                "Modell herunterladen ({mb} MB)").format(
                    mb=f"{ki.download_groesse(modell) / 2**20:.0f}"))
            self._modell_tooltip(self.ki_laden_knopf, modell)
        if offen and an:
            hoehe, breite = ki.ausgabe_form(self.sitzung.ausgabe_form(),
                                            self.ki_faktor.currentData())
            self.ki_ergebnis.setText(f"{breite} × {hoehe} px")
        else:
            self.ki_ergebnis.setText("")

    def ki_modell_laden(self, modell: ki.Modell):
        """Fehlende Modelldateien laden - erst nach Rueckfrage mit Quelle, Groesse und Lizenz."""
        groesse = ki.download_groesse(modell)
        ziel = ki.modell_ordner()
        frage = _(
            "Silberkorn lädt {mb} MB von:\n{quelle}\n\n"
            "Das Modell stammt von {herkunft} und wird nach dem Laden gegen seine "
            "Prüfsumme geprüft.\n\n"
            "Ablage: {ordner}\n\nJetzt herunterladen?").format(
                mb=f"{groesse / 2**20:.1f}", quelle=modell.release, herkunft=modell.herkunft,
                ordner=ziel)
        antwort = QMessageBox.question(self, _("KI-Modell herunterladen"), frage,
                                       QMessageBox.StandardButton.Yes
                                       | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
        if antwort != QMessageBox.StandardButton.Yes:
            return
        anzeige = QProgressDialog(_("Modell wird heruntergeladen …"), _("Abbrechen"), 0, 100,
                                  self)
        anzeige.setWindowTitle(self.fenster.windowTitle())
        anzeige.setWindowModality(Qt.WindowModality.WindowModal)
        anzeige.setMinimumDuration(0)

        def fortschritt(geladen, gesamt):
            anzeige.setValue(round(100 * geladen / max(gesamt, 1)))
            QApplication.processEvents()
            return not anzeige.wasCanceled()

        try:
            ki.herunterladen(modell, fortschritt)
        except ki.KiAbbruch:
            self.fenster.melden(_("Herunterladen abgebrochen."))
            return
        except ki.KiFehler as fehler:
            self._fehler(_("Das Modell ließ sich nicht herunterladen."), str(fehler))
            return
        finally:
            anzeige.close()
            self._ki_anzeigen()
            self._ki_bild_anzeigen()
        self.fenster.melden(_("KI-Modell geladen: {ordner}").format(ordner=ziel))

    def _ki_auftrag(self, faktor: int | None = None):
        """(Hochskalierer, Faktor, Kachel) fuer den Export - oder None, wenn KI aus ist.
        faktor: statt des Faktors der Karte (fuers Drucken)."""
        if faktor is None:
            faktor = self.ki_faktor.currentData()
        if not faktor:
            return None
        modell, stufe = self._ki_modell(), self._ki_stufe()
        if not ki.angeboten(modell, stufe):
            raise ki.KiFehler(_("Dieses Modell braucht mindestens Funktionsstufe {stufe}.")
                              .format(stufe=modell.mindeststufe))
        entrauschen = self.ki_entrauschen.wert() / 100
        schluessel = (modell.schluessel, entrauschen)
        if self._ki_hochskalierer is None or self._ki_hochskalierer[0] != schluessel:
            self._ki_hochskalierer = None             # das alte Modell zuerst freigeben
            kachel = ki.kachelgroesse(modell, stufe)
            self._ki_hochskalierer = (schluessel, self._ki_laden(
                modell, kachel, lambda **art: ki.Hochskalierer(modell, entrauschen,
                                                               kachel=kachel, **art)))
        return self._ki_hochskalierer[1], faktor, ki.kachelgroesse(modell, stufe)

    def _ki_laden(self, modell: ki.Modell, kachel: int, anlegen):
        """Netz anlegen - anlegen(**art) baut Hochskalierer oder Entrauscher. Muss
        TensorRT erst eine Engine bauen, laeuft das in einem eigenen Prozess, und
        ein Fenster sagt, warum es dauert."""
        if not ki.tensorrt_baut(modell, kachel):
            return anlegen()
        anzeige = QProgressDialog("", "", 0, 0, self)
        hinweis = QLabel(_(
            "TensorRT bereitet das Modell einmalig für diese Grafikkarte vor – das dauert "
            "einige Minuten. Danach rechnet die KI rund doppelt so schnell."))
        hinweis.setWordWrap(True)
        hinweis.setMinimumWidth(420)
        anzeige.setLabel(hinweis)
        anzeige.setCancelButton(None)             # der Bau laesst sich nicht unterbrechen
        anzeige.setWindowTitle(self.fenster.windowTitle())
        anzeige.setWindowModality(Qt.WindowModality.WindowModal)
        anzeige.setMinimumDuration(0)
        anzeige.show()
        zukunft = ki.tensorrt_vorbereiten(modell, kachel)
        while not zukunft.done():
            QApplication.processEvents()
            wait([zukunft], timeout=0.05)
        anzeige.close()
        try:
            zukunft.result()
        except Exception:                        # dann eben ohne TensorRT
            self.fenster.melden(_("TensorRT ließ sich nicht vorbereiten – die KI rechnet "
                                  "mit CUDA."), fehler=True)
            return anlegen(tensorrt=False)
        return anlegen()

    # ------------------------------------------------------------------
    # KI-Entrauschen und KI-Schaerfen: einmal rechnen, dann Staerkeregler
    # ------------------------------------------------------------------

    def _ki_bild_art(self, gruppe: str) -> dict:
        """Alles, worin sich die Karten KI-Entrauschen, KI-Schaerfen und KI-Kolorieren
        unterscheiden."""
        offen = self.sitzung is not None
        if gruppe == "ki_farbe":
            return {
                "modell": ki.FARB_MODELLE["ddcolor"], "netz": ki.Kolorierer, "tensorrt": False,
                "rechnen": self.sitzung.ki_kolorieren if offen else None,
                "fertig": offen and self.sitzung.ki_koloriert,
                "fertig_text": _("Für dieses Bild berechnet. Der Regler mischt zwischen "
                                 "Original und kolorierter Fassung; Weißabgleich, Sättigung "
                                 "und Farbbereiche wirken danach wie gewohnt."),
                "offen_text": _("Für Schwarzweiß- und Sepiabilder: Die KI schätzt die Farben "
                                "aus der Helligkeit – glaubwürdig, aber geraten. Rechnet in "
                                "unter einer Sekunde."),
                "knopf": _("Kolorieren berechnen"),
                "laeuft": _("KI koloriert das Bild …"),
                "abgebrochen": _("KI-Kolorieren abgebrochen."),
                "fehlgeschlagen": _("Das KI-Kolorieren ist fehlgeschlagen."),
                "geschafft": _("KI-Kolorieren fertig ({s} s, über {weg})"),
            }
        if gruppe == "ki_rauschen":
            return {
                "modell": ki.ENTRAUSCH_MODELLE["scunet"], "netz": ki.Entrauscher,
                "rechnen": self.sitzung.ki_entrauschen if offen else None,
                "fertig": offen and self.sitzung.ki_entrauscht,
                "fertig_text": _("Für dieses Bild berechnet. Der Regler mischt zwischen "
                                 "Original und entrauschtem Bild."),
                "offen_text": _("Rechnet einmal über das ganze Bild – bei 24 Megapixeln 10 "
                                "bis 30 Sekunden. Danach wirkt der Regler sofort."),
                "knopf": _("Entrauschen berechnen"),
                "laeuft": _("KI entrauscht das Bild …"),
                "abgebrochen": _("KI-Entrauschen abgebrochen."),
                "fehlgeschlagen": _("Das KI-Entrauschen ist fehlgeschlagen."),
                "geschafft": _("KI-Entrauschen fertig ({s} s, über {weg})"),
            }
        return {
            "modell": ki.SCHAERF_MODELLE["restormer"], "netz": ki.Schaerfer,
            "rechnen": self.sitzung.ki_schaerfen if offen else None,
            "fertig": offen and self.sitzung.ki_geschaerft,
            "fertig_text": _("Für dieses Bild berechnet. Der Regler bestimmt, wie stark "
                             "die Schärfung wirkt."),
            "offen_text": _("Gegen leichte Fokus-Unschärfe. Rechnet einmal über das ganze "
                            "Bild – bei 24 Megapixeln {zeit}. Erst entrauschen, sonst "
                            "schärft die KI das Rauschen mit."),
            "knopf": _("Schärfen berechnen"),
            "laeuft": _("KI schärft das Bild …"),
            "abgebrochen": _("KI-Schärfen abgebrochen."),
            "fehlgeschlagen": _("Das KI-Schärfen ist fehlgeschlagen."),
            "geschafft": _("KI-Schärfen fertig ({s} s, über {weg})"),
        }

    def _ki_bild_bedienung(self, gruppe: str, innen: QVBoxLayout):
        hinweis = QLabel(objectName="nebentext")
        hinweis.setWordWrap(True)
        innen.addWidget(hinweis)
        knopf = QPushButton()
        knopf.clicked.connect(lambda: self._ki_bild_knopf_gedrueckt(gruppe))
        innen.addWidget(knopf)
        self._ki_bild_teile[gruppe] = (hinweis, knopf)

    def _ki_bild_anzeigen(self):
        """Hinweis, Knopf und Staerkeregler der Karten KI-Entrauschen und KI-Schaerfen."""
        stufe = self._ki_stufe()
        offen = self.sitzung is not None
        for gruppe, (hinweis, knopf) in self._ki_bild_teile.items():
            art = self._ki_bild_art(gruppe)
            modell, fertig = art["modell"], art["fertig"]
            beschriftung = None
            if not ki.angeboten(modell, stufe):
                text = _("KI-Funktionen brauchen mindestens 4 GB Grafikspeicher.")
            elif not ki.vorhanden(modell):
                text = _("Dieses Modell ist noch nicht geladen.")
                beschriftung = _("Modell herunterladen ({mb} MB)").format(
                    mb=f"{ki.download_groesse(modell) / 2**20:.0f}")
            elif fertig:
                text = art["fertig_text"]
            else:
                text = art["offen_text"].format(zeit=self._ki_schaerf_dauer())
                beschriftung = art["knopf"]
            self.fenster.beschriften(hinweis.setText, text)
            knopf.setVisible(beschriftung is not None)
            if beschriftung is not None:
                self.fenster.beschriften(knopf.setText, beschriftung)
                self._modell_tooltip(knopf, modell, _(
                    "Berechnet das Ergebnis einmal für das ganze Bild; mit „Stärke“ lässt "
                    "es sich danach stufenlos einblenden."))
                knopf.setEnabled(offen or not ki.vorhanden(modell))
            self.zeilen[gruppe].schieber.setEnabled(fertig)
        self._masken_anzeigen()
        self._entfernen_anzeigen()
        self._tiefe_anzeigen()
        self._erweitern_anzeigen()

    def _ki_schaerf_dauer(self) -> str:
        if ki.tensorrt_ordner() is not None:
            return _("knapp eine Minute")
        return _("etwa drei Minuten")

    def _ki_bild_knopf_gedrueckt(self, gruppe: str):
        modell = self._ki_bild_art(gruppe)["modell"]
        if not ki.vorhanden(modell):
            self.ki_modell_laden(modell)
        else:
            self.ki_bild_berechnen(gruppe)

    def ki_bild_berechnen(self, gruppe: str) -> bool:
        """Das ganze Bild einmal mit KI entrauschen oder schaerfen - mit Fortschritt und
        Abbrechen. Rueckgabe: ob es fertig wurde."""
        if self.sitzung is None:
            return False
        art = self._ki_bild_art(gruppe)
        modell = art["modell"]
        kachel = ki.kachelgroesse(modell, self._ki_stufe())
        anzeige = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if art.get("tensorrt", True):
                netz = self._ki_laden(
                    modell, kachel, lambda **weg: art["netz"](modell, kachel=kachel, **weg))
            else:
                netz = art["netz"](modell)
            anzeige = QProgressDialog(art["laeuft"], _("Abbrechen"), 0, 100, self)
            anzeige.setWindowTitle(self.fenster.windowTitle())
            anzeige.setWindowModality(Qt.WindowModality.WindowModal)
            anzeige.setMinimumDuration(0)

            def fortschritt(nummer, anzahl):
                anzeige.setValue(round(100 * nummer / anzahl))
                QApplication.processEvents()
                return not anzeige.wasCanceled()

            ms = art["rechnen"](netz, kachel, fortschritt)
            weg = netz.beschleuniger
            del netz                             # Grafikspeicher fuer die Bearbeitung frei
        except ki.KiAbbruch:
            self.fenster.melden(art["abgebrochen"])
            return False
        except ki.KiFehler as fehler:
            self._fehler(art["fehlgeschlagen"], str(fehler))
            return False
        except cp.cuda.memory.OutOfMemoryError:
            self._fehler(_("Für dieses Bild reicht der Grafikspeicher nicht."), "")
            return False
        finally:
            QApplication.restoreOverrideCursor()
            if anzeige is not None:
                anzeige.close()
            cp.get_default_memory_pool().free_all_blocks()
            self._ki_bild_anzeigen()
        self.fenster.melden(art["geschafft"].format(s=f"{ms / 1000:.1f}", weg=weg))
        # Eine Staerke aus der Begleitdatei bleibt; sonst wirkt das Ergebnis erst einmal ganz
        staerke = getattr(self.sitzung.werte, gruppe) or 100.0
        self.zeilen[gruppe].setzen(staerke)
        self.wert_geaendert(gruppe, staerke)
        return True

    # ------------------------------------------------------------------
    # Motiv & Hintergrund: Maske mit KI, eigene Werte fuer den Hintergrund
    # ------------------------------------------------------------------

    def _masken_bedienung(self, innen: QVBoxLayout):
        self.masken_hinweis = QLabel(objectName="nebentext")
        self.masken_hinweis.setWordWrap(True)
        innen.addWidget(self.masken_hinweis)
        self.masken_knopf = QPushButton()
        self.masken_knopf.clicked.connect(self._masken_knopf_gedrueckt)
        innen.addWidget(self.masken_knopf)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.auswahl_knopf = QPushButton()
        self.auswahl_knopf.setCheckable(True)
        self.auswahl_knopf.toggled.connect(self._auswahl_knopf_gedrueckt)
        self.auswahl_zurueck_knopf = self._knopf(_("Klick zurück"), self.klick_zuruecknehmen,
                                                 "kanal")
        self.fenster.beschriften(self.auswahl_zurueck_knopf.setToolTip,
                                 _("Den letzten Klick zurücknehmen (Strg+Z)"))
        leiste.addWidget(self.auswahl_knopf, 1)
        leiste.addWidget(self.auswahl_zurueck_knopf)
        innen.addLayout(leiste)
        self.maske_zeigen_box = QCheckBox()
        self.fenster.beschriften(self.maske_zeigen_box.setText, _("Maske zeigen"))
        self.fenster.beschriften(self.maske_zeigen_box.setToolTip, _(
            "Färbt den Hintergrund in der Vorschau rot ein – nur zur Kontrolle, nicht "
            "im gespeicherten Bild."))
        self.maske_zeigen_box.toggled.connect(lambda _an: self.zeichnen_anfordern())
        self.maske_umkehren_box = QCheckBox()
        self.fenster.beschriften(self.maske_umkehren_box.setText, _("Umkehren"))
        self.fenster.beschriften(self.maske_umkehren_box.setToolTip, _(
            "Die Regler dieser Karte wirken auf das Motiv statt auf den Hintergrund."))
        self.maske_umkehren_box.toggled.connect(
            lambda an: self.wert_geaendert("maske_umkehren", an))
        leiste = QHBoxLayout()
        leiste.addWidget(self.maske_zeigen_box)
        leiste.addWidget(self.maske_umkehren_box)
        leiste.addStretch(1)
        innen.addLayout(leiste)
        self.freistellen_box = QCheckBox()
        self.fenster.beschriften(self.freistellen_box.setText,
                                 _("Hintergrund durchsichtig speichern"))
        self.fenster.beschriften(self.freistellen_box.setToolTip, _(
            "Beim Speichern als PNG oder TIFF wird der Hintergrund transparent."))
        self.freistellen_box.toggled.connect(lambda an: self.wert_geaendert("freistellen", an))
        innen.addWidget(self.freistellen_box)

    def _masken_modell(self) -> ki.Modell:
        return ki.MASKEN_MODELLE["birefnet"]

    def _auswahl_modell(self) -> ki.Modell:
        return ki.AUSWAHL_MODELLE["sam2"]

    def _masken_anzeigen(self):
        """Hinweis, Knopf, Schalter und Regler der Karte Motiv & Hintergrund."""
        if not hasattr(self, "masken_knopf"):
            return
        modell, stufe = self._masken_modell(), self._ki_stufe()
        sam = self._auswahl_modell()
        offen = self.sitzung is not None
        fertig = offen and self.sitzung.ki_maske_da
        per_klick = fertig and self.sitzung.maske_per_klick
        klicken = self._klick_ziel == "maske"
        knopf = None
        if klicken:
            text = _("Linksklick ins Bild nimmt einen Bereich dazu, Rechtsklick nimmt einen "
                     "weg. Strg+Z nimmt den letzten Klick zurück, Esc beendet.")
        elif not ki.angeboten(sam, stufe):
            text = _("KI-Funktionen brauchen mindestens 4 GB Grafikspeicher.")
        elif per_klick:
            text = _("Objekt ausgewählt. Die Regler wirken auf alles andere.")
        elif fertig:
            text = _("Motiv erkannt. Die Regler wirken auf den Hintergrund.")
        else:
            text = _("Die KI erkennt das Motiv – bei 24 Megapixeln in wenigen Sekunden – "
                     "oder wählt aus, was man anklickt. Danach lässt sich der Hintergrund "
                     "getrennt bearbeiten oder durchsichtig speichern.")
            if not ki.angeboten(modell, stufe):
                text += " " + _("Das Erkennen ohne Klick braucht 6 GB Grafikspeicher.")
        if not klicken and ki.angeboten(modell, stufe) and (not fertig or per_klick):
            if not ki.vorhanden(modell):
                knopf = _("Motiv erkennen · {mb} MB").format(
                    mb=f"{ki.download_groesse(modell) / 2**20:.0f}")
            else:
                knopf = _("Motiv erkennen")
        self.fenster.beschriften(self.masken_hinweis.setText, text)
        self.masken_knopf.setVisible(knopf is not None)
        if knopf is not None:
            self.fenster.beschriften(self.masken_knopf.setText, knopf)
            self._modell_tooltip(self.masken_knopf, modell, _(
                "Die KI erkennt das Hauptmotiv – die Regler dieser Karte wirken dann auf den "
                "Hintergrund."))
            self.masken_knopf.setEnabled(offen or not ki.vorhanden(modell))
        self.auswahl_knopf.setVisible(ki.angeboten(sam, stufe))
        self.fenster.beschriften(
            self.auswahl_knopf.setText, _("Objekt anklicken") if ki.vorhanden(sam) else
            _("Objekt anklicken · {mb} MB").format(
                mb=f"{ki.download_groesse(sam) / 2**20:.0f}"))
        self._modell_tooltip(self.auswahl_knopf, sam, _(
            "Ein Objekt im Bild per Klick auswählen – die Regler dieser Karte wirken dann "
            "auf alles andere."))
        self.auswahl_knopf.setEnabled(offen or not ki.vorhanden(sam))
        if self.auswahl_knopf.isChecked() != klicken:
            self.auswahl_knopf.blockSignals(True)
            self.auswahl_knopf.setChecked(klicken)
            self.auswahl_knopf.blockSignals(False)
        self.auswahl_zurueck_knopf.setVisible(klicken)
        self.auswahl_zurueck_knopf.setEnabled(klicken and bool(self.sitzung.klicks))
        for box in (self.maske_zeigen_box, self.maske_umkehren_box, self.freistellen_box):
            box.setEnabled(fertig)
        werte = self.sitzung.werte if offen else filter.Einstellungen()
        for box, an in ((self.maske_umkehren_box, werte.maske_umkehren),
                        (self.freistellen_box, werte.freistellen)):
            if box.isChecked() != an:
                box.blockSignals(True)
                box.setChecked(an)
                box.blockSignals(False)
        for regler in filter.REGLER:
            if regler.gruppe == "maske":
                self.zeilen[regler.name].schieber.setEnabled(fertig)

    def _masken_knopf_gedrueckt(self):
        modell = self._masken_modell()
        if not ki.vorhanden(modell):
            self.ki_modell_laden(modell)
        else:
            self.maske_berechnen()

    def maske_berechnen(self):
        """Die Maske des Motivs einmal mit KI berechnen."""
        if self.sitzung is None:
            return
        self.auswahl_beenden()
        modell = self._masken_modell()
        kachel = modell.kacheln[modell.mindeststufe]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            netz = self._ki_laden(modell, kachel,
                                  lambda **weg: ki.Freisteller(modell, **weg))
            ms = self.sitzung.ki_freistellen(netz)
            self._klick_marken["maske"] = []
            weg = netz.beschleuniger
            del netz                             # Grafikspeicher fuer die Bearbeitung frei
        except ki.KiFehler as fehler:
            self._fehler(_("Das Motiv ließ sich nicht erkennen."), str(fehler))
            return
        except cp.cuda.memory.OutOfMemoryError:
            self._fehler(_("Für dieses Bild reicht der Grafikspeicher nicht."), "")
            return
        finally:
            QApplication.restoreOverrideCursor()
            cp.get_default_memory_pool().free_all_blocks()
            self._masken_anzeigen()
        self.fenster.melden(_("Motiv erkannt ({s} s, über {weg})").format(
            s=f"{ms / 1000:.1f}", weg=weg))
        self.zeichnen_anfordern()

    def _sam_klickt(self) -> bool:
        """Waehlt SAM gerade per Klick aus? Fokus und Pipette brauchen kein Netz."""
        return self._klick_ziel in ("maske", "entfernen")

    def _klick_knoepfe(self) -> dict:
        return {"maske": self.auswahl_knopf, "entfernen": self.entfern_klick_knopf}

    def _auswahl_knopf_gedrueckt(self, an: bool, ziel: str = "maske"):
        sam = self._auswahl_modell()
        if an and not ki.vorhanden(sam):
            knopf = self._klick_knoepfe()[ziel]
            knopf.blockSignals(True)
            knopf.setChecked(False)
            knopf.blockSignals(False)
            self.ki_modell_laden(sam)
        elif an:
            self.auswahl_beginnen(ziel)
        elif self._klick_ziel == ziel:
            self.auswahl_beenden()

    def auswahl_beginnen(self, ziel: str = "maske"):
        """Klickmodus: SAM sieht das Bild einmal, danach waehlt jeder Klick aus - fuer die
        Maske des Motivs oder fuer die Markierung zum Entfernen."""
        if self.sitzung is None:
            return
        self.zuschneiden(False)
        self.pinsel_beenden()
        if self._klick_ziel is not None and self._klick_ziel != ziel:
            self.auswahl_beenden()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self._auswaehler is None:
                self._auswaehler = ki.Auswaehler(self._auswahl_modell())
            ms = self.sitzung.ki_auswahl_beginnen(self._auswaehler, ziel)
        except (ki.KiFehler, cp.cuda.memory.OutOfMemoryError) as fehler:
            self._auswaehler = None
            text = str(fehler) if isinstance(fehler, ki.KiFehler) else _(
                "Für dieses Bild reicht der Grafikspeicher nicht.")
            self._fehler(_("Die Auswahl per Klick ließ sich nicht starten."), text)
            return
        finally:
            QApplication.restoreOverrideCursor()
            cp.get_default_memory_pool().free_all_blocks()
            self._masken_anzeigen()
            self._entfernen_anzeigen()
        if not self.sitzung.klicks_von(ziel):
            self._klick_marken[ziel] = []
        self._klick_ziel = ziel
        self.leinwand.klickmodus_setzen(True)
        if ziel == "maske":
            # Die Maskenansicht zeigt sofort, was ausgewaehlt ist
            self._maske_zeigen_vorher = self.maske_zeigen_box.isChecked()
            self.maske_zeigen_box.setChecked(True)
        self.fenster.melden(_("Bereit zum Klicken ({s} s)").format(s=f"{ms / 1000:.1f}"))
        self._masken_anzeigen()
        self._entfernen_anzeigen()
        self.zeichnen_anfordern()

    def auswahl_beenden(self):
        """Klickmodus verlassen; die Auswahl bleibt, SAM gibt den Grafikspeicher frei."""
        if self._klick_ziel is None:
            return
        ziel, self._klick_ziel = self._klick_ziel, None
        self._auswaehler = None
        cp.get_default_memory_pool().free_all_blocks()
        self.leinwand.klickmodus_setzen(False)
        if ziel == "maske":
            self.maske_zeigen_box.setChecked(self._maske_zeigen_vorher)
        self._masken_anzeigen()
        self._entfernen_anzeigen()
        self._tiefe_anzeigen()
        self._film_anzeigen()
        self._erweitern_anzeigen()
        self.zeichnen_anfordern()

    def _bild_geklickt(self, x: float, y: float, dazu: bool):
        ziel = self._klick_ziel
        if ziel is None or self.sitzung is None or self._vorher:
            return
        quelle = self.sitzung.quelle_von(x, y)
        if quelle is None:
            return
        if ziel == "film":
            self._film_setzen(self.sitzung.werte.film, *self.sitzung.film_maske_messen(*quelle))
            self.auswahl_beenden()               # ein Klick genuegt
            return
        if ziel == "fokus":
            wert = round(self.sitzung.tiefe_an(*quelle))
            self.zeilen["fokus"].setzen(wert)
            self.wert_geaendert("fokus", float(wert))
            self.auswahl_beenden()               # ein Klick genuegt
            return
        try:
            ms = self.sitzung.ki_klick(self._auswaehler, *quelle, dazu, ziel)
        except (ki.KiFehler, cp.cuda.memory.OutOfMemoryError) as fehler:
            self._fehler(_("Die Auswahl ist fehlgeschlagen."), str(fehler))
            return
        self._klick_marken[ziel].append((x, y, dazu))
        self._klick_geo[ziel] = geometrie.aus(self.sitzung.werte)
        self.fenster.rechenzeit_zeigen(ms)
        self._masken_anzeigen()
        self._entfernen_anzeigen()
        self.zeichnen_anfordern()

    def klick_zuruecknehmen(self):
        ziel = self._klick_ziel
        if not self._sam_klickt() or self.sitzung is None:
            return
        if self.sitzung.ki_klick_zurueck(self._auswaehler, ziel):
            del self._klick_marken[ziel][-1:]
            self._masken_anzeigen()
            self._entfernen_anzeigen()
            self.zeichnen_anfordern()

    # ------------------------------------------------------------------
    # Scan & Film: Negative umwandeln
    # ------------------------------------------------------------------

    def _film_karte(self) -> QFrame:
        karte, innen = self._karte(_("Scan & Film"))
        self.film_hinweis = QLabel(objectName="nebentext")
        self.film_hinweis.setWordWrap(True)
        innen.addWidget(self.film_hinweis)
        gitter = QGridLayout()
        gitter.setColumnStretch(1, 1)
        beschriftung = QLabel()
        self.fenster.beschriften(beschriftung.setText, _("Film"))
        self.film_art = QComboBox()
        self._eintrag(self.film_art, _("Kein Film"), "")
        self._eintrag(self.film_art, _("Farbnegativ"), "farbnegativ")
        self._eintrag(self.film_art, _("Schwarzweiß-Negativ"), "sw_negativ")
        self._eintrag(self.film_art, _("Dia"), "dia")
        self.fenster.beschriften(self.film_art.setToolTip, _(
            "Ein Negativ wird ins Positiv gewandelt – über die Dichte des Films, wie im "
            "Labor. Filmmaske sowie Schwarz- und Weißpunkt schätzt Silberkorn dabei selbst."))
        self.film_art.currentIndexChanged.connect(self._film_art_gewaehlt)
        gitter.addWidget(beschriftung, 0, 0)
        gitter.addWidget(self.film_art, 0, 1)
        innen.addLayout(gitter)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.film_pipette_knopf = QPushButton()
        self.film_pipette_knopf.setCheckable(True)
        self.fenster.beschriften(self.film_pipette_knopf.setText, _("Filmmaske anklicken"))
        self.fenster.beschriften(self.film_pipette_knopf.setToolTip, _(
            "Ein Klick auf unbelichteten Film – den Rand oder den Steg zwischen zwei Bildern "
            "– misst die Farbe der Filmmaske genau."))
        self.film_pipette_knopf.toggled.connect(self._film_pipette_gedrueckt)
        self.film_auto_knopf = self._knopf(_("Automatisch"), self.film_automatisch)
        self.fenster.beschriften(self.film_auto_knopf.setToolTip, _(
            "Schätzt Filmmaske, Schwarz- und Weißpunkt neu aus dem Bild – etwa nach einem "
            "Klick mit der Pipette."))
        leiste.addWidget(self.film_pipette_knopf, 1)
        leiste.addWidget(self.film_auto_knopf, 1)
        innen.addLayout(leiste)
        innen.addWidget(self._staub_bedienung())
        self.trennen_knopf = self._knopf(_("Fotos trennen …"), self.fotos_trennen)
        self.fenster.beschriften(self.trennen_knopf.setToolTip, _(
            "Sucht auf einem Flachbett-Scan die einzelnen Abzüge, richtet sie gerade aus, "
            "beschneidet sie auf ihren Rand und speichert jeden als eigene Datei."))
        innen.addWidget(self.trennen_knopf)
        return karte

    def _staub_bedienung(self) -> QWidget:
        """Staub und Kratzer ueber den Infrarotkanal - nur sichtbar, wenn der Scan einen hat."""
        self.staub_teil = QWidget()
        innen = QVBoxLayout(self.staub_teil)
        innen.setContentsMargins(0, 8, 0, 0)
        self.staub_hinweis = QLabel(objectName="nebentext")
        self.staub_hinweis.setWordWrap(True)
        innen.addWidget(self.staub_hinweis)
        gitter = QGridLayout()
        gitter.setColumnStretch(1, 1)
        beschriftung = QLabel()
        self.fenster.beschriften(beschriftung.setText, _("Empfindlichkeit"))
        self.staub_regler = QSlider(Qt.Orientation.Horizontal)
        self.staub_regler.setRange(0, 100)
        self.staub_regler.setValue(staub.EMPFINDLICHKEIT)
        self.fenster.beschriften(self.staub_regler.setToolTip, _(
            "Wie schwach eine Stelle im Infrarot sein darf, um als Staub zu gelten. Mehr "
            "findet auch feine Fusseln, kann aber Bildteile erfassen."))
        self.staub_regler.valueChanged.connect(lambda _w: self._staub_uhr.start())
        gitter.addWidget(beschriftung, 0, 0)
        gitter.addWidget(self.staub_regler, 0, 1)
        innen.addLayout(gitter)
        self.staub_zeigen_box = QCheckBox()
        self.fenster.beschriften(self.staub_zeigen_box.setText, _("Fundstellen zeigen"))
        self.fenster.beschriften(self.staub_zeigen_box.setToolTip, _(
            "Färbt in der Vorschau blau, was als Staub oder Kratzer gefunden ist."))
        self.staub_zeigen_box.toggled.connect(lambda _an: self._staub_suchen())
        innen.addWidget(self.staub_zeigen_box)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.staub_knopf = self._knopf(_("Staub entfernen"), self.staub_entfernen)
        self.fenster.beschriften(self.staub_knopf.setToolTip, _(
            "Füllt alle Fundstellen: kleine Punkte und dünne Kratzer die Grafikkarte, breite "
            "Stellen LaMa, wenn das Modell von „Objekte entfernen“ geladen ist."))
        self.staub_weg_knopf = self._knopf(_("Zurückholen"), self.staub_zurueckholen)
        self.fenster.beschriften(self.staub_weg_knopf.setToolTip,
                                 _("Nimmt das Füllen von Staub und Kratzern zurück."))
        leiste.addWidget(self.staub_knopf, 1)
        leiste.addWidget(self.staub_weg_knopf, 1)
        innen.addLayout(leiste)
        # Am Regler wird erst gesucht, wenn er kurz ruht
        self._staub_uhr = QTimer(self, singleShot=True, interval=STAUB_PAUSE_MS)
        self._staub_uhr.timeout.connect(self._staub_suchen)
        return self.staub_teil

    def _staub_anzeigen(self):
        if not hasattr(self, "staub_teil"):
            return
        offen = self.sitzung is not None
        da = offen and self.sitzung.infrarot_da
        self.staub_teil.setVisible(da)
        if not da:
            return
        if not self.sitzung.infrarot_film:
            text = _("Der Infrarotkanal zeigt das Motiv selbst, nicht den Film – etwa bei "
                     "Luftbildern. Staub lässt sich daraus nicht erkennen.")
        elif self.sitzung.staub_entfernt:
            text = _("{n} Stellen gefüllt. Ändert sich die Empfindlichkeit, füllt „Staub "
                     "entfernen“ neu.").format(n=self.sitzung.staub_gefuellt)
        elif self.sitzung.staub_fund is not None and self.staub_zeigen_box.isChecked():
            text = _("{n} Stellen gefunden.").format(n=self.sitzung.staub_fund[1])
        elif self.sitzung.werte.film == "sw_negativ":
            text = _("Bei Schwarzweißfilm hält das Silber selbst Infrarot auf – dann findet "
                     "die Suche oft das Bild statt Staub. Mit „Fundstellen zeigen“ prüfen.")
        else:
            text = _("Der Scan hat einen Infrarotkanal: Staub und Kratzer sind darin dunkel "
                     "und lassen sich finden und füllen.")
        self.fenster.beschriften(self.staub_hinweis.setText, text)
        nutzbar = self.sitzung.infrarot_film
        for widget in (self.staub_regler, self.staub_zeigen_box, self.staub_knopf):
            widget.setEnabled(nutzbar)
        self.staub_weg_knopf.setEnabled(self.sitzung.staub_entfernt)

    def _staub_suchen(self):
        """Fundstellen fuer die Empfindlichkeit des Reglers - nur, wenn sie gezeigt werden."""
        if self.sitzung is None or not self.sitzung.infrarot_film:
            return
        zeigen = self.staub_zeigen_box.isChecked()
        fund = self.sitzung.staub_fund
        if zeigen and (fund is None or fund[0] != self.staub_regler.value()):
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.sitzung.staub_finden(self.staub_regler.value())
            except cp.cuda.memory.OutOfMemoryError:
                self._fehler(_("Für dieses Bild reicht der Grafikspeicher nicht."), "")
                return
            finally:
                QApplication.restoreOverrideCursor()
        self.sitzung.staub_zeigen = zeigen
        self.sitzung.vollbild_vergessen()
        self._staub_anzeigen()
        self.zeichnen_anfordern()

    def staub_entfernen(self):
        """Staub und Kratzer fuellen - breite Stellen mit LaMa, wenn es geladen ist."""
        if self.sitzung is None or not self.sitzung.infrarot_film:
            return
        lama = self._entfern_modell()
        mit_ki = ki.vorhanden(lama) and ki.angeboten(lama, self._ki_stufe())
        anzeige = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            entferner = None
            if mit_ki:
                if self._entferner is None:
                    self._entferner = ki.Entferner(lama, ki.kachelgroesse(lama,
                                                                         self._ki_stufe()))
                entferner = self._entferner
                anzeige = QProgressDialog(_("Staub wird entfernt …"), _("Abbrechen"), 0, 100,
                                          self)
                anzeige.setWindowTitle(self.fenster.windowTitle())
                anzeige.setWindowModality(Qt.WindowModality.WindowModal)
                anzeige.setMinimumDuration(500)

            def fortschritt(nummer, anzahl):
                if anzeige is None:
                    return True
                anzeige.setValue(round(100 * nummer / anzahl))
                QApplication.processEvents()
                return not anzeige.wasCanceled()

            ms = self.sitzung.staub_entfernen(self.staub_regler.value(), entferner, fortschritt)
        except (ki.KiFehler, cp.cuda.memory.OutOfMemoryError) as fehler:
            text = str(fehler) if isinstance(fehler, ki.KiFehler) else _(
                "Für dieses Bild reicht der Grafikspeicher nicht.")
            self._fehler(_("Das Entfernen ist fehlgeschlagen."), text)
            return
        finally:
            if anzeige is not None:
                anzeige.close()
            QApplication.restoreOverrideCursor()
            cp.get_default_memory_pool().free_all_blocks()
        self.staub_zeigen_box.setChecked(False)       # zeigt sonst, was schon gefuellt ist
        self._staub_anzeigen()
        self.fenster.melden(_("Staub entfernt ({s} s)").format(s=f"{ms / 1000:.1f}"))
        self.zeichnen_anfordern()

    def fotos_trennen(self):
        """Die Fotos auf einem Flachbett-Scan finden, als eigene Dateien speichern und eines
        davon zum Bearbeiten oeffnen."""
        if self.sitzung is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            fotos = self.sitzung.fotos_finden()
            vorschauen = [self.sitzung.foto_vorschau(foto) for foto in fotos]
        finally:
            QApplication.restoreOverrideCursor()
        if not fotos:
            self.fenster.melden(_("Auf diesem Scan sind keine einzelnen Fotos zu erkennen."),
                                fehler=True)
            return
        dialog = TrennenDialog(self, vorschauen, self.sitzung.daten.pfad)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        ordner = dialog.ordner()
        # Nur ein Dateiname, kein Pfad - und ohne Zeichen, die Windows verbietet
        name = "".join(z for z in os.path.basename(dialog.name()) if z not in VERBOTEN)
        name = name.strip(" .") or os.path.splitext(self.sitzung.daten.name)[0]
        if not os.path.isdir(ordner):
            self._fehler(_("Die Fotos ließen sich nicht speichern."),
                         _("Den Ordner gibt es nicht: {ordner}").format(ordner=ordner))
            return
        gewaehlt = dialog.gewaehlt()
        endung = dialog.endung()
        bits = 16 if self.sitzung.daten.bits == 16 and bilddatei.SCHREIBBAR[endung][2] else 8
        pfade = trennen.dateinamen(ordner, name, endung, len(gewaehlt))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.sitzung.fotos_speichern([fotos[i] for i in gewaehlt], pfade, bits)
        except (bilddatei.BildFehler, OSError, cp.cuda.memory.OutOfMemoryError) as fehler:
            self._fehler(_("Die Fotos ließen sich nicht speichern."), str(fehler))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.fenster.melden(_("{n} Fotos gespeichert in {ordner}").format(
            n=len(pfade), ordner=ordner))
        oeffnen = dialog.danach_oeffnen()
        if oeffnen is not None:
            self.oeffnen(pfade[gewaehlt.index(oeffnen)])

    def staub_zurueckholen(self):
        if self.sitzung is None or not self.sitzung.staub_verwerfen():
            return
        self._staub_anzeigen()
        self.zeichnen_anfordern()

    def _film_anzeigen(self):
        if not hasattr(self, "film_hinweis"):
            return
        offen = self.sitzung is not None
        werte = self.sitzung.werte if offen else filter.Einstellungen()
        messen = self._klick_ziel == "film"
        if messen:
            text = _("Auf unbelichteten Film klicken – den Rand oder den Steg zwischen zwei "
                     "Bildern. Esc bricht ab.")
        elif film.ist_negativ(werte.film):
            text = _("Umgewandelt. Weißabgleich, Licht und Kurven wirken danach wie gewohnt. "
                     "Ist der Filmrand mitgescannt, misst die Pipette die Maske genauer.")
        elif werte.film == "dia":
            text = _("Dias sind schon positiv und werden nicht umgewandelt.")
        else:
            text = _("Wandelt gescannte oder abfotografierte Negative ins Positiv – am besten "
                     "als ersten Schritt, vor den KI-Karten.")
        self.fenster.beschriften(self.film_hinweis.setText, text)
        self._staub_anzeigen()
        nummer = self.film_art.findData(werte.film)
        if nummer >= 0 and nummer != self.film_art.currentIndex():
            self.film_art.blockSignals(True)
            self.film_art.setCurrentIndex(nummer)
            self.film_art.blockSignals(False)
        negativ = offen and film.ist_negativ(werte.film)
        self.film_art.setEnabled(offen)
        self.trennen_knopf.setEnabled(offen)
        self.film_pipette_knopf.setEnabled(negativ)
        self.film_auto_knopf.setEnabled(negativ)
        if self.film_pipette_knopf.isChecked() != messen:
            self.film_pipette_knopf.blockSignals(True)
            self.film_pipette_knopf.setChecked(messen)
            self.film_pipette_knopf.blockSignals(False)

    def _film_setzen(self, art: str, maske: tuple, umfang: tuple):
        werte = self.sitzung.werte
        werte.film, werte.film_maske, werte.film_umfang = art, maske, umfang
        self._film_anzeigen()
        self.zeichnen_anfordern()

    def _film_art_gewaehlt(self, *_args):
        if self.sitzung is None:
            return
        art = self.film_art.currentData()
        werte = self.sitzung.werte
        if not film.ist_negativ(art):
            if self._klick_ziel == "film":
                self.auswahl_beenden()
            self._film_setzen(art, (), ())
        elif film.aktiv(werte.film, werte.film_maske, werte.film_umfang):
            self._film_setzen(art, werte.film_maske, werte.film_umfang)  # nur die Filmart
        else:
            self._film_setzen(art, *self.sitzung.film_schaetzen(art))

    def film_automatisch(self):
        """Filmmaske und Umfang neu aus dem Bild schaetzen."""
        if self.sitzung is None or not film.ist_negativ(self.sitzung.werte.film):
            return
        art = self.sitzung.werte.film
        self._film_setzen(art, *self.sitzung.film_schaetzen(art))

    def _film_pipette_gedrueckt(self, an: bool):
        if not an:
            if self._klick_ziel == "film":
                self.auswahl_beenden()
            return
        if self.sitzung is None or not film.ist_negativ(self.sitzung.werte.film):
            return
        self.zuschneiden(False)
        self.pinsel_beenden()
        self.auswahl_beenden()
        self._klick_ziel = "film"
        self.leinwand.klickmodus_setzen(True)
        self._film_anzeigen()

    # ------------------------------------------------------------------
    # Objekte entfernen: markieren per Klick oder Pinsel, fuellen mit LaMa
    # ------------------------------------------------------------------

    def _entfern_karte(self) -> QFrame:
        karte, innen = self._karte(_("Objekte entfernen"))
        self.entfern_hinweis = QLabel(objectName="nebentext")
        self.entfern_hinweis.setWordWrap(True)
        innen.addWidget(self.entfern_hinweis)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.entfern_klick_knopf = QPushButton()
        self.entfern_klick_knopf.setCheckable(True)
        self.entfern_klick_knopf.toggled.connect(
            lambda an: self._auswahl_knopf_gedrueckt(an, "entfernen"))
        self.pinsel_knopf = QPushButton()
        self.pinsel_knopf.setCheckable(True)
        self.fenster.beschriften(self.pinsel_knopf.setText, _("Pinsel"))
        self.fenster.beschriften(self.pinsel_knopf.setToolTip, _(
            "Kleinigkeiten übermalen, etwa Flecken oder Leitungen – die rechte Maustaste "
            "radiert."))
        self.pinsel_knopf.toggled.connect(self._pinsel_knopf_gedrueckt)
        self.entfern_klick_zurueck_knopf = self._knopf(_("Klick zurück"),
                                                       self.klick_zuruecknehmen, "kanal")
        leiste.addWidget(self.entfern_klick_knopf, 1)
        leiste.addWidget(self.pinsel_knopf, 1)
        leiste.addWidget(self.entfern_klick_zurueck_knopf)
        innen.addLayout(leiste)
        self.pinsel_zeile = QWidget()
        zeile = QHBoxLayout(self.pinsel_zeile)
        zeile.setContentsMargins(0, 0, 0, 0)
        groesse = QLabel()
        self.fenster.beschriften(groesse.setText, _("Pinselgröße"))
        self.pinsel_groesse = QSlider(Qt.Orientation.Horizontal)
        self.pinsel_groesse.setRange(3, 150)
        self.pinsel_groesse.setValue(20)
        self.pinsel_groesse.valueChanged.connect(self._pinsel_groesse_geaendert)
        zeile.addWidget(groesse)
        zeile.addWidget(self.pinsel_groesse, 1)
        innen.addWidget(self.pinsel_zeile)
        self.entfernen_knopf = self._knopf("", self.entfernen, "hauptschalter")
        innen.addWidget(self.entfernen_knopf)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.markierung_weg_knopf = self._knopf(_("Markierung löschen"),
                                                self.markierung_verwerfen)
        self.fenster.beschriften(self.markierung_weg_knopf.setToolTip,
                                 _("Die blaue Markierung verwerfen, ohne etwas zu entfernen."))
        self.entfernung_zurueck_knopf = self._knopf(_("Zurücknehmen"),
                                                    self.entfernung_zuruecknehmen)
        self.fenster.beschriften(self.entfernung_zurueck_knopf.setToolTip,
                                 _("Letzte Entfernung zurücknehmen"))
        leiste.addWidget(self.markierung_weg_knopf, 1)
        leiste.addWidget(self.entfernung_zurueck_knopf, 1)
        innen.addLayout(leiste)
        return karte

    # ------------------------------------------------------------------
    # Anonymisieren: Flaechen verpixeln, Gesichter finden, Metadaten
    # ------------------------------------------------------------------

    def _anonym_karte(self) -> QFrame:
        karte, innen = self._karte(_("Anonymisieren"))
        self.anonym_hinweis = QLabel(objectName="nebentext")
        self.anonym_hinweis.setWordWrap(True)
        innen.addWidget(self.anonym_hinweis)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.gesichter_knopf = self._knopf(_("Gesichter finden"), self.gesichter_finden)
        self.fenster.beschriften(self.gesichter_knopf.setToolTip, _(
            "Legt um jedes erkannte Gesicht eine Fläche. Prüfen und nachbessern – sehr "
            "kleine, verdeckte oder seitliche Gesichter können fehlen."))
        self.flaechen_knopf = QPushButton()
        self.flaechen_knopf.setCheckable(True)
        self.fenster.beschriften(self.flaechen_knopf.setText, _("Flächen bearbeiten"))
        self.fenster.beschriften(self.flaechen_knopf.setToolTip, _(
            "Auf freiem Grund ziehen legt eine Fläche an; Flächen verschieben, an den Ecken "
            "die Größe ändern, Entf löscht die gewählte."))
        self.flaechen_knopf.toggled.connect(
            lambda an: self.flaechen_beginnen() if an else self.flaechen_beenden())
        leiste.addWidget(self.gesichter_knopf, 1)
        leiste.addWidget(self.flaechen_knopf, 1)
        innen.addLayout(leiste)

        gitter = QGridLayout()
        gitter.setColumnStretch(1, 1)
        gitter.setVerticalSpacing(4)
        beschriftung = QLabel()
        self.fenster.beschriften(beschriftung.setText, _("Form"))
        self.anonym_form = QComboBox()
        self._eintrag(self.anonym_form, _("Ellipse"), "ellipse")
        self._eintrag(self.anonym_form, _("Rechteck"), "rechteck")
        self.anonym_form.currentIndexChanged.connect(self._anonym_form_gewaehlt)
        gitter.addWidget(beschriftung, 0, 0)
        gitter.addWidget(self.anonym_form, 0, 1)
        beschriftung = QLabel()
        self.fenster.beschriften(beschriftung.setText, _("Wirkung"))
        self.anonym_art = QComboBox()
        self._eintrag(self.anonym_art, _("Mosaik"), "mosaik")
        self._eintrag(self.anonym_art, _("Weichzeichnen"), "weich")
        self._eintrag(self.anonym_art, _("Schwarz füllen"), "fuellen")
        self.anonym_art.currentIndexChanged.connect(self._anonym_art_gewaehlt)
        gitter.addWidget(beschriftung, 1, 0)
        gitter.addWidget(self.anonym_art, 1, 1)
        self.anonym_bloecke_text = QLabel()
        self.fenster.beschriften(self.anonym_bloecke_text.setText, _("Raster"))
        self.anonym_bloecke = QSlider(Qt.Orientation.Horizontal)
        self.anonym_bloecke.setRange(int(anonym.BLOECKE_MIN), int(anonym.BLOECKE_MAX))
        self.anonym_bloecke.setValue(int(anonym.BLOECKE))
        self.fenster.beschriften(self.anonym_bloecke.setToolTip, _(
            "Blöcke über die Breite einer Fläche. Weniger ist sicherer: feine Mosaike "
            "lassen sich teilweise zurückrechnen."))
        self.anonym_bloecke.valueChanged.connect(self._anonym_bloecke_geaendert)
        gitter.addWidget(self.anonym_bloecke_text, 2, 0)
        gitter.addWidget(self.anonym_bloecke, 2, 1)
        innen.addLayout(gitter)

        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.flaeche_weg_knopf = self._knopf(_("Fläche löschen"), self.flaeche_loeschen)
        self.flaechen_weg_knopf = self._knopf(_("Alle löschen"), self.flaechen_loeschen)
        leiste.addWidget(self.flaeche_weg_knopf, 1)
        leiste.addWidget(self.flaechen_weg_knopf, 1)
        innen.addLayout(leiste)
        self.metadaten_box = QCheckBox()
        self.fenster.beschriften(self.metadaten_box.setText,
                                 _("Ohne GPS und Seriennummern speichern"))
        self.fenster.beschriften(self.metadaten_box.setToolTip, _(
            "Nimmt beim Speichern GPS-Position, Seriennummern von Kamera und Objektiv, den "
            "Besitzernamen und die Herstellerdaten aus den Metadaten."))
        self.metadaten_box.toggled.connect(self._metadaten_umgeschaltet)
        innen.addWidget(self.metadaten_box)

        self.leinwand.flaeche_gezogen.connect(self._flaeche_gezogen)
        self.leinwand.flaeche_loeschen.connect(self.flaeche_loeschen)
        self._flaeche_start = None            # Flaechen beim Beginn des Ziehens
        self._gesichtsfinder: anonym.Gesichtsfinder | None = None
        return karte

    def _anonym_anzeigen(self):
        if not hasattr(self, "anonym_hinweis"):
            return
        offen = self.sitzung is not None
        flaechen = self.sitzung.werte.anonym_flaechen if offen else ()
        bearbeiten = self.leinwand.flaechenmodus
        gewaehlt = self.leinwand.flaeche_gewaehlt
        if bearbeiten:
            text = _("Auf freiem Grund ziehen legt eine Fläche an. Flächen verschieben, an "
                     "den Ecken die Größe ändern; Entf löscht, Esc beendet.")
        elif flaechen:
            text = _("{n} Flächen. Das Mosaik wird beim Speichern fest ins Bild "
                     "gerechnet.").format(n=len(flaechen))
        else:
            text = _("Gesichter, Kennzeichen oder Hausnummern unkenntlich machen.")
        self.fenster.beschriften(self.anonym_hinweis.setText, text)
        for widget in (self.gesichter_knopf, self.flaechen_knopf, self.anonym_form,
                       self.anonym_art, self.anonym_bloecke, self.metadaten_box):
            widget.setEnabled(offen)
        if self.flaechen_knopf.isChecked() != bearbeiten:
            self.flaechen_knopf.blockSignals(True)
            self.flaechen_knopf.setChecked(bearbeiten)
            self.flaechen_knopf.blockSignals(False)
        self.flaeche_weg_knopf.setEnabled(bearbeiten and gewaehlt is not None)
        self.flaechen_weg_knopf.setEnabled(bool(flaechen))
        werte = self.sitzung.werte if offen else filter.Einstellungen()
        for auswahl, wert in ((self.anonym_art, werte.anonym_art),
                              (self.anonym_form, self._flaechen_form())):
            nummer = auswahl.findData(wert)
            if nummer >= 0 and nummer != auswahl.currentIndex():
                auswahl.blockSignals(True)
                auswahl.setCurrentIndex(nummer)
                auswahl.blockSignals(False)
        for widget, wert in ((self.anonym_bloecke, int(round(werte.anonym_bloecke))),
                             (self.metadaten_box, werte.metadaten_entfernen)):
            widget.blockSignals(True)
            if isinstance(widget, QCheckBox):
                widget.setChecked(wert)
            else:
                widget.setValue(wert)
            widget.blockSignals(False)
        self.anonym_bloecke.setEnabled(offen and werte.anonym_art != "fuellen")
        self.fenster.beschriften(self.anonym_bloecke_text.setText,
                                 _("Stärke") if werte.anonym_art == "weich" else _("Raster"))

    def _flaechen_form(self) -> str:
        """Form der gewaehlten Flaeche, sonst die zuletzt gewaehlte fuer neue."""
        gewaehlt = self.leinwand.flaeche_gewaehlt
        if self.sitzung is not None and gewaehlt is not None \
                and gewaehlt < len(self.sitzung.werte.anonym_flaechen):
            return self.sitzung.werte.anonym_flaechen[gewaehlt][0]
        return self._neue_form

    _neue_form = "ellipse"

    def _umrisse_setzen(self):
        """Umrisse und Griffe der Flaechen fuer die Leinwand - im fertigen Bild, also
        nach Drehen, Begradigen und Zuschnitt."""
        if self.sitzung is None or not self.leinwand.flaechenmodus:
            return
        flaechen = self.sitzung.werte.anonym_flaechen
        hoehe, breite = self.sitzung.original.shape[:2]
        teile, laengen = [], []
        t = np.linspace(0, 1, 9)[:-1]
        winkel = np.linspace(0, 2 * np.pi, 49)[:-1]
        for form, x0, y0, x1, y1 in flaechen:
            ecken = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
            if form == "ellipse":
                umriss = np.stack([(x0 + x1) / 2 + (x1 - x0) / 2 * np.cos(winkel),
                                   (y0 + y1) / 2 + (y1 - y0) / 2 * np.sin(winkel)], axis=1)
            else:
                # Kanten in Stuecken - verzeichnet sind sie im Bild gebogen
                umriss = np.concatenate([a + (b - a) * t[:, None]
                                         for a, b in zip(ecken, np.roll(ecken, -1, axis=0),
                                                         strict=True)])
            teile += [umriss, ecken]
            laengen += [len(umriss), 4]
        if teile:
            punkte = np.concatenate(teile) * (breite, hoehe)
            im_bild = self.sitzung.ziel_von(punkte)
            stuecke = np.split(im_bild, np.cumsum(laengen)[:-1])
        else:
            stuecke = []
        self.leinwand.flaechen_umrisse = stuecke[0::2]
        self.leinwand.flaechen_ecken = stuecke[1::2]
        if self.leinwand.flaeche_gewaehlt is not None \
                and self.leinwand.flaeche_gewaehlt >= len(flaechen):
            self.leinwand.flaeche_gewaehlt = None
        self.leinwand.update()

    def flaechen_beginnen(self):
        if self.sitzung is None:
            self._anonym_anzeigen()
            return
        self.zuschneiden(False)
        self.auswahl_beenden()
        self.pinsel_beenden()                    # beendet auch einen alten Flaechenmodus
        self.leinwand.flaechenmodus_setzen(True)
        self._umrisse_setzen()
        self._anonym_anzeigen()

    def flaechen_beenden(self):
        if not self.leinwand.flaechenmodus:
            self._anonym_anzeigen()
            return
        self.leinwand.flaechenmodus_setzen(False)
        self._anonym_anzeigen()

    def _flaechen_setzen(self, flaechen, gewaehlt: int | None = None):
        werte = self.sitzung.werte
        if flaechen and not werte.anonym_flaechen and not werte.metadaten_entfernen:
            # Wer anonymisiert, will meist auch den Standort nicht weitergeben
            werte.metadaten_entfernen = True
            self.fenster.melden(_("Standort und Seriennummern werden nicht mitgespeichert."))
        werte.anonym_flaechen = tuple(flaechen)
        self.leinwand.flaeche_gewaehlt = gewaehlt
        self._umrisse_setzen()
        self._anonym_anzeigen()
        self.zeichnen_anfordern()

    def gesichter_finden(self):
        if self.sitzung is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self._gesichtsfinder is None:
                self._gesichtsfinder = anonym.Gesichtsfinder()
            neu = self.sitzung.gesichter_finden(self._gesichtsfinder, self._neue_form)
        except Exception as fehler:              # ORT wirft eigene Fehlerklassen
            QApplication.restoreOverrideCursor()
            self._fehler(_("Die Gesichtserkennung ist fehlgeschlagen."), str(fehler))
            return
        QApplication.restoreOverrideCursor()
        alt = list(self.sitzung.werte.anonym_flaechen)
        # Schon abgedeckte Gesichter nicht doppelt anlegen
        dazu = [f for f in neu if not any(_ueberlappung(f, a) > 0.5 for a in alt)]
        if not neu:
            self.fenster.melden(_("Keine Gesichter gefunden – Flächen von Hand aufziehen."))
        else:
            self.fenster.melden(_("{n} Gesichter gefunden – bitte prüfen und "
                                  "nachbessern.").format(n=len(neu)))
        self.flaechen_beginnen()
        if dazu:
            self._flaechen_setzen(alt + dazu)

    def _flaeche_gezogen(self, art: str, nummer: int, sx: float, sy: float, x: float, y: float,
                         fertig: bool):
        if self.sitzung is None or self._vorher:
            return
        flaechen = list(self.sitzung.werte.anonym_flaechen)
        if self._flaeche_start is None:
            self._flaeche_start = (art, nummer, tuple(flaechen))
        _art, _nummer, vorher = self._flaeche_start
        if fertig:
            self._flaeche_start = None
        hoehe, breite = self.sitzung.original.shape[:2]
        a = self.sitzung.quelle_von(sx, sy, begrenzt=False)
        b = self.sitzung.quelle_von(x, y, begrenzt=False)
        ax, ay, bx, by = a[0] / breite, a[1] / hoehe, b[0] / breite, b[1] / hoehe
        flaechen = list(vorher)
        if art == "neu":
            flaeche = anonym.flaeche_begrenzen((self._neue_form, ax, ay, bx, by))
            if flaeche is None:
                # Nur geklickt (oder zu klein): Auswahl aufheben
                self._flaechen_setzen(vorher, None)
                return
            self._flaechen_setzen([*flaechen, flaeche], len(flaechen))
            return
        form, x0, y0, x1, y1 = flaechen[nummer]
        if art == "innen":
            dx = min(max(bx - ax, -x0), 1 - x1)
            dy = min(max(by - ay, -y0), 1 - y1)
            flaeche = (form, x0 + dx, y0 + dy, x1 + dx, y1 + dy)
        else:
            ecke = int(art[-1])
            # Die gezogene Ecke folgt der Maus, die gegenueberliegende bleibt
            x0, x1 = (bx, x1) if ecke in (0, 3) else (x0, bx)
            y0, y1 = (by, y1) if ecke in (0, 1) else (y0, by)
            flaeche = anonym.flaeche_begrenzen((form, x0, y0, x1, y1)) or flaechen[nummer]
        flaechen[nummer] = flaeche
        self._flaechen_setzen(flaechen, nummer)

    def flaeche_loeschen(self, nummer: int | None = None):
        if self.sitzung is None:
            return
        if not isinstance(nummer, int) or isinstance(nummer, bool):
            nummer = self.leinwand.flaeche_gewaehlt
        flaechen = list(self.sitzung.werte.anonym_flaechen)
        if nummer is None or not 0 <= nummer < len(flaechen):
            return
        del flaechen[nummer]
        self._flaechen_setzen(flaechen, None)

    def flaechen_loeschen(self):
        if self.sitzung is not None:
            self._flaechen_setzen((), None)

    def _anonym_form_gewaehlt(self, *_args):
        form = self.anonym_form.currentData()
        self._neue_form = form
        gewaehlt = self.leinwand.flaeche_gewaehlt
        if self.sitzung is None or gewaehlt is None:
            return
        flaechen = list(self.sitzung.werte.anonym_flaechen)
        if gewaehlt < len(flaechen):
            flaechen[gewaehlt] = (form, *flaechen[gewaehlt][1:])
            self._flaechen_setzen(flaechen, gewaehlt)

    def _anonym_art_gewaehlt(self, *_args):
        if self.sitzung is not None:
            self.sitzung.werte.anonym_art = self.anonym_art.currentData()
            self._anonym_anzeigen()
            self.zeichnen_anfordern()

    def _anonym_bloecke_geaendert(self, wert: int):
        if self.sitzung is not None:
            self.sitzung.werte.anonym_bloecke = float(wert)
            self.zeichnen_anfordern()

    def _metadaten_umgeschaltet(self, an: bool):
        if self.sitzung is not None:
            self.sitzung.werte.metadaten_entfernen = an
            self._aenderung_merken()

    # ------------------------------------------------------------------
    # Metadaten: Titel, Urheber, Ort ... - geschrieben erst beim Speichern
    # ------------------------------------------------------------------

    def _metadaten_karte(self) -> QFrame:
        karte, innen = self._karte(_("Metadaten"))
        self.metadaten_hinweis = QLabel(objectName="nebentext")
        self.metadaten_hinweis.setWordWrap(True)
        innen.addWidget(self.metadaten_hinweis)
        self.metadaten_ueberblick = QLabel(objectName="nebentext")
        self.metadaten_ueberblick.setWordWrap(True)
        self.metadaten_ueberblick.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        innen.addWidget(self.metadaten_ueberblick)

        gitter = QGridLayout()
        gitter.setColumnStretch(1, 1)
        gitter.setVerticalSpacing(4)
        self._angaben_fuellen = False         # Felder werden gerade aus der Sitzung gesetzt
        self.angaben_felder: dict[str, QLineEdit | QPlainTextEdit] = {}
        zeilen = [("titel", _("Titel"), None),
                  ("beschreibung", _("Beschreibung"), None),
                  ("stichwoerter", _("Stichwörter"), _("durch Komma getrennt")),
                  ("urheber", _("Urheber"), None),
                  ("copyright", _("Copyright"), _("etwa © 2026 Name")),
                  ("stadt", _("Stadt"), None),
                  ("region", _("Region"), _("Bundesland, Kanton …")),
                  ("land", _("Land"), None),
                  ("datum", _("Datum"), _("2024-05-17 14:30, 17.05.2024 oder 1965"))]
        for nummer, (name, titel, platzhalter) in enumerate(zeilen):
            beschriftung = QLabel()
            self.fenster.beschriften(beschriftung.setText, titel)
            if name == "beschreibung":
                feld = QPlainTextEdit()
                feld.setTabChangesFocus(True)
                feld.setFixedHeight(feld.fontMetrics().lineSpacing() * 3 + 12)
                feld.textChanged.connect(lambda n=name: self._angabe_bearbeitet(n))
                gitter.addWidget(beschriftung, nummer, 0, Qt.AlignmentFlag.AlignTop)
            else:
                feld = QLineEdit()
                feld.textEdited.connect(lambda _text, n=name: self._angabe_bearbeitet(n))
                gitter.addWidget(beschriftung, nummer, 0)
            if platzhalter:
                self.fenster.beschriften(feld.setPlaceholderText, platzhalter)
            gitter.addWidget(feld, nummer, 1)
            self.angaben_felder[name] = feld
        self.angaben_felder["datum"].editingFinished.connect(self._datum_fertig)
        self.fenster.beschriften(self.angaben_felder["stichwoerter"].setToolTip, _(
            "Mehrere Stichwörter durch Komma oder Semikolon trennen."))
        self.fenster.beschriften(self.angaben_felder["urheber"].setToolTip, _(
            "Mehrere Urheber durch Semikolon trennen."))
        self.fenster.beschriften(self.angaben_felder["datum"].setToolTip, _(
            "Aufnahmedatum. Bei alten Abzügen genügt das Jahr oder Jahr und Monat."))
        beschriftung = QLabel()
        self.fenster.beschriften(beschriftung.setText, _("Bewertung"))
        self.bewertung_wahl = QComboBox()
        self.bewertung_wahl.addItem("–", 0)
        for sterne in range(1, metadaten.BEWERTUNG_MAX + 1):
            self.bewertung_wahl.addItem("★" * sterne, sterne)
        self.bewertung_wahl.currentIndexChanged.connect(
            lambda *_args: self._angabe_bearbeitet("bewertung"))
        gitter.addWidget(beschriftung, len(zeilen), 0)
        gitter.addWidget(self.bewertung_wahl, len(zeilen), 1)
        innen.addLayout(gitter)

        self.vorgabe_box = QCheckBox()
        self.fenster.beschriften(self.vorgabe_box.setText,
                                 _("Urheber und Copyright in jedes Bild"))
        self.fenster.beschriften(self.vorgabe_box.setToolTip, _(
            "Merkt sich Urheber und Copyright von hier und trägt sie in jedes Bild ein, das "
            "selbst keine hat. Gespeichert wird beides wie alles andere erst mit dem Bild."))
        self.vorgabe_box.setChecked(bool(self._metadaten_vorgabe().get("an")))
        self.vorgabe_box.toggled.connect(self._vorgabe_umgeschaltet)
        innen.addWidget(self.vorgabe_box)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.alle_metadaten_knopf = self._knopf(_("Alle Metadaten …"), self.metadaten_zeigen)
        self.fenster.beschriften(self.alle_metadaten_knopf.setToolTip, _(
            "Zeigt alles, was die Datei an EXIF, GPS, IPTC und XMP enthält."))
        self.angaben_zurueck_knopf = self._knopf(_("Zurücksetzen"), self.angaben_zuruecksetzen)
        self.fenster.beschriften(self.angaben_zurueck_knopf.setToolTip, _(
            "Nimmt nur die Änderungen an den Metadaten zurück – Regler und Bild bleiben."))
        leiste.addWidget(self.alle_metadaten_knopf, 1)
        leiste.addWidget(self.angaben_zurueck_knopf, 1)
        innen.addLayout(leiste)
        return karte

    def _metadaten_anzeigen(self):
        if not hasattr(self, "angaben_felder"):
            return
        offen = self.sitzung is not None
        angaben = self.sitzung.angaben if offen else metadaten.Angaben()
        self._angaben_fuellen = True
        try:
            for name, feld in self.angaben_felder.items():
                wert = getattr(angaben, name)
                text = ", ".join(wert) if name == "stichwoerter" else str(wert)
                if isinstance(feld, QPlainTextEdit):
                    if feld.toPlainText() != text:
                        feld.setPlainText(text)
                elif feld.text() != text:
                    feld.setText(text)
                    feld.setCursorPosition(0)
                feld.setEnabled(offen)
            self._feld_markieren(self.angaben_felder["datum"], False)
            self.bewertung_wahl.setCurrentIndex(max(0, self.bewertung_wahl.findData(
                angaben.bewertung)))
        finally:
            self._angaben_fuellen = False
        self.bewertung_wahl.setEnabled(offen)
        self.alle_metadaten_knopf.setEnabled(offen)

        if not offen:
            self.fenster.beschriften(self.metadaten_hinweis.setText, _(
                "Titel, Beschreibung, Urheber, Ort und mehr – geschrieben beim Speichern."))
            self.metadaten_ueberblick.hide()
        else:
            formate = self.sitzung.vorgefunden.formate
            if formate:
                self.fenster.beschriften(self.metadaten_hinweis.setText, _(
                    "In der Datei: {formate}. Änderungen werden beim Speichern geschrieben.")
                    .format(formate=", ".join(formate)))
            else:
                self.fenster.beschriften(self.metadaten_hinweis.setText, _(
                    "Die Datei enthält keine Metadaten. Angaben hier werden beim Speichern "
                    "geschrieben."))
            ueberblick = metadaten.ueberblick(self.sitzung.daten.exif)
            self.metadaten_ueberblick.setText("<br>".join(
                escape(text) for text in ueberblick.values()))
            self.metadaten_ueberblick.setVisible(bool(ueberblick))
        self._angaben_knoepfe()

    def _angaben_knoepfe(self):
        self.angaben_zurueck_knopf.setEnabled(
            self.sitzung is not None
            and self.sitzung.werte.angaben != self.sitzung.angaben_grundwerte())

    def _feld_markieren(self, feld: QLineEdit, ungueltig: bool):
        if bool(feld.property("ungueltig")) != ungueltig:
            feld.setProperty("ungueltig", ungueltig)
            feld.style().unpolish(feld)
            feld.style().polish(feld)

    def _angabe_bearbeitet(self, name: str):
        if self.sitzung is None or self._angaben_fuellen:
            return
        feld = self.angaben_felder.get(name)
        if name == "beschreibung":
            wert = feld.toPlainText().strip()
        elif name == "stichwoerter":
            wert = metadaten.stichwoerter_lesen(feld.text())
        elif name == "datum":
            wert = metadaten.datum_lesen(feld.text())
            self._feld_markieren(feld, wert is None)
            if wert is None:
                return                        # erst uebernehmen, wenn es ein Datum ist
        elif name == "bewertung":
            wert = self.bewertung_wahl.currentData()
        else:
            wert = feld.text().strip()
        self.sitzung.angabe_setzen(name, wert)
        if name in ("urheber", "copyright") and self.vorgabe_box.isChecked():
            self._vorgabe_speichern()
        self._angaben_knoepfe()
        self._aenderung_merken()

    def _datum_fertig(self):
        """Nach der Eingabe das Datum einheitlich zeigen - oder das gueltige zurueckholen."""
        if self.sitzung is None:
            return
        feld = self.angaben_felder["datum"]
        datum = self.sitzung.angaben.datum
        if metadaten.datum_lesen(feld.text()) is None:
            self.fenster.melden(_("Das Datum ist nicht lesbar – etwa 2024-05-17, 17.05.2024 "
                                  "oder nur 1965."), fehler=True)
        self._angaben_fuellen = True
        feld.setText(datum)
        self._angaben_fuellen = False
        self._feld_markieren(feld, False)

    def angaben_zuruecksetzen(self):
        # Der Knopf schaltet sich gleich selbst ab; Qt gaebe den Fokus sonst an das
        # naechste Element weiter und rollte die Reglerleiste dorthin
        if self.angaben_zurueck_knopf.hasFocus():
            self.alle_metadaten_knopf.setFocus(Qt.FocusReason.OtherFocusReason)
        if self.sitzung is not None:
            self.sitzung.werte.angaben = self.sitzung.angaben_grundwerte()
        self._metadaten_anzeigen()
        self._aenderung_merken()

    def metadaten_zeigen(self):
        if self.sitzung is not None:
            daten = self.sitzung.daten
            MetadatenDialog(self, daten.name, daten.exif, daten.xmp, daten.iptc).exec()

    def _metadaten_vorgabe(self) -> dict:
        vorgabe = einstellungen.load_config().get("metadaten_vorgabe")
        return vorgabe if isinstance(vorgabe, dict) else {}

    def _vorgabe_werte(self) -> tuple[str, str]:
        """Urheber und Copyright fuer jedes Bild - leer, wenn ausgeschaltet."""
        vorgabe = self._metadaten_vorgabe()
        if not vorgabe.get("an"):
            return "", ""
        return (str(vorgabe.get("urheber") or ""), str(vorgabe.get("copyright") or ""))

    def _vorgabe_speichern(self):
        daten = einstellungen.load_config()
        vorgabe = {"an": self.vorgabe_box.isChecked()}
        if self.sitzung is not None:
            angaben = self.sitzung.angaben
            vorgabe.update(urheber=angaben.urheber, copyright=angaben.copyright)
        else:
            alt = daten.get("metadaten_vorgabe")
            alt = alt if isinstance(alt, dict) else {}
            vorgabe.update(urheber=alt.get("urheber", ""), copyright=alt.get("copyright", ""))
        daten["metadaten_vorgabe"] = vorgabe
        einstellungen.save_config(daten)

    def _vorgabe_umgeschaltet(self, _an: bool):
        self._vorgabe_speichern()
        if self.sitzung is not None:
            self.sitzung.angaben_vorgeben(*self._vorgabe_werte())
        self._metadaten_anzeigen()
        self._aenderung_merken()

    def _entfern_modell(self) -> ki.Modell:
        return ki.ENTFERN_MODELLE["lama"]

    def _entfernen_anzeigen(self):
        if not hasattr(self, "entfernen_knopf"):
            return
        lama, sam, stufe = self._entfern_modell(), self._auswahl_modell(), self._ki_stufe()
        offen = self.sitzung is not None
        klicken = self._klick_ziel == "entfernen"
        malen = self.leinwand.pinselmodus
        markiert = offen and self.sitzung.markierung_da
        entfernt = self.sitzung.entfernt if offen else 0
        nutzbar = ki.angeboten(lama, stufe)
        if not nutzbar:
            text = _("KI-Funktionen brauchen mindestens 4 GB Grafikspeicher.")
        elif klicken:
            text = _("Linksklick markiert ein Objekt, Rechtsklick nimmt einen Bereich weg. "
                     "Strg+Z nimmt den letzten Klick zurück, Esc beendet.")
        elif malen:
            text = _("Mit der linken Maustaste übermalen, was weg soll; die rechte radiert. "
                     "Die mittlere verschiebt das vergrößerte Bild, Esc beendet.")
        elif markiert:
            text = _("Blau markiert ist, was verschwindet. „Entfernen“ füllt die Stelle mit "
                     "passendem Hintergrund.")
        else:
            text = _("Ein Objekt anklicken oder übermalen – die KI füllt die Stelle mit dem, "
                     "was dahinter liegen könnte.")
        if nutzbar and entfernt and not (klicken or malen):
            text += " " + _("Bisher entfernt: {n}.").format(n=entfernt)
        self.fenster.beschriften(self.entfern_hinweis.setText, text)
        for widget in (self.entfern_klick_knopf, self.pinsel_knopf, self.entfernen_knopf,
                       self.markierung_weg_knopf, self.entfernung_zurueck_knopf):
            widget.setVisible(nutzbar)
        self.entfern_klick_knopf.setVisible(nutzbar and ki.angeboten(sam, stufe))
        self.fenster.beschriften(
            self.entfern_klick_knopf.setText, _("Anklicken") if ki.vorhanden(sam) else
            _("Anklicken · {mb} MB").format(
                mb=f"{ki.download_groesse(sam) / 2**20:.0f}"))
        self._modell_tooltip(self.entfern_klick_knopf, sam, _(
            "Ein Objekt per Klick markieren – Rechtsklick nimmt einen Bereich wieder weg."))
        self.entfern_klick_knopf.setEnabled(offen or not ki.vorhanden(sam))
        self.pinsel_knopf.setEnabled(offen)
        for knopf, an in ((self.entfern_klick_knopf, klicken), (self.pinsel_knopf, malen)):
            if knopf.isChecked() != an:
                knopf.blockSignals(True)
                knopf.setChecked(an)
                knopf.blockSignals(False)
        self.entfern_klick_zurueck_knopf.setVisible(klicken)
        self.entfern_klick_zurueck_knopf.setEnabled(
            klicken and bool(self.sitzung.klicks_von("entfernen")))
        self.pinsel_zeile.setVisible(nutzbar and malen)
        if ki.vorhanden(lama):
            self.fenster.beschriften(self.entfernen_knopf.setText, _("Entfernen"))
            self.entfernen_knopf.setEnabled(markiert)
        else:
            self.fenster.beschriften(
                self.entfernen_knopf.setText, _("Entfernen · {mb} MB").format(
                    mb=f"{ki.download_groesse(lama) / 2**20:.0f}"))
            self.entfernen_knopf.setEnabled(True)
        self._modell_tooltip(self.entfernen_knopf, lama, _(
            "Füllt die blau markierte Stelle mit passendem Hintergrund."))
        # Blau als Hauptknopf nur, wenn wirklich etwas zum Entfernen markiert ist
        rolle = "hauptschalter" if markiert and ki.vorhanden(lama) else ""
        if self.entfernen_knopf.objectName() != rolle:
            self.entfernen_knopf.setObjectName(rolle)
            self.entfernen_knopf.style().unpolish(self.entfernen_knopf)
            self.entfernen_knopf.style().polish(self.entfernen_knopf)
        self.markierung_weg_knopf.setEnabled(markiert)
        self.entfernung_zurueck_knopf.setEnabled(entfernt > 0)

    def _pinsel_knopf_gedrueckt(self, an: bool):
        if an:
            self.pinsel_beginnen()
        else:
            self.pinsel_beenden()

    def pinsel_beginnen(self):
        if self.sitzung is None:
            return
        self.zuschneiden(False)
        self.auswahl_beenden()
        self.flaechen_beenden()
        self.lokal_beenden()
        self.leinwand.pinsel_radius = self.pinsel_groesse.value()
        self.leinwand.pinselmodus_setzen(True)
        self._entfernen_anzeigen()

    def pinsel_beenden(self):
        # Wer einen anderen Modus beginnt, beendet hiermit auch das Bearbeiten von Flaechen
        # und Masken
        self.flaechen_beenden()
        self.lokal_beenden()
        if not self.leinwand.pinselmodus:
            return
        self.leinwand.pinselmodus_setzen(False)
        self._entfernen_anzeigen()

    def _pinsel_groesse_geaendert(self, wert: int):
        self.leinwand.pinsel_radius = wert
        self.leinwand.update()

    def _pinsel_gezogen(self, x: float, y: float, dazu: bool, neu: bool):
        if self.sitzung is None or self._vorher:
            return
        quelle = self.sitzung.quelle_von(x, y)
        if quelle is None:
            self._pinsel_letzter = None
            return
        radius = self.pinsel_groesse.value() / self.leinwand.massstab()
        punkte = [quelle]
        if not neu and self._pinsel_letzter is not None:
            # Zwischen zwei Mausmeldungen lueckenlos stempeln
            (x0, y0), (x1, y1) = self._pinsel_letzter, quelle
            schritte = int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / max(radius / 2, 0.5))
            punkte = [(x0 + (x1 - x0) * i / (schritte + 1), y0 + (y1 - y0) * i / (schritte + 1))
                      for i in range(1, schritte + 2)]
        self._pinsel_letzter = quelle
        self.sitzung.pinseln(punkte, radius, dazu)
        if neu:
            self._entfernen_anzeigen()
        self.zeichnen_anfordern()

    def markierung_verwerfen(self):
        if self.sitzung is None:
            return
        self.sitzung.markierung_verwerfen()
        self._klick_marken["entfernen"] = []
        self._entfernen_anzeigen()
        self.zeichnen_anfordern()

    def entfernen(self):
        """Das Markierte mit LaMa entfernen."""
        lama = self._entfern_modell()
        if not ki.vorhanden(lama):
            self.ki_modell_laden(lama)
            return
        if self.sitzung is None or not self.sitzung.markierung_da:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self._entferner is None:
                self._entferner = ki.Entferner(lama, ki.kachelgroesse(lama, self._ki_stufe()))
            ms = self.sitzung.ki_entfernen(self._entferner)
            self._klick_marken["entfernen"] = []
            if self._sam_klickt():               # SAM soll das neue Bild sehen
                self.sitzung.ki_auswahl_beginnen(self._auswaehler, self._klick_ziel)
        except (ki.KiFehler, cp.cuda.memory.OutOfMemoryError) as fehler:
            text = str(fehler) if isinstance(fehler, ki.KiFehler) else _(
                "Für dieses Bild reicht der Grafikspeicher nicht.")
            self._fehler(_("Das Entfernen ist fehlgeschlagen."), text)
            return
        finally:
            QApplication.restoreOverrideCursor()
            cp.get_default_memory_pool().free_all_blocks()
            self._entfernen_anzeigen()
        if ms is not None:
            self.fenster.melden(_("Entfernt ({s} s)").format(s=f"{ms / 1000:.1f}"))
        self.zeichnen_anfordern()

    def entfernung_zuruecknehmen(self):
        if self.sitzung is None or not self.sitzung.entfernen_zurueck():
            return
        if self._sam_klickt():
            self.sitzung.ki_auswahl_beginnen(self._auswaehler, self._klick_ziel)
        self._entfernen_anzeigen()
        self.zeichnen_anfordern()

    # ------------------------------------------------------------------
    # Tiefe & Bokeh
    # ------------------------------------------------------------------

    def _tiefe_bedienung(self, innen: QVBoxLayout):
        self.tiefe_hinweis = QLabel(objectName="nebentext")
        self.tiefe_hinweis.setWordWrap(True)
        innen.addWidget(self.tiefe_hinweis)
        self.tiefe_knopf = QPushButton()
        self.tiefe_knopf.clicked.connect(self._tiefe_knopf_gedrueckt)
        innen.addWidget(self.tiefe_knopf)
        self.fokus_knopf = QPushButton()
        self.fokus_knopf.setCheckable(True)
        self.fenster.beschriften(self.fokus_knopf.setText, _("Fokus ins Bild klicken"))
        self.fenster.beschriften(self.fokus_knopf.setToolTip, _(
            "Ein Klick ins Bild stellt auf diese Entfernung scharf."))
        self.fokus_knopf.toggled.connect(self._fokus_knopf_gedrueckt)
        innen.addWidget(self.fokus_knopf)
        self.tiefe_zeigen_box = QCheckBox()
        self.fenster.beschriften(self.tiefe_zeigen_box.setText, _("Tiefenkarte zeigen"))
        self.fenster.beschriften(self.tiefe_zeigen_box.setToolTip, _(
            "Zeigt in der Vorschau die geschätzte Tiefe: hell ist nah, dunkel fern."))
        self.tiefe_zeigen_box.toggled.connect(lambda _an: self.zeichnen_anfordern())
        self.bokeh_motiv_box = QCheckBox()
        self.fenster.beschriften(self.bokeh_motiv_box.setText, _("Motiv scharf halten"))
        self.fenster.beschriften(self.bokeh_motiv_box.setToolTip, _(
            "Ist das Motiv erkannt oder angeklickt, bleibt es scharf, gleich wie tief es "
            "liegt."))
        self.bokeh_motiv_box.toggled.connect(lambda an: self.wert_geaendert("bokeh_motiv", an))
        leiste = QHBoxLayout()
        leiste.addWidget(self.tiefe_zeigen_box)
        leiste.addWidget(self.bokeh_motiv_box)
        leiste.addStretch(1)
        innen.addLayout(leiste)

    def _tiefe_modell(self) -> ki.Modell:
        return ki.TIEFEN_MODELLE["tiefe"]

    def _tiefe_anzeigen(self):
        if not hasattr(self, "tiefe_knopf"):
            return
        modell, stufe = self._tiefe_modell(), self._ki_stufe()
        offen = self.sitzung is not None
        fertig = offen and self.sitzung.ki_tiefe_da
        knopf = None
        if not ki.angeboten(modell, stufe):
            text = _("KI-Funktionen brauchen mindestens 4 GB Grafikspeicher.")
        elif not ki.vorhanden(modell):
            text = _("Dieses Modell ist noch nicht geladen.")
            knopf = _("Modell herunterladen ({mb} MB)").format(
                mb=f"{ki.download_groesse(modell) / 2**20:.0f}")
        elif fertig:
            text = _("Tiefe geschätzt. Die Unschärfe wächst mit dem Abstand zur "
                     "Fokusebene, nach vorn wie nach hinten.")
        else:
            text = _("Die KI schätzt, wie weit alles im Bild entfernt ist – in "
                     "Sekundenbruchteilen. Danach lässt sich der Hintergrund wie mit "
                     "einem lichtstarken Objektiv weichzeichnen.")
            knopf = _("Tiefe berechnen")
        self.fenster.beschriften(self.tiefe_hinweis.setText, text)
        self.tiefe_knopf.setVisible(knopf is not None)
        if knopf is not None:
            self.fenster.beschriften(self.tiefe_knopf.setText, knopf)
            self._modell_tooltip(self.tiefe_knopf, modell, _(
                "Schätzt die Tiefe des ganzen Bildes – danach wirken Unschärfe, Fokus und "
                "Schärfentiefe."))
            self.tiefe_knopf.setEnabled(offen or not ki.vorhanden(modell))
        fokussieren = self._klick_ziel == "fokus"
        self.fokus_knopf.setVisible(fertig)
        if self.fokus_knopf.isChecked() != fokussieren:
            self.fokus_knopf.blockSignals(True)
            self.fokus_knopf.setChecked(fokussieren)
            self.fokus_knopf.blockSignals(False)
        self.tiefe_zeigen_box.setEnabled(fertig)
        self.bokeh_motiv_box.setEnabled(fertig and self.sitzung.ki_maske_da)
        werte = self.sitzung.werte if offen else filter.Einstellungen()
        if self.bokeh_motiv_box.isChecked() != werte.bokeh_motiv:
            self.bokeh_motiv_box.blockSignals(True)
            self.bokeh_motiv_box.setChecked(werte.bokeh_motiv)
            self.bokeh_motiv_box.blockSignals(False)
        for regler in filter.REGLER:
            if regler.gruppe == "tiefe":
                self.zeilen[regler.name].schieber.setEnabled(fertig)

    def _tiefe_knopf_gedrueckt(self):
        modell = self._tiefe_modell()
        if not ki.vorhanden(modell):
            self.ki_modell_laden(modell)
        else:
            self.tiefe_berechnen()

    def tiefe_berechnen(self):
        """Die Tiefe einmal mit KI schaetzen, danach auf das Motiv scharf stellen."""
        if self.sitzung is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            netz = ki.Tiefenschaetzer(self._tiefe_modell())
            ms = self.sitzung.ki_tiefe(netz)
            del netz                             # Grafikspeicher fuer die Bearbeitung frei
        except (ki.KiFehler, cp.cuda.memory.OutOfMemoryError) as fehler:
            text = str(fehler) if isinstance(fehler, ki.KiFehler) else _(
                "Für dieses Bild reicht der Grafikspeicher nicht.")
            self._fehler(_("Die Tiefe ließ sich nicht schätzen."), text)
            return
        finally:
            QApplication.restoreOverrideCursor()
            cp.get_default_memory_pool().free_all_blocks()
            self._tiefe_anzeigen()
        fokus = round(self.sitzung.fokus_vorschlag())
        self.zeilen["fokus"].setzen(fokus)
        self.wert_geaendert("fokus", float(fokus))
        if self.sitzung.werte.bokeh == 0:
            self.zeilen["bokeh"].setzen(50)
            self.wert_geaendert("bokeh", 50.0)
        self.fenster.melden(_("Tiefe geschätzt ({s} s)").format(s=f"{ms / 1000:.1f}"))

    def _fokus_knopf_gedrueckt(self, an: bool):
        if not an:
            if self._klick_ziel == "fokus":
                self.auswahl_beenden()
            return
        if self.sitzung is None or not self.sitzung.ki_tiefe_da:
            return
        self.zuschneiden(False)
        self.pinsel_beenden()
        self.auswahl_beenden()
        self._klick_ziel = "fokus"
        self.leinwand.klickmodus_setzen(True)
        self._tiefe_anzeigen()

    def _hsl_karte(self) -> QFrame:
        karte, innen = self._karte(_("Farbbereiche"))
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.hsl_modus = filter.HSL[0]
        self._hsl_knoepfe: dict[str, QPushButton] = {}
        gruppe = QButtonGroup(karte)
        for name, text in zip(filter.HSL, (_("Farbton"), _("Sättigung"), _("Luminanz")),
                              strict=True):
            knopf = QPushButton(objectName="kanal")
            knopf.setCheckable(True)
            self.fenster.beschriften(knopf.setText, text)
            knopf.clicked.connect(lambda _an, n=name: self._hsl_modus_waehlen(n))
            gruppe.addButton(knopf)
            self._hsl_knoepfe[name] = knopf
            leiste.addWidget(knopf)
        self._hsl_knoepfe[self.hsl_modus].setChecked(True)
        leiste.addStretch(1)
        innen.addLayout(leiste)
        gitter = QGridLayout()
        gitter.setVerticalSpacing(2)
        gitter.setColumnStretch(0, 1)
        innen.addLayout(gitter)
        self.hsl_zeilen = [ReglerZeile(self, regler, gitter, 2 * i)
                           for i, regler in enumerate(HSL_REGLER)]
        return karte

    def _hsl_modus_waehlen(self, modus: str):
        self.hsl_modus = modus
        self._hsl_anzeigen()

    def _hsl_anzeigen(self):
        werte = (getattr(self.sitzung.werte, self.hsl_modus) if self.sitzung is not None
                 else filter.HSL_NEUTRAL)
        for zeile, wert in zip(self.hsl_zeilen, werte, strict=True):
            zeile.setzen(wert)

    def _sw_karte(self) -> QFrame:
        """Schwarzweiss mit Mischer je Farbbereich, darunter die Teiltonung."""
        karte, innen = self._karte(_("Schwarzweiß & Tönung"))
        self.sw_box = QCheckBox()
        self.fenster.beschriften(self.sw_box.setText, _("In Schwarzweiß umwandeln"))
        self.fenster.beschriften(self.sw_box.setToolTip, _(
            "Die Regler darunter bestimmen, wie hell jede Farbe als Grau wird – wie ein "
            "Farbfilter vor dem Objektiv bei Schwarzweißfilm."))
        self.sw_box.toggled.connect(lambda an: self.wert_geaendert("sw", an))
        innen.addWidget(self.sw_box)
        self.sw_filter_wahl = QComboBox()
        self.fenster.beschriften(self.sw_filter_wahl.setPlaceholderText, _("Eigene Mischung"))
        self.fenster.beschriften(self.sw_filter_wahl.setToolTip, _(
            "Mischung wie ein klassischer Farbfilter: Rot und Orange dunkeln den Himmel ab, "
            "Grün hellt Laub auf."))
        self._eintrag(self.sw_filter_wahl, _("Ohne Filter"), "")
        for name in filter.SW_FILTER:
            self._eintrag(self.sw_filter_wahl, sw_filter_titel(name), name)
        self.sw_filter_wahl.activated.connect(self._sw_filter_gewaehlt)
        innen.addWidget(self.sw_filter_wahl)
        gitter = QGridLayout()
        gitter.setVerticalSpacing(2)
        gitter.setColumnStretch(0, 1)
        innen.addLayout(gitter)
        self.sw_zeilen = [ReglerZeile(self, regler, gitter, 2 * i)
                          for i, regler in enumerate(SW_REGLER)]

        titel = QLabel(objectName="kartentitel")
        self.fenster.beschriften(titel.setText, _("Teiltonung"))
        innen.addSpacing(8)
        innen.addWidget(titel)
        self.ton_vorlage_wahl = QComboBox()
        self.fenster.beschriften(self.ton_vorlage_wahl.setPlaceholderText, _("Eigene Tönung"))
        self.fenster.beschriften(self.ton_vorlage_wahl.setToolTip, _(
            "Lichter und Schatten getrennt einfärben – auf Schwarzweiß wie im Labor getönt, "
            "auf Farbbildern als Farblook."))
        self._eintrag(self.ton_vorlage_wahl, _("Ohne Tönung"), "")
        for name in filter.TONUNG_VORLAGEN:
            self._eintrag(self.ton_vorlage_wahl, tonung_titel(name), name)
        self.ton_vorlage_wahl.activated.connect(self._ton_vorlage_gewaehlt)
        innen.addWidget(self.ton_vorlage_wahl)
        gitter = QGridLayout()
        gitter.setVerticalSpacing(2)
        gitter.setColumnStretch(0, 1)
        innen.addLayout(gitter)
        for nummer, name in enumerate(filter.TONUNG):
            art = FarbtonZeile if name.endswith("_farbton") else ReglerZeile
            self.zeilen[name] = art(self, filter.REGLER_NACH_NAME[name], gitter, 2 * nummer)
        return karte

    # ------------------------------------------------------------------
    # Lokale Anpassungen (lokal.py): Masken aus Verlauf und Radial
    # ------------------------------------------------------------------

    def _lokal_karte(self) -> QFrame:
        karte, innen = self._karte(_("Lokale Anpassungen"))
        self._lokal_maske: int | None = None      # gewaehlte Maske
        self._lokal_teil: int | None = None       # gewaehlter Teil der Maske
        self._lokal_start = None                  # Masken beim Beginn eines Zugs
        self._lokal_sitzung = None                # fuer welche Sitzung die Wahl gilt
        self._lokal_baut = False                  # Listen werden gerade neu gefuellt
        self._lokal_pinsel_neu = False            # der naechste Strich beginnt einen Teil
        self._malen = {r.name: r.vorgabe for r in MALEN_REGLER}
        hinweis = QLabel(objectName="nebentext")
        hinweis.setWordWrap(True)
        self.fenster.beschriften(hinweis.setText, _(
            "Regler nur für einen Bereich: eine neue Maske wählen und im Bild aufziehen."))
        innen.addWidget(hinweis)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        beschriftung = QLabel()
        self.fenster.beschriften(beschriftung.setText, _("Neue Maske:"))
        leiste.addWidget(beschriftung)
        self.lokal_neu_knoepfe = {}
        for art in lokal.ARTEN:
            knopf = self._knopf(lokal_art_titel(art),
                                lambda _an=False, a=art: self.lokal_neue_maske(a), "kanal")
            leiste.addWidget(knopf)
            self.lokal_neu_knoepfe[art] = knopf
        self.fenster.beschriften(self.lokal_neu_knoepfe["verlauf"].setToolTip, _(
            "Verlauf von voller zu keiner Wirkung – im Bild vom Anfang zum Ende ziehen."))
        self.fenster.beschriften(self.lokal_neu_knoepfe["radial"].setToolTip, _(
            "Ellipse, innen volle Wirkung – im Bild von der Mitte nach außen ziehen."))
        self.fenster.beschriften(self.lokal_neu_knoepfe["pinsel"].setToolTip, _(
            "Den Bereich frei ins Bild malen."))
        leiste.addStretch(1)
        innen.addLayout(leiste)

        self.lokal_liste = QListWidget()
        zeile = self.lokal_liste.fontMetrics().height() + 8
        self.lokal_liste.setFixedHeight(zeile * LOKAL_LISTE_ZEILEN + 6)
        self.fenster.beschriften(self.lokal_liste.setToolTip, _(
            "Häkchen schaltet eine Maske ein und aus, Doppelklick benennt sie um."))
        self.lokal_liste.currentRowChanged.connect(self._lokal_gewaehlt)
        self.lokal_liste.itemChanged.connect(self._lokal_an_geaendert)
        self.lokal_liste.itemDoubleClicked.connect(lambda _eintrag: self.lokal_umbenennen())
        innen.addWidget(self.lokal_liste)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.lokal_umbenennen_knopf = self._knopf(_("Umbenennen …"), self.lokal_umbenennen,
                                                  "kanal")
        self.lokal_duplizieren_knopf = self._knopf(_("Duplizieren"), self.lokal_duplizieren,
                                                   "kanal")
        self.lokal_loeschen_knopf = self._knopf(_("Löschen"), self.lokal_loeschen, "kanal")
        for knopf in (self.lokal_umbenennen_knopf, self.lokal_duplizieren_knopf,
                      self.lokal_loeschen_knopf):
            leiste.addWidget(knopf)
        leiste.addStretch(1)
        innen.addLayout(leiste)

        # Was nur fuer die gewaehlte Maske gilt
        self.lokal_bereich = QWidget()
        bereich = QVBoxLayout(self.lokal_bereich)
        bereich.setContentsMargins(0, 4, 0, 0)
        titel = QLabel(objectName="kartentitel")
        self.fenster.beschriften(titel.setText, _("Bereich"))
        bereich.addWidget(titel)
        self.lokal_teile = QListWidget()
        self.lokal_teile.setFixedHeight(zeile * 3 + 6)
        self.lokal_teile.currentRowChanged.connect(self._lokal_teil_gewaehlt)
        bereich.addWidget(self.lokal_teile)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        beschriftung = QLabel()
        self.fenster.beschriften(beschriftung.setText, _("Teil dazu:"))
        leiste.addWidget(beschriftung)
        self.lokal_teil_knoepfe = {}
        for art in lokal.ARTEN:
            knopf = self._knopf(lokal_art_titel(art),
                                lambda _an=False, a=art: self.lokal_teil_neu(a), "kanal")
            self.fenster.beschriften(knopf.setToolTip, _(
                "Der Maske einen weiteren Teil hinzufügen – im Bild aufziehen."))
            leiste.addWidget(knopf)
            self.lokal_teil_knoepfe[art] = knopf
        leiste.addStretch(1)
        bereich.addLayout(leiste)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.lokal_modus_wahl = QComboBox()
        for modus in lokal.MODI:
            self._eintrag(self.lokal_modus_wahl, lokal_modus_titel(modus), modus)
        self.fenster.beschriften(self.lokal_modus_wahl.setToolTip, _(
            "Wie der gewählte Teil mit den Teilen davor zusammenwirkt."))
        self.lokal_modus_wahl.activated.connect(self._lokal_modus_gewaehlt)
        self.lokal_umkehren_box = QCheckBox()
        self.fenster.beschriften(self.lokal_umkehren_box.setText, _("Umkehren"))
        self.lokal_umkehren_box.toggled.connect(self._lokal_umkehren)
        self.lokal_teil_weg_knopf = self._knopf("✕", self.lokal_teil_loeschen, "kanal")
        self.fenster.beschriften(self.lokal_teil_weg_knopf.setToolTip,
                                 _("Den gewählten Teil löschen (Entf)"))
        leiste.addWidget(self.lokal_modus_wahl, 1)
        leiste.addWidget(self.lokal_umkehren_box)
        leiste.addWidget(self.lokal_teil_weg_knopf)
        bereich.addLayout(leiste)
        gitter = QGridLayout()
        gitter.setVerticalSpacing(2)
        gitter.setColumnStretch(0, 1)
        bereich.addLayout(gitter)
        self.lokal_weich_zeile = ReglerZeile(self, LOKAL_WEICH, gitter, 0)
        # Der Pinsel: Einstellungen fuer die naechsten Striche
        self.lokal_malen_feld = QWidget()
        malen = QVBoxLayout(self.lokal_malen_feld)
        malen.setContentsMargins(0, 0, 0, 0)
        hinweis = QLabel(objectName="nebentext")
        hinweis.setWordWrap(True)
        self.fenster.beschriften(hinweis.setText, _(
            "Im Bild malen; mit der rechten Maustaste oder Alt radieren. [ und ] ändern die "
            "Größe."))
        malen.addWidget(hinweis)
        gitter = QGridLayout()
        gitter.setVerticalSpacing(2)
        gitter.setColumnStretch(0, 1)
        malen.addLayout(gitter)
        self.malen_zeilen = {regler.name: ReglerZeile(self, regler, gitter, 2 * nummer)
                             for nummer, regler in enumerate(MALEN_REGLER)}
        bereich.addWidget(self.lokal_malen_feld)
        self.lokal_zeigen_box = QCheckBox()
        self.fenster.beschriften(self.lokal_zeigen_box.setText, _("Maske zeigen (O)"))
        self.fenster.beschriften(self.lokal_zeigen_box.setToolTip, _(
            "Färbt den Bereich der gewählten Maske ein – je kräftiger, desto stärker wirkt sie."))
        self.lokal_zeigen_box.toggled.connect(lambda _an: self.zeichnen_anfordern())
        bereich.addWidget(self.lokal_zeigen_box)
        gitter = QGridLayout()
        gitter.setVerticalSpacing(2)
        gitter.setColumnStretch(0, 1)
        bereich.addLayout(gitter)
        self.lokal_zeilen = {regler.name[6:]: ReglerZeile(self, regler, gitter, 2 * nummer)
                             for nummer, regler in enumerate(LOKAL_REGLER)}
        self.lokal_fertig_knopf = self._knopf(_("Fertig"), self.lokal_beenden, "kanal")
        self.fenster.beschriften(self.lokal_fertig_knopf.setToolTip, _(
            "Das Bearbeiten der Maske beenden (Esc) – sie wirkt weiter."))
        leiste = QHBoxLayout()
        leiste.addStretch(1)
        leiste.addWidget(self.lokal_fertig_knopf)
        bereich.addLayout(leiste)
        innen.addWidget(self.lokal_bereich)
        return karte

    def _lokal_anzeigen(self):
        """Listen, Knoepfe und Regler der Karte auf die Masken der Sitzung setzen."""
        offen = self.sitzung is not None
        if self._lokal_sitzung is not self.sitzung:
            # Ein anderes Bild: keine Maske mehr gewaehlt
            self._lokal_sitzung = self.sitzung
            self._lokal_maske = self._lokal_teil = None
            self._lokal_start = None
            if self.leinwand.lokalmodus:
                self.leinwand.lokalmodus_setzen(False)
        masken = self.sitzung.werte.masken if offen else ()
        if self._lokal_maske is not None and self._lokal_maske >= len(masken):
            self._lokal_maske = self._lokal_teil = None
        if self._lokal_maske is None and self.leinwand.lokalmodus:
            self.leinwand.lokalmodus_setzen(False)
        gewaehlt = self._lokal_maske is not None
        self._lokal_baut = True
        self.lokal_liste.clear()
        for maske in masken:
            eintrag = QListWidgetItem(maske.name or "–")
            eintrag.setFlags(eintrag.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            eintrag.setCheckState(Qt.CheckState.Checked if maske.an else Qt.CheckState.Unchecked)
            self.lokal_liste.addItem(eintrag)
        self.lokal_liste.setCurrentRow(self._lokal_maske if gewaehlt else -1)
        self.lokal_liste.setEnabled(offen)
        platz = len(masken) < lokal.MAX_MASKEN
        for knopf in self.lokal_neu_knoepfe.values():
            knopf.setEnabled(offen and platz)
        self.lokal_umbenennen_knopf.setEnabled(gewaehlt)
        self.lokal_duplizieren_knopf.setEnabled(gewaehlt and platz)
        self.lokal_loeschen_knopf.setEnabled(gewaehlt)
        self.lokal_bereich.setVisible(gewaehlt)
        if not gewaehlt:
            self._lokal_pinsel_neu = False
        self.lokal_teile.clear()
        if gewaehlt:
            maske = masken[self._lokal_maske]
            if self._lokal_teil is not None and self._lokal_teil >= len(maske.teile):
                self._lokal_teil = len(maske.teile) - 1 if maske.teile else None
            for teil in maske.teile:
                self.lokal_teile.addItem(lokal_teil_text(teil))
            self.lokal_teile.setCurrentRow(-1 if self._lokal_teil is None else self._lokal_teil)
            teil = None if self._lokal_teil is None else maske.teile[self._lokal_teil]
            self.lokal_modus_wahl.setCurrentIndex(
                self.lokal_modus_wahl.findData(teil.modus if teil else "dazu"))
            # Der erste Teil hat keinen davor - fuer ihn gibt es nur „Hinzufuegen“
            self.lokal_modus_wahl.setEnabled(teil is not None and self._lokal_teil > 0)
            self.lokal_umkehren_box.blockSignals(True)
            self.lokal_umkehren_box.setChecked(bool(teil and teil.umkehren))
            self.lokal_umkehren_box.blockSignals(False)
            self.lokal_umkehren_box.setEnabled(teil is not None)
            self.lokal_teil_weg_knopf.setEnabled(teil is not None)
            radial = teil is not None and teil.art == "radial"
            for widget in (self.lokal_weich_zeile.titel, self.lokal_weich_zeile.anzeige,
                           self.lokal_weich_zeile.schieber):
                widget.setVisible(radial)
            # Wartet ein anderes Werkzeug auf den Zug im Bild, ruht der Pinsel
            pinsel = self._lokal_pinsel_neu or (teil is not None and teil.art == "pinsel"
                                                and self.leinwand.lokal_neu is None)
            self.lokal_malen_feld.setVisible(pinsel)
            if self.leinwand.lokalmodus and self.leinwand.lokal_pinsel != pinsel:
                self.leinwand.lokal_pinsel_setzen(pinsel)
            if radial:
                self.lokal_weich_zeile.setzen(teil.daten[5])
            for knopf in self.lokal_teil_knoepfe.values():
                knopf.setEnabled(len(maske.teile) < lokal.MAX_TEILE)
            for name, zeile in self.lokal_zeilen.items():
                zeile.setzen(lokal.wert(maske, name))
        self._lokal_baut = False
        self._lokal_formen_setzen()

    def _lokal_formen_setzen(self):
        """Linien und Griffe der Teile der gewaehlten Maske fuer die Leinwand - im fertigen
        Bild, also nach Drehen, Begradigen und Zuschnitt."""
        if self.sitzung is None or not self.leinwand.lokalmodus or self._lokal_maske is None:
            return
        maske = self.sitzung.werte.masken[self._lokal_maske]
        hoehe, breite = self.sitzung.original.shape[:2]
        formen = []
        for teil in maske.teile:
            zuege = lokal.linien(teil, breite, hoehe)
            griffe = lokal.griffe(teil, breite, hoehe)
            punkte = np.concatenate([*zuege, np.array(list(griffe.values()))])
            im_bild = self.sitzung.ziel_von(punkte)
            stuecke = np.split(im_bild, np.cumsum([len(z) for z in zuege]))
            formen.append({"linien": stuecke[:-1],
                           "griffe": dict(zip(griffe, map(tuple, stuecke[-1]), strict=True))})
        self.leinwand.lokal_formen = formen
        self.leinwand.lokal_gewaehlt = self._lokal_teil
        self._malen_radius_zeigen()
        self.leinwand.update()

    def _lokal_modus_beginnen(self):
        """Maskenmodus der Leinwand: die anderen Modi enden."""
        if not self.leinwand.lokalmodus:
            self.zuschneiden(False)
            self.auswahl_beenden()
            self.pinsel_beenden()
            self.leinwand.lokalmodus_setzen(True)

    def lokal_beenden(self):
        """Die Masken nicht mehr bearbeiten - sie wirken weiter."""
        if not self.leinwand.lokalmodus:
            return
        self.leinwand.lokalmodus_setzen(False)
        self._lokal_maske = self._lokal_teil = None
        self._lokal_anzeigen()
        self.zeichnen_anfordern()

    def _lokal_setzen(self, masken, maske: int | None, teil: int | None, voll: bool = True):
        """Neue Masken in die Werte; voll=False waehrend eines Zugs - dann ohne die Listen
        neu zu fuellen."""
        self.sitzung.werte.masken = tuple(masken)
        self._lokal_maske, self._lokal_teil = maske, teil
        if voll:
            self._lokal_anzeigen()
        else:
            self._lokal_formen_setzen()
        self.zeichnen_anfordern()

    def lokal_neue_maske(self, art: str):
        if self.sitzung is None or len(self.sitzung.werte.masken) >= lokal.MAX_MASKEN:
            return
        masken = list(self.sitzung.werte.masken)
        namen = {m.name for m in masken}
        nummer = len(masken) + 1
        while str(_("Maske {n}").format(n=nummer)) in namen:
            nummer += 1
        masken.append(lokal.Maske(str(_("Maske {n}").format(n=nummer))))
        self._lokal_modus_beginnen()
        self._lokal_setzen(masken, len(masken) - 1, None)
        self.lokal_teil_neu(art)

    def lokal_teil_neu(self, art: str):
        if self.sitzung is None or self._lokal_maske is None:
            return
        self._lokal_modus_beginnen()
        if art == "pinsel":
            # Der erste Strich legt den Teil an; „Maske zeigen“ zeigt, was gemalt ist
            self.leinwand.lokal_werkzeug_setzen(None)
            self._lokal_pinsel_neu = True
            self.lokal_zeigen_box.setChecked(True)
            self._lokal_anzeigen()
            self.fenster.melden(_("Im Bild malen."))
            return
        self._lokal_pinsel_neu = False
        self.leinwand.lokal_werkzeug_setzen(art)
        self._lokal_anzeigen()
        self.fenster.melden(_("Verlauf im Bild vom Anfang zum Ende ziehen.") if art == "verlauf"
                            else _("Radial im Bild von der Mitte nach außen ziehen."))

    def _lokal_gewaehlt(self, zeile: int):
        if self._lokal_baut or self.sitzung is None:
            return
        if zeile < 0:
            self.lokal_beenden()
            return
        maske = self.sitzung.werte.masken[zeile]
        self._lokal_modus_beginnen()
        self.leinwand.lokal_werkzeug_setzen(None)
        self._lokal_pinsel_neu = False
        self._lokal_maske, self._lokal_teil = zeile, (0 if maske.teile else None)
        self._lokal_anzeigen()
        self.zeichnen_anfordern()

    def _lokal_teil_gewaehlt(self, zeile: int):
        if self._lokal_baut or self.sitzung is None or self._lokal_maske is None:
            return
        self._lokal_teil = zeile if zeile >= 0 else None
        self._lokal_pinsel_neu = False
        self.leinwand.lokal_werkzeug_setzen(None)
        self._lokal_anzeigen()

    def _lokal_an_geaendert(self, eintrag: QListWidgetItem):
        if self._lokal_baut or self.sitzung is None:
            return
        nummer = self.lokal_liste.row(eintrag)
        masken = list(self.sitzung.werte.masken)
        an = eintrag.checkState() == Qt.CheckState.Checked
        if 0 <= nummer < len(masken) and masken[nummer].an != an:
            masken[nummer] = dataclasses.replace(masken[nummer], an=an)
            self._lokal_setzen(masken, self._lokal_maske, self._lokal_teil)

    def lokal_umbenennen(self):
        if self.sitzung is None or self._lokal_maske is None:
            return
        masken = list(self.sitzung.werte.masken)
        maske = masken[self._lokal_maske]
        name, ok = QInputDialog.getText(self, _("Maske umbenennen"), _("Name:"),
                                        text=maske.name)
        name = " ".join(name.split())[:lokal.MAX_NAME]
        if ok and name and name != maske.name:
            masken[self._lokal_maske] = dataclasses.replace(maske, name=name)
            self._lokal_setzen(masken, self._lokal_maske, self._lokal_teil)

    def lokal_duplizieren(self):
        if self.sitzung is None or self._lokal_maske is None \
                or len(self.sitzung.werte.masken) >= lokal.MAX_MASKEN:
            return
        masken = list(self.sitzung.werte.masken)
        maske = masken[self._lokal_maske]
        name = str(_("{name} – Kopie").format(name=maske.name))[:lokal.MAX_NAME]
        masken.insert(self._lokal_maske + 1, dataclasses.replace(maske, name=name))
        self._lokal_setzen(masken, self._lokal_maske + 1, self._lokal_teil)

    def lokal_loeschen(self):
        if self.sitzung is None or self._lokal_maske is None:
            return
        masken = list(self.sitzung.werte.masken)
        del masken[self._lokal_maske]
        self._lokal_setzen(masken, None, None)
        self.lokal_beenden()

    def lokal_teil_loeschen(self, nummer: int | None = None):
        if self.sitzung is None or self._lokal_maske is None:
            return
        if not isinstance(nummer, int) or isinstance(nummer, bool):
            nummer = self._lokal_teil
        masken = list(self.sitzung.werte.masken)
        maske = masken[self._lokal_maske]
        if nummer is None or not 0 <= nummer < len(maske.teile):
            return
        teile = list(maske.teile)
        del teile[nummer]
        if teile and teile[0].modus != "dazu":
            teile[0] = dataclasses.replace(teile[0], modus="dazu")
        masken[self._lokal_maske] = dataclasses.replace(maske, teile=tuple(teile))
        self._lokal_setzen(masken, self._lokal_maske, min(nummer, len(teile) - 1)
                           if teile else None)

    def _lokal_teil_aendern(self, **aenderung):
        if self.sitzung is None or self._lokal_maske is None or self._lokal_teil is None:
            return
        masken = list(self.sitzung.werte.masken)
        maske = masken[self._lokal_maske]
        teile = list(maske.teile)
        teile[self._lokal_teil] = dataclasses.replace(teile[self._lokal_teil], **aenderung)
        masken[self._lokal_maske] = dataclasses.replace(maske, teile=tuple(teile))
        self._lokal_setzen(masken, self._lokal_maske, self._lokal_teil)

    def _lokal_modus_gewaehlt(self, nummer: int):
        self._lokal_teil_aendern(modus=self.lokal_modus_wahl.itemData(nummer))

    def _lokal_umkehren(self, an: bool):
        self._lokal_teil_aendern(umkehren=an)

    def _lokal_wert(self, name: str, wert: float):
        """Ein Regler der Karte: Wert der gewaehlten Maske oder weicher Rand des Teils."""
        if self._lokal_maske is None:
            return
        masken = list(self.sitzung.werte.masken)
        maske = masken[self._lokal_maske]
        if name == "lokal_weich":
            if self._lokal_teil is None or maske.teile[self._lokal_teil].art != "radial":
                return
            teile = list(maske.teile)
            daten = list(teile[self._lokal_teil].daten)
            daten[5] = wert
            teile[self._lokal_teil] = dataclasses.replace(teile[self._lokal_teil],
                                                          daten=tuple(daten))
            masken[self._lokal_maske] = dataclasses.replace(maske, teile=tuple(teile))
        else:
            masken[self._lokal_maske] = lokal.mit_wert(maske, name[6:], wert)
        self._lokal_setzen(masken, self._lokal_maske, self._lokal_teil, voll=False)

    def _lokal_gezogen(self, art: str, nummer: int, griff: str, sx: float, sy: float,
                       x: float, y: float, fertig: bool):
        if self.sitzung is None or self._vorher or self._lokal_maske is None:
            return
        if self._lokal_start is None:
            self._lokal_start = self.sitzung.werte.masken
        vorher = self._lokal_start
        if fertig:
            self._lokal_start = None
        hoehe, breite = self.sitzung.original.shape[:2]
        a = self.sitzung.quelle_von(sx, sy, begrenzt=False)
        b = self.sitzung.quelle_von(x, y, begrenzt=False)
        masken = list(vorher)
        maske = masken[self._lokal_maske]
        if art == "neu":
            teil = lokal.neuer_teil(griff, a, b, breite, hoehe)
            if teil is None:
                # Nur geklickt: nichts anlegen, das Werkzeug bleibt gewaehlt
                self._lokal_setzen(masken, self._lokal_maske, self._lokal_teil, voll=fertig)
                return
            teile = (*maske.teile, teil)
            if fertig:
                self.leinwand.lokal_werkzeug_setzen(None)
        else:
            if not 0 <= nummer < len(maske.teile):
                return
            teile = list(maske.teile)
            teile[nummer] = lokal.gezogen(teile[nummer], griff, a, b, breite, hoehe)
        masken[self._lokal_maske] = dataclasses.replace(maske, teile=tuple(teile))
        neu = len(teile) - 1 if art == "neu" else nummer
        self._lokal_setzen(masken, self._lokal_maske, neu, voll=fertig or neu != self._lokal_teil)

    def _lokal_gemalt(self, x: float, y: float, radieren: bool, neu: bool):
        """Ein Punkt des Pinsels: beginnt einen Strich oder setzt ihn fort - im Teil, der
        gewaehlt ist, oder in einem neuen."""
        if self.sitzung is None or self._vorher or self._lokal_maske is None:
            return
        hoehe, breite = self.sitzung.original.shape[:2]
        lang = max(hoehe, breite)
        px, py = self.sitzung.quelle_von(x, y, begrenzt=False)
        unten, oben = lokal.PUNKT_BEREICH
        punkt = (min(max(px / breite, unten), oben), min(max(py / hoehe, unten), oben))
        masken = list(self.sitzung.werte.masken)
        maske = masken[self._lokal_maske]
        teile = list(maske.teile)
        nummer = self._lokal_teil
        if self._lokal_pinsel_neu or nummer is None or teile[nummer].art != "pinsel":
            if not neu or len(teile) >= lokal.MAX_TEILE:
                return
            teile.append(lokal.Teil("pinsel", ()))
            nummer = len(teile) - 1
            self._lokal_pinsel_neu = False
        teil = teile[nummer]
        if teil.punkte() >= lokal.MAX_PUNKTE:
            if neu:
                self.fenster.melden(_("Dieser Pinsel-Teil ist voll – für mehr einen neuen "
                                      "Teil anlegen."))
            return
        if neu:
            if len(teil.striche) >= lokal.MAX_STRICHE:
                return
            radius = max(self._malen["malen_groesse"] / 100 * MALEN_GROESSTER,
                         lokal.STRICH["radius"][0])
            striche = (*teil.striche, lokal.Strich(radius, self._malen["malen_weich"],
                                                   self._malen["malen_deckkraft"], radieren,
                                                   punkt))
        else:
            if not teil.striche:
                return
            letzter = teil.striche[-1]
            lx, ly = letzter.punkte[-2:]
            abstand = math.hypot((punkt[0] - lx) * breite, (punkt[1] - ly) * hoehe)
            if abstand < lokal.PINSEL_ABSTAND * letzter.radius * lang:
                return                         # zu nah am letzten Punkt
            striche = (*teil.striche[:-1],
                       dataclasses.replace(letzter, punkte=letzter.punkte + punkt))
        teile[nummer] = dataclasses.replace(teil, striche=striche)
        masken[self._lokal_maske] = dataclasses.replace(maske, teile=tuple(teile))
        self._lokal_setzen(masken, self._lokal_maske, nummer,
                           voll=neu and nummer != self._lokal_teil)

    def _malen_radius_zeigen(self):
        """Der Kreis auf der Leinwand zeigt die Groesse des naechsten Strichs."""
        if self.sitzung is None:
            return
        lang = max(self.sitzung.original.shape[:2])
        radius = self._malen["malen_groesse"] / 100 * MALEN_GROESSTER * lang
        self.leinwand.pinsel_radius = max(radius * self.leinwand.massstab(), 1.0)
        self.leinwand.update()

    def _malen_groesse_schritt(self, richtung: int):
        if not (self.leinwand.lokalmodus and self.leinwand.lokal_pinsel):
            return
        zeile = self.malen_zeilen["malen_groesse"]
        wert = zeile.wert() * (MALEN_SCHRITT if richtung > 0 else 1 / MALEN_SCHRITT)
        wert = round(min(max(wert, zeile.regler.minimum), zeile.regler.maximum))
        if wert == zeile.wert():
            wert = min(max(wert + richtung, zeile.regler.minimum), zeile.regler.maximum)
        zeile.setzen(wert)
        zeile._bewegt()

    def _lokal_zeigen_taste(self):
        if self.leinwand.lokalmodus and self.lokal_zeigen_box.isEnabled():
            self.lokal_zeigen_box.toggle()

    def _sw_anzeigen(self):
        """Schalter, Mischer und Vorlagen auf die Werte der Sitzung setzen."""
        offen = self.sitzung is not None
        werte = self.sitzung.werte if offen else filter.Einstellungen()
        if self.sw_box.isChecked() != werte.sw:
            self.sw_box.blockSignals(True)
            self.sw_box.setChecked(werte.sw)
            self.sw_box.blockSignals(False)
        self.sw_box.setEnabled(offen)
        for zeile, wert in zip(self.sw_zeilen, werte.sw_mischer, strict=True):
            zeile.setzen(wert)
            zeile.schieber.setEnabled(offen and werte.sw)
        self.sw_filter_wahl.setEnabled(offen and werte.sw)
        filtername = next((name for name, mischung in filter.SW_FILTER.items()
                           if mischung == tuple(werte.sw_mischer)),
                          "" if not any(werte.sw_mischer) else None)
        self.sw_filter_wahl.setCurrentIndex(self.sw_filter_wahl.findData(filtername)
                                            if filtername is not None else -1)
        ton = tuple(getattr(werte, name) for name in filter.TONUNG)
        vorlage = next((name for name, vorgabe in filter.TONUNG_VORLAGEN.items()
                        if vorgabe == ton), "" if not werte.tonung_aktiv() else None)
        self.ton_vorlage_wahl.setCurrentIndex(self.ton_vorlage_wahl.findData(vorlage)
                                              if vorlage is not None else -1)
        self.ton_vorlage_wahl.setEnabled(offen)

    def _sw_filter_gewaehlt(self, nummer: int):
        if self.sitzung is None:
            return
        name = self.sw_filter_wahl.itemData(nummer)
        self._festhalten(sofort=True)             # eine eben gemachte Aenderung zuerst
        self._schritt_name = "sw_filter"
        self.sitzung.werte.sw_mischer = filter.SW_FILTER.get(name, filter.HSL_NEUTRAL)
        self._sw_anzeigen()
        self.zeichnen_anfordern()

    def _ton_vorlage_gewaehlt(self, nummer: int):
        if self.sitzung is None:
            return
        name = self.ton_vorlage_wahl.itemData(nummer)
        self._festhalten(sofort=True)             # eine eben gemachte Aenderung zuerst
        self._schritt_name = "ton_vorlage"
        werte = self.sitzung.werte
        if name:
            for feld, wert in zip(filter.TONUNG, filter.TONUNG_VORLAGEN[name], strict=True):
                setattr(werte, feld, wert)
        else:
            werte.ton_lichter_saettigung = werte.ton_schatten_saettigung = 0.0
            werte.ton_balance = 0.0
        for feld in filter.TONUNG:
            self.zeilen[feld].setzen(getattr(werte, feld))
        self._sw_anzeigen()
        self.zeichnen_anfordern()

    def _lut_bedienung(self, innen: QVBoxLayout):
        self.lut_name = QLabel(objectName="nebentext")
        self.lut_name.setWordWrap(True)
        # Der Titel steht in der LUT - auch in einer fremden Begleitdatei; nie als HTML zeigen
        self.lut_name.setTextFormat(Qt.TextFormat.PlainText)
        innen.addWidget(self.lut_name)
        leiste = QHBoxLayout()
        leiste.setSpacing(6)
        self.lut_knopf = self._knopf(_("LUT laden …"), self.lut_dialog)
        self.lut_entfernen_knopf = self._knopf(_("Entfernen"), self.lut_entfernen)
        leiste.addWidget(self.lut_knopf)
        leiste.addWidget(self.lut_entfernen_knopf)
        leiste.addStretch(1)
        innen.addLayout(leiste)
        self._lut_anzeigen()

    def _lut_anzeigen(self):
        pfad = self.sitzung.werte.lut if self.sitzung is not None else ""
        if pfad:
            try:
                titel = lut.laden(pfad).titel
            except lut.LutFehler:
                titel = os.path.basename(pfad)
            self.fenster.beschriften(self.lut_name.setText, _("Geladen: {name}").format(name=titel))
        else:
            self.fenster.beschriften(self.lut_name.setText, _("Keine LUT geladen."))
        self.lut_entfernen_knopf.setEnabled(bool(pfad))

    def lut_dialog(self):
        if self.sitzung is None:
            return
        ordner = einstellungen.load_config().get("lut_ordner", "")
        pfad, _filter = QFileDialog.getOpenFileName(
            self, _("LUT laden"), ordner if os.path.isdir(ordner) else self._letzter_ordner(),
            "Cube-LUT (*.cube)")
        if not pfad:
            return
        try:
            lut.laden(pfad)
        except lut.LutFehler as fehler:
            self._fehler(_("Die LUT lässt sich nicht lesen."), str(fehler))
            return
        daten = einstellungen.load_config()
        daten["lut_ordner"] = os.path.dirname(pfad)
        einstellungen.save_config(daten)
        self.sitzung.werte.lut = pfad
        self._lut_anzeigen()
        self.zeichnen_anfordern()

    def lut_entfernen(self):
        if self.sitzung is None:
            return
        self.sitzung.werte.lut = ""
        self._lut_anzeigen()
        self.zeichnen_anfordern()

    def _kurvenkarte(self) -> QFrame:
        karte, innen = self._karte(_("Gradationskurve"))
        self.kurven = KurvenEditor(
            self.fenster.beschriften,
            {"kurve_hell": _("Hell"), "kurve_rot": _("R"), "kurve_gruen": _("G"),
             "kurve_blau": _("B")},
            _("Zurücksetzen"))
        self.fenster.beschriften(
            self.kurven.flaeche.setToolTip,
            _("Klicken setzt einen Punkt, Ziehen verschiebt ihn, Doppelklick entfernt ihn."))
        self.kurven.geaendert.connect(self.wert_geaendert)
        innen.addWidget(self.kurven)
        return karte

    def _knoepfe_freischalten(self):
        offen = self.sitzung is not None
        for widget in (self.speichern_knopf, self.veroeffentlichen_knopf, self.drucken_knopf,
                       self.vorher_knopf, self.zuruecksetzen_knopf):
            widget.setEnabled(offen)
        self._voreinstellungen_freischalten()
        for zeile in [*self.zeilen.values(), *self.hsl_zeilen]:
            zeile.schieber.setEnabled(offen)
        for knopf in self._hsl_knoepfe.values():
            knopf.setEnabled(offen)
        self._sw_anzeigen()
        self._lokal_anzeigen()
        self.kurven.setEnabled(offen)
        self.lut_knopf.setEnabled(offen)
        self._ki_anzeigen()
        for widget in (self.links_knopf, self.rechts_knopf, self.spiegeln_knopf,
                       self.zuschneiden_knopf, self.verhaeltnis_wahl, self.zuschnitt_weg_knopf,
                       self.einpassen_knopf, self.zoom100_knopf):
            widget.setEnabled(offen)
        self._lut_anzeigen()
        self._ki_bild_anzeigen()            # beschriftet auch Motiv, Entfernen, Tiefe, Erweitern
        self._film_anzeigen()
        self._anonym_anzeigen()
        self._objektiv_anzeigen()
        self._metadaten_anzeigen()
        self._verlauf_anzeigen()

    # ------------------------------------------------------------------
    # Regler und Vorschau
    # ------------------------------------------------------------------

    def wert_geaendert(self, name: str, wert):
        if name.startswith("malen_"):
            self._malen[name] = wert                 # gilt fuer den naechsten Strich
            self._malen_radius_zeigen()
            return
        if self.sitzung is None or name == "ki_entrauschen":
            return
        if name.startswith("hsl_") and name[4:].isdigit():
            # Ein Farbbereichsregler: gilt fuer die gerade gewaehlte Eigenschaft
            werte = list(getattr(self.sitzung.werte, self.hsl_modus))
            werte[int(name[4:])] = wert
            name, wert = self.hsl_modus, tuple(werte)
        elif name.startswith("lokal_"):
            self._lokal_wert(name, wert)
            return
        elif name.startswith("sw_") and name[3:].isdigit():
            werte = list(self.sitzung.werte.sw_mischer)
            werte[int(name[3:])] = wert
            name, wert = "sw_mischer", tuple(werte)
        setattr(self.sitzung.werte, name, wert)
        if name in ("sw", "sw_mischer") or name in filter.TONUNG:
            self._sw_anzeigen()                   # Mischer frei? Passt die Vorlage noch?
        self.zeichnen_anfordern()

    def zeichnen_anfordern(self):
        """Faellt bei schnellem Ziehen mehrere Aenderungen in ein Neuzeichnen zusammen."""
        self._aenderung_merken()
        if not self._zeichnen_angefordert:
            self._zeichnen_angefordert = True
            QTimer.singleShot(0, self._zeichnen)

    def _zeichnen(self):
        self._zeichnen_angefordert = False
        if self.sitzung is None:
            self.leinwand.zeigen(None)
            self.kurven.histogramm_zeigen(None)
            self.fenster.rechenzeit_zeigen(None)
            return
        werte = filter.Einstellungen() if self._vorher else self.sitzung.werte
        self.sitzung.maske_zeigen = self.maske_zeigen_box.isChecked() and not self._vorher
        if self.leinwand.zuschnitt is not None:
            # Im Zuschnittmodus das ganze Bild zeigen, der Rahmen liegt darueber
            werte = dataclasses.replace(werte, zuschnitt=VOLLER_ZUSCHNITT)
        # „Vorher“ zeigt nach einem KI-Erweitern das Original ohne die erfundenen Raender -
        # eingepasst; in der 100-%-Ansicht passte der sichtbare Ausschnitt nicht mehr
        ohne_raender = self._vorher and self.sitzung.erweitert and self.leinwand.zoom is None
        self.leinwand.voll_form = self.sitzung.ausgabe_form(werte, ohne_erweiterung=ohne_raender)
        if not self._vorher:
            self._umrisse_setzen()                 # Geometrie kann sich geaendert haben
            self._lokal_formen_setzen()
        self.sitzung.lokal_zeigen = (self._lokal_maske if self.leinwand.lokalmodus
                                     and self.lokal_zeigen_box.isChecked()
                                     and not self._vorher else None)
        if self._klick_ziel is not None:
            ziel = self._klick_ziel
            gleich = (not self._vorher
                      and self._klick_geo.get(ziel) == geometrie.aus(self.sitzung.werte))
            self.leinwand.klickpunkte = list(self._klick_marken.get(ziel, [])) if gleich else []
        self.sitzung.tiefe_zeigen = self.tiefe_zeigen_box.isChecked() and not self._vorher
        self.sitzung.staub_zeigen = self.staub_zeigen_box.isChecked() and not self._vorher
        if self.leinwand.zoom is None:
            bild, ms, histogramm = self.sitzung.vorschau(werte=werte,
                                                         ohne_erweiterung=ohne_raender,
                                                         ohne_flicken=self._vorher)
            self.leinwand.zeigen(bild)
        else:
            bereich = self.leinwand.sichtbarer_bereich()
            if bereich is None:
                return
            x0, y0, breite, hoehe = bereich
            bild, ms, histogramm = self.sitzung.ausschnitt(x0, y0, breite, hoehe, werte,
                                                           ohne_flicken=self._vorher)
            self.leinwand.zeigen_ausschnitt(bild, x0, y0)
        self.kurven.histogramm_zeigen(histogramm)
        self.fenster.rechenzeit_zeigen(ms)
        self._ki_anzeigen()
        self._ki_bild_anzeigen()
        self._verlauf_anzeigen()

    def _vorher_zeigen(self, an: bool):
        self._vorher = an
        self.zeichnen_anfordern()

    def alles_zuruecksetzen(self):
        self.zuschnitt_abbrechen()
        self._festhalten(sofort=True)             # eine eben gemachte Aenderung zuerst
        self._schritt_name = "zuruecksetzen"
        if self.erweitern_box.isChecked():
            # Auch die KI-Erweiterung gehoert zu „alles“: Abwaehlen verwirft sie
            self.erweitern_box.setChecked(False)
        if self.sitzung is not None:
            self.sitzung.werte = self.sitzung.grundwerte()
            # Auch entfernte Objekte gehoeren zu „alles“
            self._klick_marken["entfernen"] = []
            if self.sitzung.entfernungen_verwerfen() and self._sam_klickt():
                self.sitzung.ki_auswahl_beginnen(self._auswaehler, self._klick_ziel)
        self._alles_anzeigen()
        self._entfernen_anzeigen()
        self.zeichnen_anfordern()

    def _alles_anzeigen(self):
        """Alle Bedienelemente auf die Werte der Sitzung (oder die Vorgaben) setzen."""
        werte = self.sitzung.werte if self.sitzung is not None else filter.Einstellungen()
        for name, zeile in self.zeilen.items():
            zeile.setzen(getattr(werte, name))
        self.kurven.alle_setzen({name: getattr(werte, name) for name in filter.KURVEN})
        self._hsl_anzeigen()
        self._sw_anzeigen()
        self._lokal_anzeigen()
        self._lut_anzeigen()
        self._ki_bild_anzeigen()
        self._film_anzeigen()
        self._anonym_anzeigen()
        self._objektiv_anzeigen()
        self._metadaten_anzeigen()
        self._umrisse_setzen()

    # ------------------------------------------------------------------
    # Verlauf: Rueckgaengig und Wiederholen
    # ------------------------------------------------------------------

    def _verlauf_beginnen(self):
        """Neues Bild: der Verlauf beginnt mit seinem Stand. Er darf hoechstens einen Teil
        des Grafikspeichers zusaetzlich belegen."""
        self._verlauf_uhr.stop()
        self._schritt_name = ""
        budget = max(VERLAUF_MINDESTENS, int(self._vram() * VERLAUF_ANTEIL))
        self.verlauf = verlauf.Verlauf(budget)
        if self.sitzung is not None:
            self.verlauf.beginnen(self.sitzung.stand())
        self._verlauf_anzeigen()

    def _aenderung_merken(self):
        if self.sitzung is not None:
            self._verlauf_uhr.start()             # beginnt bei jeder Aenderung von vorn

    def _festhalten(self, sofort: bool = False):
        """Den Stand der Sitzung in den Verlauf - nicht, solange eine Maus noch zieht oder
        die Maske per Klick entsteht: Die Klicks nimmt Strg+Z einzeln zurueck, im
        Verlauf zaehlt die fertige Auswahl als ein Schritt."""
        if self.sitzung is None:
            return
        if not sofort and (self._klick_ziel == "maske"
                           or QApplication.mouseButtons() != Qt.MouseButton.NoButton):
            self._verlauf_uhr.start()
            return
        self._verlauf_uhr.stop()
        self.verlauf.festhalten(self.sitzung.stand(), self._schritt_name)
        self._schritt_name = ""
        self._verlauf_anzeigen()

    def _strg_z(self):
        """Strg+Z nimmt bei der Auswahl per Klick zuerst die Klicks zurueck, danach den Verlauf."""
        ziel = self._klick_ziel
        if (ziel in ("maske", "entfernen") and self.sitzung is not None
                and self.sitzung.klicks_von(ziel)):
            self.klick_zuruecknehmen()
        else:
            self.rueckgaengig()

    def rueckgaengig(self):
        self._im_verlauf_gehen(zurueck=True)

    def wiederholen(self):
        self._im_verlauf_gehen(zurueck=False)

    def _im_verlauf_gehen(self, zurueck: bool):
        if self.sitzung is None:
            return
        # Zuschnitt und Klickauswahl zuerst beenden, damit Rahmen und Werte zusammenpassen
        self.zuschnitt_abbrechen()
        self.auswahl_beenden()
        self._festhalten(sofort=True)             # eine eben gemachte Aenderung zuerst
        schritt = self.verlauf.schritt_zurueck() if zurueck else self.verlauf.schritt_vor()
        if schritt is None:
            return
        text = self._schritt_text(*schritt)
        stand = self.verlauf.zurueck() if zurueck else self.verlauf.vor()
        teile_vorher, teile = dict(self.sitzung.stand().teile), dict(stand.teile)
        self.sitzung.stand_setzen(stand)
        if teile["maske"][0] is not teile_vorher["maske"][0]:
            self._klick_marken["maske"] = []
        if teile["erweiterung"] is not teile_vorher["erweiterung"]:
            # Die Klickmarken lagen im alten Format
            self._klick_marken = {"maske": [], "entfernen": []}
        if self.sitzung.erweitert and not self.erweitern_box.isChecked():
            self.erweitern_box.blockSignals(True)  # Abwaehlen verwuerfe die Erweiterung
            self.erweitern_box.setChecked(True)
            self.erweitern_box.blockSignals(False)
        self.leinwand.flaeche_gewaehlt = None
        self._alles_anzeigen()
        self._entfernen_anzeigen()
        self._erweitern_anzeigen()
        self._verlauf_anzeigen()
        self.fenster.melden((_("Rückgängig: {schritt}") if zurueck else
                             _("Wiederholt: {schritt}")).format(schritt=text))
        self.zeichnen_anfordern()

    def _verlauf_anzeigen(self):
        if not hasattr(self, "rueckgaengig_knopf"):
            return
        offen = self.sitzung is not None
        zurueck = vor = None
        if offen and self.verlauf.aktuell is not None:
            jetzt = self.sitzung.stand()
            if not verlauf.gleich(jetzt, self.verlauf.aktuell):
                # Noch nicht festgehalten: Rueckgaengig nimmt sie zurueck, Wiederholen
                # gibt es danach nicht mehr
                zurueck = (self.verlauf.aktuell, jetzt, self._schritt_name)
            else:
                zurueck = self.verlauf.schritt_zurueck()
                vor = self.verlauf.schritt_vor()
        self.rueckgaengig_knopf.setEnabled(zurueck is not None)
        self.wiederholen_knopf.setEnabled(vor is not None)
        if zurueck is None:
            text = _("Rückgängig (Strg+Z)")
        else:
            text = _("Rückgängig: {schritt} (Strg+Z)").format(schritt=self._schritt_text(*zurueck))
        self.fenster.beschriften(self.rueckgaengig_knopf.setToolTip, text)
        if vor is None:
            text = _("Wiederholen (Strg+Y)")
        else:
            text = _("Wiederholen: {schritt} (Strg+Y)").format(schritt=self._schritt_text(*vor))
        self.fenster.beschriften(self.wiederholen_knopf.setToolTip, text)

    def _schritt_text(self, vorher: verlauf.Stand, nachher: verlauf.Stand, name: str) -> str:
        """Was ein Schritt geaendert hat, in wenigen Worten - fuer Tooltip und Meldung."""
        if name == "zuruecksetzen":
            return _("Zurücksetzen")
        if name == "voreinstellung":
            return _("Voreinstellung")
        if name == "einfuegen":
            return _("Einstellungen eingefügt")
        if name == "sw_filter":
            return _("Schwarzweiß-Filter")
        if name == "ton_vorlage":
            return _("Tönungsvorlage")
        teile = dict(vorher.teile), dict(nachher.teile)
        felder = verlauf.unterschied(vorher, nachher)
        # Eine KI-Berechnung sagt mehr als der Regler, den sie dabei mitstellt - das
        # Erweitern auch mehr als der Zuschnitt, den es aufhebt
        ki_felder = [feld for feld in felder if feld in teile[0]]
        still = {self._aenderung_text(feld, *teile)[1] for feld in ki_felder}
        if "erweiterung" in ki_felder:
            still |= {"zuschnitt", "objektivprofil"}
        texte = []
        for feld in felder:
            text, gruppe = self._aenderung_text(feld, *teile)
            if feld not in ki_felder and gruppe in still:
                continue
            if text not in texte:
                texte.append(text)
        if not texte:
            return _("Änderung")
        return ", ".join(texte) if len(texte) <= 2 else _("mehrere Änderungen")

    @staticmethod
    def _aenderung_text(feld: str, teile_vorher: dict, teile_nachher: dict) -> tuple[str, str]:
        """(Text, Gruppe) fuer ein geaendertes Feld der Werte oder ein KI-Ergebnis."""
        regler = filter.REGLER_NACH_NAME.get(feld)
        if regler is not None:
            titel = regler_titel(feld)
            if regler.gruppe in ("rauschen", "ki_rauschen", "ki_schaerfe", "ki_farbe", "maske",
                                 "tiefe", "lut", "korn"):
                titel = f"{gruppen_titel(regler.gruppe)}: {titel}"
            elif regler.gruppe == "tonung":
                titel = f"{_('Teiltonung')} – {titel}"
            return titel, regler.gruppe
        if feld == "staub":
            return (_("Staub entfernt") if teile_nachher[feld] is not None else
                    _("Staub zurückgeholt")), "staub"
        if feld == "flicken":
            mehr = len(teile_nachher[feld]) - len(teile_vorher[feld])
            if mehr > 0:
                return _("Objekt entfernt"), "flicken"
            return (_("Entferntes Objekt zurückgeholt") if mehr == -1 else
                    _("Entfernte Objekte zurückgeholt")), "flicken"
        gruppe = {"ki_entrauscht": "ki_rauschen", "ki_geschaerft": "ki_schaerfe",
                  "ki_koloriert": "ki_farbe", "maske_umkehren": "maske", "freistellen": "maske",
                  "bokeh_motiv": "tiefe", "erweiterung": "geometrie",
                  **dict.fromkeys(filter.KURVEN, "kurven"),
                  **dict.fromkeys(filter.HSL, "hsl"),
                  **dict.fromkeys(filter.SW_FELDER, "sw"),
                  **dict.fromkeys(filter.LOKAL_FELDER, "lokal"),
                  **dict.fromkeys(filter.ANONYM_FELDER, "anonym"),
                  **dict.fromkeys(filter.FILM_FELDER, "film")}.get(feld, feld)
        if gruppe in ("ki_rauschen", "ki_schaerfe", "ki_farbe", "maske", "tiefe"):
            return gruppen_titel(gruppe), gruppe
        texte = {"kurven": _("Gradationskurve"), "hsl": _("Farbbereiche"), "lut": _("LUT"),
                 "sw": _("Schwarzweiß"), "lokal": _("Lokale Anpassungen"),
                 "anonym": _("Anonymisieren"), "angaben": _("Metadaten"),
                 "film": _("Scan & Film"),
                 "drehung90": _("Drehen"), "spiegeln": _("Spiegeln"),
                 "zuschnitt": _("Zuschnitt"), "objektivprofil": _("Objektivprofil"),
                 "geometrie": _("KI-Erweitern")}
        return texte.get(gruppe, feld), gruppe

    # ------------------------------------------------------------------
    # Voreinstellungen und Einstellungen kopieren (voreinstellungen.py)
    # ------------------------------------------------------------------

    def _voreinstellungen_karte(self) -> QFrame:
        karte, innen = self._karte(_("Voreinstellungen"))
        hinweis = QLabel(objectName="nebentext")
        hinweis.setWordWrap(True)
        self.fenster.beschriften(hinweis.setText, _(
            "Einstellungen unter einem Namen sichern und auf andere Bilder legen – oder "
            "von einem Bild aufs nächste kopieren."))
        innen.addWidget(hinweis)
        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.vor_wahl = QComboBox()
        self.vor_wahl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.vor_wahl.currentIndexChanged.connect(lambda _i: self._voreinstellungen_freischalten())
        self.vor_anwenden_knopf = self._knopf(_("Anwenden"), self.voreinstellung_anwenden,
                                              "kanal")
        self.fenster.beschriften(self.vor_anwenden_knopf.setToolTip, _(
            "Die gewählte Voreinstellung auf dieses Bild legen. Lässt sich mit „Rückgängig“ "
            "zurücknehmen."))
        leiste.addWidget(self.vor_wahl, 1)
        leiste.addWidget(self.vor_anwenden_knopf)
        innen.addLayout(leiste)

        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.vor_sichern_knopf = self._knopf(_("Sichern …"), self.voreinstellung_sichern, "kanal")
        self.fenster.beschriften(self.vor_sichern_knopf.setToolTip, _(
            "Die Einstellungen dieses Bildes als Voreinstellung sichern – welche, steht im "
            "nächsten Schritt zur Wahl."))
        self.vor_loeschen_knopf = self._knopf(_("Löschen"), self.voreinstellung_loeschen,
                                              "kanal")
        self.fenster.beschriften(self.vor_loeschen_knopf.setToolTip,
                                 _("Die gewählte Voreinstellung löschen"))
        self.vor_mehr_knopf = self._knopf("…", None, "kanal")
        self.fenster.beschriften(self.vor_mehr_knopf.setToolTip,
                                 _("Voreinstellungen importieren und exportieren"))
        menue = QMenu(self.vor_mehr_knopf)
        import_aktion = menue.addAction("")
        self.fenster.beschriften(import_aktion.setText, _("Importieren …"))
        import_aktion.triggered.connect(self.voreinstellung_importieren)
        self.vor_export_aktion = menue.addAction("")
        self.fenster.beschriften(self.vor_export_aktion.setText, _("Exportieren …"))
        self.vor_export_aktion.triggered.connect(self.voreinstellung_exportieren)
        self.vor_mehr_knopf.setMenu(menue)
        leiste.addWidget(self.vor_sichern_knopf)
        leiste.addWidget(self.vor_loeschen_knopf)
        leiste.addWidget(self.vor_mehr_knopf)
        leiste.addStretch(1)
        innen.addLayout(leiste)

        leiste = QHBoxLayout()
        leiste.setSpacing(4)
        self.vor_kopieren_knopf = self._knopf(_("Kopieren"), self.einstellungen_kopieren, "kanal")
        self.fenster.beschriften(self.vor_kopieren_knopf.setToolTip, _(
            "Einstellungen dieses Bildes merken, um sie auf ein anderes zu legen "
            "(Strg+Umschalt+C)"))
        self.vor_einfuegen_knopf = self._knopf(_("Einfügen"), self.einstellungen_einfuegen,
                                               "kanal")
        self.fenster.beschriften(self.vor_einfuegen_knopf.setToolTip, _(
            "Die kopierten Einstellungen auf dieses Bild legen (Strg+Umschalt+V)"))
        leiste.addWidget(self.vor_kopieren_knopf)
        leiste.addWidget(self.vor_einfuegen_knopf)
        leiste.addStretch(1)
        innen.addLayout(leiste)
        self._voreinstellungen_auffrischen()
        return karte

    def _voreinstellungen_auffrischen(self, waehlen: str | None = None):
        gewaehlt = waehlen if waehlen is not None else self.vor_wahl.currentText()
        self.vor_wahl.blockSignals(True)
        self.vor_wahl.clear()
        self.vor_wahl.addItems(voreinstellungen.namen())
        self.vor_wahl.setCurrentIndex(max(0, self.vor_wahl.findText(gewaehlt)))
        self.vor_wahl.blockSignals(False)
        self._voreinstellungen_freischalten()

    def _voreinstellungen_freischalten(self):
        if not hasattr(self, "vor_einfuegen_knopf"):
            return                                # waehrend des Aufbaus
        offen = self.sitzung is not None
        da = self.vor_wahl.count() > 0
        self.vor_wahl.setEnabled(da)
        self.vor_anwenden_knopf.setEnabled(offen and da)
        self.vor_loeschen_knopf.setEnabled(da)
        self.vor_export_aktion.setEnabled(da)
        self.vor_sichern_knopf.setEnabled(offen)
        self.vor_kopieren_knopf.setEnabled(offen)
        self.vor_einfuegen_knopf.setEnabled(offen and self._zwischenablage is not None)

    @staticmethod
    def _auswahl_vorgabe() -> voreinstellungen.Auswahl:
        """Die zuletzt gewaehlten Gruppen - sonst die Vorgabe."""
        gemerkt = einstellungen.load_config().get("voreinstellung_auswahl")
        if isinstance(gemerkt, dict) and isinstance(gemerkt.get("gruppen"), list):
            gruppen = tuple(g for g in voreinstellungen.GRUPPEN if g in gemerkt["gruppen"])
            if gruppen:
                return voreinstellungen.Auswahl(gruppen, gemerkt.get("film_messung") is True)
        return voreinstellungen.Auswahl()

    @staticmethod
    def _auswahl_merken(auswahl: voreinstellungen.Auswahl):
        daten = einstellungen.load_config()
        daten["voreinstellung_auswahl"] = {"gruppen": list(auswahl.gruppen),
                                           "film_messung": auswahl.film_messung}
        einstellungen.save_config(daten)

    def _werte_fuer_voreinstellung(self, auswahl: voreinstellungen.Auswahl) -> dict | None:
        try:
            return voreinstellungen.als_dict(self.sitzung.werte, auswahl, VERSION)
        except lut.LutFehler as fehler:
            self._fehler(_("Die LUT lässt sich nicht mehr lesen."), str(fehler))
            return None

    def _ersetzen_ok(self, name: str) -> bool:
        if not voreinstellungen.vorhanden(name):
            return True
        return QMessageBox.question(
            self, _("Voreinstellung ersetzen"),
            _("Die Voreinstellung „{name}“ gibt es schon. Ersetzen?").format(name=name)
        ) == QMessageBox.StandardButton.Yes

    def voreinstellung_sichern(self):
        if self.sitzung is None:
            return
        dialog = VoreinstellungDialog(self, self._auswahl_vorgabe(), True,
                                      self.vor_wahl.currentText())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, auswahl = dialog.gewaehlter_name(), dialog.auswahl()
        self._auswahl_merken(auswahl)
        if not self._ersetzen_ok(name):
            return
        daten = self._werte_fuer_voreinstellung(auswahl)
        if daten is None:
            return
        try:
            voreinstellungen.sichern(name, daten)
        except voreinstellungen.VoreinstellungFehler as fehler:
            self._fehler(_("Die Voreinstellung lässt sich nicht sichern."), str(fehler))
            return
        self._voreinstellungen_auffrischen(name)
        self.fenster.melden(_("Voreinstellung „{name}“ gesichert.").format(name=name))

    def voreinstellung_anwenden(self):
        name = self.vor_wahl.currentText()
        if self.sitzung is None or not name:
            return
        try:
            daten = voreinstellungen.laden(name)
        except voreinstellungen.VoreinstellungFehler as fehler:
            self._fehler(_("Die Voreinstellung lässt sich nicht lesen."), str(fehler))
            return
        if self._einstellungen_uebernehmen(daten, "voreinstellung"):
            self.fenster.melden(_("Voreinstellung „{name}“ angewendet.").format(name=name))

    def voreinstellung_loeschen(self):
        name = self.vor_wahl.currentText()
        if not name or QMessageBox.question(
                self, _("Voreinstellung löschen"),
                _("Die Voreinstellung „{name}“ löschen?").format(name=name)
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            voreinstellungen.loeschen(name)
        except voreinstellungen.VoreinstellungFehler as fehler:
            self._fehler(_("Die Voreinstellung lässt sich nicht löschen."), str(fehler))
        self._voreinstellungen_auffrischen("")

    def voreinstellung_importieren(self):
        pfad, _filter = QFileDialog.getOpenFileName(
            self, _("Voreinstellung importieren"), self._letzter_ordner(),
            _("Voreinstellung (*.json)"))
        if not pfad:
            return
        try:
            voreinstellungen.datei_lesen(pfad)          # erst pruefen, dann nach dem Namen fragen
        except voreinstellungen.VoreinstellungFehler as fehler:
            self._fehler(_("Die Datei ist keine lesbare Voreinstellung."), str(fehler))
            return
        name, ok = QInputDialog.getText(self, _("Voreinstellung importieren"), _("Name"),
                                        text=voreinstellungen.vorgeschlagener_name(pfad))
        if not ok:
            return
        name = voreinstellungen.name_pruefen(name)
        if name is None:
            self._fehler(_("Dieser Name taugt nicht für eine Voreinstellung."), "")
            return
        if not self._ersetzen_ok(name):
            return
        try:
            voreinstellungen.importieren(pfad, name)
        except voreinstellungen.VoreinstellungFehler as fehler:
            self._fehler(_("Die Datei ist keine lesbare Voreinstellung."), str(fehler))
            return
        self._voreinstellungen_auffrischen(name)
        self.fenster.melden(_("Voreinstellung „{name}“ importiert.").format(name=name))

    def voreinstellung_exportieren(self):
        name = self.vor_wahl.currentText()
        if not name:
            return
        pfad, _filter = QFileDialog.getSaveFileName(
            self, _("Voreinstellung exportieren"),
            os.path.join(self._letzter_ordner(), name + voreinstellungen.ENDUNG),
            _("Voreinstellung (*.json)"))
        if not pfad:
            return
        try:
            voreinstellungen.datei_schreiben(pfad, voreinstellungen.laden(name))
        except voreinstellungen.VoreinstellungFehler as fehler:
            self._fehler(_("Die Voreinstellung lässt sich nicht exportieren."), str(fehler))
            return
        self.fenster.melden(_("Voreinstellung exportiert: {name}")
                            .format(name=os.path.basename(pfad)))

    def einstellungen_kopieren(self):
        if self.sitzung is None:
            return
        dialog = VoreinstellungDialog(self, self._auswahl_vorgabe(), False)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        auswahl = dialog.auswahl()
        self._auswahl_merken(auswahl)
        daten = self._werte_fuer_voreinstellung(auswahl)
        if daten is None:
            return
        self._zwischenablage = daten
        self._voreinstellungen_freischalten()
        self.fenster.melden(_("Einstellungen kopiert – mit Strg+Umschalt+V auf ein anderes "
                              "Bild legen."))

    def einstellungen_einfuegen(self):
        if self.sitzung is None or self._zwischenablage is None:
            return
        if self._einstellungen_uebernehmen(self._zwischenablage, "einfuegen"):
            self.fenster.melden(_("Einstellungen eingefügt."))

    def _einstellungen_uebernehmen(self, daten: dict, schritt: str) -> bool:
        """Eine Voreinstellung oder kopierte Einstellungen auf das Bild legen - als ein
        Schritt fuer Rueckgaengig."""
        sitzung = self.sitzung
        try:
            gelesen = voreinstellungen.anwenden(daten, sitzung.werte)
        except voreinstellungen.VoreinstellungFehler as fehler:
            self._fehler(_("Die Voreinstellung lässt sich nicht lesen."), str(fehler))
            return False
        werte = gelesen.ergebnis.werte
        if "objektivprofil" in gelesen.ergebnis.felder:
            werte.objektivprofil = (sitzung.objektiv_terme() if gelesen.ergebnis.objektivprofil
                                    else ())
        if gelesen.film_schaetzen:
            werte.film_maske, werte.film_umfang = sitzung.film_schaetzen(werte.film)
        self.zuschnitt_abbrechen()
        self._festhalten(sofort=True)             # eine eben gemachte Aenderung zuerst
        self._schritt_name = schritt
        sitzung.werte = werte
        self._alles_anzeigen()
        self.zeichnen_anfordern()
        if gelesen.ergebnis.verworfen:
            self._fehler(_("Einige Werte waren ungültig und wurden übergangen."),
                         ", ".join(gelesen.ergebnis.verworfen))
        return True

    # ------------------------------------------------------------------
    # Begleitdatei: die Bearbeitung neben dem Bild (begleitdatei.py)
    # ------------------------------------------------------------------

    def _begleitdateien_erlaubt(self) -> bool:
        """Darf Silberkorn Begleitdateien schreiben? Beim ersten Mal wird gefragt."""
        erlaubt = einstellungen.begleitdateien()
        if erlaubt is not None:
            return erlaubt
        antwort = QMessageBox.question(
            self, _("Bearbeitung neben dem Bild sichern?"),
            _("Silberkorn kann die Bearbeitung in einer kleinen Begleitdatei neben dem Bild "
              "sichern – „{name}“. Wird das Bild später wieder geöffnet, ist alles wie zuvor: "
              "Regler, entfernte Objekte, Staub, Maske und KI-Erweiterung. Das Bild selbst "
              "bleibt unverändert.\n\nBegleitdateien anlegen? Das lässt sich oben über "
              "„Begleitdateien“ jederzeit ändern.").format(
                name=os.path.basename(begleitdatei.pfad_fuer(self.sitzung.daten.pfad))),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        erlaubt = antwort == QMessageBox.StandardButton.Yes
        einstellungen.begleitdateien_setzen(erlaubt)
        self.fenster.begleitdateien_anzeigen()
        return erlaubt

    def begleitdatei_sichern(self) -> bool:
        """Die Bearbeitung neben das Bild schreiben, wenn sie sich geaendert hat - ist alles
        zurueckgesetzt, die Begleitdatei loeschen. Rueckgabe: ob nichts verloren geht."""
        sitzung = self.sitzung
        if sitzung is None or not sitzung.begleit_geaendert:
            return True
        if not self._begleitdateien_erlaubt():
            return False
        pfad = sitzung.daten.pfad
        if not sitzung.bearbeitet:
            if begleitdatei.entfernen(pfad):
                ordner_seite.begleitdatei_geaendert(self.fenster, pfad)
            sitzung.begleit_gesichert()
            return True
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            inhalt = sitzung.begleit_inhalt(sitzung.begleit_vorschau())
            begleitdatei.schreiben(pfad, inhalt, begleitdatei.fingerabdruck(pfad), VERSION)
        except begleitdatei.BegleitFehler:
            self.fenster.melden(_("Die Bearbeitung ließ sich nicht neben dem Bild sichern – "
                                  "der Ordner ist schreibgeschützt oder nicht erreichbar."),
                                fehler=True)
            return False
        except cp.cuda.memory.OutOfMemoryError:
            self.fenster.melden(_("Für dieses Bild reicht der Grafikspeicher nicht."),
                                fehler=True)
            return False
        finally:
            QApplication.restoreOverrideCursor()
        sitzung.begleit_gesichert()
        ordner_seite.begleitdatei_geaendert(self.fenster, pfad)
        return True

    def _begleitdatei_laden(self) -> bool:
        """Liegt neben dem eben geoeffneten Bild eine Begleitdatei, ihre Bearbeitung
        uebernehmen. Rueckgabe: ob etwas uebernommen wurde."""
        sitzung = self.sitzung
        pfad = sitzung.daten.pfad
        if not os.path.isfile(begleitdatei.pfad_fuer(pfad)):
            return False
        hoehe, breite = sitzung.original.shape[:2]
        try:
            with _sanduhr():
                inhalt = begleitdatei.lesen(pfad, hoehe, breite, sitzung.grundwerte())
            if not inhalt.passt and QMessageBox.question(
                    self, _("Begleitdatei passt nicht"),
                    _("Die Begleitdatei zu {name} gehört zu einer anderen Fassung des Bildes – "
                      "das Bild wurde seither verändert. Nur die Reglerwerte übernehmen? "
                      "Entfernte Objekte, Staub, Maske und KI-Erweiterung gehen dabei nicht "
                      "mit.").format(name=sitzung.daten.name)
            ) != QMessageBox.StandardButton.Yes:
                return False
            with _sanduhr():
                sitzung.begleit_anwenden(inhalt)
            if not inhalt.passt:
                sitzung.begleit_veraltet()        # beim Verlassen fuer dieses Bild neu schreiben
        except begleitdatei.BegleitFehler as fehler:
            self._fehler(_("Die Begleitdatei lässt sich nicht lesen – das Bild ist "
                           "unbearbeitet geöffnet."), str(fehler))
            return False
        except cp.cuda.memory.OutOfMemoryError:
            self._fehler(_("Für dieses Bild reicht der Grafikspeicher nicht."), "")
            return False
        if inhalt.verworfen:
            self._fehler(_("Einige Werte waren ungültig und wurden übergangen."),
                         ", ".join(inhalt.verworfen))
        return True

    def _ki_neu_rechnen_anbieten(self):
        """Nach dem Oeffnen einer Begleitdatei: KI-Entrauschen, -Schaerfen und -Kolorieren
        neu berechnen - sie stehen nicht darin."""
        sitzung = self.sitzung
        if sitzung is None:
            return
        stufe = self._ki_stufe()
        offen = []
        for gruppe in sitzung.ki_neu_zu_rechnen():
            modell = self._ki_bild_art(gruppe)["modell"]
            if ki.angeboten(modell, stufe) and ki.vorhanden(modell):
                offen.append(gruppe)
        if not offen:
            return
        antwort = QMessageBox.question(
            self, _("KI-Schritte neu berechnen"),
            _("Die gesicherte Bearbeitung nutzt {schritte}. Diese Ergebnisse stehen nicht in "
              "der Begleitdatei, sie werden für das Bild neu berechnet. Jetzt berechnen?")
            .format(schritte=", ".join(gruppen_titel(g) for g in offen)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if antwort != QMessageBox.StandardButton.Yes:
            return
        gesichert = not sitzung.begleit_geaendert
        for gruppe in offen:
            if not self.ki_bild_berechnen(gruppe):
                break
        if self.sitzung is not sitzung:
            return
        if gesichert:
            sitzung.begleit_gesichert()           # gerechnet ist, was die Datei verlangt
        self._verlauf_beginnen()                  # Rueckgaengig beginnt beim fertigen Stand

    # ------------------------------------------------------------------
    # Oeffnen und Speichern
    # ------------------------------------------------------------------

    def _letzter_ordner(self) -> str:
        ordner = einstellungen.load_config().get("letzter_ordner", "")
        return ordner if os.path.isdir(ordner) else os.path.expanduser("~")

    def _letzten_ordner_merken(self, pfad: str):
        daten = einstellungen.load_config()
        daten["letzter_ordner"] = os.path.dirname(pfad)
        einstellungen.save_config(daten)

    def aenderungen_verwerfen_ok(self) -> bool:
        """Vor dem Wechsel des Bildes oder dem Beenden: die Bearbeitung in die Begleitdatei -
        geht das nicht, wird nachgefragt, bevor ungespeicherte Aenderungen verloren gehen."""
        if self.sitzung is None or self.begleitdatei_sichern() or not self.sitzung.geaendert:
            return True
        antwort = QMessageBox.question(
            self, _("Ungespeicherte Änderungen"),
            _("Die Änderungen an {name} sind nicht gespeichert. Trotzdem fortfahren?")
            .format(name=self.sitzung.daten.name),
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return antwort == QMessageBox.StandardButton.Discard

    def oeffnen_dialog(self):
        def muster(endungen):
            return " ".join(f"*{e}" for e in endungen)
        filterliste = ";;".join([
            f"{_('Alle Bilder')} ({muster(bilddatei.LESBAR)})",
            f"{_('Bilder')} ({muster(bilddatei.BILDER)})",
            f"RAW ({muster(bilddatei.RAW)})",
        ])
        pfad, _filter = QFileDialog.getOpenFileName(
            self, _("Bild öffnen"), self._letzter_ordner(), filterliste)
        if pfad:
            self.oeffnen(pfad)

    def oeffnen(self, pfad: str):
        if os.path.splitext(pfad)[1].lower() not in bilddatei.LESBAR:
            self.fenster.melden(_("Dieses Dateiformat wird nicht unterstützt."), fehler=True)
            return
        if not self.aenderungen_verwerfen_ok():
            return
        if os.path.splitext(pfad)[1].lower() in bilddatei.RAW:
            # LibRaw entwickelt auf dem Prozessor; das dauert einige Sekunden.
            self.fenster.melden(_("RAW wird entwickelt …"))
            QApplication.processEvents()
        self.auswahl_beenden()
        self.pinsel_beenden()
        self._klick_marken = {"maske": [], "entfernen": []}
        self._entferner = None
        self.tiefe_zeigen_box.setChecked(False)
        self.staub_zeigen_box.blockSignals(True)
        self.staub_zeigen_box.setChecked(False)
        self.staub_zeigen_box.blockSignals(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            daten = bilddatei.laden(pfad, raw_qualitaet=einstellungen.raw_qualitaet())
            if self.sitzung is not None:
                self.verlauf.leeren()             # haelt sonst Grafikspeicher des alten Bildes
                self.sitzung.schliessen()
                self.sitzung = None
                self._verlauf_anzeigen()
            self.sitzung = Sitzung(daten, self._vorschau_kante())
            self.sitzung.angaben_vorgeben(*self._vorgabe_werte())
            _film = self.sitzung.infrarot_film     # pruefen, solange die Sanduhr laeuft
        except bilddatei.BildFehler as fehler:
            self._fehler(_("Die Datei lässt sich nicht öffnen."), str(fehler))
            return
        except cp.cuda.memory.OutOfMemoryError:
            self._fehler(_("Für dieses Bild reicht der Grafikspeicher nicht."), "")
            return
        finally:
            QApplication.restoreOverrideCursor()

        geladen = self._begleitdatei_laden()
        self._letzten_ordner_merken(pfad)
        self.leinwand.zuschnitt = None
        self.zuschneiden_knopf.setChecked(False)
        self.leinwand.zoom = None
        self._alles_anzeigen()
        self._knoepfe_freischalten()
        self._verlauf_beginnen()
        if geladen:
            self.fenster.melden(_("{name} geöffnet – mit der gesicherten Bearbeitung")
                                .format(name=daten.name))
            QTimer.singleShot(0, self._ki_neu_rechnen_anbieten)
        else:
            self.fenster.melden(_("{name} geöffnet – {breite} × {hoehe} Pixel, {art}")
                                .format(name=daten.name, breite=daten.breite,
                                        hoehe=daten.hoehe, art=art_anzeige(daten)))
        self.zeichnen_anfordern()

    def speichern_dialog(self):
        if self.sitzung is None:
            return
        daten = self.sitzung.daten
        stamm, endung = os.path.splitext(daten.pfad)
        endung = endung.lower()
        formate = speicherformate()
        if daten.raw or daten.bits == 16:
            # Mehr als 8 Bit im Original: als 16-Bit-TIFF vorschlagen, damit nichts verloren geht
            endung, vorauswahl = ".tif", formate[4][0]
        else:
            if endung not in bilddatei.SCHREIBBAR:
                endung = ".jpg"
            vorauswahl = next(b for b, e, bits in formate
                              if bits == 8 and e == {".jpeg": ".jpg", ".tiff": ".tif"}
                              .get(endung, endung))
        freistellen = self.sitzung.werte.freistellen and self.sitzung.ki_maske_da
        if freistellen and endung not in (".png", ".tif"):
            endung, vorauswahl = ".png", formate[1][0]     # Durchsichtigkeit braucht Alpha
        pfad, gewaehlt = QFileDialog.getSaveFileName(
            self, _("Bild speichern"), f"{stamm}-bearbeitet{endung}",
            ";;".join(b for b, _e, _bits in formate), vorauswahl)
        if not pfad:
            return
        pfad, bits = ziel_bestimmen(pfad, gewaehlt)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        fortschritt_fenster = None
        try:
            auftrag = self._ki_auftrag()
            fortschritt = None
            if auftrag is not None:
                fortschritt_fenster = QProgressDialog(_("KI vergrößert das Bild …"),
                                                      _("Abbrechen"), 0, 100, self)
                fortschritt_fenster.setWindowTitle(self.fenster.windowTitle())
                fortschritt_fenster.setWindowModality(Qt.WindowModality.WindowModal)
                fortschritt_fenster.setMinimumDuration(0)

                def fortschritt(nummer, anzahl):
                    fortschritt_fenster.setValue(round(100 * nummer / anzahl))
                    QApplication.processEvents()
                    return not fortschritt_fenster.wasCanceled()
            ms = self.sitzung.exportieren(pfad, bits, auftrag, fortschritt)
        except ki.KiAbbruch:
            self.fenster.melden(_("Speichern abgebrochen."))
            return
        except ki.KiFehler as fehler:
            self._fehler(_("Die KI-Vergrößerung ist fehlgeschlagen."), str(fehler))
            return
        except bilddatei.BildFehler as fehler:
            self._fehler(_("Das Bild lässt sich nicht speichern."), str(fehler))
            return
        except cp.cuda.memory.OutOfMemoryError:
            self._fehler(_("Für dieses Bild reicht der Grafikspeicher nicht."), "")
            return
        finally:
            QApplication.restoreOverrideCursor()
            if fortschritt_fenster is not None:
                fortschritt_fenster.close()
        self._letzten_ordner_merken(pfad)
        if auftrag is not None:
            self.fenster.melden(_("Gespeichert: {name} ({ms} ms, KI über {weg})").format(
                name=os.path.basename(pfad), ms=f"{ms:.0f}", weg=auftrag[0].beschleuniger))
            return
        if freistellen and not bilddatei.SCHREIBBAR[os.path.splitext(pfad)[1].lower()][1]:
            self.fenster.melden(_("Gespeichert: {name} – ohne durchsichtigen Hintergrund, "
                                  "das kann JPEG nicht. Als PNG oder TIFF speichern.")
                                .format(name=os.path.basename(pfad)), fehler=True)
            return
        self.fenster.melden(_("Gespeichert: {name} ({ms} ms)")
                            .format(name=os.path.basename(pfad), ms=f"{ms:.0f}"))

    def veroeffentlichen_dialog(self):
        if self.sitzung is None:
            return
        sitzung = self.sitzung
        # Die Vorschau ohne eingeblendete Maske, Tiefe und Markierungen
        zeigen = sitzung.maske_zeigen, sitzung.tiefe_zeigen
        sitzung.maske_zeigen = sitzung.tiefe_zeigen = False
        try:
            vorschau, _ms, _histogramm = sitzung.vorschau()
        finally:
            sitzung.maske_zeigen, sitzung.tiefe_zeigen = zeigen
        daten = einstellungen.load_config()
        vorlage = veroeffentlichen.Vorlage.aus_dict(daten.get("veroeffentlichen"))
        dialog = VeroeffentlichenDialog(self, vorschau, sitzung.ausgabe_form(), vorlage,
                                        sitzung.ki_inhalt)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        vorlage = dialog.vorlage()
        daten["veroeffentlichen"] = vorlage.als_dict()
        einstellungen.save_config(daten)

        formate = veroeffentlichen_formate()
        stamm = os.path.splitext(sitzung.daten.pfad)[0]
        pfad, gewaehlt = QFileDialog.getSaveFileName(
            self, _("Für Veröffentlichung speichern"), f"{stamm}-web{vorlage.format}",
            ";;".join(b for b, _e in formate),
            next(b for b, e in formate if e == vorlage.format))
        if not pfad:
            return
        endung = os.path.splitext(pfad)[1].lower()
        if endung not in (".jpg", ".jpeg", ".png", ".webp", ".avif"):
            pfad += dict(formate).get(gewaehlt, ".jpg")
            endung = os.path.splitext(pfad)[1].lower()
        vorlage = dialog.mit_format(".jpg" if endung == ".jpeg" else endung)
        daten = einstellungen.load_config()
        daten["veroeffentlichen"] = vorlage.als_dict()
        daten["letzter_ordner"] = os.path.dirname(pfad)
        einstellungen.save_config(daten)

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ms, (breite, hoehe) = sitzung.veroeffentlichen(pfad, vorlage)
        except bilddatei.BildFehler as fehler:
            self._fehler(_("Das Bild lässt sich nicht speichern."), str(fehler))
            return
        except cp.cuda.memory.OutOfMemoryError:
            self._fehler(_("Für dieses Bild reicht der Grafikspeicher nicht."), "")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.fenster.melden(_("Für Veröffentlichung gespeichert: {name} – {breite} × {hoehe} "
                              "Pixel ({ms} ms)").format(name=os.path.basename(pfad),
                                                        breite=breite, hoehe=hoehe,
                                                        ms=f"{ms:.0f}"))

    def drucken_dialog(self):
        if self.sitzung is None:
            return
        sitzung = self.sitzung
        zeigen = sitzung.maske_zeigen, sitzung.tiefe_zeigen
        sitzung.maske_zeigen = sitzung.tiefe_zeigen = False
        try:
            vorschau, _ms, _histogramm = sitzung.vorschau()
        finally:
            sitzung.maske_zeigen, sitzung.tiefe_zeigen = zeigen
        daten = einstellungen.load_config()
        vorgaben = drucken.Vorgaben.aus_dict(daten.get("drucken"))
        modell = self._ki_modell()
        ki_moeglich = ki.angeboten(modell, self._ki_stufe()) and ki.vorhanden(modell)
        dialog = DruckenDialog(self, vorschau, sitzung.ausgabe_form(), vorgaben, ki_moeglich)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        daten = einstellungen.load_config()
        daten["drucken"] = dialog.vorgaben().als_dict()
        einstellungen.save_config(daten)
        drucker, platz, faktor = dialog.drucker(), dialog.platz(), dialog.ki_faktor()
        if drucker is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        anzeige = None
        try:
            fortschritt = None
            auftrag = self._ki_auftrag(faktor) if faktor else None
            if auftrag is not None:
                anzeige = QProgressDialog(_("KI vergrößert das Bild …"), _("Abbrechen"),
                                          0, 100, self)
                anzeige.setWindowTitle(self.fenster.windowTitle())
                anzeige.setWindowModality(Qt.WindowModality.WindowModal)
                anzeige.setMinimumDuration(0)

                def fortschritt(nummer, anzahl):
                    anzeige.setValue(round(100 * nummer / anzahl))
                    QApplication.processEvents()
                    return not anzeige.wasCanceled()
            rgb = sitzung.druckbild(auftrag, fortschritt)
            drucken.drucken(drucker, rgb, platz, faktor or 1)
        except ki.KiAbbruch:
            self.fenster.melden(_("Drucken abgebrochen."))
            return
        except ki.KiFehler as fehler:
            self._fehler(_("Die KI-Vergrößerung ist fehlgeschlagen."), str(fehler))
            return
        except OSError as fehler:
            self._fehler(_("Das Bild ließ sich nicht drucken."), str(fehler))
            return
        except cp.cuda.memory.OutOfMemoryError:
            self._fehler(_("Für dieses Bild reicht der Grafikspeicher nicht."), "")
            return
        finally:
            QApplication.restoreOverrideCursor()
            if anzeige is not None:
                anzeige.close()
        self.fenster.melden(_("An {drucker} gesendet.").format(drucker=drucker.printerName()))

    def _fehler(self, text: str, einzelheiten: str):
        box = QMessageBox(QMessageBox.Icon.Warning, self.fenster.windowTitle(), text,
                          QMessageBox.StandardButton.Ok, self)
        if einzelheiten:
            box.setDetailedText(einzelheiten)
        box.exec()
        self.fenster.melden(text, fehler=True)

    def _vorschau_kante(self) -> int:
        """Laengste Kante der Vorschau: so gross wie der Bildschirm in echten Pixeln."""
        bildschirm = QGuiApplication.primaryScreen()
        groesse = bildschirm.size() * bildschirm.devicePixelRatio()
        return max(1024, min(4096, max(groesse.width(), groesse.height())))

    def schliessen(self):
        self.verlauf.leeren()
        if self.sitzung is not None:
            self.sitzung.schliessen()
            self.sitzung = None
