"""Histogramm und Abschneide-Warnung als reine Funktionen - mit NumPy, ohne Grafikkarte."""

from __future__ import annotations

import numpy as np
import pytest

from silberkorn import abschneiden


def bild(farbe, form=(6, 8)):
    return np.full((*form, 3), farbe, dtype=np.uint8)


def test_histogramm_form_und_summen():
    zufall = np.random.default_rng(1).integers(0, 256, (40, 50, 3), dtype=np.uint8)
    h = abschneiden.histogramme(zufall, 2)
    assert h.shape == (4, 256)
    gezaehlt = zufall[::2, ::2].shape[0] * zufall[::2, ::2].shape[1]
    assert (h.sum(axis=1) == gezaehlt).all()


def test_histogramm_kanaele_richtig_zugeordnet():
    h = abschneiden.histogramme(bild((255, 0, 0)), 2)
    assert h[0, 255] > 0 and h[0, :255].sum() == 0          # Rot nur ganz oben
    assert h[1, 0] > 0 and h[1, 1:].sum() == 0              # Gruen und Blau ganz unten
    assert h[2, 0] > 0 and h[2, 1:].sum() == 0
    luma = round(0.2126 * 255)                              # Rec. 709
    assert h[3, luma] == h[0, 255]
    gruen = abschneiden.histogramme(bild((0, 255, 0)), 2)
    assert gruen[1, 255] > 0 and gruen[0, 0] > 0 and gruen[2, 0] > 0
    blau = abschneiden.histogramme(bild((0, 0, 255)), 2)
    assert blau[2, 255] > 0 and blau[0, 0] > 0


def test_histogramm_weiss_hat_helligkeit_255():
    h = abschneiden.histogramme(bild((255, 255, 255)), 2)
    assert h[3, 255] == h[3].sum()


def test_schrittweite_begrenzt_die_zahl_der_pixel():
    assert abschneiden.schrittweite(100, 100) == 2
    schritt = abschneiden.schrittweite(4000, 6000)          # 24 MP
    gezaehlt = (4000 // schritt) * (6000 // schritt)
    assert gezaehlt <= 1.6 * abschneiden.HISTOGRAMM_ZIEL


def test_maske_lichter_und_tiefen():
    pixel = np.full((1, 6, 3), 100, dtype=np.uint8)
    pixel[0, 0] = (255, 100, 100)        # ein Kanal bei 255: Lichter
    pixel[0, 1] = (100, 100, 0)          # ein Kanal bei 0: Tiefen
    pixel[0, 2] = (254, 100, 100)        # knapp darunter: nichts
    pixel[0, 3] = (100, 1, 100)          # knapp darueber: nichts
    pixel[0, 4] = (255, 0, 100)          # beides
    code = abschneiden.maske(pixel)
    assert code.dtype == np.uint8
    assert code[0].tolist() == [abschneiden.LICHTER, abschneiden.TIEFEN, 0, 0,
                                abschneiden.LICHTER | abschneiden.TIEFEN, 0]
    assert abschneiden.anzahlen(code) == (2, 2)


def test_markieren_faerbt_nur_die_gewaehlten_stellen():
    pixel = np.full((1, 4, 3), 100, dtype=np.uint8)
    pixel[0, 0] = (255, 100, 100)
    pixel[0, 1] = (100, 100, 0)
    pixel[0, 3] = (255, 0, 100)
    code = abschneiden.maske(pixel)
    beide = abschneiden.markieren(pixel, code, True, True)
    assert beide[0].tolist() == [[255, 0, 0], [0, 0, 255], [100, 100, 100], [255, 0, 0]]
    nur_lichter = abschneiden.markieren(pixel, code, True, False)
    assert nur_lichter[0].tolist() == [[255, 0, 0], [100, 100, 0], [100, 100, 100],
                                       [255, 0, 0]]
    nur_tiefen = abschneiden.markieren(pixel, code, False, True)
    assert nur_tiefen[0].tolist() == [[255, 100, 100], [0, 0, 255], [100, 100, 100],
                                      [0, 0, 255]]
    assert pixel[0, 0].tolist() == [255, 100, 100]          # das Bild selbst bleibt


def test_markieren_ohne_wahl_gibt_dasselbe_bild_zurueck():
    pixel = bild((255, 0, 0))
    assert abschneiden.markieren(pixel, abschneiden.maske(pixel), False, False) is pixel


@pytest.mark.parametrize("farbe", [(10, 20, 30), (254, 254, 254), (1, 1, 1)])
def test_nichts_abgeschnitten(farbe):
    pixel = bild(farbe)
    code = abschneiden.maske(pixel)
    assert abschneiden.anzahlen(code) == (0, 0)
    assert (abschneiden.markieren(pixel, code, True, True) == pixel).all()


@pytest.mark.parametrize("form", [(1, 1), (1, 7), (3, 1)])
def test_winzige_bilder(form):
    """Ein Pixel breit oder hoch: kein Absturz, und mindestens ein Pixel wird gezaehlt."""
    pixel = bild((255, 0, 128), form)
    schritt = abschneiden.schrittweite(*form)
    h = abschneiden.histogramme(pixel, schritt)
    assert h.shape == (4, 256)
    assert (h.sum(axis=1) >= 1).all()
    code = abschneiden.maske(pixel)
    assert code.shape == form
    assert abschneiden.anzahlen(code) == (form[0] * form[1], form[0] * form[1])
    markiert = abschneiden.markieren(pixel, code, True, True)
    assert markiert.shape == pixel.shape
    assert (markiert == (255, 0, 0)).all()                  # Lichter gewinnen vor Tiefen
