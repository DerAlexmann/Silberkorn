# AI models

*Back to the [README](../README.en.md) · Deutsch: [ki-modelle.md](ki-modelle.md)*

The models are not part of the program. "Download model" fetches them from releases of
this project: in the "AI upscaling" card from
[modelle-1](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-1) the fast
model with just under 10 MB and the large one with 64 MB, in the "AI denoise" card from
[modelle-2](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-2) SCUNet
with 71 MB, in the "AI sharpen" card from
[modelle-3](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-3) Restormer
with 101 MB, in the "Subject & background" card from
[modelle-4](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-4) BiRefNet
with 177 MB and for "Click object" from
[modelle-5](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-5) SAM 2
with 147 MB, in the "Remove objects" card from
[modelle-6](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-6) LaMa
with 196 MB, in the "Depth & bokeh" card from
[modelle-7](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-7) Depth
Anything V2 Small with 98 MB, and for "Extend with AI" in the "Geometry" card from
[modelle-8](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-8) FLUX.2
[klein] 4B with the outpaint LoRA with about 4.1 GB – split into several files, as GitHub
accepts at most 2 GB per file –, and in the "AI colourise" card from
[modelle-9](https://github.com/DerAlexmann/Silberkorn/releases/tag/modelle-9) DDColor
(small version) with 210 MB. Every file is checked against its SHA-256 checksum before it is used. They are stored in the `modelle`
folder next to the program or, if that is read-only, in
`%LOCALAPPDATA%\Silberkorn\modelle`.

The models are the official weights of [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)
(BSD 3-Clause, Copyright 2021 Xintao Wang), [SCUNet](https://github.com/cszn/SCUNet)
(Apache-2.0, Copyright 2022 Kai Zhang), [Restormer](https://github.com/swz30/Restormer)
(MIT, Copyright 2022 Syed Waqas Zamir), [BiRefNet](https://github.com/ZhengPeng7/BiRefNet)
(MIT, Copyright 2024 ZhengPeng) and [SAM 2](https://github.com/facebookresearch/sam2)
(Apache-2.0, Copyright Meta Platforms, Inc. and affiliates) and
[LaMa](https://github.com/advimman/lama) (Apache-2.0, Copyright 2021 Samsung Research)
and [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2) Small
(Apache-2.0) and [DDColor](https://github.com/piddnad/DDColor) in its small version
(Apache-2.0, Xiaoyang Kang et al.), converted to ONNX; in addition
[FLUX.2 [klein] 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
(Apache-2.0, Black Forest Labs) with the
[outpaint LoRA by fal](https://huggingface.co/fal/flux-2-klein-4B-outpaint-lora)
(Apache-2.0), with the LoRA merged in and the transformer quantised to int8 (NOTICE lists
all changes). To reproduce this yourself:

1. Download `realesr-general-x4v3.pth`, `realesr-general-wdn-x4v3.pth` and
   `RealESRGAN_x4plus.pth` from the
   [Real-ESRGAN releases](https://github.com/xinntao/Real-ESRGAN/releases), and
   `scunet_color_real_psnr.pth` from the
   [KAIR release v1.0](https://github.com/cszn/KAIR/releases/tag/v1.0), where the SCUNet
   weights are published, and `single_image_defocus_deblurring.pth` from the
   [Restormer release v1.0](https://github.com/swz30/Restormer/releases/tag/v1.0) and
   `BiRefNet_lite-general-2K-epoch_232.pth` from the
   [BiRefNet release v1](https://github.com/ZhengPeng7/BiRefNet/releases/tag/v1) and
   [`sam2.1_hiera_small.pt`](https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt)
   from Meta and `big-lama.zip` of LaMa (the download named in the
   [LaMa instructions](https://github.com/advimman/lama), hosted on
   [Hugging Face](https://huggingface.co/smartywu/big-lama)) and
   `depth_anything_v2_vits.pth` from
   [Depth-Anything-V2-Small](https://huggingface.co/depth-anything/Depth-Anything-V2-Small)
   and `pytorch_model.bin` from
   [ddcolor_paper_tiny](https://huggingface.co/piddnad/ddcolor_paper_tiny), renamed to
   `ddcolor_paper_tiny.bin`,
   into `modelle/quellen/`, and unpack `big-lama.zip` there.
2. `pip install torch` (only needed for this step).
3. `python werkzeuge/modelle_exportieren.py` – this writes the ONNX models to `modelle/`
   and checks them against PyTorch.
4. For AI extend, download from Hugging Face
   [FLUX.2-klein-base-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B)
   (text encoder, tokenizer, VAE, scheduler) into `<folder>/klein-base-4b/`, the
   transformer of [FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
   into `<folder>/klein-4b-destilliert/transformer/` and `flux-outpaint-lora.safetensors`
   from [fal](https://huggingface.co/fal/flux-2-klein-4B-outpaint-lora) into
   `<folder>/lora/`, then run
   `pip install torch diffusers peft transformers onnx onnx-ir scipy` and
   `python werkzeuge/outpaint_export.py <folder>`. This needs about 30 GB of RAM and
   checks every network as well as the whole pipeline against diffusers.
