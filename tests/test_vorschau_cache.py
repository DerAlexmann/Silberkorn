"""Vorschau-Cache: vorbelegt, gedeckelt, verschluesselt, und geloescht ist geloescht.
DPAPI gibt es nur unter Windows - anderswo gibt es keinen Cache, und die Tests entfallen."""

import os
import sqlite3

import pytest

from silberkorn import dpapi
from silberkorn import vorschau_cache as vc

pytestmark = pytest.mark.skipif(not dpapi.verfuegbar(), reason="DPAPI nur unter Windows")

MB = 2**20


@pytest.fixture
def ordner(tmp_path):
    return tmp_path


def _bild(ordner, name="bild.tif", inhalt=b"x" * 100):
    pfad = ordner / name
    pfad.write_bytes(inhalt)
    return str(pfad)


def test_dpapi_hin_und_zurueck():
    geheim = dpapi.schuetzen(b"vertraulich", b"zweck")
    assert b"vertraulich" not in geheim
    assert dpapi.oeffnen(geheim, b"zweck") == b"vertraulich"
    with pytest.raises(dpapi.DpapiFehler):
        dpapi.oeffnen(geheim, b"anderer zweck")
    kaputt = bytearray(geheim)
    kaputt[-3] ^= 0xFF
    with pytest.raises(dpapi.DpapiFehler):
        dpapi.oeffnen(bytes(kaputt), b"zweck")


def test_vorbelegt_und_gedeckelt(ordner):
    pfad = str(ordner / vc.DATEINAME)
    cache = vc.VorschauCache(pfad, 16 * MB)
    try:
        groesse = os.path.getsize(pfad)
        assert 15 * MB < groesse <= 16 * MB              # gleich belegt
        for nummer in range(1600):                       # mehr, als hineinpasst
            assert cache.ablegen(_bild(ordner, f"b{nummer}.tif", b"y"), os.urandom(12000))
        assert os.path.getsize(pfad) <= 16 * MB          # nie groesser als gewaehlt
        assert 0 < cache.anzahl() < 1600                 # die aeltesten sind gewichen
        assert cache.holen(str(ordner / "b1599.tif")) is not None
        assert cache.holen(str(ordner / "b0.tif")) is None
    finally:
        cache.schliessen()


def test_nichts_im_klartext(ordner):
    pfad = str(ordner / vc.DATEINAME)
    bild = _bild(ordner, "Geheimer_Ordnername_Arzt.tif")
    cache = vc.VorschauCache(pfad, 16 * MB)
    try:
        cache.ablegen(bild, b"RIFF0000WEBPVP8 " + b"sichtbare-bilddaten" * 50)
        assert cache.holen(bild).startswith(b"RIFF0000WEBP")
    finally:
        cache.schliessen()
    roh = open(pfad, "rb").read()
    assert b"sichtbare-bilddaten" not in roh and b"WEBP" not in roh
    assert b"Geheimer_Ordnername" not in roh
    assert "Geheimer_Ordnername".encode("utf-16-le") not in roh


def test_geloescht_ist_geloescht(ordner):
    """Nach Leeren steht auch der verschluesselte Inhalt nicht mehr in der Datei."""
    pfad = str(ordner / vc.DATEINAME)
    bild = _bild(ordner)
    cache = vc.VorschauCache(pfad, 16 * MB)
    try:
        cache.ablegen(bild, b"inhalt" * 2000)
        verschluesselt = bytes(cache._db.execute("SELECT daten FROM bilder").fetchone()[0])
        # Ein grosses Bild liegt ueber mehrere Seiten verteilt - Stuecke daraus suchen, nach
        # dem Kopf, den jede DPAPI-Verschluesselung gleich traegt (auch das Geheimnis)
        stuecke = [verschluesselt[i:i + 24] for i in range(100, len(verschluesselt) - 24, 500)]
        roh = open(pfad, "rb").read()
        assert sum(stueck in roh for stueck in stuecke) > len(stuecke) // 2
        cache.leeren()
        assert cache.anzahl() == 0
    finally:
        cache.schliessen()
    roh = open(pfad, "rb").read()
    assert not any(stueck in roh for stueck in stuecke)


def test_geaendertes_bild_ist_ein_fehlgriff(ordner):
    pfad = str(ordner / vc.DATEINAME)
    bild = _bild(ordner)
    cache = vc.VorschauCache(pfad, 16 * MB)
    try:
        cache.ablegen(bild, b"alt")
        with open(bild, "ab") as datei:
            datei.write(b"mehr")
        assert cache.holen(bild) is None
        assert cache.anzahl() == 0
    finally:
        cache.schliessen()


def test_aufraeumen_entfernt_verwaiste(ordner):
    pfad = str(ordner / vc.DATEINAME)
    bleibt, weg = _bild(ordner, "a.tif"), _bild(ordner, "b.tif")
    cache = vc.VorschauCache(pfad, 16 * MB)
    try:
        cache.ablegen(bleibt, b"a")
        cache.ablegen(weg, b"b")
        os.remove(weg)
        assert cache.aufraeumen() == 0
        assert cache.anzahl() == 1 and cache.holen(bleibt) == b"a"
    finally:
        cache.schliessen()


def test_fremdes_geheimnis_wird_verworfen(ordner):
    """Laesst sich das Geheimnis nicht oeffnen - anderer Benutzer, kopierte Datei -, wird
    der Cache neu angelegt; alte Eintraege sind weg."""
    pfad = str(ordner / vc.DATEINAME)
    bild = _bild(ordner)
    cache = vc.VorschauCache(pfad, 16 * MB)
    cache.ablegen(bild, b"alt")
    cache.schliessen()
    db = sqlite3.connect(pfad)
    db.execute("UPDATE meta SET wert = ? WHERE name = 'geheimnis'", (b"fremd" * 40,))
    db.commit()
    db.close()
    cache = vc.VorschauCache(pfad, 16 * MB)
    try:
        assert cache.anzahl() == 0 and cache.holen(bild) is None
    finally:
        cache.schliessen()


def test_kein_sqlite_wird_ersetzt(ordner):
    pfad = ordner / vc.DATEINAME
    pfad.write_bytes(b"irgendetwas")
    cache = vc.VorschauCache(str(pfad), 16 * MB)
    cache.schliessen()
    assert os.path.getsize(pfad) > 15 * MB


def test_kleiner_und_groesser(ordner):
    pfad = str(ordner / vc.DATEINAME)
    vc.VorschauCache(pfad, 32 * MB).schliessen()
    vc.anlegen(pfad, 16 * MB).schliessen()
    assert os.path.getsize(pfad) <= 16 * MB
    vc.anlegen(pfad, 24 * MB).schliessen()
    assert 23 * MB < os.path.getsize(pfad) <= 24 * MB


def test_zu_wenig_platz(ordner, monkeypatch):
    monkeypatch.setattr(vc, "platz_frei", lambda _ordner: 8 * MB)
    with pytest.raises(vc.CacheFehler):
        vc.VorschauCache(str(ordner / vc.DATEINAME), 16 * MB)
    assert not os.path.exists(ordner / vc.DATEINAME)


def test_entfernen(ordner):
    pfad = str(ordner / vc.DATEINAME)
    vc.VorschauCache(pfad, 16 * MB).schliessen()
    vc.entfernen(pfad)
    assert not os.path.exists(pfad)


def test_ausgenommen(ordner):
    innen = ordner / "privat" / "tief"
    innen.mkdir(parents=True)
    bild = _bild(innen)
    assert vc.ausgenommen(bild, [str(ordner / "privat")])
    assert vc.ausgenommen(bild, [str(ordner / "PRIVAT")]) == (os.name == "nt")
    assert not vc.ausgenommen(bild, [str(ordner / "priv")])     # kein blosser Praefix
    assert not vc.ausgenommen(bild, [])
