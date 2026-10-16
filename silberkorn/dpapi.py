"""
Windows-Datenschutz-API (DPAPI): Daten fuer den angemeldeten Benutzer verschluesseln

CryptProtectData verschluesselt mit einem Schluessel, den Windows aus der
Anmeldung des Benutzers ableitet und selbst verwaltet - Silberkorn muss keinen
Schluessel speichern. Entschluesseln kann nur derselbe Benutzer auf demselben
Rechner (bei Domaenenkonten auch auf anderen Rechnern der Domaene); eine
kopierte Datei, ein Backup oder eine ausgebaute Platte nuetzt Dritten nichts.

Die "Entropie" ist ein zusaetzliches Geheimnis je Verwendung: Was fuer den
Vorschau-Cache verschluesselt ist, laesst sich nicht als etwas anderes
entschluesseln.

Ohne Windows gibt es kein DPAPI; verfuegbar() ist dann False, und wer es
braucht, laesst die Funktion weg - es gibt keinen Ersatz im Klartext.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import ctypes
import os

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DpapiFehler(Exception):
    """Verschluesseln oder Entschluesseln ist fehlgeschlagen."""


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(daten: bytes) -> tuple[_Blob, ctypes.Array]:
    puffer = ctypes.create_string_buffer(daten, len(daten))
    return _Blob(len(daten), ctypes.cast(puffer, ctypes.POINTER(ctypes.c_char))), puffer


def _bibliotheken():
    if os.name != "nt":
        return None
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        return None
    argumente = [ctypes.POINTER(_Blob), ctypes.c_wchar_p, ctypes.POINTER(_Blob), ctypes.c_void_p,
                 ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_Blob)]
    crypt32.CryptProtectData.argtypes = argumente
    crypt32.CryptProtectData.restype = ctypes.c_int
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob),
                                           ctypes.POINTER(ctypes.c_wchar_p), *argumente[2:]]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


_DLLS = _bibliotheken()


def verfuegbar() -> bool:
    return _DLLS is not None


def _aufrufen(funktion, daten: bytes, entropie: bytes, unprotect: bool) -> bytes:
    if _DLLS is None:
        raise DpapiFehler("DPAPI gibt es nur unter Windows")
    _crypt32, kernel32 = _DLLS
    eingabe, _puffer1 = _blob(daten)
    zusatz, _puffer2 = _blob(entropie)
    ausgabe = _Blob()
    beschreibung = ctypes.c_wchar_p() if unprotect else None
    erste = ctypes.byref(beschreibung) if unprotect else None
    ok = funktion(ctypes.byref(eingabe), erste, ctypes.byref(zusatz), None, None,
                  CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(ausgabe))
    if not ok:
        raise DpapiFehler(f"Windows-Fehler {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(ausgabe.pbData, ausgabe.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(ausgabe.pbData, ctypes.c_void_p))
        if unprotect and beschreibung:
            kernel32.LocalFree(ctypes.cast(beschreibung, ctypes.c_void_p))


def schuetzen(daten: bytes, entropie: bytes) -> bytes:
    """Fuer den angemeldeten Benutzer verschluesseln."""
    if _DLLS is None:
        raise DpapiFehler("DPAPI gibt es nur unter Windows")
    return _aufrufen(_DLLS[0].CryptProtectData, daten, entropie, False)


def oeffnen(daten: bytes, entropie: bytes) -> bytes:
    """Entschluesseln - DpapiFehler, wenn es nicht vom selben Benutzer mit derselben
    Entropie stammt oder veraendert wurde."""
    if _DLLS is None:
        raise DpapiFehler("DPAPI gibt es nur unter Windows")
    return _aufrufen(_DLLS[0].CryptUnprotectData, daten, entropie, True)
