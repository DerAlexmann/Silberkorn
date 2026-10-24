"""Monitorprofil: Umrechnung der Anzeige in den Farbraum des Bildschirms."""

from __future__ import annotations

import io
import json
import sys

import numpy as np
import pytest
from PIL import Image, ImageCms
from test_icc import adobe_rgb_profil

from silberkorn import anzeigeprofil, einstellungen, lut


@pytest.fixture(autouse=True)
def ohne_profil():
    """Kein Test hinterlaesst eine eingeschaltete Umrechnung."""
    yield
    anzeigeprofil.setzen(None)


def _srgb_profil() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _lcms(rgb: np.ndarray, profil: bytes) -> np.ndarray:
    """Dieselbe Umrechnung direkt mit LittleCMS - die Referenz."""
    umrechnung = ImageCms.buildTransform(
        ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")),
        ImageCms.ImageCmsProfile(io.BytesIO(profil)), "RGB", "RGB",
        ImageCms.Intent.RELATIVE_COLORIMETRIC)
    return np.asarray(ImageCms.applyTransform(Image.fromarray(rgb), umrechnung))


def _zufall(hoehe: int, breite: int) -> np.ndarray:
    return np.random.default_rng(7).integers(0, 256, (hoehe, breite, 3), dtype=np.uint8)


def test_ohne_profil_bleibt_das_bild_dasselbe():
    rgb = _zufall(8, 8)
    assert anzeigeprofil.aktiv() is None
    assert anzeigeprofil.umrechnen(rgb) is rgb
    assert anzeigeprofil.umrechnen(rgb, gpu=True) is rgb


def test_srgb_profil_wird_erkannt_und_nicht_umgerechnet():
    profil = anzeigeprofil.einrichten(_srgb_profil(), "sRGB.icm")
    assert profil.srgb and profil.name == "sRGB.icm"
    anzeigeprofil.setzen(profil)
    assert anzeigeprofil.aktiv() is None
    rgb = _zufall(8, 8)
    assert anzeigeprofil.umrechnen(rgb) is rgb


def test_adobe_rgb_rechnet_wie_littlecms():
    profil = anzeigeprofil.einrichten(adobe_rgb_profil(), "adobe.icc")
    assert not profil.srgb
    anzeigeprofil.setzen(profil)
    assert anzeigeprofil.aktiv() is profil
    rgb = _zufall(64, 96)
    ergebnis = anzeigeprofil.umrechnen(rgb)
    assert ergebnis.dtype == np.uint8 and ergebnis.shape == rgb.shape
    assert np.array_equal(ergebnis, _lcms(rgb, adobe_rgb_profil()))


def test_adobe_rgb_mischt_ins_gruen_und_laesst_weiss_und_grau():
    """Ein Bildschirm mit grossem Farbraum zeigt sRGB-Gruen mit Rot und Blau darin - sonst
    leuchtete es zu stark; Weiss bleibt Weiss (relativ farbmetrisch), Grau bleibt neutral."""
    anzeigeprofil.setzen(anzeigeprofil.einrichten(adobe_rgb_profil(), "adobe.icc"))
    gruen, weiss, grau = (anzeigeprofil.umrechnen(np.array([[farbe]], dtype=np.uint8))[0, 0]
                          for farbe in ((0, 255, 0), (255, 255, 255), (128, 128, 128)))
    assert gruen[0] > 100 and gruen[1] >= 250 and gruen[2] > 30
    assert np.all(weiss >= 254)
    assert int(grau.max()) - int(grau.min()) <= 1


def test_tabelle_trifft_littlecms():
    """Die 3D-Farbtabelle fuer die Grafikkarte weicht kaum von LittleCMS ab."""
    profil = anzeigeprofil.einrichten(adobe_rgb_profil(), "adobe.icc")
    assert profil.tabelle.groesse == anzeigeprofil.GITTER
    rgb = _zufall(256, 256)
    v = rgb.astype(np.float32) / 255
    tabelle = (np.clip(lut.anwenden(v, profil.tabelle), 0, 1) * 255 + 0.5).astype(np.uint8)
    abstand = np.abs(tabelle.astype(int) - _lcms(rgb, adobe_rgb_profil()))
    assert abstand.max() <= 4 and abstand.mean() < 0.2


def test_alphakanal_und_nicht_zusammenhaengende_pixel():
    anzeigeprofil.setzen(anzeigeprofil.einrichten(adobe_rgb_profil(), "adobe.icc"))
    rgba = np.dstack([_zufall(16, 32), np.full((16, 32), 200, np.uint8)])
    teil = rgba[:, ::2]
    ergebnis = anzeigeprofil.umrechnen(teil)
    assert ergebnis.shape == (16, 16, 3)
    assert np.array_equal(ergebnis, _lcms(np.ascontiguousarray(teil[..., :3]),
                                          adobe_rgb_profil()))


@pytest.mark.parametrize("daten", [b"", b"kein profil" * 20, b"\x00" * 200])
def test_kaputtes_profil_meldet_einen_profilfehler(daten):
    with pytest.raises(anzeigeprofil.ProfilFehler, match="kaputt.icc"):
        anzeigeprofil.einrichten(daten, "kaputt.icc")


def test_zu_grosses_profil_wird_nicht_gelesen():
    with pytest.raises(anzeigeprofil.ProfilFehler):
        anzeigeprofil.einrichten(b"\x00" * (anzeigeprofil.MAX_PROFIL + 1), "riesig.icc")


def test_profil_lesen_ohne_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert anzeigeprofil.profil_lesen(0) is None


def test_profil_lesen_ohne_gemeldetes_profil(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(anzeigeprofil, "_profilpfad", lambda _fenster: None)
    assert anzeigeprofil.profil_lesen(0) is None


def test_profil_lesen_liest_die_datei(monkeypatch, tmp_path):
    pfad = tmp_path / "Breit.icc"
    pfad.write_bytes(adobe_rgb_profil())
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(anzeigeprofil, "_profilpfad", lambda _fenster: str(pfad))
    assert anzeigeprofil.profil_lesen(0) == ("Breit.icc", adobe_rgb_profil())


def test_unlesbare_profildatei_ist_ein_profilfehler(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(anzeigeprofil, "_profilpfad",
                        lambda _fenster: str(tmp_path / "fehlt.icc"))
    with pytest.raises(anzeigeprofil.ProfilFehler, match="fehlt.icc"):
        anzeigeprofil.profil_lesen(0)


@pytest.mark.skipif(sys.platform != "win32", reason="nur unter Windows")
def test_windows_meldet_ein_profil_oder_keines():
    """Mit dem echten Bildschirm: kein Absturz, und ein gemeldetes Profil ist lesbar."""
    from ctypes import windll
    gelesen = anzeigeprofil.profil_lesen(windll.user32.GetDesktopWindow())
    if gelesen is not None:
        name, daten = gelesen
        assert name and daten
        anzeigeprofil.einrichten(daten, name)


def _gpu():
    cp = pytest.importorskip("cupy")
    try:
        cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("keine Grafikkarte")
    from silberkorn import filter_gpu
    return filter_gpu


def test_gpu_gleich_der_tabelle_mit_numpy():
    filter_gpu = _gpu()
    profil = anzeigeprofil.einrichten(adobe_rgb_profil(), "adobe.icc")
    rgb = _zufall(300, 200)
    referenz = (np.clip(lut.anwenden(rgb.astype(np.float32) / 255, profil.tabelle), 0, 1)
                * 255 + 0.5).astype(np.uint8)
    gpu = filter_gpu.anzeige_umrechnen(rgb, profil.tabelle)
    assert np.abs(gpu.astype(int) - referenz).max() <= 1


def test_grosse_bilder_auf_der_gpu_kleine_mit_littlecms(monkeypatch):
    filter_gpu = _gpu()
    profil = anzeigeprofil.einrichten(adobe_rgb_profil(), "adobe.icc")
    anzeigeprofil.setzen(profil)
    aufrufe = []
    echt = filter_gpu.anzeige_umrechnen
    monkeypatch.setattr(filter_gpu, "anzeige_umrechnen",
                        lambda rgb, tabelle: aufrufe.append(rgb.shape) or echt(rgb, tabelle))
    gross = _zufall(1024, 1024)
    ergebnis = anzeigeprofil.umrechnen(gross, gpu=True)
    assert aufrufe == [(1024, 1024, 3)]
    abstand = np.abs(ergebnis.astype(int) - _lcms(gross, adobe_rgb_profil()))
    assert abstand.max() <= 4 and abstand.mean() < 0.2
    anzeigeprofil.umrechnen(gross)                       # ohne gpu: LittleCMS
    anzeigeprofil.umrechnen(_zufall(100, 100), gpu=True)  # zu klein fuer die Grafikkarte
    assert len(aufrufe) == 1


def test_gpu_tabelle_wechselt_mit_dem_profil():
    filter_gpu = _gpu()
    rgb = _zufall(64, 64)
    adobe = anzeigeprofil.einrichten(adobe_rgb_profil(), "adobe.icc")
    srgb = anzeigeprofil.einrichten(_srgb_profil(), "srgb.icm")
    erst = filter_gpu.anzeige_umrechnen(rgb, adobe.tabelle)
    dann = filter_gpu.anzeige_umrechnen(rgb, srgb.tabelle)
    assert not np.array_equal(erst, dann)
    assert np.abs(dann.astype(int) - rgb).max() <= 1


# --------------------------------------------------------------------------
# Gemerkte Einstellung
# --------------------------------------------------------------------------

@pytest.fixture
def datei(tmp_path, monkeypatch):
    pfad = tmp_path / "silberkorn.json"
    monkeypatch.setattr(einstellungen, "config_path", lambda: str(pfad))
    return pfad


def test_einstellung_ist_anfangs_aus_und_merkt_sich(datei):
    assert einstellungen.monitorprofil() is False
    datei.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    assert einstellungen.monitorprofil_setzen(True)
    assert einstellungen.monitorprofil() is True
    assert json.loads(datei.read_text(encoding="utf-8")) == {"theme": "dark",
                                                             "monitorprofil": True}
    assert einstellungen.monitorprofil_setzen(False)
    assert einstellungen.monitorprofil() is False


@pytest.mark.parametrize("wert", ["true", 1, None, [True]])
def test_einstellung_nur_echtes_true(datei, wert):
    datei.write_text(json.dumps({"monitorprofil": wert}), encoding="utf-8")
    assert einstellungen.monitorprofil() is False


def test_grosses_bild_ohne_cupy_rechnet_littlecms(monkeypatch):
    """Ohne Grafikkarte rechnet auch die Leinwand mit LittleCMS - und laedt filter_gpu nicht."""
    from silberkorn import cuda
    monkeypatch.setattr(cuda, "cupy", None)
    monkeypatch.delitem(sys.modules, "silberkorn.filter_gpu", raising=False)
    anzeigeprofil.setzen(anzeigeprofil.einrichten(adobe_rgb_profil(), "adobe.icc"))
    gross = _zufall(1000, 1100)
    assert np.array_equal(anzeigeprofil.umrechnen(gross, gpu=True),
                          _lcms(gross, adobe_rgb_profil()))
    assert "silberkorn.filter_gpu" not in sys.modules


def test_lab_profil_ist_kein_bildschirmprofil():
    lab = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    with pytest.raises(anzeigeprofil.ProfilFehler):
        anzeigeprofil.einrichten(lab, "lab.icc")


def test_littlecms_fehler_zeigt_srgb(monkeypatch):
    anzeigeprofil.setzen(anzeigeprofil.einrichten(adobe_rgb_profil(), "adobe.icc"))

    def kaputt(*_a):
        raise ImageCms.PyCMSError("kaputt")

    monkeypatch.setattr(ImageCms, "applyTransform", kaputt)
    rgb = _zufall(8, 8)
    assert np.array_equal(anzeigeprofil.umrechnen(rgb), rgb)


def test_voller_grafikspeicher_rechnet_littlecms(monkeypatch):
    filter_gpu = _gpu()
    import cupy
    anzeigeprofil.setzen(anzeigeprofil.einrichten(adobe_rgb_profil(), "adobe.icc"))

    def voll(*_a):
        raise cupy.cuda.memory.OutOfMemoryError(1, 0)

    monkeypatch.setattr(filter_gpu, "anzeige_umrechnen", voll)
    gross = _zufall(1024, 1024)
    assert np.array_equal(anzeigeprofil.umrechnen(gross, gpu=True),
                          _lcms(gross, adobe_rgb_profil()))


def test_windows_fehler_gilt_als_kein_profil(monkeypatch):
    import ctypes
    monkeypatch.setattr(sys, "platform", "win32")

    def fehler(_fenster):
        raise ctypes.ArgumentError("falsches Handle")

    monkeypatch.setattr(anzeigeprofil, "_profilpfad", fehler)
    assert anzeigeprofil.profil_lesen(0) is None
