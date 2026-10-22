# KI-Modelle

*Zurück zur [README](../README.md) · English: [ki-modelle.en.md](ki-modelle.en.md)*

Die Modelle gehören nicht zum Programm. „Modell herunterladen“ lädt sie aus
Releases dieses Projekts: in der Karte „KI-Hochskalieren“ aus
[modelle-1](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-1)
das schnelle Modell mit knapp 10 MB und das große mit 64 MB, in der Karte
„KI-Entrauschen“ aus
[modelle-2](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-2)
SCUNet mit 71 MB, in der Karte „KI-Schärfen“ aus
[modelle-3](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-3)
Restormer mit 101 MB, in der Karte „Motiv & Hintergrund“ aus
[modelle-4](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-4)
BiRefNet mit 177 MB und für „Objekt anklicken“ aus
[modelle-5](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-5)
SAM 2 mit 147 MB, in der Karte „Objekte entfernen“ aus
[modelle-6](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-6)
LaMa mit 196 MB, in der Karte „Tiefe & Bokeh“ aus
[modelle-7](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-7)
Depth Anything V2 Small mit 98 MB und in der Karte „Geometrie“ für „Mit KI
erweitern“ aus
[modelle-8](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-8)
FLUX.2 [klein] 4B mit Outpaint-LoRA mit rund 4,1 GB – auf mehrere Dateien
verteilt, denn GitHub nimmt je Datei höchstens 2 GB an –, in der Karte
„KI-Kolorieren“ aus
[modelle-9](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-9)
DDColor (kleine Fassung) mit 210 MB. Jede Datei wird gegen ihre SHA-256-Prüfsumme geprüft,
bevor sie verwendet wird.
Abgelegt werden sie im Ordner `modelle` neben dem Programm oder, wenn der
schreibgeschützt ist, unter `%LOCALAPPDATA%\Silberkorn\modelle`.

Die Modelle sind die offiziellen Gewichte von
[Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (BSD 3-Clause, Copyright 2021
Xintao Wang), [SCUNet](https://github.com/cszn/SCUNet) (Apache-2.0, Copyright
2022 Kai Zhang), [Restormer](https://github.com/swz30/Restormer) (MIT,
Copyright 2022 Syed Waqas Zamir), [BiRefNet](https://github.com/ZhengPeng7/BiRefNet)
(MIT, Copyright 2024 ZhengPeng) und [SAM 2](https://github.com/facebookresearch/sam2)
(Apache-2.0, Copyright Meta Platforms, Inc. and affiliates) und
[LaMa](https://github.com/advimman/lama) (Apache-2.0, Copyright 2021 Samsung
Research) und [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2)
Small (Apache-2.0) und [DDColor](https://github.com/piddnad/DDColor) in der
kleinen Fassung (Apache-2.0, Xiaoyang Kang u. a.), nach ONNX gewandelt; dazu
[FLUX.2 [klein] 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
(Apache-2.0, Black Forest Labs) mit der
[Outpaint-LoRA von fal](https://huggingface.co/fal/flux-2-klein-4B-outpaint-lora)
(Apache-2.0), die LoRA eingerechnet und der Transformer nach int8 quantisiert
(NOTICE nennt alle Änderungen).
Wer das selbst nachvollziehen will:

1. Aus den [Releases von Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN/releases)
   `realesr-general-x4v3.pth`, `realesr-general-wdn-x4v3.pth` und
   `RealESRGAN_x4plus.pth`, aus dem
   [Release v1.0 von KAIR](https://github.com/cszn/KAIR/releases/tag/v1.0), wo die
   SCUNet-Gewichte liegen, `scunet_color_real_psnr.pth` und aus dem
   [Release v1.0 von Restormer](https://github.com/swz30/Restormer/releases/tag/v1.0)
   `single_image_defocus_deblurring.pth` und aus dem
   [Release v1 von BiRefNet](https://github.com/ZhengPeng7/BiRefNet/releases/tag/v1)
   `BiRefNet_lite-general-2K-epoch_232.pth`, von Meta
   [`sam2.1_hiera_small.pt`](https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt)
   und `big-lama.zip` von LaMa (der Download, den die
   [LaMa-Anleitung](https://github.com/advimman/lama) nennt, liegt auf
   [Hugging Face](https://huggingface.co/smartywu/big-lama)) sowie
   `depth_anything_v2_vits.pth` von
   [Depth-Anything-V2-Small](https://huggingface.co/depth-anything/Depth-Anything-V2-Small)
   und `pytorch_model.bin` von
   [ddcolor_paper_tiny](https://huggingface.co/piddnad/ddcolor_paper_tiny), umbenannt in
   `ddcolor_paper_tiny.bin`,
   nach `modelle/quellen/` laden und `big-lama.zip` dort entpacken.
2. `pip install torch` (nur für diesen Schritt nötig).
3. `python werkzeuge/modelle_exportieren.py` – das legt die ONNX-Modelle in
   `modelle/` ab und prüft sie gegen PyTorch.
4. Für KI-Erweitern von Hugging Face
   [FLUX.2-klein-base-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B)
   (Text-Encoder, Tokenizer, VAE, Scheduler) nach `<ordner>/klein-base-4b/`, den
   Transformer von
   [FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) nach
   `<ordner>/klein-4b-destilliert/transformer/` und
   `flux-outpaint-lora.safetensors` von
   [fal](https://huggingface.co/fal/flux-2-klein-4B-outpaint-lora) nach
   `<ordner>/lora/` laden, dann
   `pip install torch diffusers peft transformers onnx onnx-ir scipy`
   und `python werkzeuge/outpaint_export.py <ordner>`. Das braucht rund 30 GB
   Arbeitsspeicher und prüft jedes Netz sowie den ganzen Ablauf gegen diffusers.
