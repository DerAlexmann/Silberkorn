"""Startmeldungen: Jeder Ablehnungsgrund hat einen Titel und einen Text."""

from __future__ import annotations

import pytest

from silberkorn import gpu_pruefung as g
from silberkorn import start
from silberkorn.uebersetzung import _


@pytest.fixture(params=["de", "en"])
def sprache(request):
    vorher = _.language
    _.language = request.param
    yield request.param
    _.language = vorher


@pytest.mark.parametrize("grund", ["kein_treiber", "keine_nvidia", "keine_rtx", "treiber_alt"])
def test_jede_ablehnung_hat_eine_meldung(grund, sprache):
    befund = start.simulierter_befund(grund)
    assert not befund.ok
    titel, text = start.meldungstext(befund)
    assert titel and text
    assert "{" not in text                   # alle Platzhalter eingesetzt


def test_treiber_meldung_nennt_beide_versionen():
    titel, text = start.meldungstext(start.simulierter_befund("treiber_alt"))
    assert "552.22" in text
    assert g.treiber_anzeige() in text


def test_wenig_vram_startet():
    befund = start.simulierter_befund("wenig_vram")
    assert befund.ok
    assert befund.stufe == g.STUFE_OHNE_KI


@pytest.fixture
def fehlerfaenger(monkeypatch, tmp_path):
    """Fehlerfaenger mit Logdatei in tmp_path; die Fenster werden nur gezaehlt."""
    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "programm_ordner", lambda: str(tmp_path))
    monkeypatch.setattr(start, "_gezeigte_fehler", set())
    monkeypatch.setattr(start, "_fehler_offen", False)
    fenster = []
    monkeypatch.setattr(start, "_fehler_fenster",
                        lambda titel, details, log: fenster.append((titel, details, log)))
    return fenster, tmp_path / start.FEHLER_LOG


def _ausloesen(text: str):
    """Einen Fehler werfen und so an den Fehlerfaenger geben wie Python selbst."""
    try:
        raise RuntimeError(text)
    except RuntimeError as fehler:
        start.unerwarteter_fehler(type(fehler), fehler, fehler.__traceback__)


def test_unerwarteter_fehler_landet_in_fenster_und_log(fehlerfaenger):
    fenster, log = fehlerfaenger
    _ausloesen("kaputt")
    assert len(fenster) == 1
    titel, details, pfad = fenster[0]
    assert "RuntimeError: kaputt" in details and "_ausloesen" in details
    assert pfad == str(log)
    assert "RuntimeError: kaputt" in log.read_text(encoding="utf-8")


def test_dieselbe_fehlerstelle_nur_ein_fenster(fehlerfaenger):
    """Ein Fehler, der sich wiederholt (etwa beim Zeichnen), oeffnet nicht endlos Fenster -
    festgehalten wird er trotzdem jedes Mal."""
    fenster, log = fehlerfaenger
    for nummer in range(3):
        _ausloesen(f"Lauf {nummer}")
    assert len(fenster) == 1
    assert log.read_text(encoding="utf-8").count("RuntimeError: Lauf") == 3


def test_kein_zweites_fenster_solange_eins_offen(fehlerfaenger, monkeypatch):
    fenster, _log = fehlerfaenger
    monkeypatch.setattr(start, "_fehler_offen", True)
    _ausloesen("waehrend das Fenster offen ist")
    assert fenster == []


def test_log_beginnt_ueber_der_grenze_neu(fehlerfaenger, monkeypatch):
    _fenster, log = fehlerfaenger
    monkeypatch.setattr(start, "FEHLER_LOG_HOECHSTENS", 10)
    start.fehler_festhalten("eins", "alt")
    start.fehler_festhalten("zwei", "neu")
    inhalt = log.read_text(encoding="utf-8")
    assert "neu" in inhalt and "alt" not in inhalt


def test_log_nicht_schreibbar(fehlerfaenger, monkeypatch, tmp_path):
    """Laesst sich die Logdatei nicht schreiben, gibt es trotzdem das Fenster - ohne Pfad."""
    from silberkorn import einstellungen
    monkeypatch.setattr(einstellungen, "programm_ordner", lambda: str(tmp_path / "fehlt"))
    fenster, _log = fehlerfaenger
    _ausloesen("ohne Log")
    assert len(fenster) == 1 and fenster[0][2] == ""


def test_fehler_im_qt_slot_erreicht_den_faenger(fehlerfaenger, monkeypatch):
    """Der eigentliche Fall: Ein Knopf, dessen Slot scheitert. PySide6 gibt den Fehler an
    sys.excepthook - ohne Fehlerfaenger verschwand er in der EXE spurlos."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QPushButton
    QApplication.instance() or QApplication([])
    fenster, _log = fehlerfaenger
    monkeypatch.setattr("sys.excepthook", start.unerwarteter_fehler)

    def scheitern():
        raise ValueError("im Slot")

    knopf = QPushButton()
    knopf.clicked.connect(scheitern)
    knopf.click()
    assert len(fenster) == 1 and "ValueError: im Slot" in fenster[0][1]


def test_scheiterndes_fenster_landet_im_log(fehlerfaenger, monkeypatch):
    """Scheitert das Fenster selbst, steht beides im Log - und beim naechsten Mal wird es
    erneut versucht, weil die Stelle noch nicht als gezeigt gilt."""
    _fenster, log = fehlerfaenger
    versuche = []

    def kaputt(titel, details, pfad):
        versuche.append(details)
        raise RuntimeError("Fenster kaputt")

    monkeypatch.setattr(start, "_fehler_fenster", kaputt)
    for _lauf in range(2):
        _ausloesen("eigentlicher Fehler")
    inhalt = log.read_text(encoding="utf-8")
    assert "eigentlicher Fehler" in inhalt and "Fenster kaputt" in inhalt
    assert len(versuche) == 2 and not start._fehler_offen


def test_kaputte_konsole_haelt_nicht_auf(fehlerfaenger, monkeypatch):
    """In der EXE kann stderr ein ungueltiges Handle sein - Log und Fenster gibt es trotzdem."""
    fenster, log = fehlerfaenger

    class Kaputt:
        def write(self, _text):
            raise OSError("ungueltiges Handle")

    monkeypatch.setattr("sys.stderr", Kaputt())
    _ausloesen("ohne Konsole")
    assert len(fenster) == 1 and "ohne Konsole" in log.read_text(encoding="utf-8")


def test_ohne_konsole(fehlerfaenger, monkeypatch):
    """Die EXE hat gar kein stderr (None)."""
    fenster, log = fehlerfaenger
    monkeypatch.setattr("sys.stderr", None)
    _ausloesen("ohne stderr")
    assert len(fenster) == 1 and "ohne stderr" in log.read_text(encoding="utf-8")


def test_strg_c_bleibt_beim_standard(fehlerfaenger, monkeypatch):
    fenster, log = fehlerfaenger
    weiter = []
    monkeypatch.setattr("sys.__excepthook__", lambda *a: weiter.append(a))
    start.unerwarteter_fehler(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert weiter and fenster == [] and not log.exists()
