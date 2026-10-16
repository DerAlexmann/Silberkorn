"""
Stapelverarbeitung: viele Bilder auf einmal - Voreinstellung, Staub, KI, Ausgabe

Fuer jedes gewaehlte Bild der Ordneransicht, eins nach dem anderen (der
Grafikspeicher reicht fuer ein Bild, nicht fuer zwanzig):

  1. Laden, eine vorhandene Begleitdatei uebernehmen. Gehoert sie zu einer
     anderen Fassung des Bildes, gelten nur ihre Reglerwerte - wie beim Oeffnen,
     nur ohne zu fragen; der Bericht nennt es.
  2. Eine Voreinstellung (oder kopierte Einstellungen) darauflegen, beim Film
     Maske und Umfang je Bild neu schaetzen, wenn sie das verlangt.
  3. Auf Wunsch Staub ueber den Infrarotkanal fuellen - nur bei Filmscans.
  4. Fuer die Ausgabe auf Wunsch KI-Entrauschen, -Schaerfen und -Kolorieren
     rechnen, deren Staerke gesetzt ist.
  5. Ausgeben - nie ueber eine vorhandene Datei - und/oder die Begleitdatei
     schreiben.

Ein Fehler betrifft nur sein Bild; die anderen laufen weiter. Abbrechen geht
zwischen zwei Bildern und waehrend einer KI-Berechnung.

Die KI-Netze laedt die Bearbeiten-Seite (TensorRT, Fortschritt); sie bleiben
fuer den ganzen Stapel geladen.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import VERSION, begleitdatei, bilddatei, film, ki, staub, voreinstellungen
from .bearbeitung import Sitzung
from .cuda import cupy as cp

# Gruppe -> Methode der Sitzung; die Reihenfolge zaehlt: Schaerfen sieht das entrauschte Bild
KI_SCHRITTE = (("ki_rauschen", "ki_entrauschen"), ("ki_schaerfe", "ki_schaerfen"),
               ("ki_farbe", "ki_kolorieren"))
VERBOTEN = set('<>:"/\\|?*')


class StapelAbbruch(Exception):
    """Der Anwender hat abgebrochen."""


@dataclass
class Auftrag:
    voreinstellung: dict | None = None     # aus voreinstellungen.als_dict, None: keine
    staub: bool = False
    ki: bool = True
    begleitdatei: bool = True
    ausgeben: bool = False
    ziel: str = ""                         # Ordner fuer die Ausgabe
    endung: str = ".jpg"
    bits: int = 8
    zusatz: str = "-bearbeitet"
    hochskalieren: bool = False


@dataclass
class Ergebnis:
    pfad: str
    ok: bool = True
    ausgabe: str = ""
    hinweise: list[str] = field(default_factory=list)


def zusatz_pruefen(text: str) -> str | None:
    """Der Namenszusatz - ohne Zeichen, die Windows in Dateinamen nicht erlaubt."""
    text = text.strip()
    if any(z in VERBOTEN or ord(z) < 32 for z in text) or text.endswith("."):
        return None
    return text


def freier_name(ordner: str, stamm: str, endung: str) -> str:
    """Name.endung oder Name-2.endung ... - nie eine vorhandene Datei."""
    pfad = os.path.join(ordner, stamm + endung)
    nummer = 1
    while os.path.exists(pfad):
        nummer += 1
        pfad = os.path.join(ordner, f"{stamm}-{nummer}{endung}")
    return pfad


class Stapel:
    def __init__(self, seite, auftrag: Auftrag, fortschritt):
        """seite: die Bearbeiten-Seite (laedt KI-Netze). fortschritt(text, anteil) -> bool,
        False bricht ab."""
        self.seite = seite
        self.auftrag = auftrag
        self.fortschritt = fortschritt
        self._netze: dict[str, object] = {}
        self._ki_auftrag = None

    def _weiter(self, text: str, anteil: float):
        if not self.fortschritt(text, anteil):
            raise StapelAbbruch

    def _netz(self, gruppe: str):
        """Das Netz fuer KI-Entrauschen, -Schaerfen oder -Kolorieren - einmal je Stapel.
        None, wenn das Modell fehlt oder die Karte es nicht kann."""
        if gruppe not in self._netze:
            art = self.seite._ki_bild_art(gruppe)
            modell = art["modell"]
            if not (ki.angeboten(modell, self.seite._ki_stufe()) and ki.vorhanden(modell)):
                self._netze[gruppe] = None
            else:
                kachel = ki.kachelgroesse(modell, self.seite._ki_stufe())
                if art.get("tensorrt", True):
                    netz = self.seite._ki_laden(
                        modell, kachel, lambda **weg: art["netz"](modell, kachel=kachel, **weg))
                else:
                    netz = art["netz"](modell)
                self._netze[gruppe] = (netz, kachel)
        return self._netze[gruppe]

    def freigeben(self):
        self._netze.clear()
        self._ki_auftrag = None
        cp.get_default_memory_pool().free_all_blocks()

    def bearbeiten(self, pfad: str, nummer: int, anzahl: int) -> Ergebnis:
        """Ein Bild ganz durch den Stapel; Fehler stehen im Ergebnis, Abbrechen wirft."""
        ergebnis = Ergebnis(pfad)
        name = os.path.basename(pfad)
        anteil = nummer / anzahl
        self._weiter(name, anteil)
        sitzung = None
        try:
            sitzung = Sitzung(bilddatei.laden(pfad), self.seite._vorschau_kante())
            sitzung.angaben_vorgeben(*self.seite._vorgabe_werte())
            self._begleitdatei_uebernehmen(sitzung, ergebnis)
            if self.auftrag.voreinstellung is not None:
                self._voreinstellung(sitzung, ergebnis)
            if self.auftrag.staub and sitzung.infrarot_film and not sitzung.staub_entfernt:
                self._weiter(name, anteil)
                sitzung.staub_entfernen(staub.EMPFINDLICHKEIT)
            if self.auftrag.ki and self.auftrag.ausgeben:
                # Nur fuer die Ausgabe: In der Begleitdatei stehen KI-Ergebnisse ohnehin nicht
                self._ki(sitzung, ergebnis, name, anteil, 1 / anzahl)
            if self.auftrag.ausgeben:
                self._weiter(name, anteil)
                ergebnis.ausgabe = self._ausgeben(sitzung, pfad)
            if self.auftrag.begleitdatei and sitzung.begleit_geaendert:
                self._begleitdatei_schreiben(sitzung, pfad)
        except StapelAbbruch:
            raise
        except ki.KiAbbruch as fehler:
            raise StapelAbbruch from fehler
        except (bilddatei.BildFehler, begleitdatei.BegleitFehler, ki.KiFehler,
                voreinstellungen.VoreinstellungFehler, OSError, ValueError) as fehler:
            ergebnis.ok = False
            ergebnis.hinweise.append(str(fehler))
        except cp.cuda.memory.OutOfMemoryError:
            ergebnis.ok = False
            ergebnis.hinweise.append("Grafikspeicher")
        finally:
            if sitzung is not None:
                sitzung.schliessen()
            cp.get_default_memory_pool().free_all_blocks()
        return ergebnis

    # ------------------------------------------------------------------

    @staticmethod
    def _begleitdatei_uebernehmen(sitzung: Sitzung, ergebnis: Ergebnis):
        pfad = sitzung.daten.pfad
        if not os.path.isfile(begleitdatei.pfad_fuer(pfad)):
            return
        hoehe, breite = sitzung.original.shape[:2]
        inhalt = begleitdatei.lesen(pfad, hoehe, breite, sitzung.grundwerte())
        sitzung.begleit_anwenden(inhalt)
        if not inhalt.passt:
            sitzung.begleit_veraltet()
            ergebnis.hinweise.append("veraltet")
        if inhalt.verworfen:
            ergebnis.hinweise.append("verworfen")

    def _voreinstellung(self, sitzung: Sitzung, ergebnis: Ergebnis):
        gelesen = voreinstellungen.anwenden(self.auftrag.voreinstellung, sitzung.werte)
        werte = gelesen.ergebnis.werte
        if "objektivprofil" in gelesen.ergebnis.felder:
            werte.objektivprofil = (sitzung.objektiv_terme() if gelesen.ergebnis.objektivprofil
                                    else ())
        if gelesen.film_schaetzen and film.ist_negativ(werte.film):
            werte.film_maske, werte.film_umfang = sitzung.film_schaetzen(werte.film)
        sitzung.werte = werte
        if gelesen.ergebnis.verworfen:
            ergebnis.hinweise.append("verworfen")

    def _ki(self, sitzung: Sitzung, ergebnis: Ergebnis, name: str, anteil: float,
            spanne: float):
        offen = sitzung.ki_neu_zu_rechnen()
        for gruppe, methode in KI_SCHRITTE:
            if gruppe not in offen:
                continue
            netz = self._netz(gruppe)
            if netz is None:
                ergebnis.hinweise.append(f"ohne {gruppe}")
                continue

            def fortschritt(i, n):
                return self.fortschritt(name, anteil + spanne * i / max(n, 1))
            getattr(sitzung, methode)(netz[0], netz[1], fortschritt)

    def _ausgeben(self, sitzung: Sitzung, pfad: str) -> str:
        a = self.auftrag
        os.makedirs(a.ziel, exist_ok=True)
        stamm = os.path.splitext(os.path.basename(pfad))[0] + a.zusatz
        ziel = freier_name(a.ziel, stamm, a.endung)
        bits = a.bits if bilddatei.SCHREIBBAR[a.endung][2] else 8
        if a.hochskalieren and self._ki_auftrag is None:
            self._ki_auftrag = self.seite._ki_auftrag()
        auftrag = self._ki_auftrag if a.hochskalieren else None
        sitzung.exportieren(ziel, bits, auftrag)
        return ziel

    @staticmethod
    def _begleitdatei_schreiben(sitzung: Sitzung, pfad: str):
        if not sitzung.bearbeitet:
            begleitdatei.entfernen(pfad)
        else:
            inhalt = sitzung.begleit_inhalt(sitzung.begleit_vorschau())
            begleitdatei.schreiben(pfad, inhalt, begleitdatei.fingerabdruck(pfad), VERSION)
        sitzung.begleit_gesichert()
