"""Welche Projektdateien der EXE-Bau neben die EXE legt."""

import hashlib
import importlib.util
import os
import re

import pytest

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _exe_bauen():
    spec = importlib.util.spec_from_file_location(
        "exe_bauen", os.path.join(WURZEL, "werkzeuge", "exe_bauen.py"))
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def test_docs_ohne_bilder_neben_die_exe(tmp_path):
    _exe_bauen().projekt_dateien(WURZEL, str(tmp_path))
    erwartet = sorted(n for n in os.listdir(os.path.join(WURZEL, "docs")) if n.endswith(".md"))
    assert erwartet, "docs/ enthaelt keine Markdown-Dateien"
    assert sorted(os.listdir(tmp_path / "docs")) == erwartet
    for name in ("LICENSE", "NOTICE", "README.md", "README.en.md", "CHANGELOG.md", "SECURITY.md",
                 "LICENSES"):
        assert (tmp_path / name).exists(), name


def test_readme_links_auf_docs_gibt_es_im_zip(tmp_path):
    # Jeder Verweis der READMEs auf docs/*.md muss im Programmordner aufloesbar sein
    _exe_bauen().projekt_dateien(WURZEL, str(tmp_path))
    for readme in ("README.md", "README.en.md"):
        text = (tmp_path / readme).read_text(encoding="utf-8")
        ziele = set(re.findall(r"\]\((docs/[^)#\s]+\.md)", text))
        assert ziele, readme
        for ziel in ziele:
            assert (tmp_path / ziel).is_file(), f"{readme} -> {ziel}"


def test_keine_toten_links_im_programmordner(tmp_path):
    bau = _exe_bauen()
    bau.projekt_dateien(WURZEL, str(tmp_path))
    assert bau.tote_links(str(tmp_path)) == []


def test_tote_links_findet_fehlende_ziele(tmp_path):
    bau = _exe_bauen()
    bau.projekt_dateien(WURZEL, str(tmp_path))
    (tmp_path / "docs" / "datenschutz.md").unlink()
    (tmp_path / "README.en.md").write_text(
        "[a](./docs/weg.en.md#teil) [b](<docs/auch weg.md>) ![c](docs/bilder/x.png)\n"
        "[d](https://example.org/weg.md) [e](#anker) [f](CONTRIBUTING.md)\n"
        "[ref]: docs/referenz.md\n"
        "```\n[g](im-code.md)\n```\n", encoding="utf-8")
    tot = bau.tote_links(str(tmp_path))
    assert "README.md -> docs/datenschutz.md" in tot
    assert "docs/datenschutz.en.md -> datenschutz.md" in tot
    assert "README.en.md -> ./docs/weg.en.md" in tot
    assert "README.en.md -> docs/referenz.md" in tot
    # Bild, Webadresse, reiner Anker, bewusste Ausnahme und Codeblock zaehlen nicht
    assert not any(t.endswith(("x.png", "example.org/weg.md", "CONTRIBUTING.md", "im-code.md"))
                   for t in tot)


def test_tote_links_prueft_security(tmp_path):
    bau = _exe_bauen()
    bau.projekt_dateien(WURZEL, str(tmp_path))
    (tmp_path / "SECURITY.md").write_text("[x](../../security/advisories/new)\n", encoding="utf-8")
    assert bau.tote_links(str(tmp_path)) == ["SECURITY.md -> ../../security/advisories/new"]


def test_tote_links_ausserhalb_des_ordners(tmp_path):
    # Liegt das Ziel neben dem Programmordner (etwa in dist/), fehlt es trotzdem im ZIP
    ordner = tmp_path / "Silberkorn"
    ordner.mkdir()
    (tmp_path / "daneben.md").write_text("da", encoding="utf-8")
    bau = _exe_bauen()
    bau.projekt_dateien(WURZEL, str(ordner))
    (ordner / "SECURITY.md").write_text("[x](../daneben.md)\n", encoding="utf-8")
    assert bau.tote_links(str(ordner)) == ["SECURITY.md -> ../daneben.md"]


def _lesen(*pfad: str) -> str:
    with open(os.path.join(WURZEL, *pfad), encoding="utf-8") as datei:
        return datei.read()


def test_pruefsumme_mit_unix_zeilenende(tmp_path):
    archiv = tmp_path / "paket.zip"
    archiv.write_bytes(b"inhalt")
    _exe_bauen().pruefsumme_schreiben(str(archiv))
    erwartet = hashlib.sha256(b"inhalt").hexdigest()
    assert (tmp_path / "paket.zip.sha256").read_bytes() == f"{erwartet}  paket.zip\n".encode()


def test_dll_ohne_lizenz_faellt_auf(tmp_path):
    intern = tmp_path / "_internal"
    for pfad in ("libssl-3.dll", "libcrypto-3.dll", "sqlite3.dll", "libffi-8.dll", "python314.dll",
                 "python3.dll", "ucrtbase.dll", "api-ms-win-crt-math-l1-1-0.dll",
                 "numpy.libs/msvcp140-a4c2.dll", "rawpy/VCOMP140.DLL", "rawpy/raw_r.dll",
                 "onnxruntime/capi/onnxruntime.dll", "PySide6/Qt6Core.dll",
                 "shiboken6/shiboken6.abi3.dll", "cupy/_core.pyd", "neu/fremd.dll", "libneu.dll"):
        (intern / pfad).parent.mkdir(parents=True, exist_ok=True)
        (intern / pfad).write_bytes(b"")
    assert _exe_bauen().dlls_ohne_lizenz(str(tmp_path)) == ["libneu.dll", "neu/fremd.dll"]


def test_openssl_1_1_faellt_auf(tmp_path):
    """OpenSSL 1.1 steht nicht unter Apache-2.0 - DRITTANBIETER.txt saehe dann falsch aus."""
    intern = tmp_path / "_internal"
    intern.mkdir()
    (intern / "libssl-1_1.dll").write_bytes(b"")
    (intern / "libcrypto-1_1-x64.dll").write_bytes(b"")
    assert len(_exe_bauen().dlls_ohne_lizenz(str(tmp_path))) == 2


def test_dll_pruefung_ohne_programmordner_bricht_ab(tmp_path):
    with pytest.raises(SystemExit, match="_internal"):
        _exe_bauen().dlls_ohne_lizenz(str(tmp_path))


def test_interpreter_bibliotheken_mit_lizenzpfad():
    zeilen = _exe_bauen().interpreter_bibliotheken().splitlines()
    assert [z.split()[0] for z in zeilen] == ["OpenSSL", "SQLite", "libffi"]
    # Auch "1.1.1t": Python 3.10 fuer Windows bringt noch OpenSSL 1.1 mit
    assert re.search(r"OpenSSL\s+\d\S*\s+Apache-2\.0 \(lizenzen/OpenSSL/LICENSE\.txt\)$", zeilen[0])
    assert re.search(r"SQLite\s+\d\S*\s+Public Domain \(lizenzen/SQLite/LICENSE\.txt\)$", zeilen[1])
    assert zeilen[2].endswith("MIT (lizenzen/Python/LICENSE.txt)")


def test_lizenztexte_der_interpreter_bibliotheken_liegen_bereit():
    bau = _exe_bauen()
    assert set(bau.INTERPRETER_LIZENZEN) == {"OpenSSL", "SQLite"}
    for name in bau.INTERPRETER_LIZENZEN:
        assert f"lizenzen/{name}/LICENSE.txt" in bau.interpreter_bibliotheken()
    assert "Apache License" in _lesen("LICENSES", bau.INTERPRETER_LIZENZEN["OpenSSL"])
    assert "public domain" in _lesen("LICENSES", bau.INTERPRETER_LIZENZEN["SQLite"])


def test_notice_nennt_was_der_interpreter_mitbringt():
    text = " ".join(_lesen("NOTICE").split())
    for angabe in ("OpenSSL (Apache License 2.0,", "SQLite (public domain,", "libffi (MIT)",
                   "Microsoft Visual C++ and Windows runtime libraries"):
        assert angabe in text, angabe


def test_versionsfehler():
    fehler_von = _exe_bauen().versionsfehler
    gut = {"ProductName": "Silberkorn", "ProductVersion": "1.2.3", "FileVersion": "1.2.3",
           "LegalCopyright": "Copyright X, MIT License. Created with assistance of Claude AI"}
    assert fehler_von(gut, "1.2.3") == []
    assert len(fehler_von(gut, "1.2.4")) == 2
    assert len(fehler_von({}, "1.2.3")) == 4
    assert fehler_von({**gut, "ProductName": ""}, "1.2.3") == ["ProductName ist ''"]
    assert fehler_von({**gut, "LegalCopyright": "Copyright X"}, "1.2.3") == [
        "LegalCopyright ohne den Hinweis auf Claude AI"]


def test_exe_nennt_die_ki_mithilfe():
    assert re.search(r'"LegalCopyright", "Copyright 2026 Alexander Unverhau, MIT License\. "\n'
                     r'\s+"Created with assistance of Claude AI"\)',
                     _lesen("silberkorn.spec"))


def test_readmes_nennen_erststart_und_lizenzliste():
    for name, hinweis in (("README.md", "**Weitere Informationen → Trotzdem ausführen**"),
                          ("README.en.md", "**More info → Run anyway**")):
        text = _lesen(name)
        assert "SmartScreen" in text and hinweis in text and "SHA-256" in text, name
        assert "`DRITTANBIETER.txt`" in text, name
    assert "DRITTANBIETER.txt" in _lesen("NOTICE")


def test_fehlerlog_ist_offengelegt():
    for pfad in (("SECURITY.md",), ("docs", "datenschutz.md"), ("docs", "datenschutz.en.md")):
        assert "`silberkorn-fehler.log`" in _lesen(*pfad), pfad


def test_dependabot_laesst_untergrenzen_und_cuda_festlegung():
    text = _lesen(".github", "dependabot.yml")
    pip, actions = text.split('- package-ecosystem: "github-actions"')
    assert '- package-ecosystem: "pip"' in pip
    assert re.search(r'^    versioning-strategy: "increase-if-necessary"$', pip, re.M)
    for paket, grenze in (("onnxruntime-gpu", ">=1.27"), ("cuda-toolkit", ">=12.9"),
                          ("nvidia-cudnn-cu12", ">=9.11")):
        assert re.search(rf'- dependency-name: "{paket}"\n\s+versions: \["{grenze}"\]', pip), paket
    assert 'interval: "monthly"' in actions
