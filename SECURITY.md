# Sicherheit

*English: please report security issues privately as described below; reports in English
are welcome.*

## Eine Lücke melden

Bitte **kein öffentliches Issue** für Sicherheitslücken. Melde sie über
GitHub: Reiter **Security** → **Report a vulnerability**
([private Sicherheitsmeldung](https://github.com/DerAlexmann/Silberkorn/security/advisories/new)). Die Meldung ist
nur für die Projektbetreuung sichtbar.

Hilfreich sind: eine Beschreibung des Problems, die Version des Programms (sie
steht in der Kopfzeile und auf dem Reiter „Info & Copyright"), Grafikkarte und
Treiberversion (ebenfalls auf diesem Reiter), das Betriebssystem und, wenn
möglich, eine Anleitung zum Nachstellen.

Eine Antwort kommt in der Regel innerhalb einer Woche.

## Unterstützte Versionen

Gepflegt wird jeweils die neueste veröffentlichte Version.

## Wie das Programm mit Daten umgeht

- **Bilder** bleiben auf dem Rechner. Sie werden weder hochgeladen noch an
  einen Dienst übergeben; gerechnet wird auf der eigenen Grafikkarte.
- **Netzwerk**: Das Programm lädt KI-Modelle nur auf ausdrücklichen Wunsch und
  nur von der angezeigten Quelle (den Releases dieses Repositorys); die EXE
  lädt beim ersten Start nach Zustimmung NVIDIAs CUDA- und cuDNN-Pakete vom
  Python Package Index (files.pythonhosted.org). Jede dieser Dateien wird gegen
  eine im Programm hinterlegte SHA-256-Prüfsumme geprüft, bevor sie verwendet
  wird. Die Objektivdatenbank von lensfun kommt nur auf Knopfdruck in der Karte
  „Objektiv“ von lensfun.github.io. Sie ändert sich laufend und hat deshalb keine
  hinterlegte Prüfsumme; ausgepackt werden nur flache XML-Dateien mit
  Größengrenzen. Sonst baut das Programm keine Verbindungen auf.
- **Gespeichert** werden in `silberkorn.json` neben dem Programm Einstellungen
  und Vorgaben: Sprache, Farbschema, Fensterlage, Ordnerpfade (zuletzt benutzte
  Ordner, LUT-Ordner, Ordneransicht, Ort des Vorschau-Caches), Vorgaben für
  Metadaten (etwa Urheber und Copyright), Drucken und Veröffentlichen. Bilder
  stehen dort nicht. Der Vorschau-Cache der
  Ordneransicht liegt verschlüsselt, standardmäßig unter `%LOCALAPPDATA%\Silberkorn` (siehe
  [docs/datenschutz.md](docs/datenschutz.md)).
