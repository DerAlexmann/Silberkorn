# Privacy

*Back to the [README](../README.en.md) · Deutsch: [datenschutz.md](datenschutz.md)*

Silberkorn works entirely on your own computer. No images are uploaded and no usage
data is sent. The AI also runs locally on the graphics card, face detection on the processor. The only network access is
downloading an AI model – and only when you explicitly ask for it in the "AI upscaling",
"AI denoise", "AI sharpen", "AI colourise", "Subject & background", "Remove objects" or
"Depth & bokeh"
card or at "Extend with AI" in the "Geometry" card and confirm the prompt that names source, size and
licence. The executable also downloads the NVIDIA libraries from pypi.org at first
start – likewise only after you agree. The lensfun lens database is only downloaded at
the push of a button in the "Lens" card, and the same goes for checking for a newer one.

Besides the slider values, a sidecar file contains a small preview of the edit and any
metadata entered, such as title or creator – passing on an image together with its
sidecar file passes on both. Sidecar files and presets from others are read with strict
checks: only known values within their limits, no file paths, nothing executable.

The folder view's preview cache lives in `%LOCALAPPDATA%\Silberkorn\vorschau.db` (the
location can be changed). Previews and paths in it are encrypted with the Windows Data
Protection API (DPAPI); lookups use a secret hash of the path. A copied file, a backup
or a removed drive therefore reveals neither images nor folder names. Images that no
longer exist drop out; after anonymising, no preview of the original remains. This does
not protect against malware running under your own account – but such malware could
read the photos themselves anyway. For the whole drive, BitLocker remains the right
layer.
