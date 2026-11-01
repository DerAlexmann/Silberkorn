"""
Scan & Film: Staub, Kratzer und Risse auf alten Fotos mit KI finden

Ohne Infrarotkanal laesst sich ein Schaden nur am Bild selbst erkennen. Das erledigt
die Kratzererkennung aus "Bringing Old Photos Back to Life": Sie schaut das Graubild
an und liefert je Pixel eine Wahrscheinlichkeit. Das Netz rechnet einmal; die
Empfindlichkeit legt danach nur noch die Schwelle fest und wirkt sofort.

Gerade Kanten im Bild haelt das Netz gelegentlich fuer Kratzer. Die Maske ist deshalb
ein Vorschlag: gefuellt wird wie beim Infrarot erst, wenn sie geprueft ist (staub.py).

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

from . import filter, staub
from .cuda import cupy as cp

EMPFINDLICHKEIT = 50          # Vorgabe des Reglers, 0..100
SCHWELLE_GROB = 0.7           # Empfindlichkeit 0
SCHWELLE_FEIN = 0.1           # Empfindlichkeit 100; bei 50 die Schwelle des Originals, 0,4
KURZE_SEITE = 2048            # groessere Bilder sieht das Netz verkleinert
RAND_PX = 2                   # so weit waechst eine Stelle: Schaeden laufen im Scan aus


def rechenfaktor(hoehe: int, breite: int) -> int:
    """Um diesen Faktor wird das Bild verkleinert, damit die kurze Seite passt."""
    return max(1, -(-min(hoehe, breite) // KURZE_SEITE))


def graubild(srgb):
    """sRGB (H, W, 3) 0..1 -> Graubild (H, W), -1..1, wie das Netz es gelernt hat."""
    grau = srgb[..., 0] * 0.299 + srgb[..., 1] * 0.587 + srgb[..., 2] * 0.114
    return (grau - 0.5) / 0.5


def karte(srgb, finder, kachel: int, fortschritt=None) -> tuple:
    """Wahrscheinlichkeitskarte eines sRGB-Bildes und der Faktor, um den sie kleiner ist."""
    faktor = rechenfaktor(*srgb.shape[:2])
    return finder.karte(graubild(filter.verkleinern_box(srgb, faktor)), kachel,
                        fortschritt), faktor


def schwelle(empfindlichkeit: float) -> float:
    anteil = min(max(empfindlichkeit, 0.0), 100.0) / 100
    return SCHWELLE_GROB - (SCHWELLE_GROB - SCHWELLE_FEIN) * anteil


def finden(wahrscheinlich, faktor: int, form: tuple, empfindlichkeit: float) -> tuple:
    """Maske der Schaeden in Bildgroesse (H, W) bool, ihr Kern und die Anzahl - wie
    staub.finden()."""
    kern = wahrscheinlich > schwelle(empfindlichkeit)
    if faktor > 1:
        kern = cp.repeat(cp.repeat(kern, faktor, axis=0), faktor, axis=1)
    fehlt = (form[0] - kern.shape[0], form[1] - kern.shape[1])
    if fehlt[0] or fehlt[1]:                      # der Rest, den das Verkleinern abschnitt
        kern = cp.pad(kern, ((0, fehlt[0]), (0, fehlt[1])), mode="edge")
    maske = staub.wachsen(kern, RAND_PX)
    return maske, kern, staub.anzahl(maske)
