"""Vorschaubilder fuer die Ordneransicht - Formate, Ausrichtung, Grenzen."""

import numpy as np
import pytest
import tifffile
from PIL import Image

from silberkorn import begleitdatei
from silberkorn import vorschaubilder as vb
from silberkorn.filter import Einstellungen


def test_jpeg_mit_ausrichtung(tmp_path):
    pfad = tmp_path / "hoch.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6                                      # 90 Grad im Uhrzeigersinn
    Image.new("RGB", (600, 400), (200, 30, 30)).save(pfad, exif=exif)
    vorschau = vb.erzeugen(str(pfad))
    assert vorschau.bild.size == (171, 256)               # hochkant gedreht
    assert not vorschau.bearbeitet


def test_avif_mit_ausrichtung(tmp_path):
    pfad = tmp_path / "hoch.avif"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (600, 400), (30, 200, 30)).save(pfad, exif=exif)
    assert vb.ist_bild(pfad.name)
    assert vb.erzeugen(str(pfad)).bild.size == (171, 256)


def test_tiff_16_bit_rgbi(tmp_path):
    pfad = tmp_path / "scan.tif"
    pixel = np.zeros((300, 500, 4), np.uint16)
    pixel[..., 0] = 65535
    tifffile.imwrite(pfad, pixel, photometric="rgb", extrasamples=[0])
    bild = vb.erzeugen(str(pfad)).bild
    assert max(bild.size) <= vb.KANTE
    assert np.asarray(bild)[5, 5].tolist() == [255, 0, 0]


def test_png_16_bit(tmp_path):
    pfad = tmp_path / "tief.png"
    import imagecodecs
    pfad.write_bytes(imagecodecs.png_encode(np.full((50, 80, 3), 40000, np.uint16)))
    assert np.asarray(vb.erzeugen(str(pfad)).bild)[0, 0].tolist() == [156, 156, 156]


def test_kaputte_datei(tmp_path):
    pfad = tmp_path / "kaputt.jpg"
    pfad.write_bytes(b"\xff\xd8 kein jpeg")
    with pytest.raises(vb.VorschauFehler):
        vb.erzeugen(str(pfad))


def test_riesige_angabe_wird_nicht_dekodiert(tmp_path, monkeypatch):
    monkeypatch.setattr(vb, "MAX_PIXEL", 100)
    pfad = tmp_path / "gross.png"
    Image.new("RGB", (20, 20)).save(pfad)
    with pytest.raises(vb.VorschauFehler):
        vb.erzeugen(str(pfad))


def test_aus_begleitdatei(tmp_path):
    pfad = tmp_path / "foto.jpg"
    Image.new("RGB", (64, 48), (0, 0, 255)).save(pfad)
    assert vb.aus_begleitdatei(str(pfad)) is None
    klein = vb.kodieren(Image.new("RGB", (32, 24), (0, 255, 0)))
    inhalt = begleitdatei.Inhalt(Einstellungen(kontrast=10.0), vorschau=klein)
    begleitdatei.schreiben(str(pfad), inhalt, begleitdatei.fingerabdruck(str(pfad)))
    bild = vb.aus_begleitdatei(str(pfad))
    assert bild is not None and bild.size == (32, 24)
    # Passt die Groesse nicht mehr, gehoert die Vorschau zu einem anderen Bild
    Image.new("RGB", (70, 48), (0, 0, 255)).save(pfad)
    assert vb.aus_begleitdatei(str(pfad)) is None


def test_zu_grosses_webp_wird_abgelehnt():
    daten = vb.kodieren(Image.new("RGB", (vb.MAX_VORSCHAU_KANTE + 1, 10)))
    with pytest.raises(vb.VorschauFehler):
        vb.dekodieren(daten)
    with pytest.raises(vb.VorschauFehler):
        vb.dekodieren(b"\x89PNG kein webp")
