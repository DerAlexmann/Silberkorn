"""
Verlauf fuer Rueckgaengig und Wiederholen

Ein Stand ist alles, was eine Bearbeitung ausmacht: eine Kopie der
Reglerwerte und Verweise auf die KI-Ergebnisse (Entrauschen, Maske, Flicken
...). Die KI-Ergebnisse werden nicht kopiert - die Sitzung ersetzt sie bei
jeder Aenderung durch neue Objekte, die alten bleiben so unveraendert im
Verlauf liegen.

Reglerschritte kosten fast nichts. Ueberholte KI-Ergebnisse dagegen halten
Grafikspeicher fest, in voller Groesse eines 24-Megapixel-Bildes rund 300 MB
je Stueck. Der Verlauf begrenzt deshalb, wie viel Grafikspeicher er ueber den
aktuellen Stand hinaus belegt; die aeltesten Schritte fallen dafuer weg.

Dieses Modul kennt weder Qt noch die Grafikkarte: Ein KI-Ergebnis ist fuer
den Verlauf ein Objekt mit nbytes und shape, gleich ob NumPy oder CuPy.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

SCHRITTE = 200                 # so viele Schritte reichen zurueck, hoechstens


@dataclass(frozen=True, eq=False)
class Stand:
    """Werte (eine eigene Kopie) und KI-Ergebnisse ((Name, Objekt), ...) als Verweise.
    nummer kennzeichnet den Inhalt der Flicken und der Erweiterung - fuer die Frage,
    ob das Bild seit dem Speichern geaendert ist."""
    werte: object
    teile: tuple[tuple[str, object], ...]
    nummer: int = 0


def _dasselbe(a, b) -> bool:
    """Dieselben Objekte - Tupel und Listen werden Stueck fuer Stueck verglichen, weil die
    Sitzung sie fuer jeden Stand neu zusammenstellt."""
    if a is b:
        return True
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_dasselbe(x, y) for x, y in zip(a, b, strict=True))
    return False


def gleich(a: Stand, b: Stand) -> bool:
    return a.werte == b.werte and _dasselbe(a.teile, b.teile)


def unterschied(a: Stand, b: Stand) -> list[str]:
    """Was sich von a nach b geaendert hat: Namen der Werte, dann der KI-Ergebnisse."""
    namen = [feld.name for feld in dataclasses.fields(a.werte)
             if getattr(a.werte, feld.name) != getattr(b.werte, feld.name)]
    teile_b = dict(b.teile)
    namen += [name for name, wert in a.teile if not _dasselbe(wert, teile_b.get(name))]
    return namen


def _felder(objekt):
    """Alle Felder (Arrays) in einem KI-Ergebnis, auch in Tupeln und Datenklassen."""
    if objekt is None or isinstance(objekt, (bool, int, float, str)):
        return
    if hasattr(objekt, "nbytes") and hasattr(objekt, "shape"):
        yield objekt
    elif isinstance(objekt, (tuple, list)):
        for teil in objekt:
            yield from _felder(teil)
    elif dataclasses.is_dataclass(objekt) and not isinstance(objekt, type):
        for feld in dataclasses.fields(objekt):
            yield from _felder(getattr(objekt, feld.name))


def _speicher(staende) -> dict[int, int]:
    """id -> Bytes aller Arrays in den Staenden, jedes nur einmal gezaehlt."""
    belegt = {}
    for stand in staende:
        for feld in _felder(stand.teile):
            belegt[id(feld)] = feld.nbytes
    return belegt


class Verlauf:
    """Staende in Reihenfolge; einer davon ist der aktuelle. Zurueck und vor bewegen nur
    den Zeiger - eine neue Aenderung schneidet ab, was davor wiederholbar war."""

    def __init__(self, budget: int, schritte: int = SCHRITTE):
        self.budget = budget                   # Grafikspeicher ueber den aktuellen Stand hinaus
        self.schritte = schritte
        self._staende: list[Stand] = []
        self._namen: list[str] = []            # was zu diesem Stand gefuehrt hat, wenn bekannt
        self._zeiger = -1

    def beginnen(self, stand: Stand):
        """Neues Bild: der Verlauf beginnt mit diesem Stand."""
        self._staende, self._namen, self._zeiger = [stand], [""], 0

    def leeren(self):
        self._staende, self._namen, self._zeiger = [], [], -1

    @property
    def aktuell(self) -> Stand | None:
        return self._staende[self._zeiger] if self._staende else None

    @property
    def kann_zurueck(self) -> bool:
        return self._zeiger > 0

    @property
    def kann_vor(self) -> bool:
        return 0 <= self._zeiger < len(self._staende) - 1

    def festhalten(self, stand: Stand, name: str = "") -> bool:
        """Einen neuen Stand ans Ende setzen, wenn er sich vom aktuellen unterscheidet.
        name benennt den Schritt, wo der Unterschied allein ihn nicht gut beschreibt."""
        if not self._staende:
            self.beginnen(stand)
            return False
        if gleich(stand, self.aktuell):
            return False
        del self._staende[self._zeiger + 1:]
        del self._namen[self._zeiger + 1:]
        self._staende.append(stand)
        self._namen.append(name)
        self._zeiger += 1
        self._kuerzen()
        return True

    def zurueck(self) -> Stand | None:
        if not self.kann_zurueck:
            return None
        self._zeiger -= 1
        return self.aktuell

    def vor(self) -> Stand | None:
        if not self.kann_vor:
            return None
        self._zeiger += 1
        return self.aktuell

    def schritt_zurueck(self) -> tuple[Stand, Stand, str] | None:
        """(vorher, nachher, Name) des Schritts, den „Rückgängig“ zuruecknaehme."""
        if not self.kann_zurueck:
            return None
        z = self._zeiger
        return self._staende[z - 1], self._staende[z], self._namen[z]

    def schritt_vor(self) -> tuple[Stand, Stand, str] | None:
        """(vorher, nachher, Name) des Schritts, den „Wiederholen“ wiederholte."""
        if not self.kann_vor:
            return None
        z = self._zeiger
        return self._staende[z], self._staende[z + 1], self._namen[z + 1]

    def grafikspeicher(self) -> int:
        """Bytes, die nur der Verlauf festhaelt - nicht auch der aktuelle Stand."""
        aktuell = _speicher([self.aktuell]) if self._staende else {}
        return sum(groesse for nummer, groesse in _speicher(self._staende).items()
                   if nummer not in aktuell)

    def _weg(self, stelle: int):
        del self._staende[stelle]
        del self._namen[stelle]
        if stelle < self._zeiger:
            self._zeiger -= 1
        self._namen[0] = ""                    # der erste Stand hat keinen Vorgaenger mehr

    def _kuerzen(self):
        while len(self._staende) - 1 > self.schritte:
            self._weg(0)
        # Nach festhalten() ist der neue Stand der letzte - es fallen die aeltesten weg
        while self._zeiger > 0 and self.grafikspeicher() > self.budget:
            self._weg(0)
