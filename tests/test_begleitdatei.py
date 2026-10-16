"""Begleitdatei: hin und zurueck, und nichts Fremdes wird ungeprueft gelesen."""

import io
import json
import os
import zipfile

import numpy as np
import pytest

from silberkorn import begleitdatei as bd
from silberkorn.filter import Einstellungen

H, W = 40, 60


@pytest.fixture
def bild(tmp_path):
    pfad = tmp_path / "foto.jpg"
    pfad.write_bytes(os.urandom(3 * 2**20))     # groesser als zweimal FINGER_BYTES
    return str(pfad)


def _inhalt() -> bd.Inhalt:
    rng = np.random.default_rng(1)
    inhalt = bd.Inhalt(Einstellungen(belichtung=0.5, ki_schaerfe=40.0), objektivprofil=False)
    inhalt.maske = rng.integers(0, 256, (H, W), dtype=np.uint8)
    inhalt.maske_per_klick = True
    inhalt.tiefe = rng.random((10, 15)).astype(np.float16)
    inhalt.flicken = [bd.Flicken(2, 12, 5, 25, rng.random((10, 20)).astype(np.float16),
                                 rng.random((10, 20, 3)).astype(np.float16))]
    inhalt.staub = bd.Staub(np.array([3, 70, 900], dtype=np.int64),
                            rng.random((3, 3)).astype(np.float32), 2)
    inhalt.erweiterung = bd.Erweiterung(10, 0, 42, 2.0, rng.integers(0, 65535, (H, 80, 3),
                                                                     dtype=np.uint16))
    inhalt.vorschau = b"RIFF-webp"
    return inhalt


def test_hin_und_zurueck(bild):
    inhalt = _inhalt()
    bd.schreiben(bild, inhalt, bd.fingerabdruck(bild), "0.8.0")
    gelesen = bd.lesen(bild, H, W)
    assert gelesen.passt and gelesen.verworfen == []
    assert gelesen.werte == inhalt.werte
    assert np.array_equal(gelesen.maske, inhalt.maske) and gelesen.maske_per_klick
    assert np.array_equal(gelesen.tiefe, inhalt.tiefe)
    f, g = gelesen.flicken[0], inhalt.flicken[0]
    assert (f.y0, f.y1, f.x0, f.x1) == (g.y0, g.y1, g.x0, g.x1)
    assert np.array_equal(f.deckkraft, g.deckkraft) and np.array_equal(f.fuellung, g.fuellung)
    assert np.array_equal(gelesen.staub.stellen, inhalt.staub.stellen)
    assert gelesen.staub.anzahl == 2
    assert np.array_equal(gelesen.erweiterung.rand, inhalt.erweiterung.rand)
    assert (gelesen.erweiterung.x, gelesen.erweiterung.seed) == (10, 42)
    assert gelesen.vorschau == b"RIFF-webp"
    assert bd.vorschau_lesen(bd.pfad_fuer(bild)) == b"RIFF-webp"
    # Keine Zwischendatei bleibt liegen
    assert sorted(os.listdir(os.path.dirname(bild))) == ["foto.jpg", "foto.jpg.silberkorn"]


def test_anderes_bild_nur_werte(bild):
    bd.schreiben(bild, _inhalt(), bd.fingerabdruck(bild))
    with open(bild, "r+b") as datei:
        datei.seek(5)
        datei.write(b"x")
    gelesen = bd.lesen(bild, H, W)
    assert not gelesen.passt
    assert gelesen.werte.belichtung == 0.5
    assert gelesen.maske is None and gelesen.flicken == [] and gelesen.erweiterung is None


def test_andere_bildgroesse_wird_abgelehnt(bild):
    bd.schreiben(bild, _inhalt(), bd.fingerabdruck(bild))
    with pytest.raises(bd.BegleitFehler):
        bd.lesen(bild, H + 1, W)


def test_schreibgeschuetzt(tmp_path):
    with pytest.raises(bd.BegleitFehler):
        bd.schreiben(str(tmp_path / "fehlt" / "foto.jpg"), bd.Inhalt(Einstellungen()),
                     {"groesse": 0, "sha256": ""})


def test_entfernen_nur_dateien(bild):
    assert not bd.entfernen(bild)                  # keine Begleitdatei da
    os.mkdir(bd.pfad_fuer(bild))
    assert not bd.entfernen(bild)                  # ein Ordner wird nicht geloescht
    assert os.path.isdir(bd.pfad_fuer(bild))


# --------------------------------------------------------------------------
# Fremde und kaputte Dateien
# --------------------------------------------------------------------------

def _archiv(bild, teile: dict, kopf: dict | None = None):
    """Eine Begleitdatei von Hand: kopf ergaenzt den gueltigen Kopf."""
    daten = {"kennung": bd.KENNUNG, "format": bd.FORMAT, "original": bd.fingerabdruck(bild),
             "werte": {}}
    daten.update(kopf or {})
    with zipfile.ZipFile(bd.pfad_fuer(bild), "w", zipfile.ZIP_DEFLATED) as archiv:
        archiv.writestr(bd.JSON_NAME, json.dumps(daten))
        for name, inhalt in teile.items():
            archiv.writestr(name, inhalt)


def _npy(array) -> bytes:
    puffer = io.BytesIO()
    np.lib.format.write_array(puffer, array, version=(1, 0), allow_pickle=True)
    return puffer.getvalue()


def test_gueltig_von_hand(bild):
    _archiv(bild, {"maske.npy": _npy(np.zeros((H, W), np.uint8))},
            {"maske": {"per_klick": False}})
    assert bd.lesen(bild, H, W).maske.shape == (H, W)


@pytest.mark.parametrize("teile, kopf", [
    ({"../boese.txt": b"x"}, None),                                 # unerwarteter Name
    ({"maske.npy": _npy(np.zeros((H, W), object))}, {"maske": {"per_klick": False}}),
    ({"maske.npy": _npy(np.zeros((H, W), np.float32))}, {"maske": {"per_klick": False}}),
    ({"maske.npy": _npy(np.zeros((W, H), np.uint8))}, {"maske": {"per_klick": False}}),
    ({"maske.npy": _npy(np.zeros((H, W), np.uint8))[:-5]}, {"maske": {"per_klick": False}}),
    ({}, {"maske": {"per_klick": False}}),                          # Teil fehlt
    ({"tiefe.npy": _npy(np.full((4, 4), np.nan, "<f2"))}, {"tiefe": True}),
    ({}, {"flicken": [[0, 50, 0, 10]]}),                            # ausserhalb des Bildes
    ({}, {"flicken": [[5, 5, 0, 10]]}),                             # leer
    ({}, {"flicken": [["0", 5, 0, 10]]}),
    ({"staub-stellen.npy": _npy(np.array([5, 5], "<i8")),           # doppelt
      "staub-werte.npy": _npy(np.zeros((2, 3), "<f4"))}, {"staub": {"anzahl": 1}}),
    ({"staub-stellen.npy": _npy(np.array([-1], "<i8")),
      "staub-werte.npy": _npy(np.zeros((1, 3), "<f4"))}, {"staub": {"anzahl": 1}}),
    ({"staub-stellen.npy": _npy(np.array([H * W], "<i8")),
      "staub-werte.npy": _npy(np.zeros((1, 3), "<f4"))}, {"staub": {"anzahl": 1}}),
    ({"erweiterung.npy": _npy(np.zeros((H, W * 10, 3), "<u2"))},
     {"erweiterung": {"x": 0, "y": 0, "seed": 1, "verhaeltnis": 2.0}}),
    ({"erweiterung.npy": _npy(np.zeros((H, 80, 3), "<u2"))},
     {"erweiterung": {"x": 30, "y": 0, "seed": 1, "verhaeltnis": 2.0}}),
    ({}, {"kennung": "etwas anderes"}),
    ({}, {"format": 99}),
])
def test_ungueltig(bild, teile, kopf):
    _archiv(bild, teile, kopf)
    with pytest.raises(bd.BegleitFehler):
        bd.lesen(bild, H, W)


def test_json_mit_nan_oder_unendlich(bild):
    with zipfile.ZipFile(bd.pfad_fuer(bild), "w") as archiv:
        archiv.writestr(bd.JSON_NAME, f'{{"kennung": "{bd.KENNUNG}", "format": 1, "werte": '
                        '{"belichtung": NaN}}')
    with pytest.raises(bd.BegleitFehler):
        bd.lesen(bild, H, W)


def test_kein_zip(bild):
    with open(bd.pfad_fuer(bild), "wb") as datei:
        datei.write(b"PK\x03\x04 kaputt")
    with pytest.raises(bd.BegleitFehler):
        bd.lesen(bild, H, W)
    with pytest.raises(bd.BegleitFehler):
        bd.lesen(bild + ".fehlt", H, W)


def test_zip_bombe_liest_nur_was_die_form_verlangt(bild):
    """Ein Array, dessen Kopf eine kleine Form angibt, dem aber Gigabytes folgen: gelesen
    wird nur bis eins hinter die erwartete Laenge - dann ist es zu lang."""
    kopf_und_daten = _npy(np.zeros((H, W), np.uint8)) + b"\0" * (50 * 2**20)
    _archiv(bild, {"maske.npy": kopf_und_daten}, {"maske": {"per_klick": False}})
    assert os.path.getsize(bd.pfad_fuer(bild)) < 2**20      # gepackt winzig
    with pytest.raises(bd.BegleitFehler):
        bd.lesen(bild, H, W)


def test_riesiger_kopf_wird_abgelehnt(bild):
    with zipfile.ZipFile(bd.pfad_fuer(bild), "w", zipfile.ZIP_DEFLATED) as archiv:
        archiv.writestr(bd.JSON_NAME, " " * (bd.MAX_JSON + 10))
    with pytest.raises(bd.BegleitFehler):
        bd.lesen(bild, H, W)


def test_pickle_im_array_wird_nie_ausgefuehrt(bild, tmp_path):
    """Ein .npy mit Objekt-Typ enthielte pickle - schon der Typ wird abgelehnt."""
    marke = tmp_path / "ausgefuehrt"

    class Boese:
        def __reduce__(self):
            return (open, (str(marke), "w"))
    array = np.empty((H, W), dtype=object)
    array[0, 0] = Boese()
    _archiv(bild, {"maske.npy": _npy(array)}, {"maske": {"per_klick": False}})
    with pytest.raises(bd.BegleitFehler):
        bd.lesen(bild, H, W)
    assert not marke.exists()
