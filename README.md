# Silberkorn

**Silberkorn - An open-source, GPU-accelerated AI image & photo enhancer powered by neural networks.**<br>
**Silberkorn - ein quelloffener, GPU-beschleunigter KI-Bild- und Fotoverbesserer auf Basis neuronaler Netze.**

[![CI](https://github.com/DerAlexmann/Silberkorn/actions/workflows/ci.yml/badge.svg)](https://github.com/DerAlexmann/Silberkorn/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/DerAlexmann/Silberkorn?sort=semver&display_name=tag&label=Version)](https://github.com/DerAlexmann/Silberkorn/releases/latest)

Supports hardware acceleration via NVIDIA CUDA / RTX series GPUs.<br>
Unterstützt Hardwarebeschleunigung über NVIDIA CUDA und Grafikkarten der RTX-Serie.

*[English version: README.en.md](README.en.md)*

> **Version 0.x.** Grundregler, RAW-Entwicklung und die KI-Funktionen sind nutzbar;
> Bedienung und Einstellungsdateien können sich bis Version 1.0 noch ändern.

![Silberkorn mit einem bearbeiteten Bild: links die Leinwand, rechts die Karten mit den Reglern](docs/bilder/de/hauptfenster.png)

---

## Was es kann

- **Entwickeln auf der GPU**: Weißabgleich, Belichtung, Kontrast, Lichter, Tiefen,
  Gradationskurven, Farbbereiche (HSL), Schwarzweiß mit Tönung, LUTs und Dunst entfernen.
- **Lokale Anpassungen**: bis zu zehn Masken aus Verlauf, Radial, Pinsel, Helligkeits- und
  Farbbereich, dazu per KI das Motiv, ein Objekt per Klick oder ein Tiefenbereich.
- **Rauschen, Schärfe, Korn**: klassische Rauschminderung, KI-Entrauschen (SCUNet),
  KI-Schärfen (Restormer) und Filmkorn mit regelbarer Stärke und Größe.
- **KI-Werkzeuge**: Hochskalieren, Motiv und Hintergrund (BiRefNet), Objekt per Klick
  (SAM 2), Objekte entfernen (LaMa), Tiefe und Bokeh (Depth Anything V2), Kolorieren
  und Erweitern.
- **Geometrie und Objektiv**: Zuschnitt, Drehen, Begradigen (auch automatisch),
  Perspektive und Objektivkorrektur.
- **16 Bit, RAW, Scan und Film**: RAW-Entwicklung auf der GPU, TIFF und PNG mit 16 Bit,
  Negative aus Scanner oder Kamera ins Positiv wandeln, Staub über den Infrarotkanal
  entfernen.
- **Abgeben**: Anonymisieren, Metadaten bereinigen, für die Veröffentlichung speichern und
  Drucken.
- **Arbeiten mit vielen Bildern**: Ordneransicht, Bewertung, Vergleich, Stapel, Kontaktbogen und
  Voreinstellungen.
- **Nicht-destruktiv**: Rückgängig und Wiederholen, Einstellungen liegen in einer
  Begleitdatei neben dem Bild, das Original bleibt unverändert.

Alle Funktionen im Detail, mit Bildschirmfotos und Tastenkürzeln: [docs/funktionen.md](docs/funktionen.md).

## Systemvoraussetzungen

Silberkorn rechnet ausschließlich auf der Grafikkarte. **Ohne NVIDIA-RTX-Grafikkarte
startet das Programm nicht**, sondern meldet beim Start, was gefunden wurde und was fehlt.
Einen Notbetrieb auf dem Prozessor gibt es bewusst nicht.

| | Mindestens |
|---|---|
| Betriebssystem | Windows 10 oder 11, 64 Bit |
| Grafikkarte | NVIDIA GeForce RTX 2000-Serie oder neuer, auch RTX-Profikarten (RTX A-Serie, RTX Ada) |
| Grafikspeicher | 4 GB für KI-Funktionen; darunter nur klassische Filter |
| Grafiktreiber | NVIDIA 570.65 oder neuer |
| Python (nur für den Start als Skript) | 3.10 oder neuer |

**Nicht unterstützt** werden GTX-Karten – auch die GTX-16-Serie, die zwar zur selben
Generation wie die RTX 2000 gehört, aber keine Tensor Cores hat – sowie Grafikkarten
anderer Hersteller.

### Funktionsstufen

Was verfügbar ist, hängt vor allem vom Grafikspeicher ab. Silberkorn erkennt die
Stufe beim Start; Funktionen einer höheren Stufe erscheinen ausgegraut mit Hinweis.

| Stufe | Grafikspeicher | Beispiele | Umfang |
|---|---|---|---|
| – | unter 4 GB | RTX 2050 (Laptop) | nur klassische Filter |
| S | 4 GB | RTX 3050 Laptop | klassische Filter, kleine KI-Modelle |
| M | 6–8 GB | RTX 2060, 3060 Ti, 4060, 5060 | alle Restaurierungsmodelle: Hochskalieren, Entrauschen, Freistellen, Objektauswahl |
| L | 12–16 GB | RTX 3060 12 GB, 4070, 5070 Ti | zusätzlich größere Modelle und generative Füllung |
| XL | 24 GB und mehr | RTX 3090, 4090, 5090 | voller Umfang |

Rechengenauigkeit: alle RTX-Karten rechnen in FP16; ab RTX 4000 (Ada) zusätzlich FP8, ab
RTX 5000 (Blackwell) auch FP4. Die Werte stehen auf dem Reiter „Info & Copyright“.

## Tech-Stack

| Bereich | Technologie | Beschreibung |
|---|---|---|
| Oberfläche | PySide6 (Qt) | Hauptfenster, Karten, Leinwand |
| Rechnen | NumPy, CuPy (CUDA 12.8) | Filterformeln als Referenz und als GPU-Kernel |
| KI | ONNX Runtime GPU, optional TensorRT | Modelle laufen lokal auf der Grafikkarte |
| Dateien | Pillow, tifffile, imagecodecs, rawpy | Laden und Speichern von 8 Bit, 16 Bit und RAW |
| Tests | pytest, ruff | Prüfung der Filter und Stilkontrolle |

## Erste Schritte

### 1. Als Programm (Windows)

Das ZIP aus dem [Release](https://github.com/DerAlexmann/Silberkorn/releases/latest)
entpacken und `Silberkorn.exe` starten – ohne Installation und ohne Adminrechte.

Die EXE bringt CUDA und cuDNN nicht mit, NVIDIAs Lizenzen erlauben die Weitergabe nicht.
Beim ersten Start fragt das Programm deshalb nach, nennt Quelle, Größe und Lizenz und
lädt nach Zustimmung einmalig NVIDIAs offizielle Pakete vom Python Package Index
(1,6 GB, ausgepackt rund 2,3 GB). Jede Datei wird gegen ihre Prüfsumme geprüft.

### 2. Als Skript

```bash
git clone https://github.com/DerAlexmann/Silberkorn.git
cd Silberkorn
pip install -r requirements.txt
python Silberkorn.pyw
```

Die Pakete bringen CuPy und die nötigen CUDA-Bibliotheken mit (zusammen gut 1 GB), ein
eigenes CUDA-Toolkit ist nicht nötig.

**Beim ersten Bearbeiten scheint das Programm kurz zu hängen.** Das ist gewollt und kein
Absturz: Die Grafikkarte übersetzt beim ersten Reglerzug die Filterprogramme für genau
diese Karte. Das dauert einige Sekunden, danach reagieren alle Regler flüssig, und spätere
Starts gehen schneller.

### 3. TensorRT (optional)

Mit TensorRT rechnet die KI rund doppelt so schnell. Die Installation ist freiwillig und
gilt nur für die Python-Fassung:

```bash
pip install -r requirements-tensorrt.txt
```

Das sind rund 1,8 GB Download. Beim ersten Einsatz eines Modells baut TensorRT einmalig
eine passende Engine für die Grafikkarte – das dauert ein bis drei Minuten (beim
KI-Schärfen und Freistellen bis zu zehn), ein Fenster weist darauf hin. TensorRT steht unter einer proprietären NVIDIA-Lizenz und
gehört deshalb zu keiner fertigen EXE. Klappt es nicht, rechnet Silberkorn mit CUDA.

### 4. Tests ausführen

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
```

Ohne Grafikkarte werden die GPU-Tests übersprungen. Die EXE selbst baut `build.cmd`.

## Bedienung

- Das Fenster ist für 1366×768 bei 125 % Skalierung ausgelegt.
- Tastenkürzel: `Y` Vorher/Nachher-Vergleich, `J` Über- und Unterbelichtungswarnung,
  `O` Maske zeigen, `[` und `]` Pinselgröße, `Strg+Z` Rückgängig. Die vollständige Liste steht
  in [docs/funktionen.md](docs/funktionen.md).

## Datenschutz

Silberkorn arbeitet vollständig auf dem eigenen Rechner. Es werden keine Bilder
hochgeladen und keine Nutzungsdaten gesendet. Verbindungen ins Netz gibt es nur nach
ausdrücklicher Zustimmung: für KI-Modelle, die NVIDIA-Bibliotheken der EXE und die
Objektivdatenbank von lensfun. Der Vorschau-Cache der Ordneransicht ist mit der
Windows-Datenschutz-API (DPAPI) verschlüsselt. Ausführlich:
[docs/datenschutz.md](docs/datenschutz.md).

## KI-Modelle

Die Modelle gehören nicht zum Programm. „Modell herunterladen“ lädt sie nach Rückfrage mit
Quelle, Größe und Lizenz aus den Releases dieses Projekts. Neue Modelle kommen nur mit
freier Lizenz (Apache 2.0, MIT, BSD) hinein. Modelle, Größen und Lizenzen im Einzelnen:
[docs/ki-modelle.md](docs/ki-modelle.md).

## Hinweis zu KI-Ergebnissen

KI-Verfahren wie Hochskalieren oder Entrauschen ergänzen Bilddetails, die im Original
nicht vorhanden waren. Bearbeitete Bilder eignen sich deshalb nicht als Beweis- oder
Dokumentationsmittel.

## Mitwirken

Fehlermeldungen, Vorschläge und Übersetzungen sind willkommen.
[CONTRIBUTING.md](CONTRIBUTING.md) erklärt Aufbau, Stil und Tests. Sicherheitslücken
bitte nicht als Issue melden, sondern über den Weg in [SECURITY.md](SECURITY.md).

1. Eigenen Branch anlegen, `main` ist geschützt und linear (Merge per Rebase).
2. Tests und `ruff` müssen durchlaufen.
3. Commit-Titel deutsch und beschreibend, ohne Conventional-Commit-Präfixe.
4. Sichtbare Änderungen im `CHANGELOG.md` unter „Unveröffentlicht“ eintragen.

## Lizenz und Rechtliches

[MIT](LICENSE) – Copyright 2026 Alexander Unverhau.
Erstellt mit Unterstützung von Claude AI.

Ausnahme sind die Nachbauten fremder Netze in `werkzeuge/netz_*.py`, die nur zum
Wandeln der KI-Modelle dienen und nicht zum Programm gehören: Jede steht unter der
Lizenz ihres Vorbilds (Apache-2.0, MIT oder BSD-3-Clause), wie im Kopf der Datei
angegeben; die Lizenztexte liegen in [LICENSES](LICENSES).

Verwendete Fremdkomponenten und ihre Lizenzen stehen in [NOTICE](NOTICE). KI-Modelle
stehen unter eigenen Lizenzen, die vor dem Herunterladen angezeigt werden. Die
NVIDIA-Bibliotheken (CUDA, cuDNN, optional TensorRT) installiert pip aus NVIDIAs
eigenen Paketen; sie stehen unter NVIDIAs Lizenzen und nicht unter der MIT-Lizenz.

**Marken:** NVIDIA, RTX, GeForce, CUDA und TensorRT sind Marken oder eingetragene Marken
der NVIDIA Corporation in den USA und anderen Ländern. Qt ist eine Marke der The Qt
Company Ltd., Python eine Marke der Python Software Foundation, Windows eine Marke der
Microsoft Corporation. Alle weiteren Marken gehören ihren jeweiligen Inhabern.

Silberkorn ist ein unabhängiges Projekt und steht in keiner Verbindung zur NVIDIA
Corporation; es wird von ihr weder unterstützt noch gesponsert.
