"""
Scan & Film: Negative umwandeln

Film speichert Licht als Dichte: Je mehr Licht ein Bild traf, desto dunkler
ist das Negativ. Der Scan misst, wie viel Licht noch durchkommt - die
Durchlaessigkeit T je Farbkanal. Umgekehrt wird deshalb ueber die Dichte
D = -log10(T), so wie Film physikalisch arbeitet, statt den Scan einfach
nach Art eines Fotonegativs zu spiegeln:

  1. Filmmaske: Auch unbelichteter Film hat eine Dichte, beim Farbnegativ
     die orange Maske. Gerechnet wird mit der Dichte darueber,
     d = log10(M / T), M die Durchlaessigkeit der Maske.
  2. Schwarz- und Weisspunkt je Kanal: Die Dichte reicht in jedem Kanal
     verschieden weit - die drei Farbschichten des Films sind unterschiedlich
     steil. Jeder Kanal wird deshalb auf denselben Umfang gebracht; das nimmt
     den Farbstich, der sonst von den Tiefen zu den Lichtern wandert. Die
     Automatik nimmt dafuer die tiefsten Schatten und hellsten Lichter des
     Motivs. Ist die Maske mit der Pipette gemessen, wird der unbelichtete
     Film selbst zum Schwarzpunkt - dort fiel kein Licht.
  3. Zurueck ins Licht: Die Dichte ist der Logarithmus der Belichtung, das
     Positiv deshalb 10 hoch der gestreckten Dichte, ueber UMFANG Zehnerstufen.

Filmmaske und Umfang werden einmal aus dem Bild geschaetzt und stehen dann
als Zahlen in den Einstellungen - so zeigen Vorschau und gespeichertes Bild
dasselbe, und Rueckgaengig nimmt eine Umwandlung zurueck wie jeden Regler.
Ohne Filmrand im Scan dient die Maske nur dazu, unbelichteten Film und den
Halter des Scanners aus der Schaetzung zu halten.

Alle Funktionen arbeiten mit NumPy- und CuPy-Arrays (filter.xp_von), in
linearem Licht wie die Filterkette.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import math

from .filter import LUMA, xp_von

ARTEN = ("", "farbnegativ", "sw_negativ", "dia")    # "" = kein Film
NEGATIVE = ("farbnegativ", "sw_negativ")
UMFANG = 1.1            # so viele Zehnerstufen Licht zwischen Schwarz- und Weisspunkt
KLEINSTE = 1e-5         # kleinste Durchlaessigkeit - darunter ist die Dichte unendlich
HELLSTE_ANTEIL = 0.5    # Prozent der hellsten Stellen, aus denen die Maske geschaetzt wird
UEBERSTRAHLT = 0.995    # in allen Kanaelen so hell: kein Film, etwa ein Perforationsloch
SCHWARZ_PROZENT = 0.5   # Perzentile der Dichte fuer Schwarz- und Weisspunkt
WEISS_PROZENT = 99.7
RAND_ANTEIL = 0.03      # so viel vom Rand zaehlt nicht fuer den Umfang: Filmrand, Halter
MASKE_NAH = 0.02        # Dichte, unter der eine Stelle als unbelichteter Film gilt
DICHTE_HOECHST = 2.7    # mehr Dichte hat kein Negativ - dort liegt der Halter des Scanners
MINDESTUMFANG = 0.05    # kleinster Dichteumfang je Kanal, gegen Teilen durch fast null
PIPETTE_ANTEIL = 0.005  # Messfeld der Pipette: Radius als Anteil der laengsten Kante


def ist_negativ(art: str) -> bool:
    return art in NEGATIVE


def aktiv(art: str, maske: tuple, umfang: tuple) -> bool:
    """Wird umgekehrt? Nur bei einem Negativ mit Maske und Umfang."""
    return ist_negativ(art) and len(maske) == 3 and len(umfang) == 6


def _dichte(rgb, maske):
    """Dichte ueber der Filmmaske, je Kanal: log10(M / T)."""
    xp = xp_von(rgb)
    m = xp.asarray(maske, dtype=xp.float32)
    return xp.log10(m / xp.maximum(rgb, xp.float32(KLEINSTE)))


def maske_schaetzen(rgb) -> tuple[float, float, float]:
    """Durchlaessigkeit der Filmmaske: die hellsten Stellen des Scans - der Filmrand, falls
    er mitgescannt ist, sonst die tiefsten Schatten des Motivs. Was in allen Kanaelen
    ueberstrahlt, ist kein Film und zaehlt nicht."""
    xp = xp_von(rgb)
    punkte = rgb.reshape(-1, 3)
    punkte = punkte[~(punkte >= UEBERSTRAHLT).all(axis=1)]
    if punkte.shape[0] == 0:
        return (1.0, 1.0, 1.0)
    # Dieselben Stellen fuer alle Kanaele: die mit der geringsten Dichte insgesamt
    helligkeit = xp.log(xp.maximum(punkte, xp.float32(KLEINSTE))).sum(axis=1)
    grenze = xp.percentile(helligkeit, 100 - HELLSTE_ANTEIL)
    hell = punkte[helligkeit >= grenze]
    return tuple(float(max(w, KLEINSTE)) for w in xp.median(hell, axis=0).tolist())


def maske_messen(rgb, x: float, y: float) -> tuple[float, float, float]:
    """Die Pipette: Filmmaske als Median eines kleinen Feldes um (x, y) in Pixeln von rgb."""
    xp = xp_von(rgb)
    hoehe, breite = rgb.shape[:2]
    radius = max(1, round(max(hoehe, breite) * PIPETTE_ANTEIL))
    x0, x1 = max(0, int(x) - radius), min(breite, int(x) + radius + 1)
    y0, y1 = max(0, int(y) - radius), min(hoehe, int(y) + radius + 1)
    feld = rgb[y0:y1, x0:x1].reshape(-1, 3)
    return tuple(float(max(w, KLEINSTE)) for w in xp.median(feld, axis=0).tolist())


def umfang_schaetzen(rgb, maske: tuple, schwarz_ist_maske: bool = False) -> tuple[float, ...]:
    """Schwarz- und Weisspunkt je Kanal als Dichte: (schwarz r, g, b, weiss r, g, b).
    schwarz_ist_maske: Schwarz ist die gemessene Filmmaske selbst, Dichte 0.

    Es zaehlt nur das Motiv - nicht der Rand des Scans, nicht unbelichteter Film
    und nicht der Halter des Scanners, der kein Licht durchlaesst. Sonst setzte
    der Filmrand den Schwarzpunkt und der Halter den Weisspunkt."""
    xp = xp_von(rgb)
    hoehe, breite = rgb.shape[:2]
    rand_y, rand_x = int(hoehe * RAND_ANTEIL), int(breite * RAND_ANTEIL)
    innen = rgb[rand_y:hoehe - rand_y or None, rand_x:breite - rand_x or None]
    d = _dichte(innen, maske).reshape(-1, 3)
    motiv = ~(d < MASKE_NAH).all(axis=1) & (d < DICHTE_HOECHST).all(axis=1)
    if int(motiv.sum()) < 16:
        motiv = xp.ones(d.shape[0], dtype=bool)
    d = d[motiv]
    if schwarz_ist_maske:
        schwarz = [0.0] * 3
    else:
        schwarz = xp.percentile(d, SCHWARZ_PROZENT, axis=0).tolist()
    weiss = xp.percentile(d, WEISS_PROZENT, axis=0).tolist()
    weiss = [max(w, s + MINDESTUMFANG) for s, w in zip(schwarz, weiss, strict=True)]
    return tuple(float(z) for z in (*schwarz, *weiss))


def schaetzen(rgb, art: str) -> tuple[tuple, tuple]:
    """Filmmaske und Umfang fuer ein Negativ, oder () und () fuer alles andere."""
    if not ist_negativ(art):
        return (), ()
    maske = maske_schaetzen(rgb)
    return maske, umfang_schaetzen(rgb, maske)


def umkehren(rgb, art: str, maske: tuple, umfang: tuple):
    """Ein Negativ ins Positiv wandeln - lineares Licht hinein und heraus. Was heller als
    der Weisspunkt ist, bleibt ueber 1 erhalten wie die Lichter einer RAW."""
    if not aktiv(art, maske, umfang):
        return rgb
    xp = xp_von(rgb)
    schwarz = xp.asarray(umfang[:3], dtype=xp.float32)
    skala = xp.asarray([UMFANG / max(w - s, MINDESTUMFANG)
                        for s, w in zip(umfang[:3], umfang[3:], strict=True)], dtype=xp.float32)
    unten = math.pow(10.0, -UMFANG)
    d = _dichte(rgb, maske)
    d -= schwarz
    d *= skala
    d -= xp.float32(UMFANG)                   # Weisspunkt bei 0, Schwarzpunkt bei -UMFANG
    xp.power(xp.float32(10.0), d, out=d)
    d -= xp.float32(unten)
    d *= xp.float32(1 / (1 - unten))
    xp.maximum(d, xp.float32(0), out=d)
    if art == "sw_negativ":
        grau = (d[..., 0] * LUMA[0] + d[..., 1] * LUMA[1] + d[..., 2] * LUMA[2])
        return xp.repeat(grau[..., None], 3, axis=2).astype(xp.float32)
    return d.astype(xp.float32, copy=False)


def zurueck(rgb, art: str, maske: tuple, umfang: tuple):
    """Umkehrung von umkehren(): ein Positiv in die Werte des Scans - etwa fuer eine
    Fuellung, die am Positiv berechnet wurde. Beim Schwarzweiss-Negativ ergibt ein Grau in
    allen Kanaelen umgewandelt wieder dasselbe Grau."""
    if not aktiv(art, maske, umfang):
        return rgb
    xp = xp_von(rgb)
    schwarz = xp.asarray(umfang[:3], dtype=xp.float32)
    skala = xp.asarray([UMFANG / max(w - s, MINDESTUMFANG)
                        for s, w in zip(umfang[:3], umfang[3:], strict=True)], dtype=xp.float32)
    unten = math.pow(10.0, -UMFANG)
    d = xp.maximum(rgb, xp.float32(0)) * xp.float32(1 - unten) + xp.float32(unten)
    d = xp.log10(d)
    d += xp.float32(UMFANG)
    d /= skala
    d += schwarz
    return (xp.asarray(maske, dtype=xp.float32) * xp.power(xp.float32(10.0), -d)).astype(
        xp.float32)

