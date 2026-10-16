"""
Vorschaubilder fuer die Ordneransicht - so billig wie moeglich

Gelesen wird, was am wenigsten kostet:

  1. Die Begleitdatei (begleitdatei.py) - sie zeigt das bearbeitete Bild.
  2. Bei RAW das eingebettete Vorschau-JPEG; bei JPEG das Bild auf ein Achtel
     verkleinert dekodiert (Pillow draft).
  3. Sonst das ganze Bild - bei grossen TIFFs und PNGs teuer. Was laenger
     dauert als TEUER_MS, gehoert in den Vorschau-Cache (vorschau_cache.py).

Jede Datei im Ordner kann von irgendwoher stammen: Groessen werden vor dem
Dekodieren geprueft (MAX_PIXEL), Fehler bleiben bei der einen Datei.

Dieses Modul kennt weder Qt noch die Grafikkarte.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import io
import os
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

from . import begleitdatei, bilddatei

KANTE = 256                   # laengste Kante eines Vorschaubildes
MAX_PIXEL = 400_000_000       # groessere Bilder bekommen kein Vorschaubild
MAX_VORSCHAU_KANTE = 1024     # so gross darf das WebP in einer Begleitdatei hoechstens sein
TEUER_MS = 120                # was laenger dauert, kommt in den Cache
WEBP_QUALITAET = 80


class VorschauFehler(Exception):
    """Fuer diese Datei gibt es kein Vorschaubild."""


@dataclass
class Vorschau:
    bild: Image.Image          # RGB, laengste Kante hoechstens KANTE
    bearbeitet: bool           # aus einer Begleitdatei
    teuer: bool                # lohnt den Cache


def ist_bild(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in bilddatei.LESBAR


def kodieren(bild: Image.Image) -> bytes:
    puffer = io.BytesIO()
    bild.save(puffer, "WEBP", quality=WEBP_QUALITAET)
    return puffer.getvalue()


def dekodieren(daten: bytes, hoechstens: int = MAX_VORSCHAU_KANTE) -> Image.Image:
    """Ein WebP aus Cache oder Begleitdatei - nur, wenn es klein ist."""
    try:
        with Image.open(io.BytesIO(daten), formats=["WEBP"]) as bild:
            if max(bild.size) > hoechstens:
                raise VorschauFehler("Vorschaubild zu groß")
            bild.load()
            return _verkleinert(bild.convert("RGB"))
    except (OSError, ValueError, Image.DecompressionBombError) as fehler:
        raise VorschauFehler(str(fehler)) from fehler


def _verkleinert(bild: Image.Image) -> Image.Image:
    if max(bild.size) > KANTE:
        bild.thumbnail((KANTE, KANTE), Image.Resampling.LANCZOS, reducing_gap=2.0)
    return bild


def _aus_array(pixel: np.ndarray) -> Image.Image:
    """Ein Array beliebiger Bittiefe als RGB-Bild (8 Bit), vorher grob verkleinert."""
    if pixel.ndim == 3 and pixel.shape[2] == 1:
        pixel = pixel[..., 0]
    schritt = max(1, max(pixel.shape[:2]) // (KANTE * 2))
    pixel = pixel[::schritt, ::schritt]
    if pixel.dtype == np.uint16:
        pixel = (pixel >> 8).astype(np.uint8)
    elif np.issubdtype(pixel.dtype, np.floating):
        pixel = (np.clip(np.nan_to_num(pixel), 0, 1) * 255 + 0.5).astype(np.uint8)
    elif pixel.dtype == np.uint32:
        pixel = (pixel >> 24).astype(np.uint8)
    elif pixel.dtype != np.uint8:
        raise VorschauFehler(f"nicht unterstützte Bittiefe: {pixel.dtype}")
    if pixel.ndim == 2:
        pixel = np.repeat(pixel[..., None], 3, axis=2)
    elif pixel.shape[2] == 2:
        pixel = np.repeat(pixel[..., :1], 3, axis=2)
    else:
        pixel = pixel[..., :3]                 # Alpha und Infrarot fallen weg
    return _verkleinert(Image.fromarray(np.ascontiguousarray(pixel), "RGB"))


def _raw(pfad: str) -> Image.Image:
    import rawpy
    try:
        with rawpy.imread(pfad) as roh:
            drehung = roh.sizes.flip
            vorschau = roh.extract_thumb()
    except (rawpy.LibRawError, OSError, ValueError) as fehler:
        raise VorschauFehler(str(fehler)) from fehler
    if vorschau.format == rawpy.ThumbFormat.JPEG:
        bild = _pillow(io.BytesIO(vorschau.data), drehen=False, formate=["JPEG"])
    else:
        bild = _aus_array(np.asarray(vorschau.data))
    # LibRaw: 3 = 180 Grad, 5 = 90 Grad gegen, 6 = 90 Grad mit dem Uhrzeigersinn
    return {3: bild.transpose(Image.Transpose.ROTATE_180),
            5: bild.transpose(Image.Transpose.ROTATE_90),
            6: bild.transpose(Image.Transpose.ROTATE_270)}.get(drehung, bild)


def _pillow(quelle, drehen: bool = True, formate=None) -> Image.Image:
    try:
        with Image.open(quelle, formats=formate) as bild:
            breite, hoehe = bild.size
            if breite * hoehe > MAX_PIXEL:
                raise VorschauFehler("Bild zu groß für eine Vorschau")
            bild.draft("RGB", (KANTE * 2, KANTE * 2))   # JPEG: verkleinert dekodieren
            bild.load()
            if drehen:
                bild = ImageOps.exif_transpose(bild)
            if bild.mode in ("I;16", "I;16B", "I;16L", "I"):
                return _aus_array(np.asarray(bild).astype(np.uint16))
            return _verkleinert(bild.convert("RGB"))
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as fehler:
        raise VorschauFehler(str(fehler)) from fehler


def _tiff(pfad: str) -> Image.Image | None:
    """TIFF mit tifffile - die kleinste Seite oder Stufe, die noch gross genug ist.
    None fuer Farbmodelle, die Pillow besser kann."""
    import tifffile
    try:
        with tifffile.TiffFile(pfad) as datei:
            seite = datei.pages[0]
            if seite.photometric not in (tifffile.PHOTOMETRIC.RGB,
                                         tifffile.PHOTOMETRIC.MINISBLACK):
                return None
            kandidaten = [seite, *(seite.pages or [])] if hasattr(seite, "pages") else [seite]
            for stufe in getattr(datei.series[0], "levels", [])[1:]:
                kandidaten.extend(stufe.pages)
            passend = [s for s in kandidaten
                       if min(s.shape[:2] if s.planarconfig != tifffile.PLANARCONFIG.SEPARATE
                              or len(s.shape) < 3 else s.shape[1:3]) >= KANTE]
            wahl = min(passend or [seite], key=lambda s: int(np.prod(s.shape)))
            if int(np.prod(wahl.shape[:3])) > MAX_PIXEL * 4:
                raise VorschauFehler("Bild zu groß für eine Vorschau")
            pixel = wahl.asarray()
            if wahl.planarconfig == tifffile.PLANARCONFIG.SEPARATE and pixel.ndim == 3:
                pixel = np.moveaxis(pixel, 0, -1)
            tag = seite.tags.get(bilddatei.EXIF_AUSRICHTUNG)
            ausrichtung = int(tag.value) if tag is not None else 1
    except (tifffile.TiffFileError, OSError, ValueError, IndexError, MemoryError) as fehler:
        raise VorschauFehler(str(fehler)) from fehler
    return _aus_array(bilddatei.ausrichten(pixel, ausrichtung))


def _png16(pfad: str) -> Image.Image:
    with open(pfad, "rb") as datei:
        kopf = datei.read(24)
    breite, hoehe = int.from_bytes(kopf[16:20], "big"), int.from_bytes(kopf[20:24], "big")
    if breite * hoehe > MAX_PIXEL:
        raise VorschauFehler("Bild zu groß für eine Vorschau")
    import imagecodecs
    try:
        with open(pfad, "rb") as datei:
            pixel = imagecodecs.png_decode(datei.read())
    except (imagecodecs.PngError, OSError, ValueError, MemoryError) as fehler:
        raise VorschauFehler(str(fehler)) from fehler
    return _aus_array(pixel)


def aus_begleitdatei(pfad: str) -> Image.Image | None:
    """Das bearbeitete Bild aus der Begleitdatei - wenn es eine gibt, die zur Groesse des
    Bildes passt. Den vollen Fingerabdruck prueft erst das Oeffnen."""
    begleit = begleitdatei.pfad_fuer(pfad)
    if not os.path.isfile(begleit):
        return None
    try:
        kopf = begleitdatei.kopf_lesen(begleit)
        original = kopf.get("original")
        if not isinstance(original, dict) or original.get("groesse") != os.path.getsize(pfad):
            return None
        daten = begleitdatei.vorschau_lesen(begleit)
        return None if daten is None else dekodieren(daten)
    except (begleitdatei.BegleitFehler, VorschauFehler, OSError):
        return None


def erzeugen(pfad: str) -> Vorschau:
    """Das Vorschaubild einer Bilddatei - ohne Begleitdatei und Cache. VorschauFehler,
    wenn es keins gibt."""
    beginn = time.perf_counter()
    endung = os.path.splitext(pfad)[1].lower()
    bild = None
    if endung in bilddatei.RAW:
        bild = _raw(pfad)
    elif endung in (".tif", ".tiff"):
        bild = _tiff(pfad)
    elif endung == ".png" and bilddatei._png_bittiefe(pfad) == 16:
        bild = _png16(pfad)
    if bild is None:
        bild = _pillow(pfad)
    teuer = (time.perf_counter() - beginn) * 1000 > TEUER_MS
    return Vorschau(bild, False, teuer)
