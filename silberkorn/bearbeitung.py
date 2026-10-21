"""
Bearbeitungssitzung: ein geoeffnetes Bild auf der Grafikkarte

Das Original liegt zweimal im Grafikspeicher - in voller Groesse fuer den
Export und verkleinert fuer die Vorschau, beide schon in linearem Licht und
in sRGB-Primaerfarben, gleich ob die Datei 8 Bit, 16 Bit oder RAW war und in
welchem Farbraum sie stand.
Jede Aenderung an einem Regler rechnet die Vorschau aus dem unveraenderten
Original neu; nichts wird ueberschrieben, jeder Regler bleibt jederzeit
umkehrbar.

Ein Negativ (Scan & Film, film.py) wird vor allem anderen ins Positiv
gewandelt - jedes Mal neu aus dem Original, das kostet einen Durchlauf. So
sehen alle Regler und KI-Netze das Positiv. Noch davor liegt, was ueber den
Infrarotkanal an Staub gefuellt ist (staub.py): als Werte des Scans, nur die
geaenderten Pixel in voller Groesse, die Vorschau ganz.

KI-Entrauschen und KI-Schaerfen sind zu teuer, um sie bei jeder
Reglerbewegung zu rechnen. Sie laufen einmal ueber das ganze Bild und liegen
danach als Korrektur im Grafikspeicher - die des Schaerfens wird aufs
Ergebnis des Entrauschens gelegt. Die Staerkeregler mischen nur noch; das
kostet je Vorschau Bruchteile einer Millisekunde.

Ebenso die Maske des Motivs (KI-Freistellen oder per Klick ausgewaehlt):
einmal berechnet, liegt sie in der Geometrie des Originals im Grafikspeicher.
Fuer den Hintergrund rechnet die Kette das Bild ein zweites Mal mit dessen
eigenen Werten; die Maske - mit derselben Geometrie wie das Bild verformt -
mischt beides.

Entfernte Objekte (LaMa) liegen als Flicken ueber dem Ausgangsbild: je ein
Ausschnitt mit Fuellung und Deckkraft, aufgelegt nach Entrauschen und Schaerfen.
Jeder laesst sich einzeln zuruecknehmen. Was entfernt werden soll, markieren
Klicks (SAM) und ein Pinsel; die Markierung liegt wie die Maske in der
Geometrie des Originals.

Die Tiefe (Depth Anything) liegt verkleinert in der Geometrie des Originals.
Aus ihr und dem Fokus folgt fuer jeden Pixel ein Unschaerferadius; das Bokeh
mischt dafuer einige unterschiedlich stark weichgezeichnete Fassungen des
fertigen Bildes, in linearem Licht, damit Lichter wie bei einem Objektiv
aufbluehen. Scharfe Bereiche fliessen dabei nicht in unscharfe hinein.

Die KI-Erweiterung (Outpainting) liegt wie die Flicken vor den Filtern: eine
Leinwand im Zielformat mit den erfundenen Raendern, in die das Ausgangsbild mit
weichem Saum eingesetzt wird. Die Filter und die Geometrie sehen danach die
ganze Leinwand; Maske, Tiefe, Markierung und Alphakanal werden dafuer am Rand
fortgesetzt. Die KI-Netze (Freistellen, Klicks, Entfernen, Tiefe) sehen weiter
nur das Original - so bleiben ihre Ergebnisse gueltig, wenn die Erweiterung
wegfaellt oder neu erzeugt wird.

Ganz am Ende liegt das Filmkorn (korn.py), nach Hintergrund und Bokeh. Beim
KI-Hochskalieren rechnet die Kette ohne Korn; es kommt erst aufs vergroesserte
Bild, die KI wuerde es sonst glaetten.

Fuer Rueckgaengig haelt der Verlauf (verlauf.py) Staende der Sitzung fest:
die Werte als Kopie, die KI-Ergebnisse als Verweise. Deshalb ersetzt jede
KI-Aenderung ihr Ergebnis durch ein neues Objekt, statt das alte zu
veraendern - der Verlauf behielte sonst nicht, was vorher war.

Dieses Modul importiert CuPy und darf deshalb erst nach der Startprufung
geladen werden.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import dataclasses
import io
import itertools
import math
import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from . import (
    abschneiden,
    anonym,
    automatik,
    begleitdatei,
    bilddatei,
    film,
    filter,
    geometrie,
    ki,
    korn,
    lokal,
    metadaten,
    objektivprofile,
    staub,
    trennen,
    verlauf,
    veroeffentlichen,
)
from .cuda import cupy as cp
from .filter import Einstellungen

SCHAERFE_GROB = 10.0           # Sigma in Pixeln: groebere Anteile der KI-Schaerfung fallen weg
MASKE_KANTE = 20.0             # Kante weicher: Sigma bei 100 % in Pixeln des Originals
MASKE_VERSCHIEBEN = 20.0       # Kante verschieben: Pixel des Originals bei +-100 %
HG_UNSCHAERFE = 40.0           # Hintergrund weichzeichnen: Sigma bei 100 % in Pixeln
MASKE_FARBE = (1.0, 0.25, 0.2)  # Maskenansicht: so wird der Hintergrund eingefaerbt
LOKAL_DECKUNG = 0.5            # so deckt die Farbe dort, wo eine lokale Maske voll wirkt
LOKAL_KI_AUFHEBEN = 4          # so viele nicht mehr gebrauchte Objektauswahlen bleiben
MARKIERUNG_FARBE = (0.2, 0.55, 1.0)   # was entfernt werden soll
MARKIERUNG_DECKUNG = 0.55
GRAU_LINEAR = 0.2158           # sRGB 128 in linearem Licht: Raender im Vergleich
BOKEH_MAX = 0.012              # Bokeh 100 %: Sigma als Anteil der laengsten Bildkante
BOKEH_STUFEN = (0.125, 0.25, 0.5, 1.0)   # weichgezeichnete Fassungen, Anteile davon
TIEFE_BEREICH = 0.35           # Schaerfentiefe 100 %: so viel der Tiefe bleibt scharf
TIEFE_UEBERGANG = 0.4          # danach waechst die Unschaerfe ueber so viel Tiefe auf voll
BEGLEIT_VORSCHAU = 256         # laengste Kante des Vorschaubildes in der Begleitdatei

# a + s * d - eine Korrektur mit Staerke auflegen
_auflegen = cp.ElementwiseKernel("float32 a, float32 d, float32 s", "float32 c",
                                 "c = a + s * d", "ne_auflegen")


@dataclass
class _Klicks:
    """Klicks fuer ein Ziel (Maske oder Markierung) samt SAM-Logits nach jedem Klick."""
    punkte: list = field(default_factory=list)      # (x, y, dazu) im Original
    logits: list = field(default_factory=list)
    vorher: object = None                           # Stand des Ziels vor dem ersten Klick


@dataclass
class _Flicken:
    """Ein entferntes Objekt: Ausschnitt, Deckkraft und Fuellung mal Deckkraft (linear)."""
    voll: tuple                     # (y0, y1, x0, x1, deckkraft (h, w), fuellung (h, w, 3))
    vorschau: tuple                 # dasselbe in der Groesse der Vorschau


@dataclass
class _Staub:
    """Staub und Kratzer gefuellt, in den Werten des Scans: die geaenderten Pixel in voller
    Groesse (Stelle im flachen Bild, Werte) und der ganze gesaeuberte Scan als Vorschau."""
    stellen: object                 # (n,) Stellen in H * W
    werte: object                   # (n, 3) linear
    vorschau: object                # (h, w, 3) in der Groesse der Vorschau
    anzahl: int                     # gefuellte Stellen


@dataclass
class _Erweiterung:
    """Die KI-Erweiterung: Leinwand (linear) mit den erfundenen Raendern und die
    Deckkraft, mit der das Ausgangsbild an (x, y) eingesetzt wird."""
    x: int                          # Lage des Originals in Pixeln des Originals,
    y: int                          # Vielfache des Vorschau-Faktors
    voll: tuple                     # (Leinwand (H, W, 3), Deckkraft (h, w))
    vorschau: tuple                 # dasselbe in der Groesse der Vorschau
    seed: int
    verhaeltnis: float              # Breite/Hoehe der Leinwand


class Sitzung:
    def __init__(self, daten: bilddatei.Bilddaten, vorschau_kante: int):
        self.daten = daten
        self.werte = Einstellungen()
        self.gespeicherte_werte = Einstellungen()
        self._speicher: dict = {}            # Zwischenergebnisse der Filter, je Bildgroesse
        # (Einstellungen, fertiges Bild auf der GPU, Histogramme, Zahl abgeschnittener
        # Pixel, Maske der abgeschnittenen Pixel)
        self._vollbild = None
        self.abgeschnitten = (0, 0)           # Pixel mit Lichtern / Tiefen am Anschlag
        # Vorher-Haelfte des Vergleichs: (Schluessel, uint8-Bild), Vorschau auf der CPU,
        # Vollbild auf der GPU. Der Schluessel kennt nur, was das Bild ohne Bearbeitung
        # bestimmt - Reglerbewegungen rechnen es nicht neu.
        self._vorher_klein = None
        self._vorher_voll = None
        self._ki_rauschfrei = None            # (voll, Vorschau): Korrektur des KI-Entrauschens
        self._ki_schaerfe = None              # (voll, Vorschau): Korrektur des KI-Schaerfens
        self._ki_maske = None                 # (voll, Vorschau): Maske des Motivs, 0..1
        self.maske_zeigen = False             # Vorschau faerbt den Hintergrund ein
        self.lokal_zeigen: int | None = None  # Vorschau faerbt den Bereich dieser Maske ein
        self._lokal_raster: dict = {}         # (Teile, voll, Geometrie, ...) -> Gewicht
        self._pinsel_raster: dict = {}        # (Striche davor, Gitter) -> Ebene, lokal.py
        # KI-Ergebnisse lokaler Masken: ("motiv",) oder ("objekt", Klicks) ->
        # (voll als uint8, Vorschau float32); dazu, was die Klicks gerade ergeben
        self._lokal_ki: dict = {}
        self._lokal_klick = None
        self._lokal_quellen_nr = 0            # zaehlt hoch, wenn sich eine Quelle aendert
        self._lokal_bild: dict = {}           # voll -> (Stand, Helligkeit, Farbton, Buntheit)
        self.maske_per_klick = False          # Maske stammt aus der Auswahl per Klick
        self._klickstand = {"maske": _Klicks(), "entfernen": _Klicks(), "lokal": _Klicks()}
        self._entfern_klick = None            # (voll, Vorschau): per Klick markiert
        self._pinsel = None                   # (voll, Vorschau): mit dem Pinsel markiert
        self._flicken: list[_Flicken] = []    # entfernte Objekte, in Reihenfolge
        # Kennung des Inhalts von Flicken, Staub und Erweiterung: jede Aenderung bekommt eine neue
        # Nummer - auch nach Rueckgaengig und einer neuen Aenderung nie eine schon vergebene
        self._nummern = itertools.count(1)
        self._flicken_stand = 0
        self._flicken_gespeichert = 0
        self._ki_tiefe = None                 # Tiefe 0..1 (1 = nah), verkleinert, im Original
        self._ki_farbe = None                 # (voll, Vorschau): Farbanteile a, b der KI
        self.tiefe_zeigen = False             # Vorschau zeigt die Tiefenkarte
        self._erweiterung: _Erweiterung | None = None
        self._staub: _Staub | None = None     # Staub und Kratzer gefuellt (Infrarot)
        self._staub_dunkel = None             # wie dunkel jede Stelle im Infrarot ist
        self._staub_film: bool | None = None  # sieht das Infrarot nach Film aus?
        self._staub_fund = None               # (Empfindlichkeit, Maske, Vorschau, Anzahl, Kern)
        self.staub_zeigen = False             # Vorschau zeigt die Fundstellen
        self._anonym_stand = ((), "mosaik", 8.0)   # wofuer die Zwischenstufen gelten
        self._film_stand: tuple = ()          # ebenso fuer die Umwandlung eines Negativs
        self._begleit_stand: verlauf.Stand | None = None   # was in der Begleitdatei steht

        self.original = daten.linear(cp)
        # Zwischenpuffer des Demosaicing an den Grafikspeicher zurueckgeben
        cp.get_default_memory_pool().free_all_blocks()
        self.vorschau_original, self.vorschau_massstab = filter.verkleinern_auf(
            self.original, vorschau_kante)
        self.objektiv = objektivprofile.Suche(False, daten.aufnahme, None)
        try:
            self.objektiv_suchen()
        except (OSError, ValueError):
            pass                                  # ohne Profil weiter
        self.vorgefunden = metadaten.lesen(daten.exif, daten.xmp, daten.iptc)
        self._angaben_vorgabe: tuple = ()         # Urheber und Copyright aus den Einstellungen
        self.begleit_gesichert()                  # nach dem Oeffnen gibt es nichts zu sichern

    @property
    def geaendert(self) -> bool:
        return (self.werte != self.gespeicherte_werte
                or self._flicken_stand != self._flicken_gespeichert)

    @property
    def klicks(self) -> list[tuple[float, float, bool]]:
        """Klicks der Maske (Motiv & Hintergrund)."""
        return self._klickstand["maske"].punkte

    def klicks_von(self, ziel: str) -> list[tuple[float, float, bool]]:
        return self._klickstand[ziel].punkte

    @property
    def markierung_da(self) -> bool:
        return self._entfern_klick is not None or self._pinsel is not None

    @property
    def ki_tiefe_da(self) -> bool:
        return self._ki_tiefe is not None

    @property
    def entfernt(self) -> int:
        """Wie viele Objekte entfernt sind."""
        return len(self._flicken)

    @property
    def infrarot_da(self) -> bool:
        """Hat der Scan einen Infrarotkanal (RGBI)?"""
        return self.daten.infrarot is not None

    @property
    def infrarot_film(self) -> bool:
        """Taugt der Infrarotkanal fuer die Staubsuche - stammt er von Film?"""
        if self.daten.infrarot is None:
            return False
        if self._staub_film is None:
            self._staub_film = staub.ist_filmscan(staub.normiert(self.daten.infrarot))
        return self._staub_film

    @property
    def staub_entfernt(self) -> bool:
        return self._staub is not None

    @property
    def staub_gefuellt(self) -> int:
        """Wie viele Stellen gefuellt sind."""
        return self._staub.anzahl if self._staub is not None else 0

    @property
    def staub_fund(self) -> tuple[float, int] | None:
        """Empfindlichkeit und Anzahl der letzten Suche, oder None."""
        return None if self._staub_fund is None else (self._staub_fund[0], self._staub_fund[3])

    @property
    def ki_entrauscht(self) -> bool:
        return self._ki_rauschfrei is not None

    @property
    def ki_geschaerft(self) -> bool:
        return self._ki_schaerfe is not None

    @property
    def ki_koloriert(self) -> bool:
        return self._ki_farbe is not None

    @property
    def ki_maske_da(self) -> bool:
        return self._ki_maske is not None

    @property
    def erweitert(self) -> bool:
        return self._erweiterung is not None

    def erweitert_auf(self, verhaeltnis: float) -> bool:
        """Ist das Bild schon auf dieses Seitenverhaeltnis erweitert?"""
        return self._erweiterung is not None and self._erweiterung.verhaeltnis == verhaeltnis

    # ------------------------------------------------------------------
    # Verlauf: Stand festhalten und wiederherstellen
    # ------------------------------------------------------------------

    def stand(self) -> verlauf.Stand:
        """Der jetzige Stand fuer Rueckgaengig: Werte als Kopie, KI-Ergebnisse als Verweise.
        Die Markierung zum Entfernen und laufende Klicks gehoeren nicht dazu - sie sind
        Arbeitsstand, kein Ergebnis."""
        return verlauf.Stand(dataclasses.replace(self.werte), (
            ("ki_entrauscht", self._ki_rauschfrei),
            ("ki_geschaerft", self._ki_schaerfe),
            ("ki_koloriert", self._ki_farbe),
            ("maske", (self._ki_maske, self.maske_per_klick)),
            ("tiefe", self._ki_tiefe),
            ("flicken", tuple(self._flicken)),
            ("erweiterung", self._erweiterung),
            ("staub", self._staub),
        ), self._flicken_stand)

    def stand_setzen(self, stand: verlauf.Stand):
        """Einen Stand aus dem Verlauf wiederherstellen."""
        teile = dict(stand.teile)
        maske_vorher = self._ki_maske
        self.werte = dataclasses.replace(stand.werte)
        self._ki_rauschfrei = teile["ki_entrauscht"]
        self._ki_schaerfe = teile["ki_geschaerft"]
        self._ki_farbe = teile["ki_koloriert"]
        self._ki_maske, self.maske_per_klick = teile["maske"]
        self._ki_tiefe = teile["tiefe"]
        self._flicken = list(teile["flicken"])
        self._erweiterung = teile["erweiterung"]
        self._staub = teile["staub"]
        self._flicken_stand = stand.nummer
        if self._ki_maske is not maske_vorher:
            # Die Klicks gehoerten zur alten Maske; weitere Klicks beginnen neu
            self._klickstand["maske"] = _Klicks()
        self._ki_fertig(0.0)

    # ------------------------------------------------------------------
    # Begleitdatei: die Bearbeitung neben dem Bild (begleitdatei.py)
    # ------------------------------------------------------------------

    def begleit_gesichert(self):
        """Der jetzige Stand ist in der Begleitdatei - oder es gibt nichts zu sichern."""
        self._begleit_stand = self.stand()

    def begleit_veraltet(self):
        """Die Begleitdatei gehoert zu einer anderen Fassung des Bildes - beim Verlassen
        neu schreiben."""
        self._begleit_stand = None

    @property
    def begleit_geaendert(self) -> bool:
        """Weicht die Bearbeitung von dem ab, was in der Begleitdatei steht?"""
        return self._begleit_stand is None or not verlauf.gleich(self.stand(),
                                                                 self._begleit_stand)

    def _still_aendern(self):
        """Fuer Aenderungen, die wie die Datei selbst zum Bild gehoeren (Urheber aus den
        Einstellungen, Objektivprofil einer RAW): Rueckgabe eine Funktion, die danach
        alles, was vorher als gespeichert galt, wieder als gespeichert markiert."""
        gespeichert = not self.geaendert
        gesichert = self._begleit_stand is not None and not self.begleit_geaendert

        def danach():
            if gespeichert:
                self.gespeicherte_werte = dataclasses.replace(self.werte)
            if gesichert:
                self.begleit_gesichert()
        return danach

    @property
    def bearbeitet(self) -> bool:
        """Gibt es ueberhaupt etwas zu sichern - oder ist alles wie nach dem Oeffnen?"""
        return (self.werte != self.grundwerte() or self._ki_rauschfrei is not None
                or self._ki_schaerfe is not None or self._ki_farbe is not None
                or self._ki_maske is not None or self._ki_tiefe is not None
                or bool(self._flicken) or self._erweiterung is not None
                or self._staub is not None)

    def begleit_vorschau(self) -> bytes:
        """Das bearbeitete Bild klein als WebP - ohne eingeblendete Maske, Tiefe oder
        Fundstellen, aber anonymisiert wie das gespeicherte Bild."""
        bild = Image.fromarray(cp.asnumpy(self._rendern(self.werte, False, self._speicher)))
        bild.thumbnail((BEGLEIT_VORSCHAU, BEGLEIT_VORSCHAU), Image.Resampling.LANCZOS)
        puffer = io.BytesIO()
        bild.save(puffer, "WEBP", quality=80)
        return puffer.getvalue()

    def begleit_inhalt(self, vorschau: bytes | None = None) -> begleitdatei.Inhalt:
        """Die Bearbeitung fuer die Begleitdatei - Arrays vom Grafikspeicher geholt."""
        inhalt = begleitdatei.Inhalt(dataclasses.replace(self.werte), vorschau=vorschau)
        if self._ki_maske is not None:
            maske = cp.clip(self._ki_maske[0], 0, 1) * 255 + 0.5
            inhalt.maske = cp.asnumpy(maske.astype(cp.uint8))
            inhalt.maske_per_klick = self.maske_per_klick
        if self._ki_tiefe is not None:
            inhalt.tiefe = cp.asnumpy(self._ki_tiefe).astype(np.float16)
        for schluessel in self._lokal_ki_gebraucht():
            if schluessel in self._lokal_ki:
                inhalt.lokal_ki.append((schluessel, cp.asnumpy(self._lokal_ki[schluessel][0])))
        for flicken in self._flicken:
            y0, y1, x0, x1, deckkraft, gefuellt = flicken.voll
            inhalt.flicken.append(begleitdatei.Flicken(
                int(y0), int(y1), int(x0), int(x1), cp.asnumpy(deckkraft).astype(np.float16),
                cp.asnumpy(gefuellt).astype(np.float16)))
        if self._staub is not None:
            inhalt.staub = begleitdatei.Staub(cp.asnumpy(self._staub.stellen).astype(np.int64),
                                              cp.asnumpy(self._staub.werte).astype(np.float32),
                                              int(self._staub.anzahl))
        if self._erweiterung is not None:
            e = self._erweiterung
            rand, deckkraft = e.voll
            srgb = filter.linear_zu_srgb(cp.clip(rand, 0, 1)) * 65535 + 0.5
            srgb = srgb.astype(cp.uint16)
            # Wo das Original ganz deckt, zaehlt die Leinwand nicht - Nullen packen sich klein
            hoehe, breite = deckkraft.shape
            srgb[e.y:e.y + hoehe, e.x:e.x + breite][deckkraft >= 1] = 0
            inhalt.erweiterung = begleitdatei.Erweiterung(e.x, e.y, int(e.seed),
                                                          float(e.verhaeltnis), cp.asnumpy(srgb))
            del srgb
        return inhalt

    def begleit_anwenden(self, inhalt: begleitdatei.Inhalt):
        """Eine gelesene Begleitdatei uebernehmen. Die Arrays hat begleitdatei.lesen schon
        auf Typ und Form zum Original geprueft; die Leinwand der Erweiterung muss
        zusaetzlich genau so liegen, wie Silberkorn sie fuer ihr Seitenverhaeltnis plant -
        sonst BegleitFehler, und nichts ist uebernommen."""
        hoehe, breite = self.original.shape[:2]
        erweiterung = None
        if inhalt.erweiterung is not None:
            e = inhalt.erweiterung
            gross_b, gross_h, x, y = self.erweiterung_planen(e.verhaeltnis)
            if e.rand.shape != (gross_h, gross_b, 3) or (e.x, e.y) != (x, y):
                raise begleitdatei.BegleitFehler("erweiterung passt nicht zum Bild")
            rand = filter.srgb_zu_linear(cp.asarray(e.rand, dtype=cp.float32) / 65535)
            deckkraft = ki.saum_deckkraft(gross_b, gross_h, x, y, breite, hoehe,
                                          ki.saum_breite(breite, hoehe), cp)
            voll = (rand, deckkraft)
            faktor = self._vorschau_faktor()
            vorschau = voll if faktor == 1 else tuple(
                filter.verkleinern_box(teil, faktor).astype(cp.float32) for teil in voll)
            erweiterung = _Erweiterung(x, y, voll, vorschau, e.seed, e.verhaeltnis)

        werte = dataclasses.replace(inhalt.werte)
        werte.objektivprofil = ()
        self.werte = werte
        self._ki_rauschfrei = self._ki_schaerfe = self._ki_farbe = None
        self._ki_maske, self.maske_per_klick = None, False
        if inhalt.maske is not None:
            voll = cp.asarray(inhalt.maske, dtype=cp.float32) / 255
            self._ki_maske = (voll, self._vorschau_von(voll))
            self.maske_per_klick = inhalt.maske_per_klick
        self._klickstand = {"maske": _Klicks(), "entfernen": _Klicks(), "lokal": _Klicks()}
        self._ki_tiefe = (None if inhalt.tiefe is None
                          else cp.asarray(inhalt.tiefe, dtype=cp.float32))
        self._lokal_ki, self._lokal_klick = {}, None
        for schluessel, maske in inhalt.lokal_ki:
            self._lokal_ki_setzen(schluessel, cp.asarray(maske, dtype=cp.float32) / 255)
        self._lokal_quellen_neu()
        self._flicken = []
        for f in inhalt.flicken:
            voll = (f.y0, f.y1, f.x0, f.x1, cp.asarray(f.deckkraft, dtype=cp.float32),
                    cp.asarray(f.fuellung, dtype=cp.float32))
            self._flicken.append(_Flicken(voll, self._flicken_vorschau(voll)))
        self._staub = None
        if inhalt.staub is not None:
            stellen = cp.asarray(inhalt.staub.stellen, dtype=cp.int64)
            werte_staub = cp.asarray(inhalt.staub.werte, dtype=cp.float32)
            sauber = self.original.copy()
            sauber.reshape(-1, 3)[stellen] = werte_staub
            vorschau = self._vorschau_von(sauber)
            if vorschau is sauber:
                vorschau = sauber.copy()
            del sauber
            self._staub = _Staub(stellen, werte_staub, vorschau, inhalt.staub.anzahl)
        self._erweiterung = erweiterung
        if inhalt.objektivprofil and self.objektiv.profil is not None:
            self.werte.objektivprofil = self.objektiv_terme()
        self._flicken_stand = next(self._nummern)
        self._ki_fertig(0.0)
        # Was in der Begleitdatei steht, gilt als gesichert - und, wie die Datei selbst,
        # nicht als ungespeicherte Aenderung
        self.gespeicherte_werte = dataclasses.replace(self.werte)
        self._flicken_gespeichert = self._flicken_stand
        self.begleit_gesichert()

    def ki_neu_zu_rechnen(self) -> list[str]:
        """Gruppen (ki_rauschen, ki_schaerfe, ki_farbe), deren Staerke gesetzt ist, deren
        Ergebnis aber fehlt - nach dem Oeffnen einer Begleitdatei. In dieser Reihenfolge
        zu rechnen: Das Schaerfen sieht das entrauschte Bild."""
        fehlt = {"ki_rauschen": self._ki_rauschfrei is None,
                 "ki_schaerfe": self._ki_schaerfe is None,
                 "ki_farbe": self._ki_farbe is None}
        gruppen = [gruppe for gruppe, offen in fehlt.items()
                   if offen and getattr(self.werte, gruppe) > 0]
        return gruppen + self.lokal_ki_fehlt()

    def ki_freistellen(self, freisteller) -> float:
        """Die Maske des Motivs einmal mit KI berechnen; Rueckgabe: Rechenzeit in ms.

        Das Netz sieht das Bild, wie es gerade entrauscht und geschaerft ist.
        """
        beginn = time.perf_counter()
        srgb = filter.linear_zu_srgb(cp.clip(self._ausgang(self.werte, True, leinwand=False),
                                             0, 1))
        voll = freisteller.maske(srgb)
        del srgb
        self._ki_maske = (voll, self._vorschau_von(voll))
        self.maske_per_klick = False
        self._klickstand["maske"] = _Klicks()
        return self._ki_fertig(beginn)

    def ki_auswahl_beginnen(self, auswaehler, ziel: str = "maske") -> float:
        """Das Bild fuer die Auswahl per Klick vorbereiten (SAM-Encoder); Rueckgabe in ms.

        Wie beim Freistellen sieht das Netz das Bild, wie es gerade entrauscht und
        geschaerft ist. Die Maske von vorher bleibt, bis der erste Klick kommt;
        stammt sie schon aus Klicks, geht es mit ihnen weiter.
        """
        beginn = time.perf_counter()
        srgb = filter.linear_zu_srgb(cp.clip(self._ausgang(self.werte, True, leinwand=False),
                                             0, 1))
        auswaehler.bild_setzen(srgb)
        del srgb
        stand = self._klickstand[ziel]
        if not stand.punkte:
            stand.vorher = self._ziel_lesen(ziel)
        cp.get_default_memory_pool().free_all_blocks()
        return (time.perf_counter() - beginn) * 1000

    def quelle_von(self, x: float, y: float,
                   begrenzt: bool = True) -> tuple[float, float] | None:
        """Punkt im fertigen Bild (Pixel) -> Punkt im Original, oder None ausserhalb
        (begrenzt=False: auch ausserhalb, etwa im Rand einer KI-Erweiterung)."""
        sx, sy = geometrie.zur_quelle(self.quellform(), geometrie.aus(self.werte), x, y)
        if self._erweiterung is not None:
            sx, sy = sx - self._erweiterung.x, sy - self._erweiterung.y
        hoehe, breite = self.original.shape[:2]
        if begrenzt and not (0 <= sx < breite and 0 <= sy < hoehe):
            return None
        return sx, sy

    def gesichter_finden(self, finder, form: str = "ellipse") -> list[tuple]:
        """Gesichter im Original als Flaechen (siehe anonym.py). Das Netz sieht das Bild,
        wie es gerade entrauscht und geschaerft ist - ohne bisherige Flaechen."""
        srgb = filter.linear_zu_srgb(cp.clip(self._ausgang(self.werte, True, leinwand=False),
                                             0, 1))
        rgb = cp.asnumpy((srgb * 255 + 0.5).astype(cp.uint8))
        del srgb
        hoehe, breite = rgb.shape[:2]
        flaechen = [anonym.als_flaeche(g, hoehe, breite, form) for g in finder.finden(rgb)]
        return [f for f in flaechen if f is not None]

    def ziel_von(self, punkte) -> np.ndarray:
        """Punkte im Original (n, 2) in Pixeln -> wo sie im fertigen Bild liegen."""
        punkte = np.asarray(punkte, dtype=np.float64).reshape(-1, 2)
        if self._erweiterung is not None:
            punkte = punkte + (self._erweiterung.x, self._erweiterung.y)
        return geometrie.von_quelle(self.quellform(), geometrie.aus(self.werte), punkte)

    def ki_klick(self, auswaehler, x: float, y: float, dazu: bool,
                 ziel: str = "maske") -> float:
        """Einen Klick (im Original) dazunehmen und die Maske neu bestimmen; Rueckgabe in ms.

        SAM bekommt alle Klicks und seine letzte Maske als Hinweis - so verfeinert
        jeder weitere Klick das Bisherige, statt neu zu beginnen.
        """
        beginn = time.perf_counter()
        stand = self._klickstand[ziel]
        vorige = stand.logits[-1] if stand.logits else None
        logits = auswaehler.roh([*stand.punkte, (x, y, dazu)], vorige)
        stand.punkte.append((x, y, dazu))
        stand.logits.append(logits)
        self._aus_klicks(auswaehler, ziel)
        return (time.perf_counter() - beginn) * 1000

    def ki_klick_zurueck(self, auswaehler, ziel: str = "maske") -> bool:
        """Den letzten Klick zuruecknehmen; ohne Klicks gilt wieder der Stand von vorher."""
        stand = self._klickstand[ziel]
        if not stand.punkte:
            return False
        stand.punkte.pop()
        stand.logits.pop()
        if stand.punkte:
            self._aus_klicks(auswaehler, ziel)
        else:
            self._ziel_setzen(ziel, stand.vorher)
        return True

    def _ziel_lesen(self, ziel: str):
        if ziel == "maske":
            return self._ki_maske, self.maske_per_klick
        if ziel == "lokal":
            return self._lokal_klick
        return self._entfern_klick

    def _ziel_setzen(self, ziel: str, wert):
        if ziel == "maske":
            self._ki_maske, self.maske_per_klick = wert
        elif ziel == "lokal":
            self._lokal_klick = wert
        else:
            self._entfern_klick = wert
        self._vollbild = None                    # das Vollbild zeigte den alten Stand

    def _aus_klicks(self, auswaehler, ziel: str):
        voll = auswaehler.maske(self._klickstand[ziel].logits[-1])
        paar = (voll, self._vorschau_von(voll))
        self._ziel_setzen(ziel, (paar, True) if ziel == "maske" else paar)

    # ------------------------------------------------------------------
    # Objekte entfernen: Markierung, LaMa, Flicken
    # ------------------------------------------------------------------

    def pinseln(self, punkte, radius: float, dazu: bool):
        """Kreise mit radius (Pixel des Originals) um die Punkte (im Original) markieren
        oder - mit dazu=False - die Markierung dort wegnehmen, auch die per Klick."""
        hoehe, breite = self.original.shape[:2]
        if self._pinsel is None and dazu:
            self._pinsel = (cp.zeros((hoehe, breite), dtype=cp.float32),
                            cp.zeros(self.vorschau_original.shape[:2], dtype=cp.float32))
        ebenen = [self._pinsel] if self._pinsel is not None else []
        if not dazu and self._entfern_klick is not None:
            ebenen.append(self._entfern_klick)
        massstaebe = (1.0, self.vorschau_massstab)
        for ebene in ebenen:
            for teil, m in zip(ebene, massstaebe, strict=True):
                for x, y in punkte:
                    _kreis(teil, x * m, y * m, max(radius * m, 0.5), dazu)
        self._vollbild = None

    def markierung_verwerfen(self):
        self._entfern_klick = None
        self._pinsel = None
        self._klickstand["entfernen"] = _Klicks()
        self._vollbild = None

    def _markierung(self, voll: bool):
        """Was entfernt werden soll (H, W) 0..1 im Original - oder None."""
        stelle = 0 if voll else 1
        ebenen = [e[stelle] for e in (self._entfern_klick, self._pinsel) if e is not None]
        if not ebenen:
            return None
        return ebenen[0] if len(ebenen) == 1 else cp.maximum(ebenen[0], ebenen[1])

    def ki_entfernen(self, entferner) -> float | None:
        """Das Markierte mit LaMa entfernen; Rueckgabe: Rechenzeit in ms, None ohne
        Markierung. LaMa sieht das Bild, wie es gerade entrauscht, geschaerft und
        retuschiert ist - so lassen sich Entfernungen stapeln."""
        markierung = self._markierung(True)
        if markierung is None:
            return None
        beginn = time.perf_counter()
        srgb = filter.linear_zu_srgb(cp.clip(self._ausgang(self.werte, True, leinwand=False),
                                             0, 1))
        ergebnis = entferner.fuellen(srgb, markierung)
        del srgb
        if ergebnis is None:
            return None
        y0, y1, x0, x1, fuellung, deckkraft = ergebnis
        gefuellt = filter.srgb_zu_linear(fuellung) * deckkraft[..., None]
        voll = (y0, y1, x0, x1, deckkraft, gefuellt)
        self._flicken.append(_Flicken(voll, self._flicken_vorschau(voll)))
        self._flicken_stand = next(self._nummern)
        self.markierung_verwerfen()
        return self._ki_fertig(beginn)

    def _flicken_vorschau(self, voll):
        """Derselbe Flicken fuer die Vorschau: Box-Mittel wie beim Verkleinern des
        Originals, damit Vorschau und Export dasselbe zeigen."""
        y0, y1, x0, x1, deckkraft, gefuellt = voll
        faktor = round(1 / self.vorschau_massstab)
        if faktor == 1:
            return voll
        vh, vb = self.vorschau_original.shape[:2]
        ya, xa = y0 // faktor, x0 // faktor
        ye, xe = min(vh, -(-y1 // faktor)), min(vb, -(-x1 // faktor))
        if ye <= ya or xe <= xa:
            return (ya, ya, xa, xa, cp.zeros((0, 0), cp.float32), cp.zeros((0, 0, 3), cp.float32))
        hoehe, breite = (ye - ya) * faktor, (xe - xa) * faktor
        oy, ox = y0 - ya * faktor, x0 - xa * faktor
        d = cp.zeros((hoehe, breite), dtype=cp.float32)
        g = cp.zeros((hoehe, breite, 3), dtype=cp.float32)
        h, w = min(y1 - y0, hoehe - oy), min(x1 - x0, breite - ox)
        d[oy:oy + h, ox:ox + w] = deckkraft[:h, :w]
        g[oy:oy + h, ox:ox + w] = gefuellt[:h, :w]
        return (ya, ye, xa, xe, filter.verkleinern_box(d, faktor).astype(cp.float32),
                filter.verkleinern_box(g, faktor).astype(cp.float32))

    def entfernungen_verwerfen(self) -> bool:
        """Alle Entfernungen, gefuellten Staub und die Markierung verwerfen - fuer
        „Zurücksetzen“.
        Rueckgabe: ob es Entfernungen gab."""
        self.markierung_verwerfen()
        if not self._flicken and self._staub is None:
            return False
        self._flicken.clear()
        self._staub = None
        self._flicken_stand = next(self._nummern)
        self._speicher.clear()
        self._vollbild = None
        return True

    def entfernen_zurueck(self) -> bool:
        """Die letzte Entfernung zuruecknehmen."""
        if not self._flicken:
            return False
        self._flicken.pop()
        self._flicken_stand = next(self._nummern)
        self._speicher.clear()
        self._vollbild = None
        return True

    def _flicken_auflegen(self, bild, stelle: int):
        gespeichert = (self.original, self.vorschau_original,
                       self._staub.vorschau if self._staub is not None else None)
        if any(bild is teil for teil in gespeichert):
            bild = bild.copy()                    # Original und gefuellter Staub bleiben
        for flicken in self._flicken:
            y0, y1, x0, x1, deckkraft, gefuellt = flicken.vorschau if stelle else flicken.voll
            if y1 <= y0 or x1 <= x0:
                continue
            teil = bild[y0:y1, x0:x1]
            teil *= (1 - deckkraft)[..., None]
            teil += gefuellt
        return bild

    # ------------------------------------------------------------------
    # KI-Erweitern: Raender im Zielformat erfinden
    # ------------------------------------------------------------------

    def _vorschau_faktor(self) -> int:
        return round(1 / self.vorschau_massstab)

    def erweiterung_planen(self, verhaeltnis: float) -> tuple[int, int, int, int]:
        """(W, H, x, y) der Leinwand im Seitenverhaeltnis Breite/Hoehe des Originals."""
        hoehe, breite = self.original.shape[:2]
        return ki.leinwand_planen(breite, hoehe, verhaeltnis, raster=self._vorschau_faktor())

    def ki_erweitern(self, erweiterer, verhaeltnis: float, seed: int,
                     fortschritt=None) -> float:
        """Das Bild mit KI auf das Seitenverhaeltnis (Breite/Hoehe des Originals, vor
        dem Drehen) erweitern; Rueckgabe: Rechenzeit in ms.

        Das Netz sieht das Bild, wie es gerade entrauscht, geschaerft und
        retuschiert ist. Gespeichert werden nur die Raender: Eingesetzt wird
        bei jeder Vorschau das aktuelle Bild - die Regler davor wirken weiter.
        """
        beginn = time.perf_counter()
        hoehe, breite = self.original.shape[:2]
        gross_b, gross_h, x, y = self.erweiterung_planen(verhaeltnis)
        srgb = filter.linear_zu_srgb(cp.clip(self._ausgang(self.werte, True, leinwand=False),
                                             0, 1))
        rand = erweiterer.raender(srgb, gross_b, gross_h, x, y, seed, fortschritt)
        del srgb
        rand = filter.srgb_zu_linear(rand)
        deckkraft = ki.saum_deckkraft(gross_b, gross_h, x, y, breite, hoehe,
                                      ki.saum_breite(breite, hoehe), cp)
        voll = (rand, deckkraft)
        faktor = self._vorschau_faktor()
        vorschau = voll if faktor == 1 else tuple(
            filter.verkleinern_box(teil, faktor).astype(cp.float32) for teil in voll)
        self._erweiterung = None                  # die alte Leinwand zuerst freigeben
        self._erweiterung = _Erweiterung(x, y, voll, vorschau, seed, verhaeltnis)
        self._profil_nachfuehren()
        self._flicken_stand = next(self._nummern)
        return self._ki_fertig(beginn)

    def erweiterung_verwerfen(self) -> bool:
        if self._erweiterung is None:
            return False
        self._erweiterung = None
        self._profil_nachfuehren()
        self._flicken_stand = next(self._nummern)
        self._ki_fertig(time.perf_counter())
        return True

    # ------------------------------------------------------------------
    # Objektivprofil
    # ------------------------------------------------------------------

    def objektiv_suchen(self) -> objektivprofile.Suche:
        """Profil fuer das Bild suchen - beim Oeffnen und nach dem Laden der Datenbank.
        Bei RAW wird ein gefundenes Profil gleich angewendet: Kamera-JPEGs sind oft
        schon in der Kamera korrigiert, dort entscheidet der Anwender."""
        self.objektiv = objektivprofile.suchen(self.daten.aufnahme)
        if self.objektiv.profil is not None and self.daten.raw and not self.werte.objektivprofil:
            danach = self._still_aendern()
            self.werte.objektivprofil = self.objektiv_terme()
            danach()
        return self.objektiv

    def grundwerte(self) -> Einstellungen:
        """Was „Alles zurücksetzen“ herstellt: alle Vorgaben, bei RAW mit dem Profil,
        dazu Urheber und Copyright, wenn sie in jedes Bild sollen."""
        werte = Einstellungen(angaben=self._angaben_vorgabe)
        if self.objektiv.profil is not None and self.daten.raw:
            werte.objektivprofil = self.objektiv_terme()
        return werte

    # ------------------------------------------------------------------
    # Metadaten
    # ------------------------------------------------------------------

    @property
    def angaben(self) -> metadaten.Angaben:
        """Titel, Urheber, Ort ... so, wie sie gespeichert werden."""
        return metadaten.mit(self.vorgefunden.angaben, self.werte.angaben)

    def angabe_setzen(self, name: str, wert):
        self.werte.angaben = metadaten.aendern(self.werte.angaben, self.vorgefunden.angaben,
                                               name, wert)

    def angaben_vorgeben(self, urheber: str, copyright_: str):
        """Urheber und Copyright fuer Bilder, die selbst keine haben. Gilt wie die Datei
        selbst nicht als Aenderung - nur gespeichert wird es mit."""
        vorgabe = ()
        for name, wert in (("urheber", urheber.strip()), ("copyright", copyright_.strip())):
            if wert and not getattr(self.vorgefunden.angaben, name):
                vorgabe = metadaten.aendern(vorgabe, self.vorgefunden.angaben, name, wert)
        alt, self._angaben_vorgabe = self._angaben_vorgabe, vorgabe
        if self.werte.angaben == alt:
            danach = self._still_aendern()
            self.werte.angaben = vorgabe
            danach()

    def angaben_grundwerte(self) -> tuple:
        """Was „Angaben zurücksetzen“ herstellt."""
        return self._angaben_vorgabe

    def _metadaten(self, breite: int, hoehe: int) -> tuple[bytes, bytes]:
        return metadaten.fuer_speichern(self.daten.exif, self.daten.xmp, self.vorgefunden,
                                        self.werte.angaben, breite, hoehe,
                                        self.werte.metadaten_entfernen)

    def objektiv_terme(self) -> tuple[float, ...]:
        """Die Terme des Profils samt Lage des Originals in dem, was die Geometrie sieht."""
        if self.objektiv.profil is None:
            return ()
        hoehe, breite = self.original.shape[:2]
        if self._erweiterung is None:
            bezug = geometrie.BEZUG_NEUTRAL
        else:
            gross_h, gross_b = self.quellform()
            bezug = ((self._erweiterung.x + breite / 2) / gross_b,
                     (self._erweiterung.y + hoehe / 2) / gross_h,
                     math.hypot(breite, hoehe) / math.hypot(gross_b, gross_h))
        return tuple(self.objektiv.profil.terme) + tuple(float(z) for z in bezug)

    def _profil_nachfuehren(self):
        if self.werte.objektivprofil:
            self.werte.objektivprofil = self.objektiv_terme()

    def quellform(self) -> tuple[int, int]:
        """Hoehe und Breite dessen, was die Geometrie sieht: Original oder Leinwand."""
        if self._erweiterung is None:
            return self.original.shape[:2]
        return self._erweiterung.voll[0].shape[:2]

    def _lage(self, stelle: int) -> tuple[int, int]:
        faktor = 1 if stelle == 0 else self._vorschau_faktor()
        return self._erweiterung.x // faktor, self._erweiterung.y // faktor

    def _auf_leinwand(self, bild, stelle: int):
        """Bild in Groesse des Originals bzw. der Vorschau in die Leinwand einsetzen."""
        rand, deckkraft = self._erweiterung.voll if stelle == 0 else self._erweiterung.vorschau
        x, y = self._lage(stelle)
        return ki.einsetzen(rand, bild, x, y, deckkraft)

    def _auf_grau(self, bild, stelle: int):
        """Wie `_auf_leinwand`, aber die Raender sind neutral grau (sRGB 128) und das
        Original sitzt unverwischt an seinem Platz."""
        rand = (self._erweiterung.voll if stelle == 0 else self._erweiterung.vorschau)[0]
        x, y = self._lage(stelle)
        hoehe, breite = bild.shape[:2]
        ergebnis = cp.full(rand.shape, GRAU_LINEAR, dtype=bild.dtype)
        ergebnis[y:y + hoehe, x:x + breite] = bild
        return ergebnis

    def _ebene_auf_leinwand(self, ebene, fortsetzen: bool = True):
        """Eine Ebene (h, w) im Original oder in der Vorschau auf die Leinwand bringen -
        mit dem Wert am Rand fortgesetzt oder mit 0 aufgefuellt."""
        if self._erweiterung is None:
            return ebene
        stelle = 0 if ebene.shape[:2] == self.original.shape[:2] else 1
        rand = (self._erweiterung.voll if stelle == 0 else self._erweiterung.vorschau)[0]
        x, y = self._lage(stelle)
        hoehe, breite = ebene.shape[:2]
        raender = ((y, rand.shape[0] - y - hoehe), (x, rand.shape[1] - x - breite))
        if fortsetzen:
            return cp.pad(ebene, raender, mode="edge")
        return cp.pad(ebene, raender)

    # ------------------------------------------------------------------
    # Tiefe & Bokeh
    # ------------------------------------------------------------------

    def ki_tiefe(self, schaetzer) -> float:
        """Die Tiefe einmal mit KI schaetzen; Rueckgabe: Rechenzeit in ms."""
        beginn = time.perf_counter()
        srgb = filter.linear_zu_srgb(cp.clip(self._ausgang(self.werte, True, leinwand=False),
                                             0, 1))
        self._ki_tiefe = schaetzer.tiefe(srgb)
        del srgb
        self._lokal_quellen_neu()
        self._vollbild = None
        cp.get_default_memory_pool().free_all_blocks()
        return (time.perf_counter() - beginn) * 1000

    def tiefe_an(self, x: float, y: float) -> float:
        """Tiefe 0..100 am Punkt (x, y) im Original - Median ueber eine kleine Umgebung."""
        hoehe, breite = self.original.shape[:2]
        th, tb = self._ki_tiefe.shape
        ty, tx = int(y / hoehe * th), int(x / breite * tb)
        teil = self._ki_tiefe[max(0, ty - 3):ty + 4, max(0, tx - 3):tx + 4]
        return float(cp.median(teil)) * 100

    def fokus_vorschlag(self) -> float:
        """Wohin scharf stellen: aufs Motiv, wenn eine Maske da ist, sonst aufs Naechste."""
        if self._ki_maske is not None:
            th, tb = self._ki_tiefe.shape
            motiv = filter.vergroessern(self._ki_maske[0], th, tb) > 0.5
            if bool(motiv.any()):
                return float(cp.median(self._ki_tiefe[motiv])) * 100
        # Ohne Maske: das Mittel des naechsten Fuenftels - meist das Motiv
        nah = self._ki_tiefe[self._ki_tiefe >= cp.percentile(self._ki_tiefe, 80.0)]
        return float(cp.median(nah)) * 100

    def _tiefe_fuer(self, werte: Einstellungen, voll: bool):
        """Tiefe in der Groesse des Originals bzw. der Vorschau und in der Geometrie
        des fertigen Bildes."""
        quelle = self.original if voll else self.vorschau_original
        tiefe = filter.vergroessern(self._ki_tiefe, *quelle.shape[:2])
        return self._in_geometrie(self._ebene_auf_leinwand(tiefe), werte)

    def _bokeh(self, ergebnis, werte: Einstellungen, voll: bool, hoechst: float):
        """Unschaerfe nach Abstand zur Fokusebene auf das fertige Bild (0..hoechst)."""
        tiefe = self._tiefe_fuer(werte, voll)
        rand = werte.schaerfentiefe / 100 * TIEFE_BEREICH
        abstand = cp.clip((cp.abs(tiefe - werte.fokus / 100) - rand) / TIEFE_UEBERGANG, 0, 1)
        if werte.bokeh_motiv and self._ki_maske is not None:
            motiv = self._in_geometrie(self._ebene_auf_leinwand(self._ki_maske[0 if voll else 1]),
                                       werte)
            abstand *= 1 - motiv
        sigma = werte.bokeh / 100 * BOKEH_MAX * max(ergebnis.shape[:2])
        radius = abstand * sigma                  # Sigma je Pixel
        linear = filter.srgb_zu_linear(cp.clip(ergebnis / hoechst, 0, 1))
        stufen = [s * sigma for s in BOKEH_STUFEN]
        fassungen = [linear]
        for stufe in stufen:
            # Normierte Faltung: Es tragen nur Pixel bei, die selbst mindestens etwa so
            # unscharf sind - ein scharfes Motiv laeuft nicht als Schein in den Hintergrund
            gewicht = cp.clip(radius / stufe, 0, 1)
            nenner = filter.grob_weichzeichnen(gewicht, stufe)
            zaehler = filter.grob_weichzeichnen(linear * gewicht[..., None], stufe)
            gueltig = (nenner > 1e-3)[..., None]
            fassungen.append(cp.where(gueltig, zaehler / cp.maximum(nenner, 1e-3)[..., None],
                                      linear))
        # Zwischen den Fassungen nach dem Radius des Pixels ueberblenden
        knoten = [0.0, *stufen]
        gemischt = cp.zeros_like(linear)
        for k, fassung in enumerate(fassungen):
            anteil = cp.ones_like(radius)
            if k > 0:
                anteil = cp.minimum(anteil, cp.clip((radius - knoten[k - 1])
                                                    / (knoten[k] - knoten[k - 1]), 0, 1))
            if k < len(knoten) - 1:
                anteil = cp.minimum(anteil, cp.clip((knoten[k + 1] - radius)
                                                    / (knoten[k + 1] - knoten[k]), 0, 1))
            gemischt += fassung * anteil[..., None]
        return filter.linear_zu_srgb(gemischt) * hoechst

    @staticmethod
    def _in_geometrie(maske, werte: Einstellungen):
        """Eine Maske im Original (H, W) in die Geometrie des fertigen Bildes bringen."""
        geo = geometrie.aus(werte)
        if not geo.ist_neutral():
            nur_form = dataclasses.replace(geo, vignette=0.0, ca_rot=0.0, ca_blau=0.0)
            maske = geometrie.anwenden(cp.repeat(maske[..., None], 3, axis=2), nur_form)[..., 0]
        return cp.ascontiguousarray(cp.clip(maske, 0, 1), dtype=cp.float32)

    # ------------------------------------------------------------------
    # Quellen lokaler Masken: KI-Ergebnisse und das Bild selbst
    # ------------------------------------------------------------------

    def _lokal_quellen_neu(self):
        """Eine Quelle hat sich geaendert - gerasterte Masken gelten nicht mehr."""
        self._lokal_quellen_nr += 1
        self._lokal_raster.clear()
        self._lokal_bild.clear()
        self._vollbild = None

    def _lokal_ki_setzen(self, schluessel: tuple, voll):
        acht = (cp.clip(voll, 0, 1) * 255 + 0.5).astype(cp.uint8)
        self._lokal_ki[schluessel] = (acht, self._vorschau_von(acht.astype(cp.float32) / 255))
        self._lokal_quellen_neu()

    def _lokal_ki_gebraucht(self) -> list[tuple]:
        """Die KI-Ergebnisse, die die Masken der jetzigen Werte brauchen - in der Reihenfolge
        der Teile, nicht der eines sets: Die haengt bei "motiv" vom Hash-Zufall ab, und die
        Begleitdatei waere bei gleicher Bearbeitung nicht gleich."""
        gebraucht = []
        for maske in self.werte.masken:
            for teil in maske.teile:
                if teil.art == "motiv":
                    schluessel = ("motiv",)
                elif teil.art == "objekt":
                    schluessel = ("objekt", teil.daten)
                else:
                    continue
                if schluessel not in gebraucht:
                    gebraucht.append(schluessel)
        return gebraucht

    def lokal_ki_da(self, schluessel: tuple) -> bool:
        return schluessel in self._lokal_ki

    def lokal_ki_fehlt(self) -> list[str]:
        """Was lokale Masken brauchen und sich neu rechnen laesst, aber fehlt:
        "lokal_motiv", "lokal_tiefe" - etwa nach einer Voreinstellung."""
        quellen = set()
        for maske in self.werte.masken:
            quellen |= lokal.quellen_von(maske)
        fehlt = []
        if "motiv" in quellen and ("motiv",) not in self._lokal_ki:
            fehlt.append("lokal_motiv")
        if "tiefe" in quellen and self._ki_tiefe is None:
            fehlt.append("lokal_tiefe")
        return fehlt

    def lokal_motiv(self, freisteller) -> float:
        """Das Motiv fuer lokale Masken einmal mit KI erkennen; Rueckgabe in ms. Wie beim
        Freistellen sieht das Netz das Bild, wie es gerade entrauscht und geschaerft ist."""
        beginn = time.perf_counter()
        srgb = filter.linear_zu_srgb(cp.clip(self._ausgang(self.werte, True, leinwand=False),
                                             0, 1))
        voll = freisteller.maske(srgb)
        del srgb
        self._lokal_ki_setzen(("motiv",), voll)
        return self._ki_fertig(beginn)

    def lokal_klicks_beginnen(self):
        """Ein Objekt neu auswaehlen: die Klicks beginnen von vorn."""
        self._klickstand["lokal"] = _Klicks()
        self._lokal_klick = None

    def lokal_objekt_merken(self, klicks: tuple):
        """Was die Klicks ergeben haben, unter ihren Klicks merken. Aeltere Staende bleiben
        fuer Rueckgaengig, aber nicht unbegrenzt."""
        if self._lokal_klick is not None:
            self._lokal_ki_setzen(("objekt", klicks), self._lokal_klick[0])
        gebraucht = set(self._lokal_ki_gebraucht()) | {("objekt", klicks), ("motiv",)}
        uebrig = [k for k in self._lokal_ki if k not in gebraucht]
        for schluessel in uebrig[:-LOKAL_KI_AUFHEBEN]:
            del self._lokal_ki[schluessel]

    def _lokal_bildquellen(self, werte: Einstellungen, voll: bool) -> dict:
        """Helligkeit (sRGB-kodiert), Farbton und Buntheit des Bildes vor allen Reglern -
        auf der Leinwand, in der Groesse von Original oder Vorschau."""
        stand = (werte.film, werte.film_maske, werte.film_umfang, id(self._staub),
                 id(self._erweiterung), self._lokal_quellen_nr)
        gespeichert = self._lokal_bild.get(voll)
        if gespeichert is not None and gespeichert[0] == stand:
            return gespeichert[1]
        self._lokal_bild.pop(voll, None)
        bild = self._film_bild(werte, voll)
        if self._erweiterung is not None:
            bild = self._auf_leinwand(bild, 0 if voll else 1)
        bild = cp.clip(bild, 0, 1)
        lab = filter.nach_oklab(bild)
        chroma = cp.sqrt(lab[..., 1] ** 2 + lab[..., 2] ** 2)
        quellen = {"helligkeit": filter.linear_zu_srgb(filter.luminanz(bild)),
                   "farbton": cp.degrees(cp.arctan2(lab[..., 2], lab[..., 1])) % 360.0,
                   "buntheit": cp.clip(chroma / filter.HSL_CHROMA_VOLL, 0, 1)}
        del lab, chroma
        self._lokal_bild[voll] = (stand, quellen)
        return quellen

    def _lokal_quellen(self, maske: lokal.Maske, werte: Einstellungen, voll: bool) -> dict:
        """Was die KI- und Bereichsteile einer Maske brauchen, auf der Leinwand."""
        noetig = lokal.quellen_von(maske)
        quellen = {}
        stelle = 0 if voll else 1
        for quelle in noetig:
            if quelle == "tiefe":
                if self._ki_tiefe is not None:
                    groesse = (self.original if voll else self.vorschau_original).shape[:2]
                    quellen["tiefe"] = self._ebene_auf_leinwand(
                        filter.vergroessern(self._ki_tiefe, *groesse))
            elif quelle == "motiv" or isinstance(quelle, tuple):
                paar = self._lokal_ki.get(("motiv",) if quelle == "motiv" else quelle)
                if paar is not None:
                    ebene = paar[0].astype(cp.float32) / 255 if stelle == 0 else paar[1]
                    quellen[quelle] = self._ebene_auf_leinwand(ebene)
        if "helligkeit" in noetig or "farbe" in noetig:
            quellen.update(self._lokal_bildquellen(werte, voll))
        return quellen

    # ------------------------------------------------------------------
    # Automatik: Auto-Ton, Auto-Weissabgleich, Pipette (automatik.py)
    # ------------------------------------------------------------------

    def ton_automatisch(self) -> automatik.Ton:
        """Belichtung, Kontrast, Lichter und Tiefen fuer ein ausgewogenes Bild - gemessen
        am fertigen Vorschaubild im Zuschnitt, mit allem anderen, wie es eingestellt ist,
        und den vier Werten auf 0 (so gibt jedes Druecken dasselbe). Aendert die Werte
        der Sitzung nicht."""
        werte = self.werte
        speicher: dict = {}      # eigene Zwischenstufen: die der Vorschau bleiben gueltig

        def rendern(ton: automatik.Ton):
            return self._rendern(dataclasses.replace(werte, **ton.felder()), False, speicher,
                                 zeigen=False, mit_korn=False)
        return automatik.ton_automatisch(rendern)

    def _weiss_bild(self):
        """Das Bild so, wie es in den Weissabgleich geht (linear, nach Negativ-Umkehr, KI und
        Flicken), aber nach der Geometrie: gemessen wird im Zuschnitt. Der Weissabgleich ist
        ein Faktor je Kanal und vertauscht darum mit der Geometrie."""
        werte = self.werte
        eingang = self._anonymisieren(self._ausgang(werte, False), werte, False, True)
        return geometrie.anwenden(eingang, geometrie.aus(werte))

    def weissabgleich_auto(self) -> tuple[float, float] | None:
        """(Temperatur, Toenung), die das Bild im Zuschnitt neutral machen, oder None, wenn
        nichts Messbares da ist. Unabhaengig von den jetzigen Werten."""
        return automatik.weissabgleich_auto(self._weiss_bild())

    def weissabgleich_punkt(self, x: float, y: float) -> tuple[float, float] | None:
        """Dasselbe fuer die Umgebung des Punktes (x, y) im fertigen Bild (Pixel in voller
        Aufloesung): Dieser Punkt wird neutral."""
        bild = self._weiss_bild()
        hoehe, breite = self.ausgabe_form()
        return automatik.weissabgleich_punkt(bild, x * bild.shape[1] / breite,
                                             y * bild.shape[0] / hoehe)

    def farbton_an(self, x: float, y: float) -> float | None:
        """Farbton (OkLCh, Grad) um den Punkt (x, y) im Original - nach Buntheit gemittelt;
        None, wo nichts bunt ist."""
        quellen = self._lokal_bildquellen(self.werte, False)
        hoehe, breite = quellen["farbton"].shape
        h_orig, b_orig = self.quellform()
        if self._erweiterung is not None:
            x, y = x + self._erweiterung.x, y + self._erweiterung.y
        sx, sy = int(x * breite / b_orig), int(y * hoehe / h_orig)
        y0, y1 = max(0, sy - 2), min(hoehe, sy + 3)
        x0, x1 = max(0, sx - 2), min(breite, sx + 3)
        if y1 <= y0 or x1 <= x0:
            return None
        winkel = cp.radians(quellen["farbton"][y0:y1, x0:x1])
        gewicht = quellen["buntheit"][y0:y1, x0:x1]
        if float(gewicht.sum()) < 1e-3:
            return None
        mitte = float(cp.degrees(cp.arctan2((cp.sin(winkel) * gewicht).sum(),
                                            (cp.cos(winkel) * gewicht).sum())))
        return mitte % 360.0

    def _lokal_gewicht(self, maske: lokal.Maske, werte: Einstellungen, voll: bool):
        """Wirkung einer lokalen Maske (H, W) in der Geometrie des fertigen Bildes. Bleibt
        gespeichert, solange sich Teile, Geometrie und Leinwand nicht aendern."""
        stelle = 0 if voll else 1
        original = self.original.shape[:2]
        if self._erweiterung is not None:
            gitter = (self._erweiterung.voll if voll else self._erweiterung.vorschau)[0]
            versatz = self._lage(stelle)
        else:
            gitter = self.original if voll else self.vorschau_original
            versatz = (0, 0)
        hoehe, breite = gitter.shape[:2]
        quelle = (self.original if voll else self.vorschau_original).shape[:2]
        faktor = (original[0] / quelle[0], original[1] / quelle[1])
        schluessel = (maske.teile, voll, geometrie.aus(werte), (hoehe, breite), versatz,
                      self._lokal_quellen_nr, (werte.film, werte.film_maske, werte.film_umfang)
                      if {"helligkeit", "farbe"} & lokal.quellen_von(maske) else ())
        if schluessel not in self._lokal_raster:
            raster = lokal.gewicht(maske, hoehe, breite, original, versatz, faktor, cp,
                                   self._pinsel_raster,
                                   self._lokal_quellen(maske, werte, voll))
            self._lokal_raster[schluessel] = self._in_geometrie(raster, werte)
        return self._lokal_raster[schluessel]

    def _lokal_karten(self, werte: Einstellungen, voll: bool):
        """Die wirkenden Masken als [(Gewicht, Werte)] fuer filter.anwenden_ausgabe - oder
        None. Was keine Maske mehr braucht, faellt aus dem Speicher."""
        karten = []
        for maske in werte.masken:
            if maske.wirkt():
                karten.append((self._lokal_gewicht(maske, werte, voll), maske.werte))
        gebraucht = {(m.teile, voll) for m in werte.masken}
        zeigen = self._lokal_zeige_maske(werte)
        if zeigen is not None:
            gebraucht.add((zeigen.teile, voll))
        for schluessel in [k for k in self._lokal_raster
                           if k[1] == voll and (k[0], k[1]) not in gebraucht]:
            del self._lokal_raster[schluessel]
        # Vom Pinsel bleibt nur, worauf ein Strich der jetzigen Masken weiter aufbaut
        davor = {t.striche[:-1] for m in werte.masken for t in m.teile if t.art == "pinsel"}
        for schluessel in [k for k in self._pinsel_raster if k[0] not in davor]:
            del self._pinsel_raster[schluessel]
        return karten or None

    def _lokal_zeige_maske(self, werte: Einstellungen) -> lokal.Maske | None:
        nummer = self.lokal_zeigen
        if nummer is None or not 0 <= nummer < len(werte.masken):
            return None
        maske = werte.masken[nummer]
        return maske if maske.teile else None

    def _maske_fuer(self, werte: Einstellungen, voll: bool):
        """Gewicht des Motivs (H, W) in der Geometrie des fertigen Bildes: Kante
        verschoben und weich, wenn gewuenscht umgekehrt. 1 heisst: Werte des ganzen
        Bildes, 0: die des Hintergrunds."""
        maske = self._ki_maske[0 if voll else 1]
        massstab = 1.0 if voll else self.vorschau_massstab
        if werte.maske_verschieben:
            from cupyx.scipy import ndimage
            weite = max(1, round(abs(werte.maske_verschieben) / 100 * MASKE_VERSCHIEBEN
                                 * massstab))
            art = ndimage.maximum_filter if werte.maske_verschieben > 0 else ndimage.minimum_filter
            maske = art(maske, size=2 * weite + 1, mode="nearest")
        if werte.maske_kante:
            maske = filter.gauss(maske, werte.maske_kante / 100 * MASKE_KANTE * massstab)
        if werte.maske_umkehren:
            maske = 1 - maske
        return self._in_geometrie(self._ebene_auf_leinwand(maske), werte)

    def _rendern(self, werte: Einstellungen, voll: bool, speicher, bits: int = 8,
                 zeigen: bool = False, leinwand: bool = True, flicken: bool = True,
                 mit_korn: bool = True, grau: bool = False, klar: dict | None = None):
        """Die ganze Kette bis zum sRGB-Bild - mit eigenem Hintergrund, falls eingestellt.
        leinwand=False: ohne die Raender einer KI-Erweiterung, flicken=False: ohne
        entfernte Objekte (beides fuer „Vorher“), mit_korn=False: ohne Filmkorn (das
        kommt beim KI-Hochskalieren erst danach), grau=True: die Raender einer KI-Erweiterung
        neutral grau statt erfunden (Vorher-Haelfte des Vergleichs). klar: ein leeres dict;
        liegen Farben der Maskenansicht, Tiefe, Staub oder Markierung im Ergebnis, steht
        darin unter "bild" dasselbe Bild davor - so zaehlt die Abschneide-Warnung
        nicht deren Farben."""
        massstab = 1.0 if voll else self.vorschau_massstab
        if not flicken and (self._flicken or self._staub is not None):
            speicher = {}       # die Zwischenstufen im Speicher enthalten die Flicken
        eingang = self._anonymisieren(self._ausgang(werte, voll, leinwand=leinwand,
                                                    flicken=flicken, grau=grau),
                                      werte, voll, leinwand)
        karten = self._lokal_karten(werte, voll)
        bild = filter.anwenden_ausgabe(eingang, werte, massstab, speicher, bits=bits,
                                       lokal=karten)
        if not leinwand and self._erweiterung is not None:
            # Masken, Tiefe und Markierung liegen auf der Leinwand
            return korn.auflegen(bild, werte) if mit_korn else bild
        markierung = self._markierung(voll) if zeigen else None
        if zeigen and self.staub_zeigen and self._staub_fund is not None:
            fund = self._staub_fund[1].astype(cp.float32) if voll else self._staub_fund[2]
            markierung = fund if markierung is None else cp.maximum(markierung, fund)
        tiefe_zeigen = zeigen and self.tiefe_zeigen and self._ki_tiefe is not None
        lokal_zeigen = self._lokal_zeige_maske(werte) if zeigen else None
        zeigen = zeigen and self.maske_zeigen
        hintergrund = self._ki_maske is not None and (werte.hintergrund_aktiv() or zeigen)
        bokeh = self._ki_tiefe is not None and werte.bokeh > 0
        if not (hintergrund or bokeh or tiefe_zeigen or markierung is not None
                or lokal_zeigen is not None):
            return korn.auflegen(bild, werte) if mit_korn else bild
        hoechst = 65535.0 if bits == 16 else 255.0
        typ = cp.uint16 if bits == 16 else cp.uint8
        ergebnis = bild.astype(cp.float32)
        maske = self._maske_fuer(werte, voll)[..., None] if hintergrund else None
        if hintergrund and werte.hintergrund_aktiv():
            hg = filter.anwenden_ausgabe(eingang, werte.fuer_hintergrund(), massstab, speicher,
                                         bits=bits, lokal=karten).astype(cp.float32)
            if werte.hg_unschaerfe:
                # Nur der Hintergrund wird verwischt: das Motiv darf nicht als Schein
                # in ihn hineinlaufen (normierte Faltung mit dem Hintergrund als Gewicht)
                sigma = werte.hg_unschaerfe / 100 * HG_UNSCHAERFE * massstab
                gewicht = 1 - maske[..., 0]
                nenner = cp.maximum(filter.gauss(gewicht, sigma), 1e-4)
                for kanal in range(3):
                    hg[..., kanal] = filter.gauss(hg[..., kanal] * gewicht, sigma) / nenner
            ergebnis = hg + maske * (ergebnis - hg)
        if bokeh:
            ergebnis = self._bokeh(ergebnis, werte, voll, hoechst)
        if mit_korn:
            ergebnis = korn.auflegen(ergebnis, werte, hoechst)
        if klar is not None and (tiefe_zeigen or (zeigen and maske is not None)
                                 or lokal_zeigen is not None or markierung is not None):
            klar["bild"] = cp.clip(ergebnis + 0.5, 0, hoechst).astype(typ)
        if tiefe_zeigen:
            ergebnis = cp.repeat(self._tiefe_fuer(werte, voll)[..., None], 3, axis=2) * hoechst
        if zeigen and maske is not None:
            farbe = cp.asarray(MASKE_FARBE, dtype=cp.float32) * hoechst
            ergebnis = maske * ergebnis + (1 - maske) * (0.4 * ergebnis + 0.6 * farbe)
        if lokal_zeigen is not None:
            m = self._lokal_gewicht(lokal_zeigen, werte, voll)[..., None] * LOKAL_DECKUNG
            farbe = cp.asarray(MASKE_FARBE, dtype=cp.float32) * hoechst
            ergebnis = ergebnis * (1 - m) + m * farbe
        if markierung is not None:
            m = self._in_geometrie(self._ebene_auf_leinwand(markierung, fortsetzen=False),
                                   werte)[..., None] * MARKIERUNG_DECKUNG
            farbe = cp.asarray(MARKIERUNG_FARBE, dtype=cp.float32) * hoechst
            ergebnis = ergebnis * (1 - m) + m * farbe
        return cp.clip(ergebnis + 0.5, 0, hoechst).astype(typ)

    def _anonymisieren(self, bild, werte: Einstellungen, voll: bool, leinwand: bool):
        """Die Flaechen zum Anonymisieren aufs Ausgangsbild - vor allen Reglern, damit
        nichts sie wieder schaerft; die KI-Netze bekommen das Bild ohne sie."""
        stand = (werte.anonym_flaechen, werte.anonym_art, werte.anonym_bloecke)
        if stand != self._anonym_stand:
            # Zwischenstufen (Entrauschen, Dunst) gelten nur fuer denselben Bildinhalt
            self._speicher.clear()
            self._anonym_stand = stand
        if not werte.anonym_flaechen:
            return bild
        original = (self.original if voll else self.vorschau_original).shape[:2]
        versatz = (0, 0)
        if leinwand and self._erweiterung is not None:
            versatz = self._lage(0 if voll else 1)
        return anonym.anwenden(bild, werte.anonym_flaechen, werte.anonym_art,
                               werte.anonym_bloecke, original, versatz)

    def _ki_korrektur(self, netz, bild, kachel: int, fortschritt):
        """Was das Netz an einem Bild in linearem Licht aendert, als Korrektur.

        Das Netz kennt Bilder in sRGB von 0 bis 1. Was heller ist - Lichter
        einer RAW -, bekommt es begrenzt zu sehen; zurueck kommt nur seine
        Korrektur, die aufs ungekuerzte Bild gelegt wird. So bleiben die
        Lichter erhalten.
        """
        begrenzt = cp.clip(bild, 0, 1)
        neu = netz.rechnen(filter.linear_zu_srgb(begrenzt), kachel, fortschritt)
        korrektur = filter.srgb_zu_linear(neu)
        del neu
        korrektur -= begrenzt
        return korrektur

    def _vorschau_von(self, voll):
        faktor = round(1 / self.vorschau_massstab)
        return voll if faktor == 1 else filter.verkleinern_box(voll, faktor).astype(cp.float32)

    def _ki_fertig(self, beginn: float) -> float:
        # Zwischenergebnisse beruhten auf dem alten Ausgangsbild
        self._speicher.clear()
        self._vollbild = None
        cp.get_default_memory_pool().free_all_blocks()
        return (time.perf_counter() - beginn) * 1000

    def ki_entrauschen(self, entrauscher, kachel: int, fortschritt=None) -> float:
        """Das Original einmal mit KI entrauschen; Rueckgabe: Rechenzeit in ms. Ein Negativ
        sieht das Netz schon umgewandelt - gespeichert wird nur seine Korrektur."""
        beginn = time.perf_counter()
        voll = self._ki_korrektur(entrauscher, self._film_bild(self.werte, True), kachel,
                                  fortschritt)
        self._ki_rauschfrei = (voll, self._vorschau_von(voll))
        return self._ki_fertig(beginn)

    def ki_schaerfen(self, schaerfer, kachel: int, fortschritt=None) -> float:
        """Das Bild einmal mit KI schaerfen; Rueckgabe: Rechenzeit in ms.

        Geschaerft wird das Original, wie es gerade entrauscht ist - Rauschen
        wuerde das Netz sonst mitschaerfen. Gespeichert wird nur die Korrektur;
        sie bleibt gueltig, wenn sich die Staerke des Entrauschens danach
        noch etwas aendert.

        Von der Korrektur bleibt nur der feine Anteil. Restormer hellt das Bild
        nebenbei auf und verschiebt die Farbe ein wenig, je Kachel verschieden;
        Schaerfe aber steckt in den feinen Strukturen. Was groeber ist als etwa
        zehn Pixel, wird deshalb abgezogen.
        """
        beginn = time.perf_counter()
        ausgang = self._ausgang(self.werte, True, schaerfen=False, leinwand=False)
        korrektur = self._ki_korrektur(schaerfer, ausgang, kachel, fortschritt)
        del ausgang
        for kanal in range(3):
            korrektur[..., kanal] -= filter.gauss(korrektur[..., kanal], SCHAERFE_GROB)
        self._ki_schaerfe = (korrektur, self._vorschau_von(korrektur))
        return self._ki_fertig(beginn)

    def ki_kolorieren(self, kolorierer, _kachel: int = 0, _fortschritt=None) -> float:
        """Die Farbe einmal mit KI schaetzen; Rueckgabe: Rechenzeit in ms.

        Das Netz sieht das Bild, wie es gerade entrauscht, geschaerft und
        geflickt ist - nur seine Helligkeit. Die Farbanteile werden fuer Original
        und Vorschau einmal auf deren Groesse gebracht; der Regler mischt sie dann
        sofort ein (farbe_einsetzen).
        """
        beginn = time.perf_counter()
        ausgang = self._ausgang(self.werte, True, leinwand=False, farbe=False)
        ab = kolorierer.farben(ausgang)
        del ausgang
        self._ki_farbe = None                     # die alte Farbe zuerst freigeben
        voll = filter.vergroessern(ab, *self.original.shape[:2]).astype(cp.float32)
        vorschau = filter.vergroessern(ab, *self.vorschau_original.shape[:2]).astype(cp.float32)
        self._ki_farbe = (cp.ascontiguousarray(voll), cp.ascontiguousarray(vorschau))
        return self._ki_fertig(beginn)

    def _film_bild(self, werte: Einstellungen, voll: bool, mit_staub: bool = True):
        """Original bzw. Vorschau - vom Staub befreit und ein Negativ schon ins Positiv
        gewandelt."""
        bild = self.original if voll else self.vorschau_original
        if mit_staub and self._staub is not None:
            if voll:
                bild = bild.copy()
                bild.reshape(-1, 3)[self._staub.stellen] = self._staub.werte
            else:
                bild = self._staub.vorschau
        stand = (werte.film, werte.film_maske, werte.film_umfang)
        if not film.aktiv(*stand):
            stand = ()
        if stand != self._film_stand:
            # Zwischenstufen (Entrauschen, Dunst) gelten nur fuer denselben Bildinhalt
            self._speicher.clear()
            self._film_stand = stand
        return film.umkehren(bild, *stand) if stand else bild

    def film_schaetzen(self, art: str) -> tuple[tuple, tuple]:
        """Filmmaske und Umfang fuer die Filmart aus dem Scan schaetzen - an der Vorschau,
        das genuegt fuer Perzentile und geht schnell."""
        return film.schaetzen(self.vorschau_original, art)

    def film_maske_messen(self, x: float, y: float) -> tuple[tuple, tuple]:
        """Die Pipette: Filmmaske an (x, y) im Original messen - sie ist dann der
        Schwarzpunkt -, den Weisspunkt dazu neu."""
        m = self.vorschau_massstab
        maske = film.maske_messen(self.vorschau_original, x * m, y * m)
        return maske, film.umfang_schaetzen(self.vorschau_original, maske,
                                            schwarz_ist_maske=True)

    # ------------------------------------------------------------------
    # Scan & Film: Staub und Kratzer ueber den Infrarotkanal
    # ------------------------------------------------------------------

    def staub_finden(self, empfindlichkeit: float) -> int:
        """Die Fehler im Infrarot suchen; Rueckgabe: wie viele Stellen. Die Fundstellen
        zeigt die Vorschau, wenn staub_zeigen gesetzt ist."""
        if self._staub_dunkel is None:
            self._staub_dunkel = staub.dunkelheit(staub.normiert(self.daten.infrarot))
        maske, kern, anzahl = staub.finden(self._staub_dunkel, empfindlichkeit)
        # In der Vorschau zeigt auch ein Staubkorn, das kleiner ist als ein Pixel
        vorschau = (self._vorschau_von(maske.astype(cp.float32)) > 0).astype(cp.float32)
        self._staub_fund = (empfindlichkeit, maske, vorschau, anzahl, kern)
        self._vollbild = None
        return anzahl

    def staub_entfernen(self, empfindlichkeit: float, entferner=None,
                        fortschritt=None) -> float:
        """Die gefundenen Stellen fuellen - breite mit LaMa, wenn entferner gegeben ist;
        Rueckgabe: Rechenzeit in ms. Ersetzt eine fruehere Fuellung."""
        beginn = time.perf_counter()
        if self._staub_fund is None or self._staub_fund[0] != empfindlichkeit:
            self.staub_finden(empfindlichkeit)
        _e, maske, _vorschau, anzahl, kern = self._staub_fund
        w = self.werte
        sauber = staub.entfernen(self.original, maske, kern, w.film, w.film_maske,
                                 w.film_umfang, entferner, fortschritt)
        flach = sauber.reshape(-1, 3)
        stellen = cp.flatnonzero((flach != self.original.reshape(-1, 3)).any(axis=1))
        werte = cp.ascontiguousarray(flach[stellen])
        vorschau = self._vorschau_von(sauber)
        if vorschau is sauber:
            vorschau = sauber.copy()
        del sauber, flach
        self._staub = _Staub(stellen, werte, vorschau, anzahl)
        self._flicken_stand = next(self._nummern)
        return self._ki_fertig(beginn)

    def staub_verwerfen(self) -> bool:
        """Den gefuellten Staub zuruecknehmen; Rueckgabe: ob es ihn gab."""
        if self._staub is None:
            return False
        self._staub = None
        self._flicken_stand = next(self._nummern)
        self._ki_fertig(0.0)
        return True

    # ------------------------------------------------------------------
    # Scan & Film: mehrere Fotos von der Scannerplatte trennen
    # ------------------------------------------------------------------

    def fotos_finden(self) -> list[trennen.Foto]:
        """Die einzelnen Fotos auf dem Scan, in Pixeln des Originals. Gesucht wird in der
        Vorschau - sie ist ganzzahlig verkleinert, die Lage laesst sich genau umrechnen."""
        faktor = 1 / self.vorschau_massstab
        return [foto.skaliert(faktor) for foto in trennen.finden(self.vorschau_original)]

    def foto_vorschau(self, foto: trennen.Foto) -> np.ndarray:
        """Ein gefundenes Foto klein, als sRGB uint8 - fuer die Auswahl."""
        teil = trennen.ausschneiden(self.vorschau_original, foto.skaliert(self.vorschau_massstab))
        return cp.asnumpy(filter.nach_8bit(teil))

    def fotos_speichern(self, fotos: list[trennen.Foto], pfade: list[str], bits: int = 8):
        """Jedes Foto gerade gerichtet aus dem unbearbeiteten Scan ausschneiden und als eigene
        Datei speichern, mit den Metadaten des Scans. Die Bearbeitung bleibt unberuehrt."""
        for foto, pfad in zip(fotos, pfade, strict=True):
            teil = trennen.ausschneiden(self.original, foto)
            rgb = cp.asnumpy(filter.nach_16bit(teil) if bits == 16 else filter.nach_8bit(teil))
            del teil
            exif, xmp = metadaten.fuer_speichern(self.daten.exif, self.daten.xmp,
                                                 self.vorgefunden, (), rgb.shape[1],
                                                 rgb.shape[0])
            bilddatei.speichern(pfad, rgb, None, exif, xmp)
        cp.get_default_memory_pool().free_all_blocks()

    def _ausgang(self, werte: Einstellungen, voll: bool, schaerfen: bool = True,
                 leinwand: bool = True, farbe: bool = True, flicken: bool = True,
                 grau: bool = False):
        """Original - als Negativ umgewandelt, je nach Staerke KI-entrauscht und KI-geschaerft,
        mit den Flicken, KI-koloriert und, wenn erweitert und leinwand gesetzt, auf der
        Leinwand."""
        stelle = 0 if voll else 1
        bild = self._film_bild(werte, voll, mit_staub=flicken)
        if self._ki_rauschfrei is not None and werte.ki_rauschen > 0:
            bild = _auflegen(bild, self._ki_rauschfrei[stelle],
                             cp.float32(min(werte.ki_rauschen, 100) / 100))
        if schaerfen and self._ki_schaerfe is not None and werte.ki_schaerfe > 0:
            bild = _auflegen(bild, self._ki_schaerfe[stelle], cp.float32(werte.ki_schaerfe / 100))
        if flicken and self._flicken:
            bild = self._flicken_auflegen(bild, stelle)
        if farbe and self._ki_farbe is not None and werte.ki_farbe > 0:
            bild = ki.farbe_einsetzen(bild, self._ki_farbe[stelle], werte.ki_farbe / 100)
        if leinwand and self._erweiterung is not None:
            bild = self._auf_grau(bild, stelle) if grau else self._auf_leinwand(bild, stelle)
        return bild

    def vorschau(self, unbearbeitet: bool = False, werte: Einstellungen | None = None,
                 ohne_erweiterung: bool = False, ohne_flicken: bool = False,
                 abschneiden_zeigen: tuple[bool, bool] = (False, False)
                 ) -> tuple[np.ndarray, float, np.ndarray]:
        """Vorschau als sRGB-uint8, Rechenzeit in ms und Histogramme (4 x 256: Rot, Gruen,
        Blau, Helligkeit). Wie viele Pixel abgeschnitten sind, steht danach in
        `abgeschnitten`.
        ohne_erweiterung: das Original ohne die von der KI erfundenen Raender,
        ohne_flicken: ohne die entfernten Objekte,
        abschneiden_zeigen: (Lichter, Tiefen) rot und blau einfaerben - nur fuer die
        Anzeige; wer speichert oder ausgibt, laesst es bei (False, False)."""
        beginn = time.perf_counter()
        if werte is None:
            werte = Einstellungen() if unbearbeitet else self.werte
        klar: dict = {}
        bild = self._rendern(werte, False, self._speicher, zeigen=not unbearbeitet,
                             leinwand=not ohne_erweiterung, flicken=not ohne_flicken,
                             klar=klar)
        # Gezaehlt wird das Bild ohne Farben der Maskenansicht und Markierungen
        quelle = klar.get("bild", bild)
        histogramm = cp.asnumpy(abschneiden.histogramme(quelle, 2))
        code = abschneiden.maske(quelle)
        self.abgeschnitten = abschneiden.anzahlen(code)
        del quelle, klar
        ergebnis = cp.asnumpy(abschneiden.markieren(bild, code, *abschneiden_zeigen))
        return ergebnis, (time.perf_counter() - beginn) * 1000, histogramm

    def ausgabe_form(self, werte: Einstellungen | None = None,
                     ohne_erweiterung: bool = False) -> tuple[int, int]:
        """Hoehe und Breite des fertigen Bildes in voller Aufloesung."""
        werte = self.werte if werte is None else werte
        quelle = self.original.shape[:2] if ohne_erweiterung else self.quellform()
        return geometrie.ausgabe_form(quelle, geometrie.aus(werte))

    def ausschnitt(self, x0: int, y0: int, breite: int, hoehe: int,
                   werte: Einstellungen | None = None,
                   ohne_flicken: bool = False,
                   abschneiden_zeigen: tuple[bool, bool] = (False, False)
                   ) -> tuple[np.ndarray, float, np.ndarray]:
        """Ausschnitt des fertigen Bildes in voller Aufloesung - fuer die 100-%-Ansicht.

        Gerechnet wird das ganze Bild, damit der Ausschnitt genau dem
        gespeicherten Bild entspricht - auch bei Filtern, die auf das ganze
        Bild schauen (Dunst, Klarheit). Das Ergebnis bleibt auf der GPU liegen,
        solange sich die Einstellungen nicht aendern; beim Verschieben wird
        nur noch ausgeschnitten und heruntergeladen.

        Das Histogramm und die Zahl der abgeschnittenen Pixel gelten fuers ganze Bild
        (das Histogramm gezaehlt auf einer Stichprobe) und liegen mit dem Vollbild im
        Speicher. Die Markierung kommt erst auf den Ausschnitt, darum rechnet das
        Umschalten der Warnung das Vollbild nicht neu.
        """
        beginn = time.perf_counter()
        werte = self.werte if werte is None else werte
        # Metadaten aendern das Bild nicht - ihretwegen nicht neu rechnen
        schluessel = (dataclasses.replace(werte, angaben=(), metadaten_entfernen=False),
                      self.maske_zeigen, self.tiefe_zeigen, self.staub_zeigen, ohne_flicken,
                      self.lokal_zeigen)
        if self._vollbild is None or self._vollbild[0] != schluessel:
            self._vollbild = None                 # das alte Vollbild zuerst freigeben
            klar: dict = {}
            bild = self._rendern(werte, True, self._speicher, zeigen=True,
                                 flicken=not ohne_flicken, klar=klar)
            quelle = klar.get("bild", bild)
            schritt = abschneiden.schrittweite(*quelle.shape[:2])
            histogramm = cp.asnumpy(abschneiden.histogramme(quelle, schritt))
            code = abschneiden.maske(quelle)
            zahlen = abschneiden.anzahlen(code)
            del quelle, klar
            self._vollbild = (schluessel, bild, histogramm, zahlen, code)
        _schluessel, vollbild, histogramm, self.abgeschnitten, code = self._vollbild
        fenster = (slice(y0, y0 + hoehe), slice(x0, x0 + breite))
        teil = abschneiden.markieren(vollbild[fenster], code[fenster], *abschneiden_zeigen)
        ergebnis = cp.asnumpy(teil)
        return ergebnis, (time.perf_counter() - beginn) * 1000, histogramm

    def vollbild_vergessen(self):
        """Das zwischengespeicherte Vollbild freigeben (etwa beim Wechsel zur Einpassung)."""
        self._vollbild = None
        self._vorher_voll = None

    def _vorher_schluessel(self, werte: Einstellungen):
        """Was die Vorher-Haelfte bestimmt: die Geometrie und, nach einem KI-Erweitern,
        Lage und Groesse der Leinwand (die Raender sind grau, ihr Inhalt zaehlt nicht)."""
        erweiterung = self._erweiterung
        leinwand = None if erweiterung is None else (erweiterung.x, erweiterung.y,
                                                     erweiterung.voll[0].shape[:2])
        return geometrie.aus(werte), leinwand

    def _vorher_rendern(self, werte: Einstellungen, voll: bool):
        # Eigener Zwischenspeicher: der der Sitzung gehoert dem bearbeiteten Bild
        return self._rendern(geometrie.nur_geometrie(werte), voll, {}, zeigen=False,
                             flicken=False, grau=True)

    def vorher_vorschau(self, werte: Einstellungen | None = None) -> np.ndarray:
        """Vorschau des unbearbeiteten Bildes in der Geometrie von `werte` (sonst der der
        Sitzung) - gleiche Form wie die bearbeitete. Entfernte Objekte fehlen, ein Negativ
        bleibt ein Negativ, KI-Raender sind grau. Wird nur neu gerechnet, wenn sich die
        Geometrie oder die Leinwand aendert."""
        werte = self.werte if werte is None else werte
        schluessel = self._vorher_schluessel(werte)
        if self._vorher_klein is None or self._vorher_klein[0] != schluessel:
            bild = cp.asnumpy(self._vorher_rendern(werte, False))
            self._vorher_klein = (schluessel, bild)
        return self._vorher_klein[1]

    def vorher_ausschnitt(self, x0: int, y0: int, breite: int, hoehe: int,
                          werte: Einstellungen | None = None) -> np.ndarray:
        """Ausschnitt der Vorher-Haelfte in voller Aufloesung (100-%-Ansicht); wie beim
        Vollbild bleibt das ganze Bild auf der GPU, bis sich die Geometrie aendert."""
        werte = self.werte if werte is None else werte
        schluessel = self._vorher_schluessel(werte)
        if self._vorher_voll is None or self._vorher_voll[0] != schluessel:
            self._vorher_voll = None              # das alte zuerst freigeben
            self._vorher_voll = (schluessel, self._vorher_rendern(werte, True))
        return cp.asnumpy(self._vorher_voll[1][y0:y0 + hoehe, x0:x0 + breite])

    def _alpha(self, faktor: int = 1):
        """Alphakanal mit derselben Geometrie wie das Bild - ohne Vignette und Farbsaeume."""
        alpha = self.daten.alpha
        if alpha is None:
            return None
        if self._erweiterung is not None:         # die erfundenen Raender sind deckend
            hoehe, breite = alpha.shape[:2]
            gross_h, gross_b = self.quellform()
            x, y = self._lage(0)
            alpha = np.pad(alpha, ((y, gross_h - y - hoehe), (x, gross_b - x - breite)),
                           constant_values=np.iinfo(alpha.dtype).max)
        geo = geometrie.aus(self.werte)
        if geo.ist_neutral() and faktor == 1:
            return alpha
        hoechst = 65535.0 if alpha.dtype == np.uint16 else 255.0
        ebene = cp.asarray(alpha, dtype=cp.float32) / hoechst
        if not geo.ist_neutral():
            nur_form = dataclasses.replace(geo, vignette=0.0, ca_rot=0.0, ca_blau=0.0)
            ebene = geometrie.anwenden(cp.repeat(ebene[..., None], 3, axis=2), nur_form)[..., 0]
        if faktor > 1:
            ebene = filter.vergroessern(ebene, ebene.shape[0] * faktor, ebene.shape[1] * faktor)
        return cp.asnumpy((cp.clip(ebene, 0, 1) * hoechst + 0.5).astype(alpha.dtype))

    def _alpha_gesamt(self, faktor: int = 1):
        """Alphakanal fuers Speichern - beim Freistellen mit der Maske verrechnet."""
        alpha = self._alpha(faktor)
        if not (self.werte.freistellen and self._ki_maske is not None):
            return alpha
        maske = self._maske_fuer(self.werte, True)
        if faktor > 1:
            maske = filter.vergroessern(maske, maske.shape[0] * faktor, maske.shape[1] * faktor)
        if alpha is None:
            return cp.asnumpy((cp.clip(maske, 0, 1) * 65535 + 0.5).astype(cp.uint16))
        hoechst = 65535.0 if alpha.dtype == np.uint16 else 255.0
        gesamt = cp.asarray(alpha, dtype=cp.float32) * maske
        return cp.asnumpy(cp.clip(gesamt + 0.5, 0, hoechst).astype(alpha.dtype))

    def exportieren(self, pfad: str, bits: int = 8, ki_auftrag=None, fortschritt=None) -> float:
        """Rechnet das Bild in voller Groesse und speichert es; Rueckgabe in ms.

        ki_auftrag ist (Hochskalierer, Faktor, Kachelgroesse) oder None. Mit KI
        wird das fertige Bild in 16 Bit gerechnet und danach in Kacheln
        vergroessert; fortschritt(i, n) meldet jede fertige Kachel.
        """
        beginn = time.perf_counter()
        if ki_auftrag is None:
            rgb = cp.asnumpy(self._rendern(self.werte, True, None, bits=bits))
            faktor = 1
        else:
            hochskalierer, faktor, kachel = ki_auftrag
            fertig = self._rendern(self.werte, True, None, bits=16, mit_korn=False)
            srgb = fertig.astype(cp.float32) / 65535
            del fertig
            cp.get_default_memory_pool().free_all_blocks()
            rgb = hochskalierer.hochskalieren(srgb, faktor, kachel, bits, fortschritt)
            del srgb
            rgb = self._korn_nach_hochskalieren(rgb)
        # Zwischenergebnisse der vollen Groesse sofort zurueckgeben - der
        # Speicherpool von CuPy hielte sie sonst fuer das naechste Mal fest.
        cp.get_default_memory_pool().free_all_blocks()
        exif, xmp = self._metadaten(rgb.shape[1], rgb.shape[0])
        bilddatei.speichern(pfad, rgb, self._alpha_gesamt(faktor), exif, xmp)
        self.gespeicherte_werte = dataclasses.replace(self.werte)
        self._flicken_gespeichert = self._flicken_stand
        return (time.perf_counter() - beginn) * 1000

    def _korn_nach_hochskalieren(self, rgb: np.ndarray) -> np.ndarray:
        """Das Korn erst aufs hochskalierte Bild - die KI glaettete es sonst. In Streifen
        auf der Grafikkarte; das grosse Bild muss nicht auf einmal hinauf."""
        if not korn.aktiv(self.werte):
            return rgb
        form = rgb.shape[:2]
        for oben in range(0, form[0], korn.STREIFEN):
            teil = cp.asarray(rgb[oben:oben + korn.STREIFEN])
            rgb[oben:oben + korn.STREIFEN] = cp.asnumpy(
                korn.auflegen(teil, self.werte, form=form, y0=oben))
        return rgb

    def druckbild(self, ki_auftrag=None, fortschritt=None) -> np.ndarray:
        """Das fertige Bild fuer den Drucker: sRGB mit 8 Bit, Durchsichtiges auf Weiss.
        ki_auftrag wie bei exportieren(). Gilt nicht als Speichern."""
        if ki_auftrag is None:
            rgb = cp.asnumpy(self._rendern(self.werte, True, None, bits=8))
            faktor = 1
        else:
            hochskalierer, faktor, kachel = ki_auftrag
            fertig = self._rendern(self.werte, True, None, bits=16, mit_korn=False)
            srgb = fertig.astype(cp.float32) / 65535
            del fertig
            cp.get_default_memory_pool().free_all_blocks()
            rgb = hochskalierer.hochskalieren(srgb, faktor, kachel, 8, fortschritt)
            del srgb
            rgb = self._korn_nach_hochskalieren(rgb)
        cp.get_default_memory_pool().free_all_blocks()
        alpha = self._alpha_gesamt(faktor)
        if alpha is None:
            return rgb
        hoechst = 65535.0 if alpha.dtype == np.uint16 else 255.0
        deckung = alpha.astype(np.float32)[..., None] / hoechst
        return (rgb * deckung + 255.0 * (1 - deckung) + 0.5).astype(np.uint8)

    @property
    def ki_inhalt(self) -> bool:
        """Enthaelt das Bild von der KI erfundene Teile (Erweitern, Objekte entfernen,
        Kolorieren)?"""
        return (self._erweiterung is not None or bool(self._flicken)
                or (self._ki_farbe is not None and self.werte.ki_farbe > 0))

    def veroeffentlichen(self, pfad: str, vorlage) -> tuple[float, tuple[int, int]]:
        """Fuers Netz speichern: verkleinert, mit Wasserzeichen und Rechteangaben.
        Rueckgabe: Rechenzeit in ms und Breite, Hoehe. Gilt nicht als Speichern der
        Arbeit - das Bild in voller Groesse ist ja nicht gesichert."""
        beginn = time.perf_counter()
        rgb = cp.asnumpy(self._rendern(self.werte, True, None, bits=16))
        cp.get_default_memory_pool().free_all_blocks()
        exif, _xmp = self._metadaten(rgb.shape[1], rgb.shape[0])
        groesse = veroeffentlichen.speichern(pfad, rgb, self._alpha_gesamt(), exif, vorlage,
                                             self.ki_inhalt, self.angaben)
        return (time.perf_counter() - beginn) * 1000, groesse

    def schliessen(self):
        """Grafikspeicher sofort freigeben, nicht erst beim Aufraeumen von Python."""
        self.original = None
        self.vorschau_original = None
        self._vollbild = None
        self._vorher_klein = self._vorher_voll = None
        self._ki_rauschfrei = None
        self._ki_schaerfe = None
        self._ki_maske = None
        self._klickstand = {"maske": _Klicks(), "entfernen": _Klicks(), "lokal": _Klicks()}
        self._entfern_klick = None
        self._pinsel = None
        self._flicken = []
        self._ki_tiefe = None
        self._ki_farbe = None
        self._erweiterung = None
        self._staub = None
        self._staub_dunkel = None
        self._staub_fund = None
        self._speicher.clear()
        cp.get_default_memory_pool().free_all_blocks()


def _kreis(ebene, x: float, y: float, radius: float, dazu: bool):
    """Eine weiche Kreisscheibe in eine Ebene (H, W) stempeln oder herausnehmen."""
    hoehe, breite = ebene.shape
    y0, y1 = max(0, int(y - radius - 1)), min(hoehe, int(y + radius + 2))
    x0, x1 = max(0, int(x - radius - 1)), min(breite, int(x + radius + 2))
    if y1 <= y0 or x1 <= x0:
        return
    yy = cp.arange(y0, y1, dtype=cp.float32)[:, None] + 0.5
    xx = cp.arange(x0, x1, dtype=cp.float32)[None, :] + 0.5
    abstand = cp.sqrt((yy - y) ** 2 + (xx - x) ** 2)
    scheibe = cp.clip(radius + 0.5 - abstand, 0, 1)      # ein Pixel weicher Rand
    teil = ebene[y0:y1, x0:x1]
    if dazu:
        cp.maximum(teil, scheibe, out=teil)
    else:
        cp.minimum(teil, 1 - scheibe, out=teil)
