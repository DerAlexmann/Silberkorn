"""
Histogramm und Abschneide-Warnung: Zaehlen und Einfaerben auf dem fertigen sRGB-Bild

Keine Bildformel der Verarbeitungskette, sondern Auswertung des Ergebnisses - darum
nur NumPy/CuPy ueber xp_von() und keine Kernel. Ohne Grafikkarte testbar.

Ein Pixel gilt als abgeschnitten, wenn mindestens ein Kanal 255 (Lichter) oder 0
(Tiefen) erreicht - wie die Warnung in Lightroom. Die Maske hat je Pixel zwei Bits;
das Einfaerben passiert erst fuers Anzeigen, nie im Bild, das gespeichert wird.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import math

from . import filter

LICHTER = 1                    # Bit der Maske: ein Kanal bei 255
TIEFEN = 2                     # Bit der Maske: ein Kanal bei 0
LICHTER_FARBE = (255, 0, 0)    # so erscheinen abgeschnittene Lichter im Bild
TIEFEN_FARBE = (0, 0, 255)     # und abgeschnittene Tiefen
HISTOGRAMM_ZIEL = 1_500_000    # so viele Pixel zaehlt das Histogramm hoechstens


def schrittweite(hoehe: int, breite: int, ziel: int = HISTOGRAMM_ZIEL) -> int:
    """Jeder wievielte Pixel in Zeile und Spalte gezaehlt wird, damit es hoechstens
    etwa ziel Pixel sind. Mindestens 2: Jeder vierte Pixel genuegt fuer die Form."""
    return max(2, math.ceil(math.sqrt(hoehe * breite / ziel)))


def histogramme(rgb, schritt: int = 2):
    """Histogramme als Feld (4, 256): Rot, Gruen, Blau und die Helligkeit (Rec. 709 auf
    den sRGB-Werten), gezaehlt auf jedem schritt-ten Pixel."""
    xp = filter.xp_von(rgb)
    probe = rgb[::schritt, ::schritt]
    # Ein Zaehlen fuer alle drei Kanaele: jeder bekommt einen eigenen Bereich von 256
    versatz = xp.arange(3, dtype=xp.int32) * 256
    farben = xp.bincount((probe.astype(xp.int32) + versatz).ravel(), minlength=768)[:768]
    gewichte = xp.asarray(filter.LUMA, dtype=xp.float32)
    hell = (probe.astype(xp.float32) @ gewichte + 0.5).astype(xp.int32)
    hell = xp.bincount(hell.ravel(), minlength=256)[:256]
    return xp.concatenate([farben.reshape(3, 256), hell[None]], axis=0)


def maske(rgb):
    """Je Pixel ein uint8: Bit LICHTER, wenn ein Kanal 255 erreicht, Bit TIEFEN bei 0."""
    xp = filter.xp_von(rgb)
    hoechster = rgb.max(axis=2)
    niedrigster = rgb.min(axis=2)
    return ((hoechster >= 255).astype(xp.uint8) * LICHTER
            | (niedrigster <= 0).astype(xp.uint8) * TIEFEN)


def anzahlen(code) -> tuple[int, int]:
    """Wie viele Pixel abgeschnitten sind: (Lichter, Tiefen)."""
    xp = filter.xp_von(code)
    return (int(xp.count_nonzero(code & LICHTER)), int(xp.count_nonzero(code & TIEFEN)))


def markieren(rgb, code, lichter: bool, tiefen: bool):
    """Eine Kopie von rgb mit rot gefaerbten Lichtern und blau gefaerbten Tiefen - je
    nachdem, was gewaehlt ist. Ohne Wahl kommt rgb selbst zurueck. Wo beides zutrifft,
    gewinnt Rot."""
    if not (lichter or tiefen):
        return rgb
    xp = filter.xp_von(rgb)
    ergebnis = rgb
    if tiefen:
        ergebnis = xp.where((code & TIEFEN).astype(bool)[..., None],
                            xp.asarray(TIEFEN_FARBE, dtype=rgb.dtype), ergebnis)
    if lichter:
        ergebnis = xp.where((code & LICHTER).astype(bool)[..., None],
                            xp.asarray(LICHTER_FARBE, dtype=rgb.dtype), ergebnis)
    return ergebnis
