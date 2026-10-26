"""
Bilder vergleichen: welches Bild wo steht, und die Bilder selbst

Links steht der Favorit, rechts ein Kandidat. Bei mehr als zwei Bildern blaettert man
rechts durch die uebrigen; "Tauschen" macht den Kandidaten zum Favoriten.

Jedes Bild wird einmal mit seiner Bearbeitung aus der Begleitdatei in voller
Aufloesung gerechnet (ohne KI-Hochskalieren) und danach als 8-Bit-Bild im
Arbeitsspeicher gehalten - die 100-%-Ausschnitte kommen von dort, die Grafikkarte
ist gleich wieder frei. Weil ein Bild so 3 Byte je Pixel belegt, behaelt der
Speicher nur die zuletzt gebrauchten.

Wie bei drucken.py braucht das Modul beim Import weder Qt noch die Grafikkarte.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import collections
import os
import time
from dataclasses import dataclass, field

import numpy as np

VORSCHAU_KANTE = 2048        # eingepasst gezeigt; laengste Kante in Pixeln
SPEICHER_BILDER = 3          # Favorit, Kandidat und der zuletzt gezeigte


@dataclass
class Vergleichsbild:
    pfad: str
    vorschau: np.ndarray | None = None      # (H, W, 3) uint8, sRGB, fuer die Einpassung
    voll: np.ndarray | None = None          # das fertige Bild, sRGB mit 8 Bit
    verkleinert: bool = False               # Grafikspeicher zu knapp: voll ist die Vorschau
    datum: str = ""
    datum_aufnahme: bool = False            # True: aus den Angaben, sonst Aenderungsdatum
    aufnahme: dict[str, str] = field(default_factory=dict)   # metadaten.ueberblick
    bearbeitet: bool = False                # eine Begleitdatei wurde angewandt
    veraltet: bool = False                  # die Begleitdatei passt nicht ganz zum Bild
    verworfen: bool = False                 # ungueltige Werte der Begleitdatei uebergangen
    fehler: str = ""

    @property
    def form(self) -> tuple[int, int] | None:
        """Hoehe und Breite des fertigen Bildes."""
        return None if self.voll is None else self.voll.shape[:2]


class Reihe:
    """Welches Bild links (Favorit) und welches rechts (Kandidat) steht."""

    def __init__(self, pfade: list[str]):
        if len(pfade) < 2:
            raise ValueError("Zum Vergleichen braucht es mindestens zwei Bilder.")
        if len(set(pfade)) != len(pfade):
            raise ValueError("Jedes Bild darf nur einmal vorkommen.")
        self.pfade = list(pfade)
        self.favorit = 0
        self.kandidat = 1

    def _kandidaten(self) -> list[int]:
        return [nummer for nummer in range(len(self.pfade)) if nummer != self.favorit]

    @property
    def links(self) -> str:
        return self.pfade[self.favorit]

    @property
    def rechts(self) -> str:
        return self.pfade[self.kandidat]

    @property
    def blaetterbar(self) -> bool:
        return len(self.pfade) > 2

    def stelle(self) -> tuple[int, int]:
        """Der wievielte Kandidat rechts steht und wie viele es gibt (ab 1)."""
        kandidaten = self._kandidaten()
        return kandidaten.index(self.kandidat) + 1, len(kandidaten)

    def blaettern(self, schritt: int):
        """Den naechsten (1) oder vorigen (-1) Kandidaten zeigen - am Ende geht es von
        vorn los."""
        kandidaten = self._kandidaten()
        stelle = kandidaten.index(self.kandidat)
        self.kandidat = kandidaten[(stelle + schritt) % len(kandidaten)]

    def tauschen(self):
        self.favorit, self.kandidat = self.kandidat, self.favorit


class Speicher:
    """Die zuletzt gebrauchten Bilder; laden(pfad) -> Vergleichsbild rechnet ein neues.
    Was sich nicht laden liess, bleibt nicht liegen - beim naechsten Mal wird es neu
    versucht (etwa wenn der Grafikspeicher wieder frei ist)."""

    def __init__(self, laden, platz: int = SPEICHER_BILDER):
        self._laden = laden
        self._platz = platz
        self._bilder: collections.OrderedDict[str, Vergleichsbild] = collections.OrderedDict()

    def holen(self, pfad: str) -> Vergleichsbild:
        bild = self._bilder.pop(pfad, None)
        if bild is None:
            bild = self._laden(pfad)
        if bild.fehler:
            return bild
        self._bilder[pfad] = bild
        while len(self._bilder) > self._platz:
            self._bilder.popitem(last=False)
        return bild

    def da(self, pfad: str) -> bool:
        return pfad in self._bilder

    def leeren(self):
        self._bilder.clear()


def mitte_uebertragen(mitte: tuple[float, float], von: tuple[int, int],
                      nach: tuple[int, int]) -> tuple[float, float]:
    """Die Bildmitte einer Leinwand auf ein anders grosses Bild: dieselbe Stelle im
    Verhaeltnis zu Breite und Hoehe. von, nach: (Hoehe, Breite)."""
    (x, y), (hoehe_von, breite_von), (hoehe_nach, breite_nach) = mitte, von, nach
    return x / breite_von * breite_nach, y / hoehe_von * hoehe_nach


def ausschnitt(bild: np.ndarray, bereich: tuple[int, int, int, int]) -> np.ndarray:
    """Der Bereich (x0, y0, Breite, Hoehe) des Bildes - als Sicht, ohne Kopie."""
    x0, y0, breite, hoehe = bereich
    return bild[y0:y0 + hoehe, x0:x0 + breite]


def _auf_weiss(rgb: np.ndarray) -> np.ndarray:
    """Die Vorschau ohne Alphakanal - Durchsichtiges auf Weiss wie bei druckbild()."""
    if rgb.shape[2] == 3:
        return np.ascontiguousarray(rgb)
    deckung = rgb[..., 3:4].astype(np.float32) / 255.0
    return (rgb[..., :3] * deckung + 255.0 * (1 - deckung) + 0.5).astype(np.uint8)


def _ladefehler() -> tuple[type[BaseException], ...]:
    from . import begleitdatei, bilddatei
    from .cuda import cupy as cp

    fehler = (bilddatei.BildFehler, begleitdatei.BegleitFehler, OSError, ValueError,
              MemoryError)
    if cp is not None:
        fehler += (cp.cuda.memory.OutOfMemoryError, cp.cuda.runtime.CUDARuntimeError)
    return fehler


def _gpu_voll() -> tuple[type[BaseException], ...]:
    from .cuda import cupy as cp

    return (MemoryError,) if cp is None else (MemoryError, cp.cuda.memory.OutOfMemoryError)


def _datum(angabe: str, pfad: str) -> tuple[str, bool]:
    if angabe:
        return angabe.replace("T", " "), True
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(pfad))), False
    except OSError:
        return "", False


def laden(pfad: str, kante: int = VORSCHAU_KANTE, raw_qualitaet: str = "schnell"
          ) -> Vergleichsbild:
    """Das Bild mit seiner Bearbeitung - Vorschau und volles Bild. Was sich nicht laden
    laesst, steht in `fehler`; reicht nur der Grafikspeicher fuer das volle Bild nicht,
    gilt die Vorschau (verkleinert)."""
    from . import begleitdatei, bilddatei, metadaten
    from .bearbeitung import Sitzung
    from .cuda import cupy as cp
    from .stapel import Ergebnis, Stapel

    bild = Vergleichsbild(pfad)
    fehler = _ladefehler()
    sitzung = None
    try:
        sitzung = Sitzung(bilddatei.laden(pfad, raw_qualitaet=raw_qualitaet), kante)
        ergebnis = Ergebnis(pfad)
        bild.bearbeitet = os.path.isfile(begleitdatei.pfad_fuer(pfad))
        Stapel._begleitdatei_uebernehmen(sitzung, ergebnis)
        bild.veraltet = "veraltet" in ergebnis.hinweise
        bild.verworfen = "verworfen" in ergebnis.hinweise
        bild.datum, bild.datum_aufnahme = _datum(sitzung.angaben.datum, pfad)
        bild.aufnahme = metadaten.ueberblick(sitzung.daten.exif)
        bild.vorschau = _auf_weiss(sitzung.vorschau()[0])
        try:
            bild.voll = sitzung.druckbild()
        except _gpu_voll():
            if cp is not None:
                cp.get_default_memory_pool().free_all_blocks()
            bild.voll, bild.verkleinert = bild.vorschau, True
    except fehler as grund:
        bild.vorschau = bild.voll = None
        bild.fehler = str(grund) or type(grund).__name__
    finally:
        if sitzung is not None:
            sitzung.schliessen()
        if cp is not None:
            cp.get_default_memory_pool().free_all_blocks()
    return bild
