# Silberkorn – Hinweise für Claude Code

Fotoeditor für Windows mit PySide6, NumPy/CuPy und ONNX Runtime (NVIDIA-GPU).
Stil, Projektaufbau und „Einen Filter ergänzen“ stehen in `CONTRIBUTING.md` –
die Regeln dort gelten, hier steht nur, was darüber hinausgeht.

## Sprache

- Mit dem Anwender immer Deutsch, auch in kurzen Zwischenmeldungen.
- Code, Kommentare, Docstrings, Commit-Nachrichten und PR-Texte auf Deutsch.
- Neue Oberflächentexte durch `_("…")` führen und die englische Übersetzung in
  `uebersetzung.py` ergänzen.

## Prüfen

- Tests: `python -m pytest -q` (ohne Grafikkarte werden die GPU-Tests übersprungen).
- Stil: `ruff check .` – Ruff ist der einzige Linter/Formatierer, kein black/isort.
- Neue Formeln immer zweifach: Referenz in `filter.py` (NumPy/CuPy über `xp_von()`)
  und Kernel in `filter_gpu.py`, dazu ein Gleichheitstest.
- Keine CUDA-Bibliothek vor der Startprüfung importieren.

## Oberfläche

- Das Fenster muss bei 1366×768 mit 125 % Skalierung passen: Breite ≤ 1090 px.
- Farben nur über Objektnamen und das Stylesheet in `farben.py`.
- Neue Einstellungsfelder laufen automatisch durch Rückgängig, Begleitdatei
  (`werteformat.py`, streng geprüft, mit Höchstzahlen) und Voreinstellungen –
  dort jeweils mitdenken.

## Sicherheit und Datenschutz

- Begleitdateien und Voreinstellungen sind fremde Eingaben: nie `pickle`,
  `np.load(allow_pickle=False)`, Werte nur per Whitelist mit Typ-/Bereichsprüfung,
  keine Pfade aus Dateien übernehmen (UNC → NTLM-Leck), atomar schreiben.
- Downloads (NVIDIA-Bibliotheken, Modelle, Objektivdatenbank) erst nach
  Zustimmung; Ordner erst beim Herunterladen anlegen; jede Datei mit SHA-256.
- Neue KI-Modelle nur mit freier Lizenz (Apache 2.0, MIT, BSD), Lizenztext nach
  `LICENSES/`, Eintrag in `NOTICE`.

## Git

- `main` ist geschützt und linear: Arbeit auf einem eigenen Branch, PR, Merge per Rebase.
- Commit-Titel deutsch und beschreibend („Ordner erst nach Zustimmung anlegen“),
  keine Conventional-Commit-Präfixe.
- Sichtbare Änderungen bekommen einen Eintrag in `CHANGELOG.md` unter
  „[Unveröffentlicht]“.

## Nicht vorschlagen (bewusst verworfen)

- Unsichtbares Wasserzeichen.
- HEIC/HEIF in der EXE (Lizenz libheif/HEVC); `silberkorn.spec` schließt es aus.
- SVG öffnen oder als Wasserzeichen-Logo.
- Das große DDColor-Modell – nur das kleine.
- DeMosaic/DeTwirl oder anderes Rückgängigmachen von Anonymisierung.
