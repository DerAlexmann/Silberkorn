"""
Kratzererkennung nachgebaut - fuer den ONNX-Export, nicht Teil der App

Nachbau des U-Nets, das in "Bringing Old Photos Back to Life" (Wan u. a.,
CVPR 2020) Kratzer, Risse und Staub auf alten Fotos findet
(Global/detection.py, Gewichte checkpoints/detection/FT_Epoch_latest.pt).
Das Netz bekommt ein Graubild, (Grau - 0,5) / 0,5, Hoehe und Breite Vielfache
von 16, und liefert je Pixel die Wahrscheinlichkeit eines Schadens. Die Namen
der Module entsprechen dem Original, damit load_state_dict(strict=True) die
offiziellen Gewichte laedt.

Nach dem Code von Microsoft (https://github.com/microsoft/Bringing-Old-Photos-Back-to-Life,
Global/detection_models/networks.py, MIT License, Copyright (c) Microsoft Corporation).

Geaendert gegenueber dem Original:
- Nur die Fassung, die detection.py baut (1 Kanal, Tiefe 4, 64 Filter, Batch-
  Normierung, bilineares Hochrechnen, weiches Verkleinern); ohne DataParallel
  und Synchronized-BatchNorm, im Auswertemodus rechnet beides wie BatchNorm2d.
- Die Sigmoid-Funktion, die detection.py nach dem Netz anwendet, gehoert hier
  zum Netz.
- Das weiche Verkleinern ist neu geschrieben, nicht uebernommen: ein 3x3-
  Binomialfilter (1 2 1) mit gespiegeltem Rand und Schrittweite 2. Die
  Filterwerte stehen als Puffer "filt" in den Gewichten von Microsoft.

Als Bearbeitung des Codes von Microsoft steht diese Datei unter der MIT License
(Text in LICENSES/MIT-Bringing-Old-Photos.txt).

Licensed under MIT License
Copyright (c) Microsoft Corporation
Copyright 2026 Alexander Unverhau (Aenderungen)
Created with assistance of Claude AI
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

TIEFE = 4
FILTER = 64
VIELFACHES = 2 ** TIEFE


class Verkleinern(nn.Module):
    """Weich verkleinern: Binomialfilter 3x3, gespiegelter Rand, Schrittweite 2."""

    def __init__(self, kanaele: int):
        super().__init__()
        zeile = torch.tensor([1.0, 2.0, 1.0])
        kern = zeile[:, None] * zeile[None, :]
        self.register_buffer("filt", (kern / kern.sum()).expand(kanaele, 1, 3, 3).clone())

    def forward(self, x):
        return F.conv2d(F.pad(x, (1, 1, 1, 1), mode="reflect"), self.filt, stride=2,
                        groups=x.shape[1])


def _faltungen(ein: int, aus: int) -> nn.Sequential:
    schichten = []
    for _ in range(2):
        schichten += [nn.ReflectionPad2d(1), nn.Conv2d(ein, aus, 3), nn.BatchNorm2d(aus),
                      nn.LeakyReLU(0.2, True)]
        ein = aus
    return nn.Sequential(*schichten)


class Faltblock(nn.Module):
    def __init__(self, ein: int, aus: int):
        super().__init__()
        self.block = _faltungen(ein, aus)

    def forward(self, x):
        return self.block(x)


class Hochblock(nn.Module):
    def __init__(self, ein: int, aus: int):
        super().__init__()
        self.up = nn.Sequential(nn.Upsample(mode="bilinear", scale_factor=2, align_corners=False),
                                nn.ReflectionPad2d(1), nn.Conv2d(ein, aus, 3))
        self.conv_block = Faltblock(ein, aus)

    def forward(self, x, bruecke):
        return self.conv_block(torch.cat([self.up(x), bruecke], 1))


class Kratzernetz(nn.Module):
    def __init__(self):
        super().__init__()
        self.first = nn.Sequential(nn.ReflectionPad2d(3), nn.Conv2d(1, FILTER, 7),
                                   nn.LeakyReLU(0.2, True))
        kanaele = FILTER
        self.down_sample = nn.ModuleList()
        self.down_path = nn.ModuleList()
        for i in range(TIEFE):
            self.down_sample.append(nn.Sequential(
                nn.ReflectionPad2d(1), nn.Conv2d(kanaele, kanaele, 3), nn.BatchNorm2d(kanaele),
                nn.LeakyReLU(0.2, True), Verkleinern(kanaele)))
            self.down_path.append(Faltblock(kanaele, FILTER * 2 ** (i + 1)))
            kanaele = FILTER * 2 ** (i + 1)
        self.up_path = nn.ModuleList()
        for i in reversed(range(TIEFE)):
            self.up_path.append(Hochblock(kanaele, FILTER * 2 ** i))
            kanaele = FILTER * 2 ** i
        self.last = nn.Sequential(nn.ReflectionPad2d(1), nn.Conv2d(kanaele, 1, 3))

    def forward(self, x):
        x = self.first(x)
        bruecken = []
        for verkleinern, falten in zip(self.down_sample, self.down_path, strict=True):
            bruecken.append(x)
            x = falten(verkleinern(x))
        for hoch, bruecke in zip(self.up_path, reversed(bruecken), strict=True):
            x = hoch(x, bruecke)
        return torch.sigmoid(self.last(x))

    @staticmethod
    def gewichte(daten: dict) -> dict:
        """Der state_dict aus dem Checkpoint von Microsoft (Schluessel "model_state")."""
        zustand = daten.get("model_state", daten)
        return {k.removeprefix("module."): v for k, v in zustand.items()}
