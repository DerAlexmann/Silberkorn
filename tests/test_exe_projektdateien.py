"""Welche Projektdateien der EXE-Bau neben die EXE legt."""

import importlib.util
import os
import re

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
