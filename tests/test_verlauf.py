"""Verlauf fuer Rueckgaengig und Wiederholen - ohne Grafikkarte, mit NumPy statt CuPy."""

from __future__ import annotations

import dataclasses

import numpy as np

from silberkorn import verlauf
from silberkorn.filter import Einstellungen
from silberkorn.verlauf import Stand, Verlauf

MB = 2**20


def stand(belichtung: float = 0.0, **teile) -> Stand:
    return Stand(Einstellungen(belichtung=belichtung), tuple(teile.items()))


def feld(mb: int):
    return np.zeros(mb * MB, dtype=np.uint8)


def test_gleicher_stand_ist_kein_schritt():
    v = Verlauf(budget=0)
    v.beginnen(stand())
    assert not v.festhalten(stand())
    assert not v.kann_zurueck
    assert v.festhalten(stand(1.0))
    assert v.kann_zurueck and not v.kann_vor


def test_zurueck_vor_und_abschneiden():
    v = Verlauf(budget=0)
    v.beginnen(stand())
    for wert in (1.0, 2.0, 3.0):
        v.festhalten(stand(wert))
    assert v.zurueck().werte.belichtung == 2.0
    assert v.zurueck().werte.belichtung == 1.0
    assert v.vor().werte.belichtung == 2.0
    # Eine neue Aenderung schneidet ab, was wiederholbar war
    v.festhalten(stand(5.0))
    assert not v.kann_vor
    assert v.zurueck().werte.belichtung == 2.0
    assert v.zurueck().werte.belichtung == 1.0
    assert v.zurueck().werte.belichtung == 0.0
    assert v.zurueck() is None


def test_ki_ergebnisse_nach_identitaet():
    """KI-Ergebnisse sind gleich, wenn es dieselben Objekte sind - Tupel und Listen
    zaehlen Stueck fuer Stueck, weil die Sitzung sie fuer jeden Stand neu baut."""
    a, b = feld(1), feld(1)
    assert verlauf.gleich(stand(flicken=(a, b)), stand(flicken=(a, b)))
    assert not verlauf.gleich(stand(flicken=(a,)), stand(flicken=(a, b)))
    assert not verlauf.gleich(stand(maske=a), stand(maske=a.copy()))
    assert verlauf.unterschied(stand(maske=a), stand(1.0, maske=b)) == ["belichtung", "maske"]


def test_namen_der_schritte():
    v = Verlauf(budget=0)
    v.beginnen(stand())
    v.festhalten(stand(1.0), "zuruecksetzen")
    vorher, nachher, name = v.schritt_zurueck()
    assert (vorher.werte.belichtung, nachher.werte.belichtung, name) == (0.0, 1.0,
                                                                         "zuruecksetzen")
    assert v.schritt_vor() is None
    v.zurueck()
    assert v.schritt_vor()[2] == "zuruecksetzen" and v.schritt_zurueck() is None


def test_hoechstens_so_viele_schritte():
    v = Verlauf(budget=0, schritte=3)
    v.beginnen(stand())
    for wert in range(1, 10):
        v.festhalten(stand(float(wert)))
    zurueck = 0
    while v.zurueck() is not None:
        zurueck += 1
    assert zurueck == 3 and v.aktuell.werte.belichtung == 6.0


def test_grafikspeicher_begrenzt():
    """Ueberholte KI-Ergebnisse belegen Grafikspeicher; die aeltesten Schritte fallen weg,
    bis der Verlauf wieder ins Budget passt. Der aktuelle Stand zaehlt nicht mit."""
    v = Verlauf(budget=25 * MB)
    v.beginnen(stand())
    eins, zwei, drei = feld(10), feld(10), feld(10)
    v.festhalten(stand(ki=eins))
    v.festhalten(stand(ki=zwei))
    assert v.grafikspeicher() == 10 * MB          # eins ist ueberholt, zwei aktuell
    v.festhalten(stand(ki=drei))
    assert v.grafikspeicher() == 20 * MB
    v.festhalten(stand(1.0, ki=drei))             # nur ein Regler: kostet nichts
    v.festhalten(stand(ki=feld(10)))
    assert v.grafikspeicher() <= 25 * MB
    schritte = []
    while (s := v.zurueck()) is not None:
        schritte.append(s)
    assert dict(schritte[-1].teile)["ki"] is zwei    # der Stand mit eins ist weggefallen


def test_ohne_budget_bleibt_nur_ein_ki_schritt():
    """Selbst ohne Budget laesst sich der letzte Schritt zuruecknehmen, solange er nur
    Regler betraf - der Stand davor haelt keinen Grafikspeicher."""
    v = Verlauf(budget=0)
    v.beginnen(stand(ki=feld(1)))
    v.festhalten(stand(ki=feld(1)))
    assert not v.kann_zurueck                     # der alte Stand haette 1 MB gekostet
    v.festhalten(stand(1.0, ki=v.aktuell.teile[0][1]))
    assert v.kann_zurueck


def test_felder_in_datenklassen_gefunden():
    @dataclasses.dataclass
    class Flicken:
        voll: tuple
        vorschau: tuple

    f = Flicken((1, 2, feld(2)), (1, 2, feld(1)))
    assert sum(t.nbytes for t in verlauf._felder(((f,), None, True))) == 3 * MB
