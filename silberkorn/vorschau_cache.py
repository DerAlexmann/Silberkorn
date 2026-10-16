"""
Vorschau-Cache: kleine Vorschaubilder teurer Dateien, verschluesselt und gedeckelt

Fuer die Ordneransicht. Die meisten Vorschaubilder kosten fast nichts - RAWs
und Kamera-JPEGs bringen eins mit, JPEGs lassen sich auf ein Achtel verkleinert
lesen. Teuer sind grosse TIFFs und PNGs, etwa Scans; nur sie kommen hierher.

Der Cache ist eine einzige SQLite-Datei mit fester Groesse, die der Anwender
waehlt:

- Vorbelegt: Beim Anlegen wird die Datei einmal auf die volle Groesse
  geschrieben und wieder geleert. SQLite gibt den Platz nicht zurueck
  (auto_vacuum aus) und verwendet die freien Seiten wieder - die Datei bleibt so
  gross wie gewaehlt, ohne spaeter zu ueberraschen.
- Gedeckelt: max_page_count laesst SQLite nie ueber die Groesse wachsen. Ist
  der Cache voll, weichen die am laengsten nicht gesehenen Bilder.
- Verschluesselt: Jedes Vorschaubild und jeder Pfad ist mit DPAPI fuer den
  angemeldeten Benutzer verschluesselt (dpapi.py). Gesucht wird ueber einen
  HMAC des Pfads mit einem Geheimnis, das selbst per DPAPI geschuetzt ist - so
  laesst sich auch fuer einen bekannten Pfad nicht pruefen, ob er im Cache ist.
  Laesst sich das Geheimnis nicht oeffnen (anderer Benutzer, kopierte Datei),
  wird der Cache verworfen und neu angelegt.
- Geloescht ist geloescht: secure_delete ueberschreibt freigegebene Seiten mit
  Nullen; das Journal (TRUNCATE) wird nach jedem Schreiben geleert und waechst
  nicht wie eine WAL-Datei.

Ohne DPAPI (nicht Windows) gibt es keinen Cache - nie einen im Klartext.

Ein Cache gehoert einem Thread: SQLite-Verbindungen lassen sich nicht teilen.
Die Ordneransicht benutzt ihn nur aus ihrem Hintergrund-Thread.

Dieses Modul kennt weder Qt noch die Grafikkarte.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import shutil
import sqlite3
import time

from . import dpapi

FORMAT = 1
DATEINAME = "vorschau.db"
SEITE = 4096
VORSCHLAG_MB = 200
MIN_MB = 16
MAX_MB = 100_000
RESERVE = 64 * 2**20          # so viel bleibt auf der Platte mindestens frei
ENTROPIE = b"Silberkorn-Vorschau-Cache-1"
FUELLBLOCK = 2**20
WEICHEN_ANTEIL = 0.05         # ist der Cache voll, weicht so viel auf einmal


class CacheFehler(Exception):
    """Der Cache laesst sich nicht anlegen oder benutzen."""


def standard_ordner() -> str:
    basis = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(basis, "Silberkorn")


def normalisiert(pfad: str) -> str:
    """Ein Pfad in einer Form - gleich, wie er geschrieben wurde."""
    return os.path.normcase(os.path.realpath(os.path.abspath(pfad)))


def ausgenommen(pfad: str, ordner: list[str]) -> bool:
    """Liegt pfad in einem der Ordner (oder darunter)?"""
    ziel = normalisiert(pfad)
    for eintrag in ordner:
        basis = normalisiert(eintrag)
        try:
            if os.path.commonpath([ziel, basis]) == basis:
                return True
        except ValueError:                    # anderes Laufwerk
            continue
    return False


def platz_frei(ordner: str) -> int:
    """Wie viel Byte ein Cache in diesem Ordner hoechstens belegen kann."""
    pruefen = ordner
    while not os.path.isdir(pruefen):
        oben = os.path.dirname(pruefen)
        if oben == pruefen:
            return 0
        pruefen = oben
    return max(0, shutil.disk_usage(pruefen).free - RESERVE)


class VorschauCache:
    def __init__(self, pfad: str, groesse: int):
        """Oeffnet den Cache oder legt ihn an - vorbelegt auf groesse Byte. CacheFehler,
        wenn DPAPI fehlt, der Platz nicht reicht oder die Datei nicht zu benutzen ist."""
        if not dpapi.verfuegbar():
            raise CacheFehler("ohne DPAPI kein Cache")
        self.pfad = pfad
        self.groesse = max(MIN_MB * 2**20, int(groesse)) // SEITE * SEITE
        self._db: sqlite3.Connection | None = None
        try:
            self._oeffnen()
        except (sqlite3.Error, dpapi.DpapiFehler, CacheFehler):
            # Fremder Benutzer, kaputte oder alte Datei: verwerfen und neu anlegen
            self.schliessen()
            self._datei_entfernen()
            try:
                self._oeffnen()
            except (sqlite3.Error, dpapi.DpapiFehler, CacheFehler) as fehler:
                self.schliessen()
                self._datei_entfernen()
                raise CacheFehler(str(fehler)) from fehler

    # ------------------------------------------------------------------

    def _oeffnen(self):
        neu = not os.path.exists(self.pfad)
        if neu:
            os.makedirs(os.path.dirname(os.path.abspath(self.pfad)), exist_ok=True)
        self._db = sqlite3.connect(self.pfad, timeout=2.0, isolation_level=None)
        db = self._db
        if neu:
            db.execute(f"PRAGMA page_size = {SEITE}")
            db.execute("PRAGMA auto_vacuum = NONE")
        db.execute("PRAGMA secure_delete = ON")
        db.execute("PRAGMA journal_mode = TRUNCATE")
        db.execute("PRAGMA synchronous = NORMAL")    # ein Cache: Verlust kostet nur Zeit
        db.execute("PRAGMA busy_timeout = 2000")
        db.execute("CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, wert BLOB)")
        db.execute("CREATE TABLE IF NOT EXISTS bilder (schluessel BLOB PRIMARY KEY, "
                   "merkmal BLOB NOT NULL, pfad BLOB NOT NULL, daten BLOB NOT NULL, "
                   "zuletzt INTEGER NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS bilder_zuletzt ON bilder (zuletzt)")
        if neu:
            geheimnis = secrets.token_bytes(32)
            db.execute("INSERT INTO meta VALUES ('format', ?)", (FORMAT,))
            db.execute("INSERT INTO meta VALUES ('geheimnis', ?)",
                       (dpapi.schuetzen(geheimnis, ENTROPIE),))
        zeilen = dict(db.execute("SELECT name, wert FROM meta"))
        if zeilen.get("format") != FORMAT or "geheimnis" not in zeilen:
            raise CacheFehler("unbekanntes Format")
        self._geheimnis = dpapi.oeffnen(bytes(zeilen["geheimnis"]), ENTROPIE)
        if len(self._geheimnis) != 32:
            raise CacheFehler("ungültiges Geheimnis")
        if db.execute("PRAGMA page_size").fetchone()[0] != SEITE:
            raise CacheFehler("andere Seitengröße")
        self._deckeln()

    def _deckeln(self):
        """Groesse setzen: SQLite waechst nie darueber; fehlender Platz wird vorbelegt."""
        db = self._db
        seiten = self.groesse // SEITE
        jetzt = db.execute("PRAGMA page_count").fetchone()[0]
        if jetzt > seiten:
            raise CacheFehler("Datei größer als der Deckel")
        if jetzt < seiten:
            ordner = os.path.dirname(os.path.abspath(self.pfad))
            if platz_frei(ordner) < (seiten - jetzt) * SEITE:
                raise CacheFehler("zu wenig Platz")
        db.execute(f"PRAGMA max_page_count = {seiten}")
        if jetzt < seiten:
            self._vorbelegen()

    def _vorbelegen(self):
        """Mit Nullen fuellen und wieder freigeben. Die Nullen muessen beim Freigeben nicht
        noch einmal ueberschrieben werden, und erst am Ende muss alles auf der Platte sein."""
        db = self._db
        db.execute("PRAGMA secure_delete = OFF")
        db.execute("PRAGMA synchronous = OFF")
        try:
            self._fuellen()
        finally:
            db.execute("PRAGMA synchronous = NORMAL")
            db.execute("PRAGMA secure_delete = ON")

    def _fuellen(self):
        db = self._db
        db.execute("CREATE TABLE IF NOT EXISTS fuellung (x BLOB)")
        try:
            while True:
                db.execute("INSERT INTO fuellung VALUES (zeroblob(?))", (FUELLBLOCK,))
        except sqlite3.OperationalError as fehler:
            if "full" not in str(fehler).lower():
                raise
        try:
            while True:                       # die letzten Seiten in kleineren Stuecken
                db.execute("INSERT INTO fuellung VALUES (zeroblob(?))", (SEITE * 4,))
        except sqlite3.OperationalError as fehler:
            if "full" not in str(fehler).lower():
                raise
        db.execute("DROP TABLE fuellung")

    def _datei_entfernen(self):
        for endung in ("", "-journal"):
            try:
                os.remove(self.pfad + endung)
            except FileNotFoundError:
                pass
            except OSError as fehler:
                raise CacheFehler(str(fehler)) from fehler

    def schliessen(self):
        if self._db is not None:
            try:
                self._db.close()
            except sqlite3.Error:
                pass
            self._db = None

    # ------------------------------------------------------------------

    def _schluessel(self, pfad: str) -> bytes:
        return hmac.new(self._geheimnis, normalisiert(pfad).encode("utf-8"),
                        hashlib.sha256).digest()

    def _merkmal(self, pfad: str) -> bytes | None:
        """Groesse und Aenderungszeit der Datei - aendert sich das Bild, passt es nicht mehr."""
        try:
            stat = os.stat(pfad)
        except OSError:
            return None
        return hmac.new(self._geheimnis, f"{stat.st_size}:{stat.st_mtime_ns}".encode(),
                        hashlib.sha256).digest()

    def holen(self, pfad: str) -> bytes | None:
        """Das Vorschaubild zu pfad - oder None, wenn es fehlt oder das Bild sich seither
        geaendert hat (dann faellt der alte Eintrag weg)."""
        schluessel = self._schluessel(pfad)
        try:
            zeile = self._db.execute("SELECT merkmal, daten FROM bilder WHERE schluessel = ?",
                                     (schluessel,)).fetchone()
            if zeile is None:
                return None
            if bytes(zeile[0]) != self._merkmal(pfad):
                self._db.execute("DELETE FROM bilder WHERE schluessel = ?", (schluessel,))
                return None
            daten = dpapi.oeffnen(bytes(zeile[1]), ENTROPIE)
            self._db.execute("UPDATE bilder SET zuletzt = ? WHERE schluessel = ?",
                             (time.time_ns(), schluessel))
            return daten
        except dpapi.DpapiFehler:
            self.vergessen(pfad)
            return None
        except sqlite3.Error:
            return None

    def ablegen(self, pfad: str, daten: bytes) -> bool:
        """Ein Vorschaubild ablegen - ist der Cache voll, weichen die aeltesten."""
        merkmal = self._merkmal(pfad)
        if merkmal is None:
            return False
        zeile = (self._schluessel(pfad), merkmal,
                 dpapi.schuetzen(normalisiert(pfad).encode("utf-8"), ENTROPIE),
                 dpapi.schuetzen(daten, ENTROPIE), time.time_ns())
        for _versuch in range(4):
            try:
                self._db.execute("INSERT OR REPLACE INTO bilder VALUES (?, ?, ?, ?, ?)", zeile)
                return True
            except sqlite3.OperationalError as fehler:
                if "full" not in str(fehler).lower() or not self._weichen():
                    return False
            except sqlite3.Error:
                return False
        return False

    def _weichen(self) -> bool:
        """Die am laengsten nicht gesehenen Bilder entfernen; Rueckgabe: ob es welche gab."""
        anzahl = self._db.execute("SELECT COUNT(*) FROM bilder").fetchone()[0]
        if anzahl == 0:
            return False
        weg = max(1, int(anzahl * WEICHEN_ANTEIL))
        self._db.execute("DELETE FROM bilder WHERE schluessel IN (SELECT schluessel FROM "
                         "bilder ORDER BY zuletzt LIMIT ?)", (weg,))
        return True

    def vergessen(self, pfad: str):
        try:
            self._db.execute("DELETE FROM bilder WHERE schluessel = ?",
                             (self._schluessel(pfad),))
        except sqlite3.Error:
            pass

    def aufraeumen(self, zeitlimit: float = 2.0, ab: int = 0) -> int:
        """Eintraege entfernen, deren Bild es nicht mehr gibt oder das sich geaendert hat.
        Arbeitet hoechstens zeitlimit Sekunden; Rueckgabe: wo es weitergeht (rowid), 0 am
        Ende."""
        ende = time.monotonic() + zeitlimit
        try:
            zeilen = self._db.execute("SELECT rowid, pfad, merkmal FROM bilder WHERE rowid > ? "
                                      "ORDER BY rowid", (ab,)).fetchall()
        except sqlite3.Error:
            return 0
        for rowid, verschluesselt, merkmal in zeilen:
            if time.monotonic() > ende:
                return rowid - 1
            try:
                pfad = dpapi.oeffnen(bytes(verschluesselt), ENTROPIE).decode("utf-8")
                ok = bytes(merkmal) == self._merkmal(pfad)
            except (dpapi.DpapiFehler, UnicodeDecodeError):
                ok = False
            if not ok:
                try:
                    self._db.execute("DELETE FROM bilder WHERE rowid = ?", (rowid,))
                except sqlite3.Error:
                    return 0
        return 0

    def leeren(self):
        """Alle Vorschaubilder loeschen - die Seiten werden ueberschrieben, die Datei bleibt
        so gross wie gewaehlt."""
        self._db.execute("DELETE FROM bilder")

    def belegt(self) -> int:
        """Wie viel Byte die Vorschaubilder belegen."""
        seiten = self._db.execute("PRAGMA page_count").fetchone()[0]
        frei = self._db.execute("PRAGMA freelist_count").fetchone()[0]
        return (seiten - frei) * SEITE

    def dateigroesse(self) -> int:
        return self._db.execute("PRAGMA page_count").fetchone()[0] * SEITE

    def anzahl(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM bilder").fetchone()[0]


def anlegen(pfad: str, groesse: int) -> VorschauCache:
    """Cache oeffnen; ist er groesser als gewuenscht, wird er neu und kleiner angelegt."""
    try:
        return VorschauCache(pfad, groesse)
    except CacheFehler:
        if not os.path.exists(pfad):
            raise
    entfernen(pfad)                            # zu gross oder unbrauchbar: neu
    return VorschauCache(pfad, groesse)


def entfernen(pfad: str):
    """Den Cache loeschen. Sein Inhalt ist verschluesselt; vorher wird er trotzdem
    geleert, damit freigegebene Seiten ueberschrieben sind."""
    try:
        db = sqlite3.connect(pfad, timeout=2.0, isolation_level=None)
        try:
            db.execute("PRAGMA secure_delete = ON")
            db.execute("DELETE FROM bilder")
        finally:
            db.close()
    except sqlite3.Error:
        pass
    for endung in ("", "-journal"):
        try:
            os.remove(pfad + endung)
        except FileNotFoundError:
            pass
        except OSError as fehler:
            raise CacheFehler(str(fehler)) from fehler
