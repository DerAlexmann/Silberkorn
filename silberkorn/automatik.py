"""
Automatik: Auto-Ton, Auto-Weissabgleich, Weissabgleich-Pipette und Auto-Begradigen

Reine Rechenfunktionen ohne Qt und ohne Sitzung - die Oberflaeche ruft sie auf und
setzt nur die vorhandenen Reglerwerte. Eine neue Bildformel gibt es hier nicht: Der
Auto-Ton fragt ueber `render` die echte Filterkette der Sitzung und schliesst aus den
Ergebnissen auf Belichtung, Kontrast, Lichter und Tiefen; der Weissabgleich misst nur
und kehrt die Formel von `filter.weissabgleich` um; das Begradigen misst die Richtung
der Kanten und findet den Winkel, bei dem Waagrechte und Senkrechte gerade stehen.

Alles rechnet mit NumPy oder CuPy (`filter.xp_von`); die Ergebnisse sind Zahlen auf dem
Reglerraster, damit mehrfaches Druecken dasselbe ergibt.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from . import filter as f

# ---------------------------------------------------------------------------
# Weissabgleich
# ---------------------------------------------------------------------------

# So stark wirken Temperatur und Toenung 100 in filter.weissabgleich (dort und im Kernel
# als Zahl geschrieben; test_automatik prueft beide Wege gegen diese Werte)
WB_TEMPERATUR = 0.35
WB_TOENUNG = 0.25
WB_KLEIN = 0.002                 # darunter ist ein Kanal Rauschen / abgeschnitten (linear)
WB_GROSS = 0.97                  # darueber ist ein Kanal abgeschnitten (linear)
WB_PERZENTILE = (5.0, 95.0)      # nur die Mitte der Helligkeiten zaehlt
WB_NEUTRAL = 33.0                # so viel Prozent der Pixel, die am wenigsten bunten, zaehlen
WB_MINDEST_ANTEIL = 0.01         # so viele Pixel muessen mindestens uebrig bleiben
WB_MINDEST_PIXEL = 16
STICHPROBE = 300_000             # hoechstens so viele Pixel werden gemessen


def _stichprobe(bild):
    """Jedes n-te Pixel in Zeile und Spalte, damit die Messung auch bei 100 Megapixeln
    schnell bleibt."""
    schritt = max(1, math.ceil(math.sqrt(bild.shape[0] * bild.shape[1] / STICHPROBE)))
    return bild[::schritt, ::schritt]


def weissabgleich_aus_mittel(rot: float, gruen: float, blau: float,
                             ) -> tuple[float, float] | None:
    """Temperatur und Toenung, die den Bezug mit diesen linearen Mittelwerten neutral
    machen (Umkehrung von filter.weissabgleich), auf Reglerbereich und -schritt
    gebracht. None, wenn ein Kanal fehlt oder nicht endlich ist."""
    werte = (rot, gruen, blau)
    if not all(math.isfinite(w) and w > 1e-6 for w in werte):
        return None
    k = math.log(blau / rot) / 2
    m = math.log(gruen / math.sqrt(rot * blau))
    temperatur = _auf_regler("temperatur", k / WB_TEMPERATUR * 100)
    toenung = _auf_regler("toenung", m / WB_TOENUNG * 100)
    return temperatur, toenung


def _auf_regler(name: str, wert: float) -> float:
    """Auf den Bereich und das Raster des Reglers."""
    regler = f.REGLER_NACH_NAME[name]
    wert = min(regler.maximum, max(regler.minimum, wert))
    return round(round(wert / regler.schritt) * regler.schritt, regler.nachkomma)


def _mittel(pixel) -> tuple[float, float, float]:
    rot, gruen, blau = (float(w) for w in pixel.mean(axis=0))
    return rot, gruen, blau


def weissabgleich_auto(rgb_linear) -> tuple[float, float] | None:
    """Grauwelt: Das Bild im Mittel neutral machen - robust gemacht.

    Es zaehlen nur Pixel ohne abgeschnittenen oder abgesoffenen Kanal und mit einer
    Helligkeit zwischen dem 5. und 95. Perzentil, davon die am wenigsten bunten Drittel - so
    ziehen grosse farbige Flaechen (Wiese, Himmel) das Ergebnis nicht auf ihre Seite.
    rgb_linear: (H, W, 3), linear.

    Rueckgabe (Temperatur, Toenung) oder None, wenn zu wenig Messbares da ist (leeres,
    einfarbiges oder fast schwarzes oder weisses Bild).
    """
    xp = f.xp_von(rgb_linear)
    bild = _stichprobe(rgb_linear).reshape(-1, 3).astype(xp.float32)
    ok = (bild.min(axis=1) > WB_KLEIN) & (bild.max(axis=1) < WB_GROSS) \
        & xp.isfinite(bild).all(axis=1)
    if int(ok.sum()) < max(WB_MINDEST_PIXEL, WB_MINDEST_ANTEIL * bild.shape[0]):
        return None
    bild = bild[ok]
    hell = f.luminanz(bild)
    unten, oben = (float(w) for w in xp.percentile(hell, xp.asarray(WB_PERZENTILE)))
    mitte = bild[(hell >= unten) & (hell <= oben)]
    if mitte.shape[0] < WB_MINDEST_PIXEL:
        return None
    # Die am wenigsten bunten: bei einem Farbstich ist jedes Pixel etwas bunt, aber grosse
    # farbige Flaechen (Wiese, Himmel) sind es deutlich mehr als alles Neutrale
    bunt = (mitte.max(axis=1) - mitte.min(axis=1)) / xp.maximum(mitte.max(axis=1), f.EPS)
    neutral = mitte[bunt <= xp.percentile(bunt, WB_NEUTRAL)]
    if neutral.shape[0] < WB_MINDEST_PIXEL:
        neutral = mitte
    return weissabgleich_aus_mittel(*_mittel(neutral))


def weissabgleich_punkt(rgb_linear, x: float, y: float, radius: int = 2,
                        ) -> tuple[float, float] | None:
    """Pipette: Temperatur und Toenung, die die Umgebung von (x, y) neutral machen.
    Gemittelt wird ein Quadrat von (2*radius+1) Pixeln Seitenlaenge (linear). None, wenn
    der Punkt dafuer nicht taugt: zu dunkel oder ein Kanal abgeschnitten."""
    hoehe, breite = rgb_linear.shape[:2]
    cx, cy = int(x), int(y)
    if not (0 <= cx < breite and 0 <= cy < hoehe):
        return None
    feld = rgb_linear[max(0, cy - radius):cy + radius + 1, max(0, cx - radius):cx + radius + 1]
    mittel = _mittel(feld.reshape(-1, 3))
    if not all(math.isfinite(w) and WB_KLEIN < w < WB_GROSS for w in mittel):
        return None
    return weissabgleich_aus_mittel(*mittel)


# ---------------------------------------------------------------------------
# Ton
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ton:
    """Die vier Werte, die der Auto-Ton setzt (Namen wie in filter.Einstellungen)."""
    belichtung: float = 0.0
    kontrast: float = 0.0
    lichter: float = 0.0
    tiefen: float = 0.0

    def felder(self) -> dict[str, float]:
        return dataclasses.asdict(self)


MITTELGRAU = 0.18                # Ziel fuer den Median der Helligkeit (linear)
EV_TOTZONE = 0.2                 # so weit darf der Median von Mittelgrau abweichen (EV)
EV_GRENZE = 2.0                  # hoechstens so viele Lichtwerte
LICHTER_REST = 0.3               # so weit duerfen Lichter ueber das Weiss hinaus wachsen (EV)
ABGESCHNITTEN = (2.0, 0.985, 0.02)    # Toleranz in Prozent; Weiss ab (sRGB); Schwarz bis (sRGB)
SPREIZUNG_OK = 0.5               # Abstand 5.-95. Perzentil (sRGB), ab dem nichts zu tun ist
KONTRAST_MAX = 60
LICHTER_MAX = 80
TIEFEN_MAX = 40


@dataclass(frozen=True)
class _Hell:
    """Kennzahlen der Helligkeit eines Bildes (sRGB-kodiert, 0..1)."""
    median: float
    p5: float
    p95: float
    p98: float
    weiss: float                 # Anteil in Prozent im Weiss
    schwarz: float               # Anteil in Prozent im Schwarz


def _messen(bild_8bit) -> _Hell:
    """Kennzahlen aus einem sRGB-Bild (uint8, GPU oder CPU)."""
    xp = f.xp_von(bild_8bit)
    probe = _stichprobe(bild_8bit)
    v = f.linear_zu_srgb(f.luminanz(f.von_8bit(probe))).reshape(-1)
    v = np.asarray(xp.asnumpy(v) if xp is not np else v, dtype=np.float64)
    if v.size == 0:
        return _Hell(0.5, 0.5, 0.5, 0.5, 0.0, 0.0)
    p5, median, p95, p98 = (float(w) for w in np.quantile(v, [0.05, 0.5, 0.95, 0.98]))
    _toleranz, weiss, schwarz = ABGESCHNITTEN
    return _Hell(median, p5, p95, p98, float(np.mean(v >= weiss)) * 100,
                 float(np.mean(v <= schwarz)) * 100)


def _lichtwerte(hell: float) -> float:
    """Lichtwerte, um die der sRGB-kodierte Wert `hell` ueber oder unter Mittelgrau liegt."""
    lin = float(f.srgb_zu_linear(np.asarray([hell], dtype=np.float32))[0])
    return math.log2(max(lin, 1e-4) / MITTELGRAU)


def _belichtung_runden(ev: float) -> float:
    ev = min(EV_GRENZE, max(-EV_GRENZE, ev))
    return round(round(ev / 0.05) * 0.05, 2)


def _fuenfer(wert: float, grenze: float) -> float:
    return float(min(grenze, max(0, 5 * round(wert / 5))))


def _belichtung_fuer(hell: _Hell, bisher: float = 0.0) -> float:
    """Belichtung (gesamt, mit `bisher` schon eingerechnet), die den Median auf Mittelgrau
    bringt - ohne die Lichter ueber das Weiss zu schieben."""
    # Bis zum Rand der Totzone, nicht darueber hinaus: ein gut belichtetes Bild bleibt, wie es
    # ist, und der Uebergang hat keine Stufe
    roh = -_lichtwerte(hell.median)
    fehlt = math.copysign(max(0.0, abs(roh) - EV_TOTZONE), roh)
    ziel = bisher + fehlt
    if fehlt > 0:
        # Die hellsten 2 % duerfen nicht weit ueber das Weiss wachsen
        platz = -_lichtwerte(hell.p98) + math.log2(1 / MITTELGRAU) + LICHTER_REST
        ziel = min(ziel, bisher + max(0.0, platz))
    return _belichtung_runden(ziel)


def ton_automatisch(render: Callable[[Ton], object]) -> Ton:
    """Belichtung, Kontrast, Lichter und Tiefen, die das Bild ausgewogen machen.

    `render(ton)` liefert das fertige sRGB-Bild (uint8, H x W x 3) der echten Filterkette
    mit diesen vier Werten (und allem anderen, wie es gerade eingestellt ist) - im
    Zuschnitt, wenn das Bild zugeschnitten ist. Lichter, Tiefen und Kontrast wirken
    nichtlinear und aufeinander, darum wird gemessen statt gerechnet:

    1. ohne alle vier: Median auf Mittelgrau heben oder senken, hoechstens ±2 EV und
       ohne die Lichter weit ueber das Weiss zu schieben;
    2. mit dieser Belichtung: Lichter zurueck, wo viel im Weiss liegt, Tiefen auf, wo viel
       im Schwarz liegt, Kontrast, wo das Bild flau ist;
    3. mit allem: die Belichtung noch einmal nachziehen, weil Lichter und Tiefen den
       Median verschoben haben.

    Die Messung geht immer von den vier Werten auf 0 aus - mehrfaches Druecken gibt
    dasselbe. Ein gut belichtetes Bild bleibt fast unveraendert.
    """
    basis = _messen(render(Ton()))
    belichtung = _belichtung_fuer(basis)
    hell = _messen(render(Ton(belichtung=belichtung)))
    toleranz = ABGESCHNITTEN[0]
    lichter = tiefen = kontrast = 0.0
    if hell.weiss > toleranz:
        lichter = -_fuenfer(10 + 10 * (hell.weiss - toleranz), LICHTER_MAX)
    if hell.schwarz > toleranz:
        tiefen = _fuenfer(10 + 8 * (hell.schwarz - toleranz), TIEFEN_MAX)
    spreizung = hell.p95 - hell.p5
    if spreizung < SPREIZUNG_OK:
        # Die Kurve wirkt in der Mitte mit der Steigung 1 + Kontrast/200
        kontrast = _fuenfer(200 * (SPREIZUNG_OK / max(spreizung, 0.05) - 1), KONTRAST_MAX)
    ton = Ton(belichtung, kontrast, lichter, tiefen)
    if lichter or tiefen or kontrast:
        nach = _messen(render(ton))
        ton = dataclasses.replace(ton, belichtung=_belichtung_fuer(nach, belichtung))
    return ton


# ---------------------------------------------------------------------------
# Begradigen
# ---------------------------------------------------------------------------

NEIGUNG_BEREICH = 20.0           # so weit darf das Bild schief sein (Grad), mehr wird nicht gesucht
NEIGUNG_PIXEL = 1_000_000        # auf so viele Pixel wird zum Messen verkleinert
NEIGUNG_GLAETTEN = 1.0           # Unschaerfe vor den Kanten (Pixel des verkleinerten Bildes)
NEIGUNG_STUFE = 0.25             # Breite eines Histogrammfachs (Grad)
NEIGUNG_FENSTER = 1.5            # um den Gipfel zaehlt dieser Abstand (Grad)
NEIGUNG_KANTE = 0.25             # nur Kanten ab diesem Anteil der 99. Perzentil-Staerke zaehlen
NEIGUNG_KANTE_MIN = 0.02         # und mindestens so stark (Unterschied in sRGB-Helligkeit)
NEIGUNG_MIN_PIXEL = 500          # so viele Kantenpixel braucht es mindestens
NEIGUNG_MIN_ANTEIL = 0.002       # ... und so viel Anteil an allen Pixeln
NEIGUNG_KLAR = 4.0               # der Gipfel muss so viel mal ueber dem Durchschnitt liegen


def _verkleinern(bild):
    """Blockmittel auf etwa NEIGUNG_PIXEL - mittelt statt auszulassen, damit feine Linien
    nicht zu Treppen werden."""
    hoehe, breite = bild.shape
    schritt = max(1, math.ceil(math.sqrt(hoehe * breite / NEIGUNG_PIXEL)))
    if schritt == 1:
        return bild
    h, b = hoehe // schritt * schritt, breite // schritt * schritt
    return bild[:h, :b].reshape(h // schritt, schritt, b // schritt, schritt).mean(axis=(1, 3))


def neigung(rgb_linear) -> float | None:
    """Winkel fuer den Regler `begradigen`, der das Bild gerade stellt, oder None.

    Gemessen wird die Richtung der Kanten, gewichtet nach Staerke; was waagrecht oder
    senkrecht sein soll, haeuft sich um den Winkel der Schieflage (beide Richtungen zaehlen
    zusammen). Gesucht wird nur bis ±NEIGUNG_BEREICH. Der Wert gilt fuer das Bild, wie es
    ist: ohne Drehen und Spiegeln (die rechnet die Sitzung um) und ohne Perspektive.
    rgb_linear: (H, W, 3), linear.

    None, wenn zu wenig Kanten da sind oder sich keine Richtung deutlich haeuft (Wolken,
    Rauschen, Muster in alle Richtungen).
    """
    if min(rgb_linear.shape[:2]) < 16:
        return None
    xp = f.xp_von(rgb_linear)
    hell = f.linear_zu_srgb(xp.clip(f.luminanz(rgb_linear.astype(xp.float32)), 0, 1))
    hell = f.gauss(_verkleinern(hell), NEIGUNG_GLAETTEN)
    # Sobel
    gx = (hell[:-2, 2:] + 2 * hell[1:-1, 2:] + hell[2:, 2:]
          - hell[:-2, :-2] - 2 * hell[1:-1, :-2] - hell[2:, :-2]) / 8
    gy = (hell[2:, :-2] + 2 * hell[2:, 1:-1] + hell[2:, 2:]
          - hell[:-2, :-2] - 2 * hell[:-2, 1:-1] - hell[:-2, 2:]) / 8
    staerke = xp.sqrt(gx * gx + gy * gy)
    grenze = max(NEIGUNG_KANTE_MIN, NEIGUNG_KANTE * float(xp.percentile(staerke, 99)))
    stark = staerke > grenze
    anzahl = int(stark.sum())
    if anzahl < max(NEIGUNG_MIN_PIXEL, NEIGUNG_MIN_ANTEIL * staerke.size):
        return None
    # Richtung der Linie (y nach unten) ist senkrecht zum Verlauf; Abstand zur naechsten
    # Waagrechten oder Senkrechten in [-45, 45)
    linie = xp.degrees(xp.arctan2(gx[stark], -gy[stark]))
    abweichung = (linie + 45.0) % 90.0 - 45.0
    abweichung = np.asarray(xp.asnumpy(abweichung) if xp is not np else abweichung,
                            dtype=np.float64)
    gewicht = np.asarray(xp.asnumpy(staerke[stark]) if xp is not np else staerke[stark],
                         dtype=np.float64)
    faecher = np.arange(-45.0, 45.0 + NEIGUNG_STUFE, NEIGUNG_STUFE)
    histogramm, _ = np.histogram(abweichung, bins=faecher, weights=gewicht)
    mitten = (faecher[:-1] + faecher[1:]) / 2
    breite = max(1, round(NEIGUNG_FENSTER / NEIGUNG_STUFE))
    summe = np.convolve(histogramm, np.ones(2 * breite + 1), mode="same")
    erlaubt = np.abs(mitten) <= NEIGUNG_BEREICH
    if not erlaubt.any():
        return None
    gipfel = int(np.argmax(np.where(erlaubt, summe, -1.0)))
    mitte = float(mitten[gipfel])
    nah = np.abs(abweichung - mitte) <= NEIGUNG_FENSTER
    anteil = float(gewicht[nah].sum()) / float(gewicht.sum())
    gleichverteilt = 2 * NEIGUNG_FENSTER / 90.0
    if anteil < NEIGUNG_KLAR * gleichverteilt:
        return None
    schief = float(np.average(abweichung[nah], weights=gewicht[nah]))
    return _auf_regler("begradigen", -schief)


def begradigen_fuer(winkel: float, spiegeln: bool) -> float:
    """Der Reglerwert, der ein Bild mit der Schieflage `winkel` (aus `neigung`) gerade
    stellt, wenn es gespiegelt wird. Begradigen wirkt vor dem Spiegeln und der Drehung um
    90 Grad (geometrie._rueckwaerts): Im Spiegelbild steht die Schieflage andersherum, die
    Vierteldrehung aendert sie nicht."""
    return _auf_regler("begradigen", -winkel if spiegeln else winkel)
