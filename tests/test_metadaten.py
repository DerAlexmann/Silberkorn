"""Metadaten: lesen aus EXIF, IPTC und XMP, aendern, beim Speichern schreiben."""

from __future__ import annotations

import struct

import numpy as np
import pytest
from PIL import Image

from silberkorn import bilddatei, metadaten
from silberkorn.metadaten import Angaben

GPS_IFD, EXIF_IFD = 0x8825, 0x8769

XMP_QUELLE = b"""<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:tiff="http://ns.adobe.com/tiff/1.0/"
    xmlns:exif="http://ns.adobe.com/exif/1.0/"
    xmlns:aux="http://ns.adobe.com/exif/1.0/aux/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
    tiff:Orientation="6" crs:Exposure2012="+0.50" photoshop:City="Bremen"
    xmpMM:DocumentID="xmp.did:1234">
   <dc:title><rdf:Alt><rdf:li xml:lang="de">Hafen</rdf:li>
     <rdf:li xml:lang="x-default">Harbour</rdf:li></rdf:Alt></dc:title>
   <dc:subject><rdf:Bag><rdf:li>Schiff</rdf:li><rdf:li>Wasser</rdf:li></rdf:Bag></dc:subject>
   <exif:GPSLatitude>53,5.0N</exif:GPSLatitude>
   <aux:SerialNumber>12345</aux:SerialNumber>
   <crs:ToneCurve><rdf:Seq><rdf:li>0, 0</rdf:li></rdf:Seq></crs:ToneCurve>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""


def kamera_exif() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Testwerk"
    exif[0x0110] = "Testwerk Z 7"
    exif[0x013B] = "Kamera Besitzer"
    exif[0x010E] = "OLYMPUS DIGITAL CAMERA"            # kein echter Text
    unter = exif.get_ifd(EXIF_IFD)
    unter[0x829A] = 0.004                               # 1/250 s
    unter[0x829D] = 8.0
    unter[0x8827] = 200
    unter[0x920A] = 35.0
    unter[0x9003] = "2024:05:17 14:30:05"
    unter[0xA002], unter[0xA003] = 4000, 3000
    exif.get_ifd(GPS_IFD)[2] = (52.0, 31.0, 0.0)
    return exif.tobytes()


def iim_block(felder: dict) -> dict:
    """IPTC-IIM so, wie iim_lesen es liefert."""
    return {schluessel: list(werte) for schluessel, werte in felder.items()}


def lese(exif=b"", xmp=b"", iptc=None) -> Angaben:
    return metadaten.lesen(exif, xmp, iptc or {}).angaben


# --------------------------------------------------------------------------
# Eingaben
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text, erwartet", [
    ("", ""), ("1965", "1965"), ("1965-7", "1965-07"), ("2024-05-17", "2024-05-17"),
    ("2024:05:17 14:30:05", "2024-05-17 14:30:05"), ("17.05.2024", "2024-05-17"),
    ("17.5.2024 9:05", "2024-05-17 09:05"), ("2024-05-17T14:30:05+02:00", "2024-05-17 14:30:05"),
    ("2024-02-30", None), ("Sommer", None), ("0000:00:00 00:00:00", None),
])
def test_datum_lesen(text, erwartet):
    assert metadaten.datum_lesen(text) == erwartet


def test_stichwoerter_ohne_doppelte():
    assert metadaten.stichwoerter_lesen("Berlin, Herbst; berlin,, Familie ") == (
        "Berlin", "Herbst", "Familie")


def test_aenderungen_nur_was_abweicht():
    basis = Angaben(titel="A")
    aenderungen = metadaten.aendern((), basis, "titel", "B")
    assert aenderungen == (("titel", "B"),)
    assert metadaten.mit(basis, aenderungen).titel == "B"
    assert metadaten.aendern(aenderungen, basis, "titel", "A") == ()


# --------------------------------------------------------------------------
# Lesen
# --------------------------------------------------------------------------

def test_lesen_aus_exif():
    angaben = lese(kamera_exif())
    assert angaben.urheber == "Kamera Besitzer"
    assert angaben.beschreibung == ""                   # Kamera-Platzhalter zaehlt nicht
    assert angaben.datum == "2024-05-17 14:30:05"


def test_xmp_vor_iptc_vor_exif():
    iptc = iim_block({(1, 90): [b"\x1b%G"], (2, 80): ["Jörg".encode()],
                      (2, 5): [b"IIM-Titel"], (2, 101): [b"Deutschland"],
                      (2, 55): [b"19650701"]})
    vorgefunden = metadaten.lesen(kamera_exif(), XMP_QUELLE, iptc)
    angaben = vorgefunden.angaben
    assert angaben.titel == "Harbour"                   # XMP, Sprachvariante x-default
    assert angaben.urheber == "Jörg"                    # IPTC vor EXIF
    assert angaben.land == "Deutschland" and angaben.stadt == "Bremen"
    assert angaben.stichwoerter == ("Schiff", "Wasser")
    assert angaben.datum == "1965-07-01"
    assert dict(vorgefunden.herkunft)["titel"] == "xmp"
    assert vorgefunden.formate == ("EXIF", "IPTC", "XMP")


def test_unsicheres_xmp_wird_nicht_gelesen():
    boese = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>' + XMP_QUELLE
    assert lese(xmp=boese) == Angaben()


def test_ueberblick():
    kurz = metadaten.ueberblick(kamera_exif())
    assert kurz["kamera"] == "Testwerk Z 7"             # Hersteller nicht doppelt
    assert kurz["belichtung"] == "1/250 s · f/8 · ISO 200 · 35 mm"


def test_eintraege_zeigen_alles():
    eintraege = metadaten.eintraege(kamera_exif(), XMP_QUELLE, {(2, 5): [b"Titel"]})
    gruppen = {gruppe for gruppe, _name, _wert in eintraege}
    assert gruppen == {"EXIF", "GPS", "IPTC", "XMP"}
    namen = {name for _gruppe, name, _wert in eintraege}
    assert {"Model", "ExposureTime", "ObjectName", "dc:title", "photoshop:City"} <= namen


# --------------------------------------------------------------------------
# Schreiben
# --------------------------------------------------------------------------

def test_exif_bekommt_aenderungen_und_groesse():
    angaben = Angaben(urheber="Jörg Müller", copyright="© 2026 Jörg", datum="1965",
                      bewertung=4, beschreibung="Am Hafen")
    roh = metadaten.exif_schreiben(kamera_exif(), angaben,
                                   {"urheber", "copyright", "datum", "bewertung", "beschreibung"},
                                   1200, 900)
    exif = metadaten.exif_laden(roh)
    unter = exif.get_ifd(EXIF_IFD)
    assert exif[0x013B] == "Jorg Muller" and exif[0x8298] == "(C) 2026 Jorg"
    assert exif[0x010E] == "Am Hafen" and exif[0x4746] == 4
    assert 0x9003 not in unter                          # nur ein Jahr: kein EXIF-Datum
    assert (unter[0xA002], unter[0xA003]) == (1200, 900)
    assert exif.get(0x0110) == "Testwerk Z 7"           # Unveraendertes bleibt


def test_exif_ohne_vorher():
    roh = metadaten.exif_schreiben(b"", Angaben(datum="2001-02-03"), {"datum"})
    assert metadaten.exif_laden(roh).get_ifd(EXIF_IFD)[0x9003] == "2001:02:03 00:00:00"
    assert metadaten.exif_schreiben(b"", Angaben(), {"titel"}) == b""


def test_xmp_wird_bereinigt_weitergegeben():
    vorgefunden = metadaten.lesen(b"", XMP_QUELLE, {})
    _exif, xmp = metadaten.fuer_speichern(b"", XMP_QUELLE, vorgefunden, (), 10, 10)
    text = xmp.decode()
    # Drehung und Entwicklungseinstellungen stimmen nach der Bearbeitung nicht mehr
    assert "Orientation" not in text and "crs:" not in text and "Exposure2012" not in text
    assert "xmp.did:1234" in text and "Hafen" in text and "Bremen" in text
    assert "GPSLatitude" in text                       # ohne Anonymisieren bleibt es
    _exif, xmp = metadaten.fuer_speichern(b"", XMP_QUELLE, vorgefunden, (), 10, 10,
                                          bereinigen=True)
    assert b"GPSLatitude" not in xmp and b"SerialNumber" not in xmp


XMP_DROHNE = b"""<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/"
    xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"
    xmlns:exif="http://ns.adobe.com/exif/1.0/"
    drone-dji:GpsLatitude="53.123456" drone-dji:GpsLongtitude="8.654321"
    drone-dji:AbsoluteAltitude="+120.5">
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Vom Deich</rdf:li></rdf:Alt></dc:title>
   <drone-dji:SerialNumber>XYZ</drone-dji:SerialNumber>
   <Iptc4xmpExt:LocationCreated><rdf:Bag><rdf:li rdf:parseType="Resource">
     <Iptc4xmpExt:City>Bremen</Iptc4xmpExt:City>
     <exif:GPSLatitude>53,7.4N</exif:GPSLatitude>
   </rdf:li></rdf:Bag></Iptc4xmpExt:LocationCreated>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"""


def test_bereinigen_laesst_nur_beschreibendes():
    """GPS in Herstellerfeldern (DJI) und verschachtelt in IPTC-Orten faellt weg."""
    vorgefunden = metadaten.lesen(b"", XMP_DROHNE, {})
    _exif, ohne = metadaten.fuer_speichern(b"", XMP_DROHNE, vorgefunden, (), 10, 10,
                                           bereinigen=True)
    for spur in (b"53.123456", b"8.654321", b"120.5", b"XYZ", b"drone-dji", b"GPSLatitude"):
        assert spur not in ohne
    assert b"Vom Deich" in ohne and b"Bremen" in ohne
    _exif, mit = metadaten.fuer_speichern(b"", XMP_DROHNE, vorgefunden, (), 10, 10)
    assert b"53.123456" in mit                         # ohne die Option bleibt es


def test_xmp_aenderung_ersetzt_alle_sprachvarianten():
    vorgefunden = metadaten.lesen(b"", XMP_QUELLE, {})
    aenderungen = metadaten.aendern((), vorgefunden.angaben, "titel", "Neuer Titel")
    _exif, xmp = metadaten.fuer_speichern(b"", XMP_QUELLE, vorgefunden, aenderungen, 10, 10)
    neu = lese(xmp=xmp)
    assert neu.titel == "Neuer Titel" and b"Hafen" not in xmp
    assert neu.stichwoerter == ("Schiff", "Wasser")


def test_iptc_wandert_nach_xmp():
    iptc = iim_block({(2, 120): [b"Nur in IIM"], (2, 25): [b"eins", b"zwei"]})
    vorgefunden = metadaten.lesen(b"", b"", iptc)
    _exif, xmp = metadaten.fuer_speichern(b"", b"", vorgefunden, (), 10, 10)
    neu = lese(xmp=xmp)
    assert neu.beschreibung == "Nur in IIM" and neu.stichwoerter == ("eins", "zwei")


def test_ohne_angaben_kein_xmp():
    vorgefunden = metadaten.lesen(kamera_exif(), b"", {})
    _exif, xmp = metadaten.fuer_speichern(kamera_exif(), b"", vorgefunden, (), 10, 10)
    assert xmp == b""


def test_raw_exif_ohne_aufbau_und_herstellernotiz():
    exif = Image.Exif()
    exif[0x0110] = "Kamera"
    exif[0x0111] = 4096                                 # StripOffsets der RAW
    exif[0x014A] = 1234                                 # SubIFDs
    exif[0x0112] = 6
    exif.get_ifd(EXIF_IFD)[0x927C] = b"\x00" * 300
    exif.get_ifd(EXIF_IFD)[0x829A] = 0.01
    sauber = metadaten.exif_laden(metadaten.saeubern(metadaten.exif_laden(exif.tobytes()),
                                                     raw=True))
    assert dict(sauber) .keys() >= {0x0110, 0x0112} and 0x0111 not in sauber
    assert 0x014A not in sauber and sauber[0x0112] == 1
    assert 0x927C not in sauber.get_ifd(EXIF_IFD) and 0x829A in sauber.get_ifd(EXIF_IFD)


# --------------------------------------------------------------------------
# Alle Formate: Kameradaten bleiben, Angaben kommen an
# --------------------------------------------------------------------------

def jpeg_mit_iim(pfad, felder: dict):
    """JPEG mit IPTC-IIM im Photoshop-Block (APP13) - so schreiben es Bridge und Co."""
    iim = b"".join(b"\x1c" + bytes(k) + struct.pack(">H", len(w)) + w
                   for k, werte in felder.items() for w in werte)
    if len(iim) % 2:
        iim += b"\x00"
    block = b"Photoshop 3.0\x00" + b"8BIM\x04\x04\x00\x00" + struct.pack(">I", len(iim)) + iim
    roh = open(pfad, "rb").read()
    with open(pfad, "wb") as datei:
        datei.write(roh[:2] + b"\xff\xed" + struct.pack(">H", len(block) + 2) + block + roh[2:])


@pytest.mark.parametrize("endung, bits", [(".jpg", 8), (".png", 8), (".png", 16), (".tif", 8),
                                          (".tif", 16), (".webp", 8), (".avif", 8)])
def test_speichern_in_allen_formaten(tmp_path, endung, bits):
    quelle = tmp_path / "quelle.jpg"
    Image.new("RGB", (40, 30), (120, 90, 60)).save(quelle, exif=kamera_exif(), xmp=XMP_QUELLE)
    jpeg_mit_iim(quelle, {(2, 120): [b"Aus IIM"]})
    daten = bilddatei.laden(str(quelle))
    vorgefunden = metadaten.lesen(daten.exif, daten.xmp, daten.iptc)
    assert vorgefunden.formate == ("EXIF", "IPTC", "XMP")
    aenderungen = metadaten.aendern((), vorgefunden.angaben, "urheber", "Jörg; Ana")
    aenderungen = metadaten.aendern(aenderungen, vorgefunden.angaben, "bewertung", 3)
    exif, xmp = metadaten.fuer_speichern(daten.exif, daten.xmp, vorgefunden, aenderungen,
                                         40, 30, bereinigen=True)

    ziel = str(tmp_path / f"ziel{endung}")
    rgb = np.full((30, 40, 3), 30000 if bits == 16 else 120,
                  np.uint16 if bits == 16 else np.uint8)
    bilddatei.speichern(ziel, rgb, None, exif, xmp)
    zurueck = bilddatei.laden(ziel)
    gelesen = metadaten.lesen(zurueck.exif, zurueck.xmp, zurueck.iptc)
    kamera = metadaten.exif_laden(zurueck.exif)
    assert kamera.get(0x0110) == "Testwerk Z 7"
    assert GPS_IFD not in kamera or not kamera.get_ifd(GPS_IFD)
    assert gelesen.angaben.urheber == "Jörg; Ana"
    assert gelesen.angaben.bewertung == 3
    assert gelesen.angaben.titel == "Harbour"           # unveraendert aus dem XMP
    assert gelesen.angaben.beschreibung == "Aus IIM"    # aus IPTC nach XMP gewandert
    assert gelesen.angaben.datum == "2024-05-17 14:30:05"
    assert b"Orientation" not in zurueck.xmp and b"GPSLatitude" not in zurueck.xmp
    with Image.open(ziel) as bild:
        assert bild.size == (40, 30)
    if endung == ".tif":
        unter = kamera.get_ifd(EXIF_IFD)
        assert abs(float(unter[0x829A]) - 0.004) < 1e-9 and unter[0x8827] == 200


# --------------------------------------------------------------------------
# Sitzung: Aenderungen zaehlen, Vorgaben, Zuruecksetzen
# --------------------------------------------------------------------------

@pytest.fixture
def sitzung():
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    from silberkorn.bearbeitung import Sitzung
    pixel = np.full((60, 80, 3), 100, np.uint8)
    daten = bilddatei.Bilddaten(pixel=pixel, profil=None, alpha=None, exif=kamera_exif(),
                                pfad="t.jpg", xmp=XMP_QUELLE)
    s = Sitzung(daten, vorschau_kante=40)
    yield s
    s.schliessen()


def test_sitzung_angaben(sitzung, tmp_path):
    assert not sitzung.geaendert and sitzung.angaben.titel == "Harbour"
    sitzung.angabe_setzen("titel", "Neu")
    assert sitzung.geaendert and sitzung.angaben.titel == "Neu"
    sitzung.angabe_setzen("titel", "Harbour")
    assert not sitzung.geaendert

    # Vorgabe nur fuer, was die Datei nicht hat - und sie zaehlt nicht als Aenderung
    sitzung.angaben_vorgeben("Alex", "© 2026 Alex")
    assert sitzung.angaben.copyright == "© 2026 Alex"
    assert sitzung.angaben.urheber == "Kamera Besitzer"
    assert not sitzung.geaendert
    sitzung.angabe_setzen("land", "Island")
    assert sitzung.grundwerte().angaben == sitzung.angaben_grundwerte() == (
        ("copyright", "© 2026 Alex"),)

    pfad = str(tmp_path / "aus.jpg")
    sitzung.exportieren(pfad)
    assert not sitzung.geaendert
    zurueck = bilddatei.laden(pfad)
    angaben = metadaten.lesen(zurueck.exif, zurueck.xmp, zurueck.iptc).angaben
    assert angaben.land == "Island" and angaben.copyright == "© 2026 Alex"
    assert metadaten.exif_laden(zurueck.exif)[0x8298] == "(C) 2026 Alex"


def test_metadaten_rechnen_das_bild_nicht_neu(sitzung):
    erstes = sitzung.ausschnitt(0, 0, 10, 10)
    bild = sitzung._vollbild[1]
    sitzung.angabe_setzen("titel", "Anders")
    sitzung.werte.metadaten_entfernen = True
    sitzung.ausschnitt(0, 0, 10, 10)
    assert sitzung._vollbild[1] is bild and erstes[0].shape == (10, 10, 3)


def test_fuers_netz_mit_angaben(sitzung, tmp_path):
    from silberkorn.veroeffentlichen import Vorlage
    sitzung.angabe_setzen("stichwoerter", ("Hafen", "Abend"))
    sitzung.angabe_setzen("stadt", "Kiel")
    pfad = str(tmp_path / "netz.jpg")
    sitzung.veroeffentlichen(pfad, Vorlage(kante=40, urheber="", copyright=""))
    with Image.open(pfad) as bild:
        xmp = metadaten.xmp_aus_bild(bild)
        exif = bild.getexif()
    angaben = lese(xmp=xmp)
    assert angaben.stichwoerter == ("Hafen", "Abend") and angaben.urheber == "Kamera Besitzer"
    assert angaben.stadt == ""                          # Kameradaten entfernt: kein Ort
    assert exif[0x013B] == "Kamera Besitzer"
