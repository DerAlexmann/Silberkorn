"""
Scan & Film: mehrere Fotos von der Scannerplatte trennen

Wer mehrere Abzuege auf einmal auf den Flachbettscanner legt, bekommt einen
Scan mit allen Fotos vor dem gleichmaessigen Deckel. Gesucht wird so:

  1. Hintergrund: Die Farbe des Deckels ist die mittlere Farbe am Rand des
     Scans - dort liegt selten ein Foto.
  2. Fotos: Was deutlich von ihr abweicht, gehoert zu einem Foto. Luecken
     (helle Flaechen im Foto, die dem Deckel aehneln) werden geschlossen und
     Loecher gefuellt, Staubkoerner fallen weg.
  3. Lage: Fuer jede Flaeche das kleinste umschliessende Rechteck - so werden
     auch schraeg aufgelegte Fotos gefunden. Es wird so gedreht, dass das Foto
     um hoechstens 45 Grad geradegerichtet wird, und ein wenig nach innen
     gezogen, damit kein Saum des Deckels stehen bleibt.

Gesucht wird auf einer verkleinerten Kopie; ausgeschnitten wird aus dem Scan
in voller Aufloesung, bikubisch wie die Geometrie (geometrie.py).

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np

from . import filter, geometrie
from .cuda import cupy as cp

ARBEIT_KANTE = 1000         # gesucht wird in dieser Groesse
RAND_ANTEIL = 0.02          # so breit ist der Rand, an dem der Deckel gemessen wird
ABWEICHUNG_MIN = 0.08       # so weit (sRGB 0..1) muss ein Pixel mindestens vom Deckel abweichen
ABWEICHUNG_STREUUNG = 5.0   # oder so viele Streuungen des Deckels, wenn der stark rauscht
SCHLIESSEN_PX = 5           # Luecken bis zu dieser Groesse (Arbeitsgroesse) schliessen
OEFFNEN_PX = 5              # Kleineres als das faellt weg (Staub, Fusseln)
MINDEST_ANTEIL = 0.01       # ein Foto bedeckt mindestens so viel des Scans
EINZUG_PX = 1.0             # so weit (Arbeitsgroesse) wird jede Kante nach innen gezogen


@dataclass(frozen=True)
class Foto:
    """Ein gefundenes Foto als gedrehtes Rechteck in Pixeln des Scans."""
    mitte_x: float
    mitte_y: float
    breite: float
    hoehe: float
    winkel: float           # Bogenmass: die Oberkante zeigt in Richtung (cos, sin)

    def skaliert(self, faktor: float) -> Foto:
        return Foto(self.mitte_x * faktor, self.mitte_y * faktor, self.breite * faktor,
                    self.hoehe * faktor, self.winkel)

    @property
    def form(self) -> tuple[int, int]:
        """Hoehe und Breite des ausgeschnittenen Fotos in Pixeln."""
        return max(1, round(self.hoehe)), max(1, round(self.breite))


def _huelle(punkte: np.ndarray) -> np.ndarray:
    """Konvexe Huelle (Andrews Monotone Chain) von Punkten (n, 2)."""
    punkte = np.unique(punkte, axis=0)
    if len(punkte) < 3:
        return punkte

    def kreuz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    unten, oben = [], []
    for p in punkte:
        while len(unten) >= 2 and kreuz(unten[-2], unten[-1], p) <= 0:
            unten.pop()
        unten.append(p)
    for p in punkte[::-1]:
        while len(oben) >= 2 and kreuz(oben[-2], oben[-1], p) <= 0:
            oben.pop()
        oben.append(p)
    return np.array(unten[:-1] + oben[:-1])


def kleinstes_rechteck(punkte: np.ndarray) -> Foto:
    """Das Rechteck kleinster Flaeche um Pixelmitten (n, 2) als (x, y) - eine seiner Kanten
    liegt auf einer Kante der konvexen Huelle. Die Pixel selbst ragen einen halben Pixel
    ueber ihre Mitten hinaus."""
    huelle = _huelle(np.asarray(punkte, dtype=np.float64))
    kanten = np.diff(np.vstack([huelle, huelle[:1]]), axis=0)
    winkel = np.unique(np.round(np.arctan2(kanten[:, 1], kanten[:, 0]) % (math.pi / 2), 9))
    if winkel.size == 0:
        winkel = np.zeros(1)
    bestes = None
    for a in winkel:
        c, s = math.cos(a), math.sin(a)
        u = huelle[:, 0] * c + huelle[:, 1] * s
        v = -huelle[:, 0] * s + huelle[:, 1] * c
        flaeche = (np.ptp(u) + 1) * (np.ptp(v) + 1)
        if bestes is None or flaeche < bestes[0] - 1e-9:
            bestes = (flaeche, a, u, v)
    _flaeche, a, u, v = bestes
    mu, mv = (u.max() + u.min()) / 2, (v.max() + v.min()) / 2
    breite, hoehe = np.ptp(u) + 1, np.ptp(v) + 1
    if a > math.pi / 4:                       # hoechstens 45 Grad geraderichten
        a -= math.pi / 2
        mu, mv = -mv, mu                      # dasselbe Rechteck im gedrehten Rahmen
        breite, hoehe = hoehe, breite
    c, s = math.cos(a), math.sin(a)
    return Foto(mu * c - mv * s, mu * s + mv * c, float(breite), float(hoehe), float(a))


def _deckel(srgb):
    """Farbe und Streuung des Hintergrunds, gemessen am Rand des Scans."""
    hoehe, breite = srgb.shape[:2]
    r = max(2, round(max(hoehe, breite) * RAND_ANTEIL))
    rand = cp.concatenate([srgb[:r].reshape(-1, 3), srgb[-r:].reshape(-1, 3),
                           srgb[:, :r].reshape(-1, 3), srgb[:, -r:].reshape(-1, 3)])
    farbe = cp.median(rand, axis=0)
    abweichung = cp.abs(rand - farbe).max(axis=1)
    # robuste Streuung: der Median der Abweichungen
    return farbe, float(cp.median(abweichung)) * 1.4826


def finden(rgb_linear) -> list[Foto]:
    """Die Fotos auf einem Scan (linear, auf der Grafikkarte), in Leserichtung - von oben
    nach unten, in einer Reihe von links nach rechts. Koordinaten in Pixeln von rgb."""
    from cupyx.scipy import ndimage
    faktor = max(1, -(-max(rgb_linear.shape[:2]) // ARBEIT_KANTE))
    klein = filter.verkleinern_box(rgb_linear, faktor).astype(cp.float32)
    srgb = filter.linear_zu_srgb(cp.clip(klein, 0, 1))
    farbe, streuung = _deckel(srgb)
    schwelle = max(ABWEICHUNG_MIN, ABWEICHUNG_STREUUNG * streuung)
    foto = (cp.abs(srgb - farbe).max(axis=2) > schwelle).view(cp.uint8)
    foto = ndimage.minimum_filter(ndimage.maximum_filter(foto, size=SCHLIESSEN_PX),
                                  size=SCHLIESSEN_PX)
    foto = ndimage.binary_fill_holes(foto.view(bool)).view(cp.uint8)
    foto = ndimage.maximum_filter(ndimage.minimum_filter(foto, size=OEFFNEN_PX),
                                  size=OEFFNEN_PX).view(bool)
    stellen, anzahl = ndimage.label(foto)
    if anzahl == 0:
        return []
    flaechen = cp.asnumpy(cp.bincount(stellen.ravel()))
    mindestens = MINDEST_ANTEIL * foto.size
    # Fuer die Huelle genuegt der Umriss jeder Flaeche
    umriss = foto & ~ndimage.minimum_filter(foto.view(cp.uint8), size=3).view(bool)
    ys, xs = (cp.asnumpy(a) for a in cp.nonzero(umriss))
    nummern = cp.asnumpy(stellen[umriss])
    fotos = []
    for nummer in range(1, int(anzahl) + 1):
        if flaechen[nummer] < mindestens:
            continue
        auswahl = nummern == nummer
        rechteck = kleinstes_rechteck(np.stack([xs[auswahl] + 0.5, ys[auswahl] + 0.5], 1))
        rechteck = Foto(rechteck.mitte_x, rechteck.mitte_y,
                        max(1.0, rechteck.breite - 2 * EINZUG_PX),
                        max(1.0, rechteck.hoehe - 2 * EINZUG_PX), rechteck.winkel)
        fotos.append(rechteck.skaliert(faktor))
    return leserichtung(fotos)


def leserichtung(fotos: list[Foto]) -> list[Foto]:
    """Von oben nach unten; was sich in der Hoehe ueberschneidet, ist eine Reihe."""
    reihen: list[list[Foto]] = []
    for foto in sorted(fotos, key=lambda f: f.mitte_y):
        reihe = reihen[-1] if reihen else None
        if reihe is not None and abs(foto.mitte_y - reihe[0].mitte_y) < reihe[0].hoehe / 2:
            reihe.append(foto)
        else:
            reihen.append([foto])
    return [foto for reihe in reihen for foto in sorted(reihe, key=lambda f: f.mitte_x)]


def ausschneiden(rgb, foto: Foto):
    """Das Foto gerade gerichtet aus dem Bild (H, W, 3) lesen - bikubisch, NumPy oder CuPy."""
    xp = filter.xp_von(rgb)
    hoehe, breite = foto.form
    c, s = math.cos(foto.winkel), math.sin(foto.winkel)
    u = (xp.arange(breite, dtype=xp.float32) + 0.5 - breite / 2)[None, :]
    v = (xp.arange(hoehe, dtype=xp.float32) + 0.5 - hoehe / 2)[:, None]
    # Pixelmitten: Stelle i liegt bei i + 0.5
    sx = foto.mitte_x + u * c - v * s - 0.5
    sy = foto.mitte_y + u * s + v * c - 0.5
    return xp.stack([geometrie._bikubisch(xp, rgb[..., k], sx, sy) for k in range(3)],
                    axis=-1).astype(xp.float32)


def dateinamen(ordner: str, name: str, endung: str, anzahl: int) -> list[str]:
    """Freie Dateinamen Name-01, Name-02 ... im Ordner - vorhandene Dateien werden
    uebersprungen, nie ueberschrieben."""
    pfade, nummer = [], 0
    while len(pfade) < anzahl:
        nummer += 1
        pfad = os.path.join(ordner, f"{name}-{nummer:02d}{endung}")
        if not os.path.exists(pfad):
            pfade.append(pfad)
    return pfade
