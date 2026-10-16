"""
Bilder laden und speichern - 8 Bit, 16 Bit und RAW

Woher die Pixel kommen:
  RAW (Bayer)    LibRaw liest das Mosaik, entwickelt wird auf der GPU (demosaik.py),
                 ebenso bei Fujis X-Trans
  RAW (sonst)    LibRaw entwickelt linear in 16 Bit, sRGB-Primaerfarben - so auch
                 jede RAW, wenn die beste Qualitaet gewaehlt ist (Verfahren DHT)
  TIFF           tifffile - 8 und 16 Bit, auch komprimiert
  PNG mit 16 Bit imagecodecs
  alles andere   Pillow, 8 Bit

Die Pixel bleiben so kodiert, wie sie in der Datei stehen; ein eingebettetes
RGB-Matrixprofil (Adobe RGB, ProPhoto, Display P3 ...) wird mitgegeben und
erst auf der Grafikkarte in lineares sRGB umgerechnet (icc.linearisieren).
Nur Profile anderer Bauart - CMYK, Graustufen, Tabellenprofile - rechnet
LittleCMS ueber Pillow schon beim Laden nach sRGB, dann mit 8 Bit.

Die EXIF-Ausrichtung wird beim Laden angewendet. EXIF, IPTC und XMP werden
mitgelesen (metadaten.py), auch aus RAW; beim Speichern schreiben alle Formate
EXIF und XMP, dazu den Alphakanal, soweit das Zielformat ihn traegt.

Einen zusaetzlichen Kanal im TIFF bestimmt das Feld ExtraSamples: Als Alpha
markiert, bleibt er Alpha; nicht naeher bezeichnet, ist er der Infrarotkanal
eines Filmscanners (RGBI, so speichern ihn VueScan und SilverFast). Der dient
nur der Bearbeitung und wird nicht mitgespeichert.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import io
import math
import os
import struct
import zlib
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageCms, ImageOps, PngImagePlugin

from . import demosaik, icc, metadaten
from .objektivprofile import Aufnahme

try:                                          # HEIC/HEIF, falls installiert
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF = True
except ImportError:
    HEIF = False

RAW = [".3fr", ".arw", ".cr2", ".cr3", ".dng", ".erf", ".iiq", ".kdc", ".mef", ".mos",
       ".mrw", ".nef", ".nrw", ".orf", ".pef", ".raf", ".rw2", ".rwl", ".sr2", ".srf",
       ".srw", ".x3f"]
BILDER = [".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"]
if HEIF:
    BILDER += [".heic", ".heif"]
LESBAR = BILDER + RAW

# Endung -> (Format, kann Alphakanal, kann 16 Bit)
SCHREIBBAR = {
    ".jpg": ("JPEG", False, False),
    ".jpeg": ("JPEG", False, False),
    ".png": ("PNG", True, True),
    ".tif": ("TIFF", True, True),
    ".tiff": ("TIFF", True, True),
    ".webp": ("WEBP", True, False),
}

JPEG_QUALITAET = 95
EXIF_AUSRICHTUNG = 0x0112
TIFF_ICC = 34675
# ExtraSamples im TIFF: nicht naeher bezeichnet, Alpha vormultipliziert, Alpha frei
EXTRA_UNBESTIMMT, EXTRA_ALPHA = 0, (1, 2)


class BildFehler(Exception):
    """Die Datei laesst sich nicht als Bild lesen oder schreiben."""


@dataclass
class Bilddaten:
    pixel: np.ndarray | None         # (H, W, 3) uint8 oder uint16, kodiert wie in der Datei
    profil: icc.Matrixprofil | None  # Farbraum der Pixel; None heisst sRGB
    alpha: np.ndarray | None         # (H, W) in derselben Bittiefe wie pixel
    exif: bytes                      # Ausrichtung bereits auf 1 gesetzt
    pfad: str
    raw: bool = False
    mosaik: demosaik.RawMosaik | None = None   # statt pixel: Mosaik fuer die GPU
    aufnahme: Aufnahme | None = None           # Kamera und Objektiv, fuer Objektivprofile
    xmp: bytes = b""                           # XMP-Paket der Datei
    iptc: dict = field(default_factory=dict)   # IPTC-IIM: {(Satz, Feld): [Bytes, ...]}
    infrarot: np.ndarray | None = None         # (H, W) Infrarotkanal eines Filmscans

    @property
    def form(self) -> tuple[int, int]:
        return self.mosaik.form if self.mosaik is not None else self.pixel.shape[:2]

    @property
    def breite(self) -> int:
        return self.form[1]

    @property
    def hoehe(self) -> int:
        return self.form[0]

    @property
    def bits(self) -> int:
        if self.mosaik is not None:
            return 16
        return 16 if self.pixel.dtype == np.uint16 else 8

    def linear(self, xp=np):
        """Das Bild in linearem sRGB als float32 - mit NumPy oder CuPy (xp)."""
        if self.mosaik is not None:
            return demosaik.entwickeln(xp.asarray(self.mosaik.daten), self.mosaik)
        return icc.linearisieren(xp.asarray(self.pixel), self.profil)

    @property
    def name(self) -> str:
        return os.path.basename(self.pfad)


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------

def _srgb_profil() -> ImageCms.ImageCmsProfile:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))


def ausrichten(pixel: np.ndarray, wert: int) -> np.ndarray:
    """EXIF-Ausrichtung 1..8 auf ein Array anwenden - wie ImageOps.exif_transpose."""
    if wert == 2:
        return pixel[:, ::-1]
    if wert == 3:
        return pixel[::-1, ::-1]
    if wert == 4:
        return pixel[::-1]
    if wert == 5:
        return np.swapaxes(pixel, 0, 1)
    if wert == 6:
        return np.rot90(pixel, 3)
    if wert == 7:
        return np.rot90(np.swapaxes(pixel, 0, 1), 2)
    if wert == 8:
        return np.rot90(pixel, 1)
    return pixel


def _kanaele_trennen(pixel: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
    """Graustufen zu RGB ausweiten und einen Alphakanal abtrennen."""
    if pixel.ndim == 2:
        return np.repeat(pixel[..., None], 3, axis=2), None
    kanaele = pixel.shape[2]
    if kanaele == 1:
        return np.repeat(pixel, 3, axis=2), None
    if kanaele == 2:
        return np.repeat(pixel[..., :1], 3, axis=2), pixel[..., 1].copy()
    if kanaele == 4:
        return pixel[..., :3], pixel[..., 3].copy()
    return pixel[..., :3], None


def _infrarot_abtrennen(pixel: np.ndarray, grundkanaele: int,
                        extras: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray | None]:
    """Den Infrarotkanal eines TIFF abtrennen: den ersten zusaetzlichen Kanal, der nicht
    naeher bezeichnet ist. Uebrig bleiben die Farbkanaele und hoechstens ein Alphakanal."""
    if pixel.ndim != 3 or pixel.shape[2] <= grundkanaele:
        return pixel, None
    extras = extras[:pixel.shape[2] - grundkanaele]
    alpha = next((grundkanaele + i for i, art in enumerate(extras) if art in EXTRA_ALPHA), None)
    infrarot = next((grundkanaele + i for i, art in enumerate(extras)
                     if art == EXTRA_UNBESTIMMT), None)
    if infrarot is None:
        return pixel, None
    behalten = list(range(grundkanaele)) + ([alpha] if alpha is not None else [])
    return pixel[..., behalten], pixel[..., infrarot].copy()


def _bittiefe_angleichen(pixel: np.ndarray) -> np.ndarray:
    """Alles, was nicht 8 oder 16 Bit ist, auf 16 Bit bringen."""
    if pixel.dtype in (np.uint8, np.uint16):
        return pixel
    if np.issubdtype(pixel.dtype, np.floating):
        return (np.clip(pixel, 0, 1) * 65535 + 0.5).astype(np.uint16)
    if pixel.dtype == np.uint32:
        return (pixel >> 16).astype(np.uint16)
    raise BildFehler(f"nicht unterstützte Bittiefe: {pixel.dtype}")


def _metadaten(pfad: str) -> tuple[bytes | None, Image.Exif, bytes, dict]:
    """Farbprofil, EXIF, XMP und IPTC ueber Pillow lesen, ohne die Pixel zu dekodieren."""
    try:
        with Image.open(pfad) as kopf:
            return (kopf.info.get("icc_profile"), metadaten.einlesen(kopf.getexif()),
                    metadaten.xmp_aus_bild(kopf),
                    metadaten.iim_lesen(kopf))
    except (OSError, ValueError, SyntaxError):
        return None, Image.Exif(), b"", {}


EXIF_IFD = 0x8769
EXIF_HERSTELLER, EXIF_MODELL = 0x010F, 0x0110
EXIF_BLENDE, EXIF_BRENNWEITE = 0x829D, 0x920A
EXIF_OBJEKTIV_DATEN, EXIF_OBJEKTIV_HERSTELLER, EXIF_OBJEKTIV = 0xA432, 0xA433, 0xA434


def _text(wert) -> str:
    if isinstance(wert, bytes):
        wert = wert.decode("utf-8", "replace")
    return " ".join(str(wert).replace("\x00", " ").split()) if wert is not None else ""


def _kommazahl(wert) -> float:
    try:
        zahl = float(wert)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
    return zahl if math.isfinite(zahl) and zahl > 0 else 0.0


def aufnahme_aus_exif(exif: Image.Exif) -> Aufnahme | None:
    """Kamera, Objektiv, Brennweite und Blende aus EXIF - oder None ohne Objektivangabe."""
    try:
        details = exif.get_ifd(EXIF_IFD)
    except (KeyError, ValueError, TypeError, OSError):
        details = {}
    objektiv = _text(details.get(EXIF_OBJEKTIV))
    if not objektiv:
        return None
    brennweiten = (0.0, 0.0)
    daten = details.get(EXIF_OBJEKTIV_DATEN)
    if isinstance(daten, (tuple, list)) and len(daten) >= 2:
        brennweiten = (_kommazahl(daten[0]), _kommazahl(daten[1]))
    return Aufnahme(_text(exif.get(EXIF_HERSTELLER)), _text(exif.get(EXIF_MODELL)), objektiv,
                    _text(details.get(EXIF_OBJEKTIV_HERSTELLER)),
                    _kommazahl(details.get(EXIF_BRENNWEITE)), _kommazahl(details.get(EXIF_BLENDE)),
                    brennweiten)


def _raw_exif(pfad: str, roh) -> Image.Exif:
    """EXIF einer RAW: aus der Datei selbst (TIFF-artige RAWs wie NEF, CR2, ARW, DNG)
    oder aus dem eingebetteten Vorschaubild (RAF, CR3, RW2 ...)."""
    _icc, exif, _xmp, _iptc = _metadaten(pfad)
    if not exif.get(EXIF_MODELL):
        import rawpy
        try:
            vorschau = roh.extract_thumb()
            if vorschau.format == rawpy.ThumbFormat.JPEG:
                with Image.open(io.BytesIO(vorschau.data)) as bild:
                    exif = metadaten.einlesen(bild.getexif())
        except (rawpy.LibRawError, OSError, ValueError, SyntaxError, AttributeError):
            pass                              # ohne Vorschaubild: ohne EXIF weiter
    return exif


def _raw_aufnahme(exif: Image.Exif, roh) -> Aufnahme | None:
    """Objektiv, Brennweite und Blende von LibRaw; Hersteller und Modell der Kamera aus
    dem EXIF."""
    objektiv = getattr(roh, "lens", None)
    andere = getattr(roh, "other", None)
    if objektiv is None or andere is None or not _text(objektiv.model):
        return None
    hersteller, kamera = _text(exif.get(EXIF_HERSTELLER)), _text(exif.get(EXIF_MODELL))
    return Aufnahme(hersteller, kamera, _text(objektiv.model), _text(objektiv.make),
                    _kommazahl(andere.focal_length), _kommazahl(andere.aperture),
                    (_kommazahl(objektiv.min_focal), _kommazahl(objektiv.max_focal)))


def _exif_ohne_ausrichtung(exif: Image.Exif) -> bytes:
    """Ausrichtung auf 1 - die Pixel sind schon gedreht -, nur beschreibende Felder."""
    return metadaten.saeubern(exif)


def _profil_oder_fehler(daten: bytes | None) -> icc.Matrixprofil | None:
    """Matrixprofil oder None (= sRGB). Andere Profile kann nur der 8-Bit-Weg."""
    profil = icc.lesen(daten)
    if profil is not None and profil.ist_srgb():
        return None
    return profil


# --------------------------------------------------------------------------
# Laden
# --------------------------------------------------------------------------

RAW_QUALITAET = ("schnell", "beste")


def _raw_laden(pfad: str, gpu: bool = True, qualitaet: str = "schnell") -> Bilddaten:
    import rawpy
    beste = qualitaet == "beste"
    try:
        with rawpy.imread(pfad) as roh:
            exif = _raw_exif(pfad, roh)
            zusatz = {"aufnahme": _raw_aufnahme(exif, roh), "xmp": metadaten.xmp_suchen(pfad)}
            exif = metadaten.saeubern(exif, raw=True)
            mosaik = demosaik.aus_rawpy(roh) if gpu and not beste else None
            if mosaik is not None:
                return Bilddaten(None, icc.LINEAR_SRGB, None, exif, pfad, raw=True, mosaik=mosaik,
                                 **zusatz)
            # Linear (Gamma 1), 16 Bit, sRGB-Primaerfarben, Weissabgleich der
            # Kamera - und ohne die automatische Aufhellung von LibRaw. Die
            # liesse 1 % der Pixel ausbrennen; so bleibt der volle Umfang des
            # Sensors erhalten, und die Helligkeit regelt die Belichtung.
            # Ebenso ohne adjust_maximum: Das setzt den Weisspunkt auf den hellsten
            # Wert im Bild, sobald der ueber 75 % liegt - die Helligkeit hinge dann
            # vom Motiv ab und wiche von der Entwicklung auf der GPU ab.
            # Beste Qualitaet: DHT (in LibRaw enthalten) - weniger Farbsaeume und
            # ruhigere Flaechen als das Standardverfahren AHD, auf dem Prozessor
            verfahren = {"demosaic_algorithm": rawpy.DemosaicAlgorithm.DHT} if beste else {}
            pixel = roh.postprocess(gamma=(1, 1), output_bps=16, use_camera_wb=True,
                                    output_color=rawpy.ColorSpace.sRGB, no_auto_bright=True,
                                    adjust_maximum_thr=0.0, **verfahren)
    except (rawpy.LibRawError, OSError, ValueError) as fehler:
        raise BildFehler(str(fehler)) from fehler
    return Bilddaten(np.ascontiguousarray(pixel), icc.LINEAR_SRGB, None, exif, pfad, raw=True,
                     **zusatz)


def _tiff_laden(pfad: str) -> Bilddaten | None:
    """TIFF mit tifffile; None fuer Farbmodelle, die Pillow besser kann (CMYK, Palette ...)."""
    import tifffile
    try:
        with tifffile.TiffFile(pfad) as datei:
            seite = datei.pages[0]
            if seite.photometric not in (tifffile.PHOTOMETRIC.RGB,
                                         tifffile.PHOTOMETRIC.MINISBLACK):
                return None
            pixel = seite.asarray()
            if seite.planarconfig == tifffile.PLANARCONFIG.SEPARATE and pixel.ndim == 3:
                pixel = np.moveaxis(pixel, 0, -1)
            grundkanaele = 3 if seite.photometric == tifffile.PHOTOMETRIC.RGB else 1
            extras = tuple(int(e) for e in (seite.extrasamples or ()))
            icc_tag = seite.tags.get(TIFF_ICC)
            icc_daten = bytes(icc_tag.value) if icc_tag is not None else None
            tag = seite.tags.get(EXIF_AUSRICHTUNG)
            ausrichtung = int(tag.value) if tag is not None else 1
    except (tifffile.TiffFileError, OSError, ValueError, IndexError) as fehler:
        raise BildFehler(str(fehler)) from fehler

    if pixel.dtype == np.uint8 and icc_daten and icc.lesen(icc_daten) is None:
        return None                           # Tabellenprofil: LittleCMS ueber Pillow
    pixel, infrarot = _infrarot_abtrennen(_bittiefe_angleichen(pixel), grundkanaele, extras)
    rgb, alpha = _kanaele_trennen(pixel)
    rgb, alpha, infrarot = (ausrichten(rgb, ausrichtung),
                            *(None if ebene is None else
                              np.ascontiguousarray(ausrichten(ebene, ausrichtung))
                              for ebene in (alpha, infrarot)))
    _icc, exif, xmp, iptc = _metadaten(pfad)
    aufnahme = aufnahme_aus_exif(exif)
    return Bilddaten(np.ascontiguousarray(rgb), _profil_oder_fehler(icc_daten), alpha,
                     _exif_ohne_ausrichtung(exif), pfad, aufnahme=aufnahme, xmp=xmp, iptc=iptc,
                     infrarot=infrarot)


def _png_bittiefe(pfad: str) -> int:
    with open(pfad, "rb") as datei:
        kopf = datei.read(26)
    if len(kopf) < 26 or kopf[:8] != b"\x89PNG\r\n\x1a\n":
        return 0
    return kopf[24]


def _png16_laden(pfad: str) -> Bilddaten:
    import imagecodecs
    try:
        with open(pfad, "rb") as datei:
            pixel = imagecodecs.png_decode(datei.read())
    except (imagecodecs.PngError, OSError, ValueError) as fehler:
        raise BildFehler(str(fehler)) from fehler
    icc_daten, exif, xmp, iptc = _metadaten(pfad)
    rgb, alpha = _kanaele_trennen(_bittiefe_angleichen(pixel))
    ausrichtung = exif.get(EXIF_AUSRICHTUNG, 1)
    rgb = ausrichten(rgb, ausrichtung)
    if alpha is not None:
        alpha = np.ascontiguousarray(ausrichten(alpha, ausrichtung))
    if icc_daten and icc.lesen(icc_daten) is None:
        raise BildFehler("16-Bit-PNG mit einem Farbprofil, das kein RGB-Matrixprofil ist")
    aufnahme = aufnahme_aus_exif(exif)
    return Bilddaten(np.ascontiguousarray(rgb), _profil_oder_fehler(icc_daten), alpha,
                     _exif_ohne_ausrichtung(exif), pfad, aufnahme=aufnahme, xmp=xmp, iptc=iptc)


def _pillow_laden(pfad: str) -> Bilddaten:
    try:
        with Image.open(pfad) as roh:
            roh.load()
            exif = metadaten.einlesen(roh.getexif())
            xmp, iptc = metadaten.xmp_aus_bild(roh), metadaten.iim_lesen(roh)
            bild = ImageOps.exif_transpose(roh)
    except (OSError, ValueError, Image.DecompressionBombError) as fehler:
        raise BildFehler(str(fehler)) from fehler

    icc_daten = bild.info.get("icc_profile")
    alpha = None
    if bild.mode in ("RGBA", "LA", "PA") or (bild.mode == "P" and "transparency" in bild.info):
        bild = bild.convert("RGBA")
        alpha = np.asarray(bild.getchannel("A")).copy()
        bild = bild.convert("RGB")

    profil = icc.lesen(icc_daten)
    if bild.mode == "RGB" and (not icc_daten or profil is not None):
        # sRGB oder Matrixprofil: Pixel unveraendert, umgerechnet wird auf der GPU
        pixel, profil = np.asarray(bild), _profil_oder_fehler(icc_daten)
    else:
        # CMYK, Graustufen, Tabellenprofile: LittleCMS rechnet nach sRGB
        profil = None
        if icc_daten and bild.mode in ("RGB", "CMYK", "L"):
            try:
                quelle = ImageCms.ImageCmsProfile(io.BytesIO(icc_daten))
                bild = ImageCms.profileToProfile(bild, quelle, _srgb_profil(), outputMode="RGB")
            except (ImageCms.PyCMSError, OSError, ValueError):
                pass                          # unlesbares Profil: wie sRGB behandeln
        pixel = np.asarray(bild.convert("RGB"))
    aufnahme = aufnahme_aus_exif(exif)
    return Bilddaten(np.ascontiguousarray(pixel), profil, alpha,
                     _exif_ohne_ausrichtung(exif), pfad, aufnahme=aufnahme, xmp=xmp, iptc=iptc)


def laden(pfad: str, raw_auf_gpu: bool = True, raw_qualitaet: str = "schnell") -> Bilddaten:
    """Laedt ein Bild. raw_auf_gpu=False laesst auch Bayer-RAWs von LibRaw entwickeln,
    raw_qualitaet="beste" ebenso, dann mit dem genaueren Verfahren DHT."""
    endung = os.path.splitext(pfad)[1].lower()
    if endung in RAW:
        return _raw_laden(pfad, raw_auf_gpu, raw_qualitaet)
    if endung in (".tif", ".tiff"):
        daten = _tiff_laden(pfad)
        if daten is not None:
            return daten
    if endung == ".png" and _png_bittiefe(pfad) == 16:
        return _png16_laden(pfad)
    return _pillow_laden(pfad)


# --------------------------------------------------------------------------
# Speichern
# --------------------------------------------------------------------------

def _png_block(art: bytes, daten: bytes) -> bytes:
    pruefsumme = zlib.crc32(art + daten) & 0xFFFFFFFF
    return struct.pack(">I", len(daten)) + art + daten + struct.pack(">I", pruefsumme)


def _png16_schreiben(pfad: str, pixel: np.ndarray, exif: bytes, xmp: bytes) -> None:
    """16-Bit-PNG mit sRGB-Profil (iCCP), EXIF (eXIf) und XMP (iTXt) hinter dem Kopf."""
    import imagecodecs
    roh = imagecodecs.png_encode(pixel, level=6)
    kopf_ende = 8 + 25                        # Signatur + IHDR-Block
    zusatz = _png_block(b"iCCP", b"sRGB\x00\x00" + zlib.compress(_srgb_profil().tobytes()))
    if exif:
        zusatz += _png_block(b"eXIf", exif[6:] if exif.startswith(b"Exif\x00\x00") else exif)
    if xmp:
        # Schluessel, Nullbyte, unkomprimiert (0, 0), ohne Sprache und Uebersetzung
        zusatz += _png_block(b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00" + xmp)
    with open(pfad, "wb") as datei:
        datei.write(roh[:kopf_ende] + zusatz + roh[kopf_ende:])


# TIFF-Felder fuer EXIF und GPS: tifffile schreibt sie nicht selbst. Es bekommt
# Platzhalter mit den naechsthoeheren, unbelegten Nummern - so bleibt die
# Reihenfolge der Felder richtig, wenn sie danach umbenannt werden.
TIFF_UNTER = {0x8769: 0x876A, 0x8825: 0x8826}
TIFF_TEXTE = (0x010F, 0x0110, 0x013B, 0x8298)    # Hersteller, Modell, Kuenstler, Copyright


def _tiff_schreiben(pfad: str, pixel: np.ndarray, exif: bytes, xmp: bytes) -> None:
    """TIFF mit tifffile - 8 Bit mit LZW, 16 Bit mit Deflate - samt EXIF und XMP.
    Pillow kann 16 Bit RGB nicht und mit LZW keine EXIF-Unterverzeichnisse."""
    import tifffile
    from PIL import TiffImagePlugin
    daten = metadaten.exif_laden(exif)
    texte = {"description": daten.get(0x010E), "software": daten.get(0x0131),
             "datetime": daten.get(0x0132)}
    zusatz = {name: wert for name, wert in texte.items() if isinstance(wert, str) and wert}
    if pixel.shape[2] == 4:
        zusatz["extrasamples"] = [2]          # 2 = freier Alphakanal
    felder = [(tag, "s", 0, daten[tag], True) for tag in TIFF_TEXTE
              if isinstance(daten.get(tag), str) and daten.get(tag)]
    unter = {tag: daten.get_ifd(tag) for tag in TIFF_UNTER if tag in daten}
    unter = {tag: werte for tag, werte in unter.items() if werte}
    felder += [(TIFF_UNTER[tag], "I", 1, 0, True) for tag in unter]
    if xmp:
        felder.append((700, "B", len(xmp), xmp, True))
    tifffile.imwrite(pfad, pixel, photometric="rgb",
                     compression="zlib" if pixel.dtype == np.uint16 else "lzw",
                     iccprofile=_srgb_profil().tobytes(), metadata=None,
                     software=zusatz.pop("software", False), extratags=felder, **zusatz)
    if not unter:
        return
    with tifffile.TiffFile(pfad) as datei:
        stellen = {tag: datei.pages[0].tags[TIFF_UNTER[tag]].offset for tag in unter}
        format_ = "<" if datei.byteorder == "<" else ">"
    with open(pfad, "r+b") as datei:
        for tag, werte in unter.items():
            verzeichnis = TiffImagePlugin.ImageFileDirectory_v2(
                prefix=b"II" if format_ == "<" else b"MM", group=tag)
            for schluessel, wert in werte.items():
                if schluessel != metadaten.INTEROP_IFD:
                    verzeichnis[schluessel] = wert
            ende = datei.seek(0, 2)
            if ende % 2:
                datei.write(b"\x00")
                ende += 1
            datei.write(verzeichnis.tobytes(ende))
            datei.seek(stellen[tag])
            datei.write(struct.pack(format_ + "HHII", tag, 4, 1, ende))   # 4 = LONG


def alpha_umrechnen(alpha: np.ndarray, bits: int) -> np.ndarray:
    if bits == 16 and alpha.dtype == np.uint8:
        return alpha.astype(np.uint16) * 257
    if bits == 8 and alpha.dtype == np.uint16:
        return ((alpha.astype(np.uint32) + 128) // 257).astype(np.uint8)
    return alpha


def speichern(pfad: str, rgb: np.ndarray, alpha: np.ndarray | None = None,
              exif: bytes = b"", xmp: bytes = b"", qualitaet: int = JPEG_QUALITAET) -> None:
    """Speichert rgb (uint8 oder uint16, sRGB) im Format der Dateiendung, mit EXIF und XMP."""
    endung = os.path.splitext(pfad)[1].lower()
    if endung not in SCHREIBBAR:
        raise BildFehler(f"unbekanntes Format: {endung}")
    format_name, kann_alpha, kann_16 = SCHREIBBAR[endung]
    bits = 16 if rgb.dtype == np.uint16 else 8
    if bits == 16 and not kann_16:
        raise BildFehler(f"{format_name} kann keine 16 Bit speichern")

    if alpha is not None and kann_alpha:
        rgb = np.dstack([rgb, alpha_umrechnen(alpha, bits)])

    try:
        if format_name == "TIFF":
            _tiff_schreiben(pfad, rgb, exif, xmp)
            return
        if bits == 16:
            _png16_schreiben(pfad, rgb, exif, xmp)
            return
        bild = Image.fromarray(rgb, "RGBA" if rgb.shape[2] == 4 else "RGB")
        optionen = {"icc_profile": _srgb_profil().tobytes()}
        if exif:
            optionen["exif"] = exif
        if xmp and format_name == "PNG":
            text = PngImagePlugin.PngInfo()
            text.add_itxt("XML:com.adobe.xmp", xmp.decode("utf-8"))
            optionen["pnginfo"] = text
        elif xmp and format_name in ("JPEG", "WEBP"):
            optionen["xmp"] = xmp
        if format_name == "JPEG":
            optionen.update(quality=qualitaet, subsampling=0)
        elif format_name == "WEBP":
            optionen.update(quality=qualitaet)
        bild.save(pfad, format_name, **optionen)
    except (OSError, ValueError, RuntimeError, KeyError) as fehler:
        raise BildFehler(str(fehler)) from fehler
