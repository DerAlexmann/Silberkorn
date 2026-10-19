"""
Filmkorn: Rauschen wie das Silberkorn eines Films - am Ende der Kette

Das Korn ist ein Rauschfeld auf einem Gitter, dessen Maschen relativ zur
langen Kante des fertigen Bildes liegen. So sieht es in jeder Groesse gleich
aus: in der 100-%-Ansicht genau wie im gespeicherten Bild, nach dem
KI-Hochskalieren so grob wie vorher im Verhaeltnis zum Bild. Jeder Gitterpunkt
bekommt seinen Zufallswert aus einem Hash seiner Lage - kein Zufallsgenerator
mit Zustand. Darum laesst sich das Korn in Streifen rechnen und ergibt
trotzdem dasselbe Bild, und ein Bild bekommt bei jedem Speichern dasselbe
Korn.

Ist eine Masche kleiner als ein Pixel - in der verkleinerten Vorschau -,
mittelt ein Pixel mehrere Koerner. Das Korn wirkt dann schwaecher, so wie es
nach dem Verkleinern eines gespeicherten Bildes auch wirkte.

Das Korn ist einfarbig und liegt auf den sRGB-kodierten Werten; am staerksten
ist es in den Mitteltoenen, Schwarz und Weiss bleiben rein. Die Rauheit laesst
es klumpen: Ein fuenfmal groeberes Rauschen verteilt die Staerke ungleich, die
mittlere Staerke bleibt.

Laeuft mit NumPy und mit CuPy - auf dem Array, das hereinkommt.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import math

import numpy as np

from .filter import LUMA, Einstellungen, xp_von

KORN_BEZUG = 4000              # Die Korngroesse gilt fuer ein Bild mit dieser langen Kante
GROESSE_KLEIN = 1.0            # Masche in Pixeln (bei KORN_BEZUG) fuer Groesse 0 ...
GROESSE_GROSS = 4.0            # ... und fuer Groesse 100
KORN_MAX = 0.08                # Staerke 100: Streuung in sRGB-kodierten Werten (0..1)
# Rauheit: Das Korn klumpt wie bei echtem Film - ein groeberes Rauschen verstaerkt es
# stellenweise und schwaecht es anderswo
KLUMPEN_GROESSE = 5.0          # Masche der Klumpen in Maschen des Korns
KLUMPEN_ANTEIL = 1.0           # Rauheit 100: so stark schwankt die Staerke des Korns
# Beide Gitter liegen schraeg zu den Pixeln: Sonst traefe jedes Pixel dieselbe Stelle
# zwischen den Gitterpunkten, wenn die Masche ganze Pixel misst - und das Korn waere zu
# schwach. Verschieden gedreht zeigen sie auch kein gemeinsames Raster.
DREHUNG = math.radians(17.0)
KLUMPEN_DREHUNG = math.radians(53.0)
SAAT = (0x1B873593, 0x5BD1E995)     # je Lage des Gitters eine eigene Folge
STREIFEN = 512                 # so viele Zeilen auf einmal - haelt den Speicher klein


def _glaetten_streuung() -> float:
    """Streuung des geglaetteten Gitterrauschens, wenn jeder Gitterpunkt gleichverteilt in
    -1..1 liegt - damit das Korn unabhaengig von der Glaettung die gewuenschte Staerke hat."""
    t = (np.arange(100000) + 0.5) / 100000
    s = t * t * (3 - 2 * t)
    eindimensional = float(np.mean((1 - s) ** 2 + s ** 2))
    return math.sqrt(eindimensional ** 2 / 3)


STREUUNG = _glaetten_streuung()


def aktiv(werte: Einstellungen) -> bool:
    return werte.korn > 0


def masche(werte: Einstellungen, lange_kante: int) -> float:
    """Abstand der Gitterpunkte in Pixeln eines Bildes mit dieser langen Kante."""
    bezug = GROESSE_KLEIN + (GROESSE_GROSS - GROESSE_KLEIN) * werte.korn_groesse / 100
    return bezug * lange_kante / KORN_BEZUG


def _hash(ix, iy, saat: int):
    """Gleichverteilt in -1..1 fuer jeden Gitterpunkt (ganze Zahlen, auch negativ)."""
    xp = xp_von(ix)
    h = (ix.astype(xp.int64) & 0xFFFFFFFF).astype(xp.uint32) * xp.uint32(0x8DA6B343)
    h ^= (iy.astype(xp.int64) & 0xFFFFFFFF).astype(xp.uint32) * xp.uint32(0xD8163841)
    h ^= xp.uint32(saat)
    h ^= h >> xp.uint32(15)
    h *= xp.uint32(0x2C1B3C6D)
    h ^= h >> xp.uint32(12)
    h *= xp.uint32(0x297A2D39)
    h ^= h >> xp.uint32(15)
    return (h >> xp.uint32(8)).astype(xp.float32) * xp.float32(2.0 / (1 << 24)) - 1


def _gitterrauschen(gx, gy, saat: int):
    """Rauschen an den Stellen (gx, gy) in Maschen: Gitterwerte weich interpoliert,
    Streuung 1."""
    xp = xp_von(gx)
    x0, y0 = xp.floor(gx), xp.floor(gy)
    tx, ty = gx - x0, gy - y0
    sx, sy = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
    ix, iy = x0.astype(xp.int64), y0.astype(xp.int64)
    oben = _hash(ix, iy, saat) * (1 - sx) + _hash(ix + 1, iy, saat) * sx
    unten = _hash(ix, iy + 1, saat) * (1 - sx) + _hash(ix + 1, iy + 1, saat) * sx
    return (oben * (1 - sy) + unten * sy) / xp.float32(STREUUNG)


def _lage(x, y, weite: float, drehung: float, saat: int):
    """Gitterrauschen mit dieser Masche (Pixel) auf gedrehtem Gitter. Ist die Masche
    kleiner als ein Pixel, mittelt ein Pixel (1/weite)^2 Gitterwerte - schwaecher."""
    xp = xp_von(x)
    c, s = math.cos(drehung), math.sin(drehung)
    gx = (x * c - y * s) / xp.float32(weite)
    gy = (x * s + y * c) / xp.float32(weite)
    return _gitterrauschen(gx, gy, saat) * xp.float32(min(1.0, weite))


def feld(hoehe: int, breite: int, werte: Einstellungen, form: tuple[int, int],
         y0: int = 0, x0: int = 0, xp=np):
    """Das Korn (hoehe, breite) fuer den Ausschnitt ab (y0, x0) eines Bildes der Form
    form = (H, W), Streuung etwa 1 bei voller Groesse."""
    weite = masche(werte, max(form))
    y = (xp.arange(y0, y0 + hoehe, dtype=xp.float32) + 0.5)[:, None]
    x = (xp.arange(x0, x0 + breite, dtype=xp.float32) + 0.5)[None, :]
    korn = _lage(x, y, weite, DREHUNG, SAAT[0])
    anteil = werte.korn_rauheit / 100 * KLUMPEN_ANTEIL
    if anteil > 0:
        klumpen = _lage(x, y, weite * KLUMPEN_GROESSE, KLUMPEN_DREHUNG, SAAT[1])
        # Die mittlere Staerke bleibt; nur ihre Verteilung wird ungleich
        verteilung = xp.maximum(1 + xp.float32(anteil) * klumpen, 0)
        korn = korn * verteilung / xp.float32(math.sqrt(1 + anteil * anteil))
    return korn


def auflegen(bild, werte: Einstellungen, hoechst: float | None = None,
             form: tuple[int, int] | None = None, y0: int = 0, x0: int = 0):
    """Korn auf ein fertiges sRGB-Bild (H, W, 3) - uint8, uint16 oder float mit hoechst.

    form und (y0, x0): Groesse des ganzen Bildes und Lage dieses Ausschnitts darin; ohne
    sie ist das Bild das ganze. Gibt ein neues Array desselben Typs zurueck."""
    if not aktiv(werte):
        return bild
    xp = xp_von(bild)
    ganzzahlig = bild.dtype in (np.uint8, np.uint16)
    if ganzzahlig:
        hoechst = 65535.0 if bild.dtype == np.uint16 else 255.0
    hoehe, breite = bild.shape[:2]
    form = (hoehe, breite) if form is None else form
    ergebnis = xp.empty_like(bild)
    staerke = xp.float32(werte.korn / 100 * KORN_MAX)
    gewichte = xp.asarray(LUMA, dtype=xp.float32)
    for oben in range(0, hoehe, STREIFEN):
        streifen = bild[oben:oben + STREIFEN].astype(xp.float32) / xp.float32(hoechst)
        v = xp.clip(streifen[..., :3] @ gewichte, 0, 1)
        # In den Mitteltoenen am staerksten, an Schwarz und Weiss null
        mitte = xp.sqrt(xp.clip(4 * v * (1 - v), 0, 1))
        korn = feld(streifen.shape[0], breite, werte, form, y0 + oben, x0, xp)
        streifen[..., :3] += (staerke * mitte * korn)[..., None]
        streifen = xp.clip(streifen, 0, 1) * xp.float32(hoechst)
        if ganzzahlig:
            streifen += 0.5
        ergebnis[oben:oben + STREIFEN] = streifen.astype(bild.dtype)
    return ergebnis
