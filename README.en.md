# Silberkorn

**Silberkorn - An open-source, GPU-accelerated AI image & photo enhancer powered by neural networks.**<br>
**Silberkorn - ein quelloffener, GPU-beschleunigter KI-Bild- und Fotoverbesserer auf Basis neuronaler Netze.**

[![CI](https://github.com/DerAlexmann/Silberkorn/actions/workflows/ci.yml/badge.svg)](https://github.com/DerAlexmann/Silberkorn/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/DerAlexmann/Silberkorn?sort=semver&display_name=tag&label=Version)](https://github.com/DerAlexmann/Silberkorn/releases/latest)

Supports hardware acceleration via NVIDIA CUDA / RTX series GPUs.

*NVIDIA and RTX are trademarks of NVIDIA Corporation.*

*[Deutsche Fassung: README.md](README.md)*

> **Version 0.x.** Basic adjustments, RAW development and the AI features are usable;
> the user interface and settings files may still change before version 1.0.

![Silberkorn with an edited image: the canvas on the left, the cards with the sliders on the right](docs/bilder/en/hauptfenster.png)

---

## What it can do

- **Develop on the GPU**: white balance, exposure, contrast, highlights, shadows, tone
  curves, colour ranges (HSL), black and white with toning, LUTs and haze removal.
- **Local adjustments**: up to ten masks made from gradient, radial, brush, luminance and
  colour range, plus subject, object by click or depth range with AI.
- **Noise, sharpness, grain**: classic noise reduction, AI denoise (SCUNet), AI sharpen
  (Restormer) and film grain with adjustable strength and size.
- **AI tools**: upscaling, subject and background (BiRefNet), object by click (SAM 2),
  remove objects (LaMa), depth and bokeh (Depth Anything V2), colourise and extend.
- **Geometry and lens**: crop, rotate, straighten (also automatically), perspective and lens
  correction.
- **16-bit, RAW, scan and film**: RAW development on the GPU, 16-bit TIFF and PNG,
  negatives from a scanner or camera turned into positives, dust removed via the
  infrared channel.
- **Hand-off**: anonymise, clean metadata, save for publishing and print.
- **Working with many images**: folder view, ratings, batch, contact sheet and presets.
- **Non-destructive**: undo and redo; settings live in a sidecar file next to the image
  and the original stays untouched.

All features in detail, with screenshots and keyboard shortcuts:
[docs/funktionen.en.md](docs/funktionen.en.md).

## System requirements

Silberkorn computes on the graphics card only. **Without an NVIDIA RTX graphics card
the program does not start**; instead it reports what was found and what is missing.
There is deliberately no fallback mode on the CPU.

| | Minimum |
|---|---|
| Operating system | Windows 10 or 11, 64-bit |
| Graphics card | NVIDIA GeForce RTX 2000 series or newer, including professional RTX cards (RTX A series, RTX Ada) |
| Video memory | 4 GB for AI features; below that classic filters only |
| Graphics driver | NVIDIA 570.65 or newer |
| Python (only when run as a script) | 3.10 or newer |

**Not supported** are GTX cards – including the GTX 16 series, which belongs to the same
generation as the RTX 2000 but has no Tensor Cores – and graphics cards from other
vendors.

### Feature tiers

What is available depends mainly on the video memory. Silberkorn detects the tier at
start-up; features of a higher tier are shown greyed out with a note.

| Tier | Video memory | Examples | Scope |
|---|---|---|---|
| – | below 4 GB | RTX 2050 (laptop) | classic filters only |
| S | 4 GB | RTX 3050 Laptop | classic filters, small AI models |
| M | 6–8 GB | RTX 2060, 3060 Ti, 4060, 5060 | all restoration models: upscaling, denoising, background removal, object selection |
| L | 12–16 GB | RTX 3060 12 GB, 4070, 5070 Ti | in addition larger models and generative fill |
| XL | 24 GB and more | RTX 3090, 4090, 5090 | full feature set |

Precision: all RTX cards compute in FP16; from the RTX 4000 (Ada) also in FP8, from the
RTX 5000 (Blackwell) also in FP4. The values are shown on the "About & copyright" tab.

## Tech stack

| Area | Technology | Description |
|---|---|---|
| Interface | PySide6 (Qt) | Main window, cards, canvas |
| Computing | NumPy, CuPy (CUDA 12.8) | Filter formulas as reference and as GPU kernels |
| AI | ONNX Runtime GPU, optional TensorRT | Models run locally on the graphics card |
| Files | Pillow, tifffile, imagecodecs, rawpy | Loading and saving 8-bit, 16-bit and RAW |
| Tests | pytest, ruff | Checking the filters and code style |

## Getting started

### 1. As a program (Windows)

Unpack the ZIP from the [release](https://github.com/DerAlexmann/Silberkorn/releases/latest)
and start `Silberkorn.exe` – no installation, no admin rights.

The executable does not include CUDA and cuDNN, NVIDIA's licences do not allow them to
be passed on. At first start the program therefore asks, names source, size and licence
and, once you agree, downloads NVIDIA's official packages from the Python Package Index
once (1.6 GB, about 2.3 GB unpacked). Every file is verified against its checksum.

### 2. As a script

```bash
git clone https://github.com/DerAlexmann/Silberkorn.git
cd Silberkorn
pip install -r requirements.txt
python Silberkorn.pyw
```

The packages bring CuPy and the required CUDA libraries (just over 1 GB in total); a
separate CUDA Toolkit installation is not needed.

**The program seems to hang briefly the first time you edit.** This is expected and not a
crash: when you move a slider for the first time, the graphics card compiles the filter
programs for exactly this card. This takes a few seconds, after that all sliders respond
smoothly, and later starts are faster.

### 3. TensorRT (optional)

With TensorRT the AI runs about twice as fast again. Installing it is optional and only
applies to the Python version:

```bash
pip install -r requirements-tensorrt.txt
```

That is about 1.8 GB to download. The first time a model is used, TensorRT builds an
engine for the graphics card once – this takes one to three minutes (up to ten for AI
sharpen and subject detection), and a window says so. TensorRT is under a proprietary NVIDIA licence and is
therefore not part of any ready-made executable. If it does not work, Silberkorn computes
with CUDA.

### 4. Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
```

Without a graphics card the GPU tests are skipped. The executable itself is built by
`build.cmd`.

## Usage

- The window is designed for 1366×768 at 125 % scaling.
- Keyboard shortcuts: `Y` before/after comparison, `J` clipping warning for highlights
  and shadows, `O` show mask, `[` and `]` brush size, `Ctrl+Z` undo. The full list is in
  [docs/funktionen.en.md](docs/funktionen.en.md).

## Privacy

Silberkorn works entirely on your own computer. No images are uploaded and no usage data
is sent. Network access only happens after your explicit consent: for AI models, the
NVIDIA libraries of the executable and the lens database from lensfun. The preview cache
of the folder view is encrypted with the Windows Data Protection API (DPAPI). In detail:
[docs/datenschutz.en.md](docs/datenschutz.en.md).

## AI models

The models are not part of the program. "Download model" fetches them from releases of
this project after a prompt that names source, size and licence. New models are only added
with a free licence (Apache 2.0, MIT, BSD). Models, sizes and licences in detail:
[docs/ki-modelle.en.md](docs/ki-modelle.en.md).

## A note on AI results

AI methods such as upscaling or denoising add image details that were not present in the
original. Processed images are therefore not suitable as evidence or for documentation
purposes.

## Contributing

Bug reports, suggestions and translations are welcome – [CONTRIBUTING.md](CONTRIBUTING.md)
explains structure, style and tests (in German; issues and pull requests in English are
just as welcome). Please report security issues not as an issue but as described in
[SECURITY.md](SECURITY.md).

1. Create your own branch; `main` is protected and linear (merge by rebase).
2. Tests and `ruff` must pass.
3. Commit titles in German and descriptive, without Conventional Commit prefixes.
4. Add visible changes to `CHANGELOG.md` under "Unveröffentlicht".

## Licence and legal notices

[MIT](LICENSE) – Copyright 2026 Alexander Unverhau.
Created with assistance of Claude AI.

The exception are the re-implementations of third-party networks in
`werkzeuge/netz_*.py`, which only serve to convert the AI models and are not part of the
program: each is under the licence of its original (Apache-2.0, MIT or BSD-3-Clause), as
stated in the file header; the licence texts are in [LICENSES](LICENSES).

Third-party components and their licences are listed in [NOTICE](NOTICE). AI models are
subject to their own licences, which are shown before downloading. The NVIDIA libraries
(CUDA, cuDNN, optionally TensorRT) are installed by pip from NVIDIA's own packages; they
are under NVIDIA's licences, not under the MIT licence.

**Trademarks:** NVIDIA, RTX, GeForce, CUDA and TensorRT are trademarks or registered
trademarks of NVIDIA Corporation in the U.S. and other countries. Qt is a trademark of The
Qt Company Ltd., Python a trademark of the Python Software Foundation, Windows a trademark
of Microsoft Corporation. All other trademarks are the property of their respective
owners.

Silberkorn is an independent project and is not affiliated with, endorsed or sponsored
by NVIDIA Corporation.
