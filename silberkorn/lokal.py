"""
Lokale Anpassungen: Masken aus Teilen, je Maske eigene Regler

Eine Maske ist ein Bereich des Bildes mit eigenen Werten fuer Weissabgleich,
Belichtung, Tonwerte, Klarheit, Dunst, Saettigung und Schaerfe. Den Bereich
bilden ihre Teile - Verlauf und Radial -, die hinzugefuegt, abgezogen oder
geschnitten werden; jeder Teil laesst sich umkehren.

Die Teile liegen im Original: Punkte als Anteil von Breite und Hoehe (0..1),
Laengen als Anteil der langen Kante. So folgen sie Drehen, Begradigen und
Zuschnitt und passen auch auf ein Bild anderer Groesse (Voreinstellungen).
Gerastert wird auf dem Gitter der Leinwand, in der Groesse von Vorschau oder
Original; die Sitzung bringt das Ergebnis in die Geometrie des fertigen
Bildes.

Gewirkt wird nach der Geometrie, vor den Tonwerten des ganzen Bildes: Aus
allen Masken entsteht je Regler eine Karte (Summe aus Gewicht mal Wert), und
dieselben Formeln wie fuer das ganze Bild rechnen damit je Pixel. Ueberlappen
sich zwei Masken, addieren sich ihre Werte.

Alles hier laeuft mit NumPy und mit CuPy - auf dem Array, das hereinkommt.
Die Daten sind unveraenderlich (frozen), damit Rueckgaengig sie als Teil der
Einstellungen kopieren und vergleichen kann.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import filter as f

ARTEN = ("verlauf", "radial")
MODI = ("dazu", "weg", "schnitt")
MAX_MASKEN = 10
MAX_TEILE = 20
MAX_NAME = 60

# Die Regler einer Maske, in dieser Reihenfolge in Maske.werte
REGLER = (
    f.Regler("temperatur", "lokal", -100, 100),
    f.Regler("toenung", "lokal", -100, 100),
    f.Regler("belichtung", "lokal", -4.0, 4.0, schritt=0.05, nachkomma=2),
    f.Regler("kontrast", "lokal", -100, 100),
    f.Regler("lichter", "lokal", -100, 100),
    f.Regler("tiefen", "lokal", -100, 100),
    f.Regler("klarheit", "lokal", -100, 100),
    f.Regler("dunst", "lokal", -100, 100),
    f.Regler("saettigung", "lokal", -100, 100),
    f.Regler("schaerfe", "lokal", -100, 100),
)
NAMEN = tuple(r.name for r in REGLER)
NEUTRAL = (0.0,) * len(REGLER)

# Daten je Art: (Name, kleinster, groesster Wert)
DATEN = {
    # Punkt A (volle Wirkung) und B (keine) als Anteil von Breite und Hoehe
    "verlauf": (("ax", -1.0, 2.0), ("ay", -1.0, 2.0), ("bx", -1.0, 2.0), ("by", -1.0, 2.0)),
    # Mitte, Halbachsen als Anteil der langen Kante, Drehung in Grad, weicher Rand in %
    "radial": (("cx", -1.0, 2.0), ("cy", -1.0, 2.0), ("rx", 0.002, 2.0), ("ry", 0.002, 2.0),
               ("winkel", -180.0, 180.0), ("weich", 0.0, 100.0)),
}
RADIAL_WEICH = 50.0              # weicher Rand eines neuen Radialfilters
SCHAERFE_RADIUS = 1.0            # Radius des lokalen Schaerfens in Pixeln des Originals
WEICH_SIGMA = 4.0                # Schaerfe -100 zeichnet mit diesem Sigma weich (Original)


@dataclass(frozen=True)
class Teil:
    art: str
    daten: tuple[float, ...]
    modus: str = "dazu"
    umkehren: bool = False


@dataclass(frozen=True)
class Maske:
    name: str
    teile: tuple[Teil, ...] = ()
    werte: tuple[float, ...] = NEUTRAL
    an: bool = True

    def wirkt(self) -> bool:
        return self.an and bool(self.teile) and any(self.werte)


def wert(maske: Maske, name: str) -> float:
    return maske.werte[NAMEN.index(name)]


def mit_wert(maske: Maske, name: str, neu: float) -> Maske:
    werte = list(maske.werte)
    werte[NAMEN.index(name)] = float(neu)
    return Maske(maske.name, maske.teile, tuple(werte), maske.an)


def daten_begrenzen(art: str, daten) -> tuple[float, ...]:
    return tuple(min(max(float(wert), unten), oben)
                 for wert, (_name, unten, oben) in zip(daten, DATEN[art], strict=True))


# --------------------------------------------------------------------------
# Bearbeiten auf der Leinwand - alles in Pixeln des Originals
# --------------------------------------------------------------------------

NEU_MINDESTENS = 0.01            # kuerzer gezogen (Anteil der langen Kante) gilt als Klick
RADIAL_KLICK = 0.15              # ein Klick legt einen Radialfilter dieser Groesse an
DREH_ABSTAND = 0.06              # Drehgriff so weit (lange Kante) ueber der Ellipse


def _radial_achsen(teil: Teil, breite: float, hoehe: float):
    cx, cy, rx, ry, winkel, _weich = teil.daten
    lang = max(breite, hoehe)
    c, s = math.cos(math.radians(winkel)), math.sin(math.radians(winkel))
    return (cx * breite, cy * hoehe), (c, s), (-s, c), rx * lang, ry * lang


def griffe(teil: Teil, breite: float, hoehe: float) -> dict[str, tuple[float, float]]:
    """Die Griffe eines Teils im Original."""
    if teil.art == "verlauf":
        ax, ay, bx, by = teil.daten
        a, b = (ax * breite, ay * hoehe), (bx * breite, by * hoehe)
        return {"a": a, "b": b, "mitte": ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)}
    (mx, my), eu, ev, ru, rv = _radial_achsen(teil, breite, hoehe)
    dreh = rv + DREH_ABSTAND * max(breite, hoehe)
    return {"mitte": (mx, my),
            "x+": (mx + eu[0] * ru, my + eu[1] * ru), "x-": (mx - eu[0] * ru, my - eu[1] * ru),
            "y+": (mx + ev[0] * rv, my + ev[1] * rv), "y-": (mx - ev[0] * rv, my - ev[1] * rv),
            "dreh": (mx - ev[0] * dreh, my - ev[1] * dreh)}


def linien(teil: Teil, breite: float, hoehe: float) -> list[np.ndarray]:
    """Was die Leinwand von einem Teil zeichnet - Linienzuege (n, 2) im Original."""
    lang = max(breite, hoehe)
    if teil.art == "verlauf":
        g = griffe(teil, breite, hoehe)
        a, b = np.array(g["a"]), np.array(g["b"])
        richtung = b - a
        laenge = float(np.hypot(*richtung)) or 1.0
        quer = np.array([-richtung[1], richtung[0]]) / laenge
        t = np.linspace(-2 * lang, 2 * lang, 33)[:, None]
        return [p + quer * t for p in (a, (a + b) / 2, b)] + [np.stack([a, b])]
    (mx, my), eu, ev, ru, rv = _radial_achsen(teil, breite, hoehe)
    w = np.linspace(0, 2 * np.pi, 73)[:, None]
    mitte, eu, ev = np.array([mx, my]), np.array(eu), np.array(ev)
    ellipse = mitte + eu * ru * np.cos(w) + ev * rv * np.sin(w)
    innen = 1 - teil.daten[5] / 100
    zuege = [ellipse]
    if 0.02 < innen < 0.98:
        zuege.append(mitte + (eu * ru * np.cos(w) + ev * rv * np.sin(w)) * innen)
    dreh = rv + DREH_ABSTAND * lang
    zuege.append(np.stack([mitte - ev * rv, mitte - ev * dreh]))
    return zuege


def neuer_teil(art: str, a, b, breite: float, hoehe: float) -> Teil | None:
    """Teil aus einem Zug von a nach b; None, wenn es nur ein Klick war (beim Verlauf)."""
    lang = max(breite, hoehe)
    weit = math.hypot(b[0] - a[0], b[1] - a[1]) >= NEU_MINDESTENS * lang
    if art == "verlauf":
        if not weit:
            return None
        daten = (a[0] / breite, a[1] / hoehe, b[0] / breite, b[1] / hoehe)
    else:
        rx = abs(b[0] - a[0]) / lang if weit else RADIAL_KLICK
        ry = abs(b[1] - a[1]) / lang if weit else RADIAL_KLICK
        daten = (a[0] / breite, a[1] / hoehe, rx, ry, 0.0, RADIAL_WEICH)
    return Teil(art, daten_begrenzen(art, daten))


def gezogen(teil: Teil, griff: str, a, b, breite: float, hoehe: float) -> Teil:
    """Der Teil, nachdem sein Griff von a nach b gezogen wurde."""
    dx, dy = (b[0] - a[0]) / breite, (b[1] - a[1]) / hoehe
    daten = list(teil.daten)
    if teil.art == "verlauf":
        if griff in ("a", "mitte"):
            daten[0] += dx
            daten[1] += dy
        if griff in ("b", "mitte"):
            daten[2] += dx
            daten[3] += dy
    else:
        lang = max(breite, hoehe)
        (mx, my), eu, ev, _ru, _rv = _radial_achsen(teil, breite, hoehe)
        px, py = b[0] - mx, b[1] - my
        if griff == "mitte":
            daten[0] += dx
            daten[1] += dy
        elif griff in ("x+", "x-"):
            daten[2] = abs(px * eu[0] + py * eu[1]) / lang
        elif griff in ("y+", "y-"):
            daten[3] = abs(px * ev[0] + py * ev[1]) / lang
        elif griff == "dreh":
            winkel = math.degrees(math.atan2(py, px)) + 90.0
            daten[4] = (winkel + 180.0) % 360.0 - 180.0
    return Teil(teil.art, daten_begrenzen(teil.art, daten), teil.modus, teil.umkehren)


# --------------------------------------------------------------------------
# Rastern
# --------------------------------------------------------------------------

def _teil_gewicht(teil: Teil, x, y, breite: float, hoehe: float):
    """Wirkung 0..1 eines Teils an den Stellen (x, y) in Pixeln des Originals."""
    xp = f.xp_von(x)
    if teil.art == "verlauf":
        ax, ay, bx, by = teil.daten
        ax, bx, ay, by = ax * breite, bx * breite, ay * hoehe, by * hoehe
        dx, dy = bx - ax, by - ay
        laenge = max(dx * dx + dy * dy, 1e-6)
        t = ((x - ax) * dx + (y - ay) * dy) / xp.float32(laenge)
        gewicht = 1 - f._glatt(xp, 0.0, 1.0, t)
    else:
        cx, cy, rx, ry, winkel, weich = teil.daten
        lang = max(breite, hoehe)
        c, s = math.cos(math.radians(winkel)), math.sin(math.radians(winkel))
        dx, dy = x - cx * breite, y - cy * hoehe
        u = (dx * c + dy * s) / xp.float32(rx * lang)
        v = (-dx * s + dy * c) / xp.float32(ry * lang)
        r = xp.sqrt(u * u + v * v)
        innen = min(1 - weich / 100, 0.999)
        gewicht = 1 - f._glatt(xp, innen, 1.0, r)
    gewicht = gewicht.astype(xp.float32)
    return 1 - gewicht if teil.umkehren else gewicht


def gewicht(maske: Maske, hoehe: int, breite: int, original: tuple[int, int],
            versatz: tuple[int, int] = (0, 0), faktor: tuple[float, float] | None = None,
            xp=np):
    """Wirkung der Maske (hoehe, breite) auf einem Gitter ueber dem Original der Groesse
    original = (H, W). faktor: Pixel des Originals je Gitterpixel (y, x) - ohne Angabe
    zeigt das Gitter genau das Original; versatz: Lage des Originals auf dem Gitter in
    Gitterpixeln (KI-Erweiterung)."""
    if faktor is None:
        faktor = (original[0] / hoehe, original[1] / breite)
    h_orig, b_orig = original
    y = ((xp.arange(hoehe, dtype=xp.float32) + 0.5 - versatz[1]) * xp.float32(faktor[0]))[:, None]
    x = ((xp.arange(breite, dtype=xp.float32) + 0.5 - versatz[0]) * xp.float32(faktor[1]))[None, :]
    ergebnis = xp.zeros((hoehe, breite), dtype=xp.float32)
    for nummer, teil in enumerate(maske.teile):
        g = _teil_gewicht(teil, x, y, b_orig, h_orig)
        g = xp.broadcast_to(g, (hoehe, breite))
        if teil.modus == "dazu" or nummer == 0 and teil.modus == "schnitt":
            ergebnis = xp.maximum(ergebnis, g)
        elif teil.modus == "weg":
            ergebnis = ergebnis * (1 - g)
        else:
            ergebnis = ergebnis * g
    return xp.ascontiguousarray(ergebnis, dtype=xp.float32)


# --------------------------------------------------------------------------
# Wirken
# --------------------------------------------------------------------------

def _karte(karten, name: str):
    """Summe aus Gewicht mal Wert ueber alle Masken - oder None, wenn keine ihn setzt."""
    stelle = NAMEN.index(name)
    summe = None
    for gewicht_, werte in karten:
        if werte[stelle] == 0:
            continue
        xp = f.xp_von(gewicht_)
        teil = gewicht_ * xp.float32(werte[stelle])
        summe = teil if summe is None else summe + teil
    return summe


def _helligkeit_setzen(rgb, y, v_neu):
    xp = f.xp_von(rgb)
    y_neu = f.srgb_zu_linear(xp.clip(v_neu, 0, None))
    return (rgb * (y_neu / xp.maximum(y, f.EPS))[..., None]).astype(xp.float32)


def anwenden(rgb, karten, massstab: float = 1.0):
    """Die Masken auf ein Bild in linearem Licht (H, W, 3) - karten: [(Gewicht (H, W),
    Werte)] in der Geometrie dieses Bildes. massstab wie in filter.anwenden()."""
    if not karten:
        return rgb
    xp = f.xp_von(rgb)
    rgb = rgb.astype(xp.float32)

    temperatur, toenung = _karte(karten, "temperatur"), _karte(karten, "toenung")
    belichtung = _karte(karten, "belichtung")
    if temperatur is not None or toenung is not None or belichtung is not None:
        null = xp.zeros(rgb.shape[:2], dtype=xp.float32)
        k = (null if temperatur is None else temperatur) * xp.float32(0.35 / 100)
        m = (null if toenung is None else toenung) * xp.float32(0.25 / 100)
        faktoren = xp.stack([xp.exp(k), xp.exp(-m), xp.exp(-k)], axis=-1)
        norm = faktoren @ xp.asarray(f.LUMA, dtype=xp.float32)
        if belichtung is not None:
            norm = norm / xp.exp2(belichtung)
        rgb = rgb * faktoren / norm[..., None]

    dunst = _karte(karten, "dunst")
    if dunst is not None:
        licht, durchlass = f.dunst_schaetzen(rgb)
        durchlass = f.vergroessern(durchlass, rgb.shape[0], rgb.shape[1])
        staerke = dunst / 100
        weg = xp.maximum(staerke, 0)
        dazu = xp.maximum(-staerke, 0)[..., None] * xp.float32(0.6)
        durchlass = xp.maximum(1 - weg * (1 - durchlass), f.DUNST_MIN_DURCHLASS)[..., None]
        rgb = xp.maximum((rgb - licht) / durchlass + licht, 0)
        rgb = (rgb * (1 - dazu) + licht * dazu).astype(xp.float32)

    kontrast, lichter = _karte(karten, "kontrast"), _karte(karten, "lichter")
    tiefen = _karte(karten, "tiefen")
    if kontrast is not None or lichter is not None or tiefen is not None:
        y = f.luminanz(rgb)
        v = f.linear_zu_srgb(y)
        innen = xp.clip(v, 0, 1)
        ueber = v - innen
        if kontrast is not None:
            c = kontrast / 100
            innen = innen + xp.maximum(c, 0) * (f._glatt(xp, 0.0, 1.0, innen) - innen)
            innen = innen + xp.maximum(-c, 0) * ((0.5 + (innen - 0.5) * 0.5) - innen)
        if lichter is not None:
            innen = innen + lichter / 100 * 0.6 * f._glatt(xp, 0.5, 1.0, innen) * (innen - 0.5)
        if tiefen is not None:
            innen = innen + tiefen / 100 * 0.6 * (1 - f._glatt(xp, 0.0, 0.5, innen)) \
                * (0.5 - innen)
        y_neu = f.srgb_zu_linear(xp.clip(innen, 0, 1) + ueber)
        schwarz = (y <= f.EPS)[..., None]
        rgb = xp.where(schwarz, y_neu[..., None],
                       rgb * (y_neu / xp.maximum(y, f.EPS))[..., None]).astype(xp.float32)

    klarheit = _karte(karten, "klarheit")
    if klarheit is not None:
        y = f.luminanz(rgb)
        v = f.linear_zu_srgb(y)
        weich = f.grob_weichzeichnen(v, f.klarheit_sigma(rgb.shape))
        gewicht_ = xp.clip(4 * v * (1 - v), 0, 1)
        rgb = _helligkeit_setzen(rgb, y, v + klarheit / 100 * gewicht_ * (v - weich))

    saettigung = _karte(karten, "saettigung")
    if saettigung is not None:
        y = f.luminanz(rgb)[..., None]
        faktor = xp.maximum(1 + saettigung / 100, 0)[..., None]
        rgb = (y + (rgb - y) * faktor).astype(xp.float32)

    schaerfe = _karte(karten, "schaerfe")
    if schaerfe is not None:
        staerke = schaerfe / 100
        if float(staerke.max()) > 0:
            y = f.luminanz(rgb)
            v = f.linear_zu_srgb(y)
            scharf = v + xp.maximum(staerke, 0) * (v - f.gauss(v, SCHAERFE_RADIUS * massstab))
            rgb = _helligkeit_setzen(rgb, y, scharf)
        if float(staerke.min()) < 0:
            sigma = WEICH_SIGMA * massstab
            weich = xp.stack([f.gauss(xp.ascontiguousarray(rgb[..., k]), sigma)
                              for k in range(3)], axis=-1)
            anteil = xp.maximum(-staerke, 0)[..., None]
            rgb = (rgb + anteil * (weich - rgb)).astype(xp.float32)
    return rgb
