"""Gemeinsame Vorbereitung der Tests.

Ohne Bildschirm (QT_QPA_PLATFORM=offscreen) findet Qt die Windows-Schriften nicht
und setzt eine Ersatzschrift - Texte werden dann breiter als im Programm, und
Messungen der Oberflaeche stimmen nicht. Unter Windows bekommt Qt deshalb den
Schriftordner, bevor irgendein Test eine QApplication anlegt.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

import os

if os.name == "nt":
    _schriften = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    if os.path.isdir(_schriften):
        os.environ.setdefault("QT_QPA_FONTDIR", _schriften)


def pytest_addoption(parser):
    parser.addoption("--tensorrt", action="store_true",
                     help="auch die TensorRT-Tests ausfuehren (der erste Lauf baut Engines, "
                          "rund 20 Minuten)")


def pytest_collection_modifyitems(config, items):
    """TensorRT-Tests nur auf Wunsch: ohne fertige Engines baut TensorRT minutenlang, und
    ein gewoehnlicher Lauf saehe aus, als hinge er."""
    if config.getoption("--tensorrt"):
        return
    import pytest
    auslassen = pytest.mark.skip(reason="TensorRT-Test, nur mit --tensorrt")
    for test in items:
        if test.get_closest_marker("tensorrt") is not None:
            test.add_marker(auslassen)
