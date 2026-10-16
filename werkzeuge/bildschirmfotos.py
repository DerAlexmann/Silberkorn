"""
Bildschirmfotos fuer die READMEs erzeugen - nur das Programmfenster

Die Motive rechnet das Skript selbst: eine Landschaft, daraus ein Farbnegativ
mit Infrarotkanal und Staub, und eine Scannerplatte mit drei Abzuegen. So
zeigen die Bilder keine fremden oder privaten Fotos. Die Einstellungsdatei
wird weder gelesen noch geschrieben - Namen aus den Vorgaben fuer Urheber und
Copyright koennen also nicht ins Bild geraten.

Aufruf (aus dem Projektordner, mit Grafikkarte):

    python werkzeuge/bildschirmfotos.py

Ergebnis: docs/bilder/de/*.png und docs/bilder/en/*.png

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

import math
import os
import sys
import tempfile

import numpy as np
from PIL import Image

PROJEKT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJEKT)
ZIEL = os.path.join(PROJEKT, "docs", "bilder")
FENSTER = (1100, 720)               # logische Groesse des Fensters
BREITE_PNG = 1400                   # so breit werden die Bilder gespeichert
BEISPIEL_ORDNER = r"D:\Fotos\Scans"


# --------------------------------------------------------------------------
# Motive
# --------------------------------------------------------------------------

def _glatt(zufall, hoehe, breite, groesse):
    """Weiches Rauschen: grobes Zufallsgitter, bilinear vergroessert."""
    gitter = zufall.random((hoehe // groesse + 2, breite // groesse + 2))
    y = np.linspace(0, gitter.shape[0] - 1.001, hoehe)
    x = np.linspace(0, gitter.shape[1] - 1.001, breite)
    y0, x0 = y.astype(int), x.astype(int)
    fy, fx = (y - y0)[:, None], (x - x0)[None, :]
    a = gitter[y0][:, x0] * (1 - fx) + gitter[y0][:, x0 + 1] * fx
    b = gitter[y0 + 1][:, x0] * (1 - fx) + gitter[y0 + 1][:, x0 + 1] * fx
    return a * (1 - fy) + b * fy


def landschaft(hoehe=1600, breite=2400, seed=1, sonne=(0.74, 0.22)):
    """Eine Seenlandschaft mit Bergen, Wald und Haus - sRGB 0..1."""
    z = np.random.default_rng(seed)
    y, x = np.mgrid[0:hoehe, 0:breite] / np.array([hoehe, breite])[:, None, None]
    horizont = 0.58
    t = np.clip(y / horizont, 0, 1)[..., None]
    bild = (1 - t) * np.array([0.22, 0.42, 0.78]) + t * np.array([0.86, 0.9, 0.94])
    # Sonne mit Schein
    abstand = np.hypot((x - sonne[0]) * breite / hoehe, y - sonne[1])
    bild += (np.exp(-(abstand / 0.18) ** 2) * 0.35)[..., None] * np.array([1.0, 0.85, 0.55])
    bild[abstand < 0.035] = (1.0, 0.97, 0.88)
    # Wolken: mehrere Groessen uebereinander, unten flacher
    rauschen = sum(_glatt(z, hoehe, breite, g) / (i + 1)
                   for i, g in enumerate((220, 110, 55, 25, 12)))
    rauschen = rauschen / sum(1 / (i + 1) for i in range(5))
    wolken = np.clip((rauschen - 0.52) * 5, 0, 1) * np.clip((0.42 - y) / 0.12, 0, 1)
    schatten = np.clip((rauschen - 0.6) * 4, 0, 1)
    farbe = 0.98 - 0.12 * schatten
    bild = bild * (1 - wolken[..., None] * 0.9) + (wolken * 0.9 * farbe)[..., None]

    def grat(hoehe_mitte, amplitude, wellen, phase):
        return hoehe_mitte - amplitude * sum(
            np.sin(x[0] * math.tau * w + p) / (i + 1)
            for i, (w, p) in enumerate(zip(wellen, phase, strict=True)))

    fern = grat(0.43, 0.08, (1.3, 3.1, 7.7), z.random(3) * math.tau)
    nah = grat(0.52, 0.06, (2.2, 5.3, 11.0), z.random(3) * math.tau)
    berg = y > fern[None, :]
    bild[berg] = bild[berg] * 0.35 + np.array([0.45, 0.52, 0.66]) * 0.65
    schnee = berg & (y < fern[None, :] + 0.025) & (fern[None, :] < 0.39)
    bild[schnee] = (0.95, 0.96, 0.98)
    wald = y > nah[None, :]
    textur = _glatt(z, hoehe, breite, 8)[wald]
    bild[wald] = np.array([0.16, 0.3, 0.18]) * (0.75 + 0.5 * textur)[:, None]
    # See: Spiegelbild mit Wellen, darunter Wiese
    see_oben, see_unten = horizont, 0.8
    see = (y >= see_oben) & (y < see_unten)
    welle = np.sin(y * 900) * 0.004 * (y - see_oben) * 8
    quelle_y = np.clip(2 * see_oben - y, 0, 1)
    sy = np.clip((quelle_y * hoehe).astype(int), 0, hoehe - 1)
    sx = np.clip(((x + welle) * breite).astype(int), 0, breite - 1)
    spiegel = bild[sy, sx] * np.array([0.7, 0.78, 0.85])
    bild[see] = spiegel[see]
    wiese = y >= see_unten
    gras = _glatt(z, hoehe, breite, 6)[wiese]
    bild[wiese] = np.array([0.36, 0.55, 0.2]) * (0.8 + 0.4 * gras)[:, None]
    # Haus mit rotem Dach am Ufer
    hx, hy, hb, hh = 0.2, 0.83, 0.07, 0.06
    haus = (np.abs(x - hx) < hb / 2) & (y > hy) & (y < hy + hh)
    bild[haus] = (0.93, 0.9, 0.84)
    dach = (y > hy - 0.045) & (y <= hy) & (np.abs(x - hx) < (y - (hy - 0.045)) / 0.045 * hb * 0.62)
    bild[dach] = (0.72, 0.16, 0.1)
    fenster = haus & (np.abs(y - hy - 0.025) < 0.01) & (np.abs(np.abs(x - hx) - 0.017) < 0.006)
    bild[fenster] = (0.25, 0.3, 0.38)
    # Baeume im Vordergrund
    for bx in (0.08, 0.31, 0.36, 0.88, 0.94):
        spitze = 0.7 + z.random() * 0.05
        baum = (y > spitze) & (y < 0.9) & (np.abs(x - bx) * breite / hoehe < (y - spitze) * 0.32)
        nadeln = _glatt(z, hoehe, breite, 4)[baum]
        bild[baum] = np.array([0.08, 0.2, 0.1]) * (0.8 + 0.4 * nadeln)[:, None]
    # Kanten glaetten wie ein Objektiv, dann etwas Korn
    from PIL import ImageFilter
    weich = Image.fromarray((np.clip(bild, 0, 1) * 255 + 0.5).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(1.0))
    bild = np.asarray(weich, dtype=np.float64) / 255 + z.normal(0, 0.01, bild.shape)
    return np.clip(bild, 0, 1).astype(np.float32)


def nach_linear(srgb):
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def negativ_mit_staub(srgb, seed=2):
    """Farbnegativ mit oranger Maske, dazu ein Infrarotkanal mit Staub und Fusseln -
    wie ein RGBI-Scan aus VueScan oder SilverFast. uint16 (H, W, 4)."""
    z = np.random.default_rng(seed)
    licht = nach_linear(srgb)
    dichte = np.maximum(np.log10(np.maximum(licht, 1e-4)) + 3.0, 0) * np.array([0.55, 0.6, 0.7])
    scan = np.array([0.47, 0.17, 0.10]) * 10.0 ** -dichte
    hoehe, breite = scan.shape[:2]
    ir = np.full((hoehe, breite), 0.86) + z.normal(0, 0.006, (hoehe, breite))
    yy, xx = np.mgrid[-8:9, -8:9]

    def fleck(cy, cx, r, staerke):
        teil = np.clip(r + 0.5 - np.hypot(yy, xx), 0, 1) * staerke
        ir[cy - 8:cy + 9, cx - 8:cx + 9] *= 1 - teil
        scan[cy - 8:cy + 9, cx - 8:cx + 9] *= (1 - teil)[..., None]

    for _ in range(500):
        fleck(int(z.integers(20, hoehe - 20)), int(z.integers(20, breite - 20)),
              z.uniform(0.8, 3.5), z.uniform(0.5, 0.9))
    for _ in range(6):
        y, x, winkel = float(z.integers(200, hoehe - 200)), float(z.integers(200, breite - 200)), \
            z.uniform(0, math.tau)
        for _schritt in range(int(z.integers(80, 220))):
            winkel += z.normal(0, 0.15)
            y, x = y + math.sin(winkel) * 2, x + math.cos(winkel) * 2
            if 20 < y < hoehe - 20 and 20 < x < breite - 20:
                fleck(int(y), int(x), 1.5, 0.85)
    kodiert = np.where(scan <= 0.0031308, scan * 12.92, 1.055 * scan ** (1 / 2.4) - 0.055)
    return np.dstack([(np.clip(kodiert, 0, 1) * 65535 + 0.5).astype(np.uint16),
                      (np.clip(ir, 0, 1) * 65535 + 0.5).astype(np.uint16)])


def scannerplatte():
    """Drei Abzuege schraeg auf dem hellen Deckel eines Flachbettscanners - sRGB uint8."""
    z = np.random.default_rng(3)
    hoehe, breite = 2480, 1800
    platte = np.full((hoehe, breite, 3), 0.93) + z.normal(0, 0.004, (hoehe, breite, 3))
    y, x = np.mgrid[0:hoehe, 0:breite] + 0.5
    lagen = ((1, 500, 470, 900, 3.0, (1.0, 1.0, 1.0)),
             (4, 1300, 1230, 760, -7.0, (1.08, 0.97, 0.8)),
             (7, 690, 1930, 980, 12.0, (0.95, 1.0, 1.05)))
    for seed, mx, my, b, grad, toenung in lagen:
        h = round(b * 2 / 3)
        abzug = landschaft(h, b, seed, sonne=(0.3 + 0.2 * seed % 1, 0.25)) * np.array(toenung)
        a = math.radians(grad)
        u = (x - mx) * math.cos(a) + (y - my) * math.sin(a)
        v = -(x - mx) * math.sin(a) + (y - my) * math.cos(a)
        schatten = (np.abs(u) < b / 2 + 3) & (v > h / 2) & (v < h / 2 + 4)
        platte[schatten] *= 0.82
        innen = (np.abs(u) < b / 2) & (np.abs(v) < h / 2)
        iu = np.clip((u + b / 2).astype(int), 0, b - 1)
        iv = np.clip((v + h / 2).astype(int), 0, h - 1)
        platte[innen] = abzug[iv[innen], iu[innen]]
    return (np.clip(platte, 0, 1) * 255 + 0.5).astype(np.uint8)


def motive_schreiben(ordner: str) -> dict[str, str]:
    import tifffile
    pfade = {"landschaft": os.path.join(ordner, "landschaft.jpg"),
             "negativ": os.path.join(ordner, "negativ-rgbi.tif"),
             "platte": os.path.join(ordner, "scannerplatte.jpg")}
    bild = landschaft()
    Image.fromarray((bild * 255 + 0.5).astype(np.uint8)).save(pfade["landschaft"], quality=95)
    tifffile.imwrite(pfade["negativ"], negativ_mit_staub(bild), photometric="rgb",
                     extrasamples=[0], compression="zlib")
    Image.fromarray(scannerplatte()).save(pfade["platte"], quality=95)
    return pfade


# --------------------------------------------------------------------------
# Aufnahmen
# --------------------------------------------------------------------------

def _speichern(pixmap, pfad: str):
    """Fensterbild auf BREITE_PNG Pixel bringen und als PNG speichern."""
    from PySide6.QtCore import Qt
    if pixmap.width() > BREITE_PNG:
        pixmap = pixmap.scaledToWidth(BREITE_PNG, Qt.TransformationMode.SmoothTransformation)
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    pixmap.save(pfad)
    with Image.open(pfad) as bild:
        bild.convert("RGB").save(pfad, optimize=True)
    print(pfad, os.path.getsize(pfad) // 1024, "KB")


def aufnehmen(sprache: str, motive: dict[str, str]):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtWidgets import QApplication, QDialog

    from silberkorn import farben, gpu_pruefung, trennen_dialog
    from silberkorn.hauptfenster import Hauptfenster
    from silberkorn.uebersetzung import _

    app = QApplication.instance()
    _.language = sprache
    fenster = Hauptfenster(gpu_pruefung.ermitteln())
    fenster.show()
    fenster.resize(*FENSTER)
    app.processEvents()
    seite = fenster.bearbeiten
    seite.aenderungen_verwerfen_ok = lambda: True      # keine Rueckfrage beim Wechsel
    ordner = os.path.join(ZIEL, sprache)

    def warten():
        for _i in range(5):
            app.processEvents()
        seite._zeichnen()
        app.processEvents()

    def karte(titel_de: str):
        titel = _(titel_de)
        nummer = next(i for i, k in enumerate(seite.karten) if seite._karten_titel[k] == titel)
        seite.zu_karte(nummer, weich=False)

    # 1. Hauptfenster mit bearbeiteter Landschaft
    seite.oeffnen(motive["landschaft"])
    for name, wert in (("belichtung", 0.15), ("kontrast", 18.0), ("tiefen", 25.0),
                       ("dynamik", 22.0), ("temperatur", 6.0)):
        seite.zeilen[name].setzen(wert)
        seite.wert_geaendert(name, wert)
    seite.zu_karte(0, weich=False)
    warten()
    _speichern(fenster.grab(), os.path.join(ordner, "hauptfenster.png"))

    # 2. Kartenauswahl aufgeklappt - die Liste ist ein eigenes Fenster, sie wird an ihrer
    # Stelle ins Fensterbild gezeichnet
    seite.kartenwahl.showPopup()
    app.processEvents()
    liste = seite.kartenwahl.view().window()
    bild = fenster.grab()
    maler = QPainter(bild)
    maler.drawPixmap(fenster.mapFromGlobal(liste.mapToGlobal(QPoint(0, 0))), liste.grab())
    maler.end()
    seite.kartenwahl.hidePopup()
    _speichern(bild, os.path.join(ordner, "kartenwahl.png"))

    # 3. Scan & Film: Negativ umgewandelt, Staub gefunden
    seite.oeffnen(motive["negativ"])
    seite.film_art.setCurrentIndex(seite.film_art.findData("farbnegativ"))
    for name, wert in (("temperatur", 12.0), ("toenung", -18.0)):   # wie nach dem Umwandeln
        seite.zeilen[name].setzen(wert)
        seite.wert_geaendert(name, wert)
    seite.staub_zeigen_box.setChecked(True)
    karte("Scan & Film")
    warten()
    _speichern(fenster.grab(), os.path.join(ordner, "scan-und-film.png"))

    # 4. Fotos trennen: der Dialog ueber dem Fenster
    seite.oeffnen(motive["platte"])
    karte("Scan & Film")
    warten()

    def zeigen(dialog):
        # Ein Beispielordner statt des temporaeren - der verriete den Benutzernamen
        dialog.ordner_feld.setText(BEISPIEL_ORDNER)
        dialog.show()
        for _i in range(5):
            app.processEvents()
        bild = fenster.grab()
        maler = QPainter(bild)
        stelle = fenster.mapFromGlobal(dialog.mapToGlobal(QPoint(0, 0)))
        maler.drawPixmap(stelle, dialog.grab())
        maler.setPen(QColor(farben.THEMES[farben.CURRENT_THEME]["ACCENT"]))
        maler.drawRect(QRect(stelle, dialog.size()).adjusted(0, 0, -1, -1))
        maler.end()
        _speichern(bild, os.path.join(ordner, "fotos-trennen.png"))
        return QDialog.DialogCode.Rejected

    trennen_dialog.TrennenDialog.exec = zeigen
    seite.fotos_trennen()
    seite.schliessen()
    fenster.close()


def main():
    from PySide6.QtWidgets import QApplication

    from silberkorn import einstellungen, farben
    # Ohne die Einstellungsdatei des Anwenders: nichts lesen, nichts schreiben
    einstellungen.load_config = lambda: {}
    einstellungen.save_config = lambda _daten: True
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(farben.stylesheet())
    with tempfile.TemporaryDirectory() as ordner:
        motive = motive_schreiben(ordner)
        for sprache in ("de", "en"):
            aufnehmen(sprache, motive)


if __name__ == "__main__":
    main()
