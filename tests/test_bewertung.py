"""Bewertung: Sterne und Ausschuss in der XMP-Begleitdatei neben dem Bild.

Die Datei ist eine fremde Eingabe: bosartige oder kaputte Inhalte ergeben keine Bewertung,
eine fremde XMP-Datei (darktable) bleibt Byte fuer Byte unberuehrt, und nichts loescht ein Bild.
"""

from __future__ import annotations

import json
import os
import re

import pytest
from PIL import Image

from silberkorn import bewertung, einstellungen, metadaten
from silberkorn.bewertung import Stand


def _bild(ordner, name="foto.jpg") -> str:
    pfad = ordner / name
    Image.new("RGB", (8, 6), (90, 120, 150)).save(pfad)
    return str(pfad)


def _xmp(rating: str = "3", rest: str = "") -> bytes:
    """Eine Datei im Stil von darktable: Rating als Attribut, dazu Verlauf und mehr."""
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
        '    xmlns:darktable="http://darktable.sf.net/" xmp:Rating="' + rating + '"\n'
        '    darktable:xmp_version="5">' + rest + '</rdf:Description>\n'
        ' </rdf:RDF>\n</x:xmpmeta>\n<?xpacket end="w"?>\n').encode("utf-8")


# --------------------------------------------------------------------------
# Eigene Datei
# --------------------------------------------------------------------------

@pytest.mark.parametrize("wert", [-1, 0, 1, 2, 3, 4, 5])
def test_schreiben_und_lesen(tmp_path, wert):
    bild = _bild(tmp_path)
    assert bewertung.lesen(bild) == Stand(0, "keine")
    bewertung.schreiben(bild, wert)
    assert bewertung.lesen(bild) == Stand(wert, "eigen")
    assert os.path.basename(bewertung.pfad_fuer(bild)) == "foto.jpg.xmp"


def test_inhalt_ist_feste_vorlage_mit_kennung(tmp_path):
    bild = _bild(tmp_path)
    bewertung.schreiben(bild, 4)
    text = (tmp_path / "foto.jpg.xmp").read_text(encoding="utf-8")
    assert 'xmp:Rating="4"' in text and 'xmp:CreatorTool="Silberkorn"' in text
    assert "sk:Kennung" in text and "DOCTYPE" not in text
    # Nur diese eine Zahl ist veraenderlich
    assert re.sub(r'Rating="4"', 'Rating="X"', text) == \
        bewertung.VORLAGE.format(wert="X")


def test_ueberschreiben_eigener_datei_und_keine_reste(tmp_path):
    bild = _bild(tmp_path)
    bewertung.schreiben(bild, 2)
    bewertung.schreiben(bild, 5)
    assert bewertung.lesen(bild) == Stand(5, "eigen")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["foto.jpg", "foto.jpg.xmp"]


@pytest.mark.parametrize("wert", [6, -2, 99, 3.0, "3", None, True])
def test_schreiben_lehnt_falsche_werte_ab(tmp_path, wert):
    bild = _bild(tmp_path)
    with pytest.raises(ValueError):
        bewertung.schreiben(bild, wert)
    assert not (tmp_path / "foto.jpg.xmp").exists()


def test_sonderzeichen_und_unicode_im_namen(tmp_path):
    for name in ("Möwe & Meer – 1 (kopie) #2.jpg", "写真 ä ß.jpg", "a b'c.jpg"):
        bild = _bild(tmp_path, name)
        bewertung.schreiben(bild, 3)
        assert bewertung.lesen(bild) == Stand(3, "eigen")
        assert (tmp_path / (name + ".xmp")).is_file()


def test_atomar_fehler_laesst_alte_datei_und_raeumt_auf(tmp_path, monkeypatch):
    bild = _bild(tmp_path)
    bewertung.schreiben(bild, 2)
    vorher = (tmp_path / "foto.jpg.xmp").read_bytes()

    def kaputt(_quelle, _ziel):
        raise PermissionError("gesperrt")

    monkeypatch.setattr(bewertung.os, "replace", kaputt)
    with pytest.raises(bewertung.BewertungFehler):
        bewertung.schreiben(bild, 5)
    assert (tmp_path / "foto.jpg.xmp").read_bytes() == vorher
    assert sorted(p.name for p in tmp_path.iterdir()) == ["foto.jpg", "foto.jpg.xmp"]


def test_fehler_beim_anlegen_der_zwischendatei(tmp_path, monkeypatch):
    bild = _bild(tmp_path)

    def kaputt(**_kw):
        raise PermissionError("schreibgeschuetzt")

    monkeypatch.setattr(bewertung.tempfile, "mkstemp", kaputt)
    with pytest.raises(bewertung.BewertungFehler):
        bewertung.schreiben(bild, 3)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["foto.jpg"]


def test_ordner_fehlt_gibt_bewertungsfehler(tmp_path):
    with pytest.raises(bewertung.BewertungFehler):
        bewertung.schreiben(str(tmp_path / "gibt-es-nicht" / "foto.jpg"), 3)


def test_ausschuss_loescht_nichts(tmp_path):
    """Kein Code-Pfad fasst die Bilddatei an: Bytes und Zeit bleiben, auch bei Ausschuss."""
    bild = _bild(tmp_path)
    vorher, zeit = open(bild, "rb").read(), os.stat(bild).st_mtime_ns
    for wert in (bewertung.AUSSCHUSS, 3, 0, bewertung.AUSSCHUSS):
        bewertung.schreiben(bild, wert)
        bewertung.lesen(bild)
    assert open(bild, "rb").read() == vorher and os.stat(bild).st_mtime_ns == zeit
    assert sorted(p.name for p in tmp_path.iterdir()) == ["foto.jpg", "foto.jpg.xmp"]


# --------------------------------------------------------------------------
# Fremde Dateien
# --------------------------------------------------------------------------

def test_fremde_datei_wird_gelesen_aber_nie_veraendert(tmp_path):
    bild = _bild(tmp_path)
    ziel = tmp_path / "foto.jpg.xmp"
    ziel.write_bytes(_xmp("4", '<darktable:history/>'))
    os.utime(ziel, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    vorher, zeit = ziel.read_bytes(), ziel.stat().st_mtime_ns
    stand = bewertung.lesen(bild)
    assert stand == Stand(4, "fremd") and not stand.aenderbar
    with pytest.raises(bewertung.FremdeDatei):
        bewertung.schreiben(bild, 1)
    with pytest.raises(bewertung.FremdeDatei):
        bewertung.schreiben(bild, bewertung.AUSSCHUSS)
    assert ziel.read_bytes() == vorher and ziel.stat().st_mtime_ns == zeit
    assert sorted(p.name for p in tmp_path.iterdir()) == ["foto.jpg", "foto.jpg.xmp"]


def test_fremde_datei_mit_ausschuss_wird_gelesen(tmp_path):
    bild = _bild(tmp_path)
    (tmp_path / "foto.jpg.xmp").write_bytes(_xmp("-1"))
    assert bewertung.lesen(bild) == Stand(-1, "fremd")


def test_eigene_datei_mit_zusaetzen_gilt_als_fremd(tmp_path):
    """Hat jemand die Datei erweitert, ueberschreibt Silberkorn sie nicht mehr."""
    bild = _bild(tmp_path)
    bewertung.schreiben(bild, 3)
    ziel = tmp_path / "foto.jpg.xmp"
    text = ziel.read_text(encoding="utf-8").replace(
        'sk:Kennung="bewertung"/>', 'sk:Kennung="bewertung"><xmp:Label>Rot</xmp:Label>'
        '</rdf:Description>')
    ziel.write_text(text, encoding="utf-8")
    vorher = ziel.read_bytes()
    assert bewertung.lesen(bild).art == "fremd"
    with pytest.raises(bewertung.FremdeDatei):
        bewertung.schreiben(bild, 1)
    assert ziel.read_bytes() == vorher


def test_lightroom_datei_ohne_bildendung_wird_weder_gelesen_noch_geschrieben(tmp_path):
    bild = _bild(tmp_path)
    lightroom = tmp_path / "foto.xmp"
    lightroom.write_bytes(_xmp("5"))
    vorher = lightroom.read_bytes()
    assert bewertung.lesen(bild) == Stand(0, "keine")
    bewertung.schreiben(bild, 2)
    assert lightroom.read_bytes() == vorher
    assert bewertung.lesen(bild) == Stand(2, "eigen")


# --------------------------------------------------------------------------
# Boesartige und kaputte Eingaben
# --------------------------------------------------------------------------

BOESE = {
    "doctype": b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>' + _xmp("3"),
    "entity": _xmp("3", "&a;").replace(b"<x:xmpmeta", b"<!ENTITY a 'b'><x:xmpmeta", 1),
    "kaputt": b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF',
    "kein_xml": b"\x00\xff\xfe nicht einmal Text",
    "leer": b"",
    "5abc": _xmp("5abc"),
    "99": _xmp("99"),
    "minus7": _xmp("-7"),
    "float": _xmp("3.5"),
    "float_ganz": _xmp("3.0"),
    "leer_wert": _xmp(""),
    "exponent": _xmp("1e0"),
    "plus": _xmp("+3"),
    "volle_breite": _xmp("５"),
    "ohne_rating": _xmp("3").replace(b'xmp:Rating="3"', b""),
    "zwei_beschreibungen": _xmp("2").replace(
        b"</rdf:RDF>", b'<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
        b'xmp:Rating="4"/></rdf:RDF>'),
    "doppeltes_attribut": _xmp("3").replace(b'xmp:Rating="3"', b'xmp:Rating="3" xmp:Rating="4"'),
    "attribut_und_element": _xmp("2", '<xmp:Rating>4</xmp:Rating>'),
    "rating_mit_unterelement": _xmp("").replace(
        b'xmp:Rating=""', b"").replace(
        b"</rdf:Description>", b'<xmp:Rating><x/></xmp:Rating></rdf:Description>'),
}


@pytest.mark.parametrize("name", sorted(BOESE))
def test_boesartige_datei_ergibt_keine_bewertung_und_bleibt_unveraendert(tmp_path, name):
    bild = _bild(tmp_path)
    ziel = tmp_path / "foto.jpg.xmp"
    ziel.write_bytes(BOESE[name])
    vorher, zeit = ziel.read_bytes(), ziel.stat().st_mtime_ns
    stand = bewertung.lesen(bild)
    assert stand.wert == 0 and stand.art in ("fremd", "unlesbar") and not stand.aenderbar
    with pytest.raises(bewertung.FremdeDatei):
        bewertung.schreiben(bild, 3)
    assert ziel.read_bytes() == vorher and ziel.stat().st_mtime_ns == zeit


def test_nur_ein_rating_als_element_zaehlt(tmp_path):
    bild = _bild(tmp_path)
    (tmp_path / "foto.jpg.xmp").write_bytes(
        _xmp("").replace(b'xmp:Rating=""', b"").replace(
            b"</rdf:Description>", b"<xmp:Rating> 4 </xmp:Rating></rdf:Description>"))
    assert bewertung.lesen(bild) == Stand(4, "fremd")


def test_riesige_datei_wird_nicht_gelesen(tmp_path, monkeypatch):
    bild = _bild(tmp_path)
    ziel = tmp_path / "foto.jpg.xmp"
    ziel.write_bytes(_xmp("3", "x" * 4096))
    gelesen = []
    echte = open

    def spaeh(pfad, *args, **kwargs):
        gelesen.append(pfad)
        return echte(pfad, *args, **kwargs)

    monkeypatch.setattr(bewertung, "LESE_MAX", 1024)
    monkeypatch.setattr("builtins.open", spaeh)
    stand = bewertung.lesen(bild)
    assert stand == Stand(0, "unlesbar") and str(ziel) not in gelesen   # nicht einmal geoeffnet


def test_milliarden_lacher_und_tiefe_verschachtelung(tmp_path):
    bild = _bild(tmp_path)
    lacher = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
              b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
              + _xmp("3", "&lol2;"))
    (tmp_path / "foto.jpg.xmp").write_bytes(lacher)
    assert bewertung.lesen(bild).wert == 0
    tief = _xmp("3", "<a>" * 5000 + "</a>" * 5000)
    (tmp_path / "foto.jpg.xmp").write_bytes(tief)
    assert bewertung.lesen(bild).wert in (0, 3)               # kein Absturz, nichts Falsches


def test_ordner_oder_verknuepfung_statt_datei_wird_nicht_angefasst(tmp_path):
    bild = _bild(tmp_path)
    (tmp_path / "foto.jpg.xmp").mkdir()
    assert bewertung.lesen(bild) == Stand(0, "unlesbar")
    with pytest.raises(bewertung.FremdeDatei):
        bewertung.schreiben(bild, 3)
    assert (tmp_path / "foto.jpg.xmp").is_dir()


def test_pfade_aus_der_datei_werden_nicht_uebernommen(tmp_path, monkeypatch):
    """about, resource und Co. in der Datei bleiben ohne Wirkung: Gelesen wird eine Zahl."""
    bild = _bild(tmp_path)
    ziel = tmp_path / "foto.jpg.xmp"
    ziel.write_bytes(_xmp("2").replace(
        b'rdf:about=""', b'rdf:about="\\\\\\\\server\\\\freigabe\\\\x.jpg"'))
    zugriffe = []
    echte = open

    def spaeh(pfad, *args, **kwargs):
        zugriffe.append(os.fspath(pfad))
        return echte(pfad, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spaeh)
    stand = bewertung.lesen(bild)
    monkeypatch.undo()
    assert stand == Stand(2, "fremd")
    assert zugriffe == [str(ziel)]


# --------------------------------------------------------------------------
# Viele lesen, Bearbeiten-Feld, Sortierung, Einstellung
# --------------------------------------------------------------------------

def test_lesen_viele_nur_vorhandene_und_abbruch(tmp_path):
    a, b, c = (_bild(tmp_path, n) for n in ("a.jpg", "b.jpg", "c.jpg"))
    bewertung.schreiben(a, 2)
    bewertung.schreiben(c, -1)
    assert bewertung.lesen_viele([a, b, c]) == {a: Stand(2, "eigen"), c: Stand(-1, "eigen")}
    assert bewertung.lesen_viele([a, b, c], lambda: False) == {}


def test_fuer_bearbeiten():
    assert bewertung.fuer_bearbeiten(Stand(4, "eigen")) == 4
    assert bewertung.fuer_bearbeiten(Stand(-1, "eigen")) == 0        # Feld auf „–“
    assert bewertung.fuer_bearbeiten(Stand(0, "eigen")) == 0         # die eigene Datei geht vor
    assert bewertung.fuer_bearbeiten(Stand(0, "keine")) is None
    assert bewertung.fuer_bearbeiten(Stand(4, "fremd")) is None      # fremde bestimmen nichts
    assert bewertung.fuer_bearbeiten(Stand(0, "unlesbar")) is None


def _name(name: str):
    return name.casefold()


def test_sortierung_name_datum_sterne_ausschuss_am_ende():
    pfade = [os.path.join("x", n) for n in ("d.jpg", "a.jpg", "c.jpg", "b.jpg", "e.jpg")]
    staende = {os.path.join("x", "a.jpg"): Stand(5, "eigen"),
               os.path.join("x", "b.jpg"): Stand(-1, "eigen"),
               os.path.join("x", "c.jpg"): Stand(5, "fremd"),
               os.path.join("x", "d.jpg"): Stand(2, "eigen")}
    zeiten = {os.path.join("x", "a.jpg"): 10.0, os.path.join("x", "b.jpg"): 50.0,
              os.path.join("x", "c.jpg"): 30.0, os.path.join("x", "d.jpg"): 20.0,
              os.path.join("x", "e.jpg"): 20.0}

    def namen(art):
        return [os.path.basename(p) for p in
                bewertung.sortiert(pfade, art, _name, staende, zeiten)]

    assert namen("name") == ["a.jpg", "c.jpg", "d.jpg", "e.jpg", "b.jpg"]
    # neueste zuerst, gleiche Zeit nach Name; Ausschuss (b, die neueste) zuletzt
    assert namen("datum") == ["c.jpg", "d.jpg", "e.jpg", "a.jpg", "b.jpg"]
    # meiste Sterne zuerst, Gleichstand (a, c) nach Name, ohne Bewertung hinten, Ausschuss am Ende
    assert namen("sterne") == ["a.jpg", "c.jpg", "d.jpg", "e.jpg", "b.jpg"]
    assert namen("unbekannt") == namen("name")


def test_sortierung_ohne_bewertungen_ist_nach_name():
    pfade = ["b.jpg", "a.jpg", "c.jpg"]
    assert bewertung.sortiert(pfade, "sterne", _name, {}, {}) == ["a.jpg", "b.jpg", "c.jpg"]


def test_sterne_kommen_ins_gespeicherte_bild_ausschuss_nicht():
    """„Speichern unter“: Die Vorgabe (Sterne aus der Datei) steht in den Angaben und damit in
    EXIF und XMP der Ausgabe; bei Ausschuss (0) bekommt die Ausgabe keine Sterne."""
    leer = metadaten.lesen(b"", b"", {})
    for sterne, erwartet in ((4, 4), (0, 0)):
        aenderungen = metadaten.aendern((), leer.angaben, "bewertung", sterne) if sterne else ()
        exif, xmp = metadaten.fuer_speichern(b"", b"", leer, aenderungen, 8, 6)
        gelesen = metadaten.lesen(exif, xmp, {}).angaben.bewertung
        assert gelesen == erwartet
    # Das Bild hatte schon Sterne, Ausschuss nimmt sie weg
    mit4 = metadaten.fuer_speichern(b"", b"", leer,
                                    metadaten.aendern((), leer.angaben, "bewertung", 4), 8, 6)
    vorhanden = metadaten.lesen(*mit4, {})
    exif, xmp = metadaten.fuer_speichern(
        *mit4, vorhanden, metadaten.aendern((), vorhanden.angaben, "bewertung", 0), 8, 6)
    assert metadaten.lesen(exif, xmp, {}).angaben.bewertung == 0


def test_ordner_sortierung_gemerkt_mit_whitelist(tmp_path, monkeypatch):
    monkeypatch.setattr(einstellungen, "programm_ordner", lambda: str(tmp_path))
    assert einstellungen.ordner_sortierung() == "name"
    for art in ("datum", "sterne", "name"):
        assert einstellungen.ordner_sortierung_setzen(art)
        assert einstellungen.ordner_sortierung() == art
    for kaputt in ("DATUM", "../x", "", None, 3, ["datum"], {"a": 1}, True):
        (tmp_path / einstellungen.CONFIG_NAME).write_text(
            json.dumps({"ordner_sortierung": kaputt}), encoding="utf-8")
        assert einstellungen.ordner_sortierung() == "name"
    einstellungen.ordner_sortierung_setzen("unsinn")
    assert einstellungen.ordner_sortierung() == "name"


# --------------------------------------------------------------------------
# Fremd und unlesbar, Wettlauf, Verknuepfung, Fehler beim Lesen vieler
# --------------------------------------------------------------------------

def test_fremd_und_unlesbar_sind_verschieden(tmp_path):
    fremd, kaputt = _bild(tmp_path, "a.jpg"), _bild(tmp_path, "b.jpg")
    (tmp_path / "a.jpg.xmp").write_bytes(_xmp("4"))
    (tmp_path / "b.jpg.xmp").write_bytes(b"<x:xmpmeta")
    assert bewertung.lesen(fremd) == Stand(4, "fremd")
    assert bewertung.lesen(kaputt) == Stand(0, "unlesbar")
    assert not bewertung.lesen(fremd).aenderbar and not bewertung.lesen(kaputt).aenderbar
    with pytest.raises(bewertung.FremdeDatei) as e1:
        bewertung.schreiben(fremd, 1)
    with pytest.raises(bewertung.UnlesbareDatei) as e2:
        bewertung.schreiben(kaputt, 1)
    assert not isinstance(e1.value, bewertung.UnlesbareDatei) and e2.value
    assert (tmp_path / "b.jpg.xmp").read_bytes() == b"<x:xmpmeta"


def test_eigene_datei_mit_zusaetzlichem_attribut_ist_fremd(tmp_path):
    bild = _bild(tmp_path)
    bewertung.schreiben(bild, 3)
    ziel = tmp_path / "foto.jpg.xmp"
    ziel.write_text(ziel.read_text(encoding="utf-8").replace(
        'xmp:Rating="3"', 'xmp:Rating="3" xmp:Label="Rot"'), encoding="utf-8")
    assert bewertung.lesen(bild) == Stand(3, "fremd")


def test_gefaelschte_kennung_mit_anderem_werkzeug_ist_fremd(tmp_path):
    bild = _bild(tmp_path)
    bewertung.schreiben(bild, 3)
    ziel = tmp_path / "foto.jpg.xmp"
    ziel.write_text(ziel.read_text(encoding="utf-8").replace(
        'xmp:CreatorTool="Silberkorn"', 'xmp:CreatorTool="darktable"'), encoding="utf-8")
    vorher = ziel.read_bytes()
    assert bewertung.lesen(bild) == Stand(3, "fremd")
    with pytest.raises(bewertung.FremdeDatei):
        bewertung.schreiben(bild, 1)
    assert ziel.read_bytes() == vorher


def test_wettlauf_fremde_datei_erscheint_vor_dem_ersetzen(tmp_path, monkeypatch):
    """Die zweite Pruefung vor os.replace: Taucht die fremde Datei erst nach dem Schreiben der
    Zwischendatei auf, bleibt sie Byte fuer Byte unberuehrt und es bleibt kein Rest."""
    bild = _bild(tmp_path)
    ziel = tmp_path / "foto.jpg.xmp"
    fremd = _xmp("5", "<darktable:history/>")
    echte = bewertung.lesen
    aufrufe = []

    def lesen(pfad):
        aufrufe.append(pfad)
        if len(aufrufe) == 2:                   # nach dem Zwischenschreiben
            ziel.write_bytes(fremd)
        return echte(pfad)

    monkeypatch.setattr(bewertung, "lesen", lesen)
    with pytest.raises(bewertung.FremdeDatei):
        bewertung.schreiben(bild, 2)
    assert len(aufrufe) == 2
    assert ziel.read_bytes() == fremd
    assert sorted(p.name for p in tmp_path.iterdir()) == ["foto.jpg", "foto.jpg.xmp"]


def test_verknuepfung_als_xmp_ist_unlesbar_und_ziel_bleibt(tmp_path):
    bild = _bild(tmp_path)
    ziel = tmp_path / "ziel.xmp"
    bewertung.schreiben(str(tmp_path / "ziel"), 4)       # gueltiger eigener Inhalt
    vorher = ziel.read_bytes()
    try:
        os.symlink(ziel, tmp_path / "foto.jpg.xmp")
    except OSError:
        pytest.skip("Verknuepfungen sind hier nicht erlaubt")
    assert bewertung.lesen(bild) == Stand(0, "unlesbar")
    with pytest.raises(bewertung.UnlesbareDatei):
        bewertung.schreiben(bild, 1)
    assert ziel.read_bytes() == vorher
    assert os.path.islink(tmp_path / "foto.jpg.xmp")
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_lesen_viele_unerwartete_ausnahme_trifft_nur_dieses_bild(tmp_path, monkeypatch):
    a, b, c = (_bild(tmp_path, n) for n in ("a.jpg", "b.jpg", "c.jpg"))
    bewertung.schreiben(a, 2)
    bewertung.schreiben(c, 5)
    echte = bewertung.lesen

    def lesen(pfad):
        if pfad == b:
            raise RuntimeError("unerwartet")
        return echte(pfad)

    monkeypatch.setattr(bewertung, "lesen", lesen)
    assert bewertung.lesen_viele([a, b, c]) == {
        a: Stand(2, "eigen"), b: Stand(0, "unlesbar"), c: Stand(5, "eigen")}
