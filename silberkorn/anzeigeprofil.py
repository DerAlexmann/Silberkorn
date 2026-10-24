"""
Monitorprofil: die Anzeige in den Farbraum des Bildschirms umrechnen

Silberkorn rechnet und speichert in sRGB. Ein Bildschirm mit grossem Farbraum
(Display P3, Adobe RGB) zeigt sRGB-Werte ohne Umrechnung zu bunt. Ist ein
Farbprofil fuer den Bildschirm hinterlegt, rechnet dieses Modul jedes Bild kurz
vor der Anzeige in den Farbraum des Bildschirms um - relativ farbmetrisch, wie
es Bildbetrachter tun. Gespeicherte Bilder, Druck und Histogramm bleiben sRGB.

Kleine Bilder (Kacheln, Dialogvorschauen) rechnet LittleCMS ueber Pillow. Fuer
die Leinwand waere das zu langsam (rund 70 ms je Neuzeichnen); dafuer rechnet
LittleCMS einmal je Profil eine 3D-Farbtabelle, die die Grafikkarte mit
derselben tetraedrischen Interpolation wie eine .cube-LUT anwendet. So gilt jede
Profilart (Matrix- wie Tabellenprofile).

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import io
import os
import sys
from dataclasses import dataclass

import numpy as np

from . import lut

# 255 = 51 * 5: die Gitterpunkte liegen genau auf 8-Bit-Werten, die LittleCMS umrechnet
GITTER = 52
MAX_PROFIL = 4 * 2**20            # Monitorprofile haben wenige KB; groessere sind keine
GPU_AB = 2**20                    # ab so vielen Pixeln lohnt die Grafikkarte
SRGB_TOLERANZ = 1.0 / 255         # weicht die Tabelle weniger ab, ist es sRGB


class ProfilFehler(Exception):
    """Das Farbprofil des Bildschirms laesst sich nicht lesen."""


@dataclass(frozen=True, eq=False)
class Monitorprofil:
    name: str                     # Dateiname des Profils, fuer den Tooltip
    umrechnung: object            # ImageCms-Transform sRGB -> Bildschirm
    tabelle: lut.Lut              # dieselbe Umrechnung als Farbtabelle, beide kodiert
    srgb: bool                    # entspricht sRGB: umrechnen aendert nichts


_aktiv: Monitorprofil | None = None


def aktiv() -> Monitorprofil | None:
    return _aktiv


def setzen(profil: Monitorprofil | None):
    """Ab jetzt so anzeigen; None (oder ein sRGB-Profil) heisst: nicht umrechnen."""
    global _aktiv
    _aktiv = None if profil is None or profil.srgb else profil


def _gitter() -> np.ndarray:
    """Alle Gitterpunkte als uint8-Bild, Index [b, g, r] wie in einer .cube-LUT."""
    stufen = np.round(np.linspace(0, 255, GITTER)).astype(np.uint8)
    b, g, r = np.meshgrid(stufen, stufen, stufen, indexing="ij")
    return np.stack([r, g, b], axis=-1).reshape(GITTER * GITTER, GITTER, 3)


def einrichten(daten: bytes, name: str) -> Monitorprofil:
    """Farbtabelle sRGB -> Bildschirm aus den Bytes eines ICC-Profils."""
    from PIL import Image, ImageCms

    if not daten or len(daten) > MAX_PROFIL:
        raise ProfilFehler(name)
    try:
        quelle = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        ziel = ImageCms.ImageCmsProfile(io.BytesIO(daten))
        # Ohne Zwischenspeicher: die Kacheln rechnen mehrere Threads mit derselben Umrechnung
        umrechnung = ImageCms.buildTransform(quelle, ziel, "RGB", "RGB",
                                             ImageCms.Intent.RELATIVE_COLORIMETRIC,
                                             flags=ImageCms.Flags.NOCACHE)
        gitter = _gitter()
        aus = np.asarray(ImageCms.applyTransform(Image.fromarray(gitter), umrechnung))
    except (ImageCms.PyCMSError, OSError, ValueError, TypeError) as fehler:
        raise ProfilFehler(name) from fehler
    tabelle = (aus.reshape(GITTER, GITTER, GITTER, 3) / 255.0).astype(np.float32)
    soll = gitter.reshape(GITTER, GITTER, GITTER, 3) / 255.0
    srgb = bool(np.abs(tabelle - soll).max() <= SRGB_TOLERANZ)
    return Monitorprofil(name, umrechnung, lut.Lut(tabelle, np.zeros(3), np.ones(3), name),
                         srgb)


def umrechnen(rgb: np.ndarray, gpu: bool = False) -> np.ndarray:
    """sRGB-Pixel (uint8, H x W x 3) fuer den Bildschirm; ohne Profil unveraendert.
    gpu: grosse Bilder auf der Grafikkarte rechnen - nur wer CuPy ohnehin geladen hat
    (die Leinwand), damit keine CUDA-Bibliothek vor der Startpruefung kommt.

    Scheitert die Grafikkarte (Speicher voll), rechnet LittleCMS - langsamer, aber gleich.
    Scheitert auch das, kommt das Bild in sRGB: Eine Anzeige soll nie ausfallen."""
    profil = _aktiv
    if profil is None:
        return rgb
    rgb = np.ascontiguousarray(rgb[..., :3])
    if gpu and rgb.shape[0] * rgb.shape[1] >= GPU_AB:
        from .cuda import cupy
        if cupy is not None:
            from . import filter_gpu
            try:
                return filter_gpu.anzeige_umrechnen(rgb, profil.tabelle)
            except (cupy.cuda.memory.OutOfMemoryError,
                    cupy.cuda.runtime.CUDARuntimeError):
                pass
    from PIL import Image, ImageCms
    try:
        return np.asarray(ImageCms.applyTransform(Image.fromarray(rgb), profil.umrechnung))
    except (ImageCms.PyCMSError, ValueError, OSError):
        return rgb


# --------------------------------------------------------------------------
# Windows: das Profil des Bildschirms, auf dem ein Fenster steht
# --------------------------------------------------------------------------

def profil_lesen(fenster: int) -> tuple[str, bytes] | None:
    """Name und Bytes des Farbprofils fuer den Bildschirm des Fensters (HWND); None, wenn
    Windows keines meldet oder es kein Windows ist."""
    if sys.platform != "win32":
        return None
    import ctypes
    try:
        pfad = _profilpfad(fenster)
    except (OSError, AttributeError, ctypes.ArgumentError):
        return None                       # ohne Antwort von Windows gilt sRGB, wie ohne Profil
    if not pfad:
        return None
    name = os.path.basename(pfad)
    try:
        with open(pfad, "rb") as datei:
            daten = datei.read(MAX_PROFIL + 1)
    except OSError as fehler:
        raise ProfilFehler(name) from fehler
    return name, daten


def _profilpfad(fenster: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    class _MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]

    user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
    gdi32.CreateDCW.restype = wintypes.HDC
    gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                ctypes.c_void_p]
    gdi32.GetICMProfileW.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.DWORD),
                                     wintypes.LPWSTR]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]

    monitor = user32.MonitorFromWindow(fenster, 2)        # MONITOR_DEFAULTTONEAREST
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    geraet = gdi32.CreateDCW(info.szDevice, info.szDevice, None, None)
    if not geraet:
        return None
    try:
        laenge = wintypes.DWORD(0)
        gdi32.GetICMProfileW(geraet, ctypes.byref(laenge), None)
        if not 0 < laenge.value <= 32768:
            return None
        puffer = ctypes.create_unicode_buffer(laenge.value)
        if not gdi32.GetICMProfileW(geraet, ctypes.byref(laenge), puffer):
            return None
        return puffer.value or None
    finally:
        gdi32.DeleteDC(geraet)
