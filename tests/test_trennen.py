"""Scan & Film: Fotos von der Scannerplatte trennen."""

from __future__ import annotations

import math

import numpy as np
import pytest

from silberkorn import trennen
from silberkorn.trennen import Foto

# Drei Abzuege, einer gerade, zwei schraeg; (mitte x, mitte y, breite, hoehe, Grad)
LAGEN = ((300, 250, 360, 240, 0.0), (820, 300, 300, 400, 12.0), (450, 720, 420, 280, -25.0))
HOEHE, BREITE = 1000, 1150


def foto_bild(breite, hoehe, nummer):
    """Ein Abzug: farbiger Verlauf, eine fast weisse Flaeche (wie der Deckel) in der Mitte
    und eine rote Ecke oben links - so ist die Lage nach dem Ausschneiden zu pruefen."""
    y, x = np.mgrid[0:hoehe, 0:breite]
    bild = np.stack([0.2 + 0.5 * x / breite, 0.15 + 0.1 * nummer + 0.3 * y / hoehe,
                     np.full(x.shape, 0.35)], -1)
    bild[hoehe // 3:2 * hoehe // 3, breite // 3:2 * breite // 3] = 0.93
    bild[:hoehe // 6, :breite // 6] = (0.9, 0.05, 0.05)
    return bild.astype(np.float32)


def scan():
    """Ein Flachbett-Scan: hellgrauer Deckel mit etwas Rauschen und Staub, darauf die Fotos."""
    zufall = np.random.default_rng(3)
    bild = np.full((HOEHE, BREITE, 3), 0.92, dtype=np.float32)
    bild += zufall.normal(0, 0.005, bild.shape).astype(np.float32)
    bild[500:503, 1000:1003] = 0.1                      # ein Staubkorn
    y, x = np.mgrid[0:HOEHE, 0:BREITE] + 0.5
    for nummer, (mx, my, b, h, grad) in enumerate(LAGEN):
        a = math.radians(grad)
        u = (x - mx) * math.cos(a) + (y - my) * math.sin(a)
        v = -(x - mx) * math.sin(a) + (y - my) * math.cos(a)
        innen = (np.abs(u) < b / 2) & (np.abs(v) < h / 2)
        quelle = foto_bild(b, h, nummer)
        iu = np.clip((u + b / 2).astype(int), 0, b - 1)
        iv = np.clip((v + h / 2).astype(int), 0, h - 1)
        bild[innen] = quelle[iv[innen], iu[innen]]
    return np.clip(bild, 0, 1)


def test_kleinstes_rechteck_eines_gedrehten_rechtecks():
    a = math.radians(30)
    u, v = np.meshgrid(np.arange(-50, 50) + 0.5, np.arange(-20, 20) + 0.5)
    x = 200 + u * math.cos(a) - v * math.sin(a)
    y = 100 + u * math.sin(a) + v * math.cos(a)
    foto = trennen.kleinstes_rechteck(np.stack([x.ravel(), y.ravel()], 1))
    assert foto.mitte_x == pytest.approx(200, abs=0.5)
    assert foto.mitte_y == pytest.approx(100, abs=0.5)
    assert math.degrees(foto.winkel) == pytest.approx(30, abs=0.5)
    assert (foto.breite, foto.hoehe) == pytest.approx((100, 40), abs=1.5)


def test_steile_lage_wird_hoechstens_45_grad_gedreht():
    a = math.radians(70)                    # ein Hochformat, um 20 Grad gegen den Uhrzeiger
    u, v = np.meshgrid(np.arange(-50, 50) + 0.5, np.arange(-20, 20) + 0.5)
    x = u * math.cos(a) - v * math.sin(a)
    y = u * math.sin(a) + v * math.cos(a)
    foto = trennen.kleinstes_rechteck(np.stack([x.ravel(), y.ravel()], 1))
    assert math.degrees(foto.winkel) == pytest.approx(-20, abs=0.5)
    assert (foto.breite, foto.hoehe) == pytest.approx((40, 100), abs=1.5)


def test_leserichtung():
    fotos = [Foto(800, 110, 100, 100, 0), Foto(100, 520, 100, 100, 0),
             Foto(120, 100, 100, 100, 0), Foto(500, 90, 100, 100, 0)]
    assert [(f.mitte_x, f.mitte_y) for f in trennen.leserichtung(fotos)] == [
        (120, 100), (500, 90), (800, 110), (100, 520)]


def test_ausschneiden_mit_numpy():
    bild = scan()
    mx, my, b, h, grad = LAGEN[1]
    teil = trennen.ausschneiden(bild, Foto(mx, my, b - 4, h - 4, math.radians(grad)))
    assert teil.shape == (h - 4, b - 4, 3)
    assert np.allclose(teil[5, 5], (0.9, 0.05, 0.05), atol=0.05)      # rote Ecke oben links
    assert np.allclose(teil[h // 2 - 2, b // 2 - 2], 0.93, atol=0.02)


def test_findet_alle_fotos_auch_schraege():
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    bild = scan()
    fotos = trennen.finden(cp.asarray(bild))
    assert len(fotos) == 3                                   # das Staubkorn zaehlt nicht
    for foto, (mx, my, b, h, grad) in zip(fotos, LAGEN, strict=True):
        assert foto.mitte_x == pytest.approx(mx, abs=3)
        assert foto.mitte_y == pytest.approx(my, abs=3)
        assert math.degrees(foto.winkel) == pytest.approx(grad, abs=1.0)
        assert foto.breite == pytest.approx(b, abs=6) and foto.breite <= b
        assert foto.hoehe == pytest.approx(h, abs=6) and foto.hoehe <= h
        teil = cp.asnumpy(trennen.ausschneiden(cp.asarray(bild), foto))
        assert np.allclose(teil[6, 6], (0.9, 0.05, 0.05), atol=0.08)
        # kein Saum des Deckels an den Raendern
        for rand in (teil[0], teil[-1], teil[:, 0], teil[:, -1]):
            assert (np.abs(rand - 0.92).max(axis=-1) > 0.03).mean() > 0.9


def test_leerer_scan_hat_keine_fotos():
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    assert trennen.finden(cp.full((300, 400, 3), 0.9, dtype=cp.float32)) == []


def test_dateinamen_ueberschreiben_nichts(tmp_path):
    (tmp_path / "Scan-02.tif").write_bytes(b"")
    namen = [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
             for p in trennen.dateinamen(str(tmp_path), "Scan", ".tif", 3)]
    assert namen == ["Scan-01.tif", "Scan-03.tif", "Scan-04.tif"]


def test_sitzung_speichert_jedes_foto(tmp_path):
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    from silberkorn import bilddatei, filter
    from silberkorn.bearbeitung import Sitzung
    daten = bilddatei.Bilddaten(pixel=filter.nach_16bit(scan()), profil=None, alpha=None,
                                exif=b"", pfad="platte.tif")
    s = Sitzung(daten, vorschau_kante=400)
    try:
        fotos = s.fotos_finden()
        assert len(fotos) == 3
        assert s.foto_vorschau(fotos[0]).dtype == np.uint8
        pfade = trennen.dateinamen(str(tmp_path), "platte", ".tif", 3)
        s.fotos_speichern(fotos, pfade, bits=16)
        for pfad, (_mx, _my, b, h, _grad) in zip(pfade, LAGEN, strict=True):
            geladen = bilddatei.laden(pfad)
            assert geladen.bits == 16
            assert abs(geladen.breite - b) <= 8 and abs(geladen.hoehe - h) <= 8
        assert not s.geaendert                       # die Bearbeitung bleibt unberuehrt
    finally:
        s.schliessen()


def test_dialog_waehlt_und_oeffnet():
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from silberkorn.trennen_dialog import TrennenDialog, format_vorgabe
    QApplication.instance() or QApplication([])
    vorschauen = [np.full((40, 60, 3), 100 + 40 * i, dtype=np.uint8) for i in range(3)]
    dialog = TrennenDialog(None, vorschauen, os.path.join("ordner", "platte.jpeg"))
    assert dialog.gewaehlt() == [0, 1, 2] and dialog.danach_oeffnen() == 0
    assert dialog.endung() == ".jpg" and dialog.name() == "platte"
    dialog.kacheln[0].setChecked(False)
    assert dialog.gewaehlt() == [1, 2] and dialog.danach_oeffnen() == 1
    dialog.oeffnen_wahl.setCurrentIndex(0)
    assert dialog.danach_oeffnen() is None
    for kachel in dialog.kacheln:
        kachel.setChecked(False)
    assert not dialog.speichern_knopf.isEnabled()
    assert format_vorgabe("x.bmp") == ".tif" and format_vorgabe("x.TIFF") == ".tif"
