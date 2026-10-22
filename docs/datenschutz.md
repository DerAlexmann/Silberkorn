# Datenschutz

*Zurück zur [README](../README.md) · English: [datenschutz.en.md](datenschutz.en.md)*

Silberkorn arbeitet vollständig auf dem eigenen Rechner. Es werden keine Bilder
hochgeladen und keine Nutzungsdaten gesendet. Auch die KI rechnet lokal auf der
Grafikkarte, die Gesichtserkennung auf dem Prozessor. Die einzige Verbindung ins
Netz ist das Laden eines KI-Modells – und
das nur, wenn man in einer der Karten „KI-Hochskalieren“, „KI-Entrauschen“,
„KI-Schärfen“, „KI-Kolorieren“, „Motiv & Hintergrund“, „Objekte entfernen“,
„Tiefe & Bokeh“ oder
bei „Mit KI erweitern“ in der Karte „Geometrie“ ausdrücklich auf das Laden klickt und die Rückfrage mit Quelle,
Größe und Lizenz bestätigt. Die EXE lädt außerdem beim ersten Start – ebenfalls
erst nach Zustimmung – die NVIDIA-Bibliotheken von pypi.org. Die
Objektivdatenbank von lensfun kommt nur auf Knopfdruck in der Karte „Objektiv“,
ebenso die Frage nach einer neueren.

Eine Begleitdatei enthält neben den Reglerwerten ein kleines Vorschaubild der
Bearbeitung und eingegebene Metadaten wie Titel oder Urheber – wer ein Bild samt
Begleitdatei weitergibt, gibt beides mit. Begleitdateien und Voreinstellungen
von anderen liest Silberkorn streng geprüft: nur bekannte Werte in ihren
Grenzen, keine Dateipfade, nichts Ausführbares.

Der Vorschau-Cache der Ordneransicht liegt unter
`%LOCALAPPDATA%\Silberkorn\vorschau.db` (der Ort ist wählbar). Vorschaubilder und
Pfade darin sind mit der Windows-Datenschutz-API (DPAPI) verschlüsselt; gesucht
wird über einen geheimen Hash des Pfads. Eine kopierte Datei, ein Backup oder eine
ausgebaute Platte verraten so weder Bilder noch Ordnernamen. Bilder, die es nicht
mehr gibt, fallen heraus; nach dem Anonymisieren gibt es keine Vorschau des
Originals mehr. Gegen Schadsoftware unter dem eigenen Konto hilft das nicht –
die könnte aber ohnehin die Fotos selbst lesen. Für die ganze Platte bleibt
BitLocker die richtige Ebene.
