"""
Lokale Anpassungen: Masken aus Teilen, je Maske eigene Regler

Eine Maske ist ein Bereich des Bildes mit eigenen Werten fuer Weissabgleich,
Belichtung, Tonwerte, Klarheit, Dunst, Saettigung und Schaerfe. Den Bereich
bilden ihre Teile - Verlauf, Radial und Pinsel -, die hinzugefuegt, abgezogen
oder geschnitten werden; jeder Teil laesst sich umkehren.

Ein Pinsel-Teil besteht aus Strichen: je Strich Radius, weicher Rand,
Deckkraft, ob er malt oder radiert, und seine Punkte. Gerastert wird jeder
Strich nur in seinem Rechteck - auf der Grafikkarte mit einem kleinen Kernel,
der fuer jeden Pixel den Abstand zum naechsten Stueck des Strichs sucht. Beim
Malen aendert sich nur der letzte Strich; was die Striche davor ergeben, bleibt
gespeichert (pinsel_speicher: (Striche davor, Gitter) -> Ebene; aufraeumen muss,
wer ihn uebergibt).

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

ARTEN = ("verlauf", "radial", "pinsel")
UEBERTRAGBAR = ("verlauf", "radial")      # ein Pinsel gehoert zu genau einem Bild
MODI = ("dazu", "weg", "schnitt")
MAX_MASKEN = 10
MAX_TEILE = 20
MAX_NAME = 60
MAX_STRICHE = 1000               # je Pinsel-Teil
MAX_PUNKTE = 20000               # alle Punkte aller Striche eines Pinsel-Teils

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
    # Der Pinsel hat keine festen Daten - nur Striche
    "pinsel": (),
}
# Ein Strich: Radius als Anteil der langen Kante, weicher Rand und Deckkraft in %,
# Punkte als Anteil von Breite und Hoehe
STRICH = {"radius": (0.0005, 0.25), "weich": (0.0, 100.0), "deckkraft": (1.0, 100.0)}
PUNKT_BEREICH = (-1.0, 2.0)
PINSEL_ABSTAND = 0.2             # ein neuer Punkt erst ab diesem Anteil des Radius
RADIAL_WEICH = 50.0              # weicher Rand eines neuen Radialfilters
SCHAERFE_RADIUS = 1.0            # Radius des lokalen Schaerfens in Pixeln des Originals
WEICH_SIGMA = 4.0                # Schaerfe -100 zeichnet mit diesem Sigma weich (Original)


@dataclass(frozen=True)
class Strich:
    radius: float
    weich: float
    deckkraft: float
    radieren: bool
    punkte: tuple[float, ...]    # x0, y0, x1, y1, ...


@dataclass(frozen=True)
class Teil:
    art: str
    daten: tuple[float, ...]
    modus: str = "dazu"
    umkehren: bool = False
    striche: tuple[Strich, ...] = ()

    def punkte(self) -> int:
        """Wie viele Punkte die Striche zusammen haben."""
        return sum(len(strich.punkte) // 2 for strich in self.striche)


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


def uebertragbar(masken) -> tuple[Maske, ...]:
    """Die Masken ohne Teile, die nur zu diesem Bild passen (Pinsel); Masken ohne Teil
    fallen weg - fuer Voreinstellungen und Kopieren."""
    ergebnis = []
    for maske in masken:
        teile = tuple(t for t in maske.teile if t.art in UEBERTRAGBAR)
        if teile:
            if teile[0].modus != "dazu":
                teile = (Teil(teile[0].art, teile[0].daten, "dazu", teile[0].umkehren),
                         *teile[1:])
            ergebnis.append(Maske(maske.name, teile, maske.werte, maske.an))
    return tuple(ergebnis)


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
    """Die Griffe eines Teils im Original - ein Pinsel hat keine."""
    if teil.art == "pinsel":
        return {}
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
    """Was die Leinwand von einem Teil zeichnet - Linienzuege (n, 2) im Original. Einen
    Pinsel zeigt „Maske zeigen“, nicht die Leinwand."""
    lang = max(breite, hoehe)
    if teil.art == "pinsel":
        return []
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

_STRICH_KERNEL = None


def _strich_kernel():
    """Abstand jedes Pixels zum naechsten Stueck eines Strichs - als weiche Scheibe."""
    global _STRICH_KERNEL
    if _STRICH_KERNEL is None:
        from .cuda import cupy as cp
        _STRICH_KERNEL = cp.ElementwiseKernel(
            "raw float32 stuecke, int32 n, raw float32 xs, raw float32 ys, int32 breite, "
            "float32 radius, float32 innen",
            "float32 g",
            r"""
            float px = xs[i % breite], py = ys[i / breite];
            float naechst = 3.0e38f;
            for (int j = 0; j < n; j++) {
                float ax = stuecke[4 * j], ay = stuecke[4 * j + 1];
                float dx = stuecke[4 * j + 2] - ax, dy = stuecke[4 * j + 3] - ay;
                float laenge = dx * dx + dy * dy;
                float t = laenge > 0.0f
                    ? fminf(fmaxf(((px - ax) * dx + (py - ay) * dy) / laenge, 0.0f), 1.0f)
                    : 0.0f;
                float ex = ax + t * dx - px, ey = ay + t * dy - py;
                naechst = fminf(naechst, ex * ex + ey * ey);
            }
            float r = sqrtf(naechst) / radius;
            float s = fminf(fmaxf((r - innen) / (1.0f - innen), 0.0f), 1.0f);
            g = 1.0f - s * s * (3.0f - 2.0f * s);
            """,
            "silberkorn_strich")
    return _STRICH_KERNEL


def _stuecke(strich: Strich, breite: float, hoehe: float) -> np.ndarray:
    """Die Stuecke eines Strichs (n, 4) als ax, ay, bx, by in Pixeln des Originals; ein
    einzelner Punkt ist ein Stueck der Laenge null."""
    punkte = np.asarray(strich.punkte, dtype=np.float64).reshape(-1, 2) * (breite, hoehe)
    if len(punkte) == 1:
        punkte = np.concatenate([punkte, punkte])
    return np.concatenate([punkte[:-1], punkte[1:]], axis=1).astype(np.float32)


def _strich_gewicht(strich: Strich, xs, ys, breite: float, hoehe: float):
    """Wirkung eines Strichs (len(ys), len(xs)) an den Stellen xs, ys (Pixel des
    Originals) - ohne Deckkraft."""
    xp = f.xp_von(xs)
    stuecke = _stuecke(strich, breite, hoehe)
    radius = strich.radius * max(breite, hoehe)
    innen = min(1 - strich.weich / 100, 0.999)
    if xp is not np:
        g = xp.empty((len(ys), len(xs)), dtype=xp.float32)
        _strich_kernel()(xp.asarray(stuecke.ravel()), np.int32(len(stuecke)), xs, ys,
                         np.int32(len(xs)), np.float32(radius), np.float32(innen), g)
        return g
    px, py = xs[None, :], ys[:, None]
    naechst = np.full((len(ys), len(xs)), np.inf, dtype=np.float32)
    for ax, ay, bx, by in stuecke:
        dx, dy = bx - ax, by - ay
        laenge = dx * dx + dy * dy
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / laenge, 0, 1) if laenge > 0 else 0.0
        naechst = np.minimum(naechst, (ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2)
    return (1 - f._glatt(np, innen, 1.0, np.sqrt(naechst) / np.float32(radius))) \
        .astype(np.float32)


def _striche_auflegen(ergebnis, striche, xs_host, ys_host, xs, ys, breite, hoehe):
    """Striche nacheinander auf eine Ebene: malen hebt sie bis zur Deckkraft, radieren
    nimmt sie im selben Mass zurueck. Jeder Strich nur in seinem Rechteck."""
    lang = max(breite, hoehe)
    for strich in striche:
        punkte = np.asarray(strich.punkte, dtype=np.float64).reshape(-1, 2) * (breite, hoehe)
        rand = strich.radius * lang
        x0 = int(np.searchsorted(xs_host, punkte[:, 0].min() - rand))
        x1 = int(np.searchsorted(xs_host, punkte[:, 0].max() + rand, side="right"))
        y0 = int(np.searchsorted(ys_host, punkte[:, 1].min() - rand))
        y1 = int(np.searchsorted(ys_host, punkte[:, 1].max() + rand, side="right"))
        if x1 <= x0 or y1 <= y0:
            continue
        g = _strich_gewicht(strich, xs[x0:x1], ys[y0:y1], breite, hoehe)
        g = g * np.float32(strich.deckkraft / 100)
        ausschnitt = ergebnis[y0:y1, x0:x1]
        if strich.radieren:
            ergebnis[y0:y1, x0:x1] = ausschnitt * (1 - g)
        else:
            ergebnis[y0:y1, x0:x1] = ausschnitt + (1 - ausschnitt) * g
    return ergebnis


def _pinsel_gewicht(teil: Teil, xs_host, ys_host, xs, ys, breite, hoehe, gitter,
                    speicher):
    """Wirkung eines Pinsel-Teils. Was die Striche ohne den letzten ergeben, steht unter
    (Striche davor, Gitter) im speicher - so rechnet beim Malen nur der Strich, der
    gerade waechst."""
    xp = f.xp_von(xs)
    davor, letzter = teil.striche[:-1], teil.striche[-1:]
    schluessel = (davor, gitter)
    speicher = {} if speicher is None else speicher
    if schluessel not in speicher:
        speicher[schluessel] = _striche_auflegen(
            xp.zeros((len(ys_host), len(xs_host)), dtype=xp.float32), davor, xs_host, ys_host,
            xs, ys, breite, hoehe)
    basis = speicher[schluessel]
    return _striche_auflegen(basis.copy(), letzter, xs_host, ys_host, xs, ys, breite, hoehe)


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
            xp=np, pinsel_speicher=None):
    """Wirkung der Maske (hoehe, breite) auf einem Gitter ueber dem Original der Groesse
    original = (H, W). faktor: Pixel des Originals je Gitterpixel (y, x) - ohne Angabe
    zeigt das Gitter genau das Original; versatz: Lage des Originals auf dem Gitter in
    Gitterpixeln (KI-Erweiterung). pinsel_speicher: siehe _pinsel_gewicht."""
    if faktor is None:
        faktor = (original[0] / hoehe, original[1] / breite)
    h_orig, b_orig = original
    ys_host = ((np.arange(hoehe, dtype=np.float32) + 0.5 - versatz[1])
               * np.float32(faktor[0]))
    xs_host = ((np.arange(breite, dtype=np.float32) + 0.5 - versatz[0])
               * np.float32(faktor[1]))
    ys, xs = xp.asarray(ys_host), xp.asarray(xs_host)
    y, x = ys[:, None], xs[None, :]
    gitter = (hoehe, breite, original, tuple(versatz), tuple(faktor))
    ergebnis = xp.zeros((hoehe, breite), dtype=xp.float32)
    for nummer, teil in enumerate(maske.teile):
        if teil.art == "pinsel":
            if not teil.striche:
                continue
            g = _pinsel_gewicht(teil, xs_host, ys_host, xs, ys, b_orig, h_orig, gitter,
                                pinsel_speicher)
            if teil.umkehren:
                g = 1 - g
        else:
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
