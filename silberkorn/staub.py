"""
Scan & Film: Staub und Kratzer ueber den Infrarotkanal finden und fuellen

Die Farbstoffe eines Films lassen Infrarot fast ungehindert durch, Staub,
Fusseln und Kratzer halten es auf. Im Infrarotkanal eines Filmscanners (RGBI)
ist der Film deshalb gleichmaessig hell, und was darin dunkel ist, ist ein
Fehler - nicht Bildinhalt. Gemessen wird gegen einen gleitenden Hintergrund
(Schliessen: erst Maximum, dann Minimum ueber etwa ein Zwanzigstel der
Bildkante), so stoeren Vignette und leichtes Uebersprechen des Bildes nicht.

Nicht jeder Infrarotkanal stammt von Film: Luftbilder zeigen im Nah-Infrarot
die Landschaft, Schwarzweissfilm mit Silberkorn und Kodachrome halten Infrarot
selbst auf. Dann schwankt der Hintergrund stark und ein grosser Teil des
Bildes waere "Staub" - ist_filmscan() lehnt solche Kanaele ab.

Gefuellt wird in zwei Arten:
  - kleine Punkte und duenne Kratzer - meist Tausende - auf der Grafikkarte:
    jede Stelle aus ihrer naechsten Umgebung, gewichtet gemittelt;
  - breite Stellen (Fusseln, Flecken) mit LaMa, jede in ihrer Umgebung.
LaMa sieht dafuer das Positiv; seine Fuellung wird in die Werte des Scans
zurueckgerechnet (film.zurueck). So bleibt die Fuellung gueltig, wenn die
Umwandlung des Negativs danach noch geaendert wird.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

from collections.abc import Callable

from . import film, filter
from .cuda import cupy as cp

EMPFINDLICHKEIT = 50          # Vorgabe des Reglers, 0..100
SCHWELLE_GROB = 0.30          # Empfindlichkeit 0: so viel dunkler als der Film muss es sein
SCHWELLE_FEIN = 0.06          # Empfindlichkeit 100
RAUSCH_SIGMA = 1.0            # so wenig wird das Infrarot vor der Suche geglaettet
HINTERGRUND_ANTEIL = 0.05     # Groesse des Schliessens als Anteil der laengsten Kante
SAUM_PX = 2                   # so weit waechst eine Stelle in ihren schwaecheren Rand
RAND_PX = 1                   # und danach noch einmal ohne Bedingung
PRUEF_KANTE = 1500            # die Pruefung auf Filmscan rechnet in dieser Groesse
FILM_SCHWANKUNG = 0.25        # hoechstens so stark schwankt der Hintergrund bei Film
FILM_ANTEIL = 0.08            # hoechstens so viel des Bildes ist bei Film "Staub"
PRUEF_SCHWELLE = 0.1
BREIT_PX = 6                  # Stellen, deren Kern nach so viel Abtragen bleibt, fuellt LaMa
LAMA_HOECHSTENS = 200         # die groessten so vielen; alle weiteren fuellt die Grafikkarte
GLATT_SIGMAS = (1.5, 3.0, 6.0, 12.0, 24.0, 48.0, 96.0)
GLATT_STUETZE = 0.1           # so viel gueltige Umgebung braucht eine Fuellung je Massstab


def normiert(infrarot):
    """Infrarotkanal (uint8 oder uint16) als float32 0..1 auf der Grafikkarte."""
    hoechst = 65535.0 if infrarot.dtype.itemsize == 2 else 255.0
    return cp.asarray(infrarot, dtype=cp.float32) / cp.float32(hoechst)


def _hintergrund(ir):
    """Der Film ohne seine Fehler: Schliessen, dann leicht geglaettet."""
    from cupyx.scipy import ndimage
    groesse = max(31, round(max(ir.shape) * HINTERGRUND_ANTEIL) | 1)
    hinter = ndimage.minimum_filter(ndimage.maximum_filter(ir, size=groesse, mode="nearest"),
                                    size=groesse, mode="nearest")
    return filter.gauss(hinter, groesse / 4)


def dunkelheit(ir):
    """Wie viel dunkler jede Stelle ist als der Film um sie herum: 0 = gar nicht, 1 = ganz.
    Leicht geglaettet, sonst hebt das Rauschen des Kanals den Hintergrund an."""
    glatt = filter.gauss(ir, RAUSCH_SIGMA)
    hinter = _hintergrund(glatt)
    return cp.clip(1 - glatt / cp.maximum(hinter, cp.float32(1e-4)), 0, 1)


def ist_filmscan(ir) -> bool:
    """Sieht der Infrarotkanal nach Film aus? Gleichmaessig hell mit wenigen dunklen
    Stellen - nicht die Landschaft eines Luftbildes und nicht das Bild selbst."""
    faktor = max(1, -(-max(ir.shape) // PRUEF_KANTE))
    klein = filter.gauss(filter.verkleinern_box(ir, faktor).astype(cp.float32), RAUSCH_SIGMA)
    hinter = _hintergrund(klein)
    schwankung = float(cp.std(hinter) / cp.maximum(cp.mean(hinter), 1e-4))
    dunkel = cp.clip(1 - klein / cp.maximum(hinter, cp.float32(1e-4)), 0, 1)
    anteil = float((dunkel > PRUEF_SCHWELLE).mean())
    return schwankung < FILM_SCHWANKUNG and anteil < FILM_ANTEIL


def schwelle(empfindlichkeit: float) -> float:
    anteil = min(max(empfindlichkeit, 0.0), 100.0) / 100
    return SCHWELLE_GROB - (SCHWELLE_GROB - SCHWELLE_FEIN) * anteil


def _wachsen(maske, px: int):
    """Eine Maske um px Pixel wachsen lassen (Quadrat)."""
    from cupyx.scipy import ndimage
    return ndimage.maximum_filter(maske.view(cp.uint8), size=2 * px + 1).view(bool)


def _schrumpfen(maske, px: int):
    from cupyx.scipy import ndimage
    return ndimage.minimum_filter(maske.view(cp.uint8), size=2 * px + 1,
                                  mode="constant", cval=1).view(bool)


def finden(dunkel, empfindlichkeit: float) -> tuple:
    """Maske der Fehler (H, W) bool, ihr Kern (was deutlich dunkel ist) und die Anzahl.
    Eine Stelle waechst in ihren schwaecheren Rand und um einen Pixel darueber - Staub ist
    im Scan etwas unscharf."""
    from cupyx.scipy import ndimage
    grenze = schwelle(empfindlichkeit)
    kern = dunkel > grenze
    saum = _wachsen(kern, SAUM_PX) & (dunkel > grenze / 3)
    maske = _wachsen(kern | saum, RAND_PX)
    _stellen, anzahl = ndimage.label(maske)
    return maske, kern, int(anzahl)


def glatt_fuellen(bild, maske):
    """Jede markierte Stelle aus ihrer Umgebung fuellen: mit dem gewichteten Mittel der
    gueltigen Nachbarn im kleinsten Massstab, der genug davon hat."""
    gueltig = (~maske).astype(cp.float32)
    ergebnis = bild.copy()
    offen = maske.copy()
    for sigma in GLATT_SIGMAS:
        if not bool(offen.any()):
            break
        weich = filter.gauss if sigma <= 8 else filter.grob_weichzeichnen
        gewicht = weich(gueltig, sigma)
        jetzt = offen & (gewicht > GLATT_STUETZE)
        if not bool(jetzt.any()):
            continue
        for kanal in range(3):
            summe = weich(bild[..., kanal] * gueltig, sigma)
            ergebnis[..., kanal][jetzt] = (summe / cp.maximum(gewicht, 1e-6))[jetzt]
        offen &= ~jetzt
    if bool(offen.any()):
        mittel = bild[~maske].mean(axis=0) if bool((~maske).any()) else bild.mean(axis=(0, 1))
        ergebnis[offen] = mittel
    return ergebnis


def breite_stellen(maske, kern) -> tuple:
    """Die Stellen, die zu breit fuer die glatte Fuellung sind: (Beschriftung, Nummern),
    die groessten zuerst. Gemessen am Kern - der Saum macht jeden Punkt einige Pixel
    breiter."""
    from cupyx.scipy import ndimage
    stellen, _anzahl = ndimage.label(maske)
    innen = _schrumpfen(kern, BREIT_PX)
    nummern = cp.unique(stellen[innen])
    nummern = nummern[nummern > 0]
    if nummern.size == 0:
        return stellen, []
    flaechen = cp.bincount(stellen.ravel())[nummern]
    return stellen, [int(n) for n in cp.asnumpy(nummern[cp.argsort(-flaechen)])]


def entfernen(scan, maske, kern, art: str, film_maske: tuple, film_umfang: tuple,
              entferner=None, fortschritt: Callable[[int, int], bool] | None = None):
    """Den Scan (linear, (H, W, 3)) an den markierten Stellen fuellen - in den Werten des
    Scans, also vor der Umwandlung eines Negativs. Mit entferner (LaMa) werden breite
    Stellen von der KI gefuellt, sonst alle auf der Grafikkarte."""
    ergebnis = glatt_fuellen(scan, maske)
    if entferner is None:
        return ergebnis
    stellen, nummern = breite_stellen(maske, kern)
    nummern = nummern[:LAMA_HOECHSTENS]
    if not nummern:
        return ergebnis
    positiv = film.umkehren(ergebnis, art, film_maske, film_umfang)
    srgb = filter.linear_zu_srgb(cp.clip(positiv, 0, 1))
    del positiv
    for i, nummer in enumerate(nummern):
        teil = entferner.fuellen(srgb, (stellen == nummer).astype(cp.float32))
        if teil is not None:
            y0, y1, x0, x1, fuellung, deckkraft = teil
            fuellung = film.zurueck(filter.srgb_zu_linear(fuellung), art, film_maske,
                                    film_umfang)
            d = deckkraft[..., None]
            bereich = ergebnis[y0:y1, x0:x1]
            bereich *= 1 - d
            bereich += d * fuellung
        if fortschritt is not None and fortschritt(i + 1, len(nummern)) is False:
            break                                 # abgebrochen: der Rest bleibt glatt gefuellt
    return ergebnis
