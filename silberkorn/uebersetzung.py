"""
Sprachumschaltung

Deutsch ist die Quellsprache: im Code steht der deutsche Text, _("...")
sucht ihn zur Laufzeit in der Sprachtabelle TRANSLATIONS (ganz unten in
dieser Datei). Dort ist auch beschrieben, wie eine weitere Sprache dazukommt.

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI
"""

from __future__ import annotations

SOURCE_LANGUAGE = "de"


class Uebersetzt(str):
    """Uebersetzter Text, der seinen deutschen Schluessel kennt.

    Verhaelt sich ueberall wie ein gewoehnlicher String. Das Hauptfenster
    liest daraus ab, wie sich eine Beschriftung nach einem Sprachwechsel neu
    bilden laesst - samt der Werte, die mit format() eingesetzt wurden.
    """

    def __new__(cls, text, schluessel, werte=None):
        neu = super().__new__(cls, text)
        neu.schluessel = schluessel
        neu.werte = werte or {}
        return neu

    def format(self, *args, **kwargs):
        if args:                             # Positionsargumente nutzt hier niemand
            return str.format(self, *args, **kwargs)
        return Uebersetzt(str.format(self, **kwargs), self.schluessel, kwargs)


class Translator:
    """Uebersetzt einen deutschen Quelltext in die eingestellte Sprache."""

    def __init__(self, language=SOURCE_LANGUAGE):
        self.language = language

    def __call__(self, text):
        if self.language == SOURCE_LANGUAGE:
            return Uebersetzt(text, text)
        return Uebersetzt(TRANSLATIONS.get(self.language, {}).get(text, text), text)

    def available(self):
        """Sprachkuerzel -> Anzeigename, Quellsprache immer zuerst."""
        names = {SOURCE_LANGUAGE: LANGUAGE_NAMES[SOURCE_LANGUAGE]}
        for code in TRANSLATIONS:
            names[code] = LANGUAGE_NAMES.get(code, code)
        return names


_ = Translator()


# --------------------------------------------------------------------------
# SPRACHTABELLE / LANGUAGE TABLE
#
# Quellsprache ist Deutsch - der deutsche Text im Code ist zugleich der
# Schluessel. Eine weitere Sprache kommt in drei Schritten dazu:
#   1. Kuerzel und Anzeigename in LANGUAGE_NAMES eintragen,
#      z. B.  "fr": "Francais"
#   2. In TRANSLATIONS einen Eintrag "fr": { ... } anlegen und die
#      gewuenschten Zeilen uebersetzen.
#   3. Fertig - die Auswahl oben rechts zeigt die Sprache sofort an.
#
# Nicht uebersetzte Zeilen erscheinen automatisch auf Deutsch, eine
# unvollstaendige Tabelle ist also unproblematisch. Platzhalter in
# geschweiften Klammern - {karte}, {stufe}, {treiber} ... - muessen in der
# Uebersetzung unveraendert vorkommen; ihre Reihenfolge im Satz ist frei.
# --------------------------------------------------------------------------

LANGUAGE_NAMES = {
    "de": "Deutsch",
    "en": "English",
}

TRANSLATIONS = {
    "en": {
        # Kopfzeile, Reiter, Statuszeile
        "Version {version}": "Version {version}",
        "Sprache & Darstellung": "Language & appearance",
        "Dunkel": "Dark",
        "Bearbeiten": "Edit",
        "Info & Copyright": "About & copyright",
        "Bereit.": "Ready.",
        "Stufe {stufe}": "Tier {stufe}",

        # Reiter Bearbeiten
        "Noch kein Bild geöffnet.": "No image opened yet.",
        "Bild hierher ziehen oder „Öffnen …“ wählen.":
            "Drag an image here or choose “Open …”.",
        "Öffnen …": "Open …",
        "Speichert das bearbeitete Bild unter einem neuen Namen (Strg+S) – das Original "
        "wird nie überschrieben.":
            "Saves the edited image under a new name (Ctrl+S) – the original is never "
            "overwritten.",
        "Vorher": "Before",
        "Gedrückt halten, um das unbearbeitete Bild zu sehen.":
            "Hold down to see the unedited image.",
        "Zurücksetzen": "Reset",
        # Anonymisieren
        "Anonymisieren": "Anonymise",
        "Gesichter finden": "Find faces",
        "Legt um jedes erkannte Gesicht eine Fläche. Prüfen und nachbessern – sehr "
        "kleine, verdeckte oder seitliche Gesichter können fehlen.":
            "Places an area around every detected face. Check and correct – very small, "
            "covered or side-on faces may be missed.",
        "Flächen bearbeiten": "Edit areas",
        "Auf freiem Grund ziehen legt eine Fläche an; Flächen verschieben, an den Ecken "
        "die Größe ändern, Entf löscht die gewählte.":
            "Drag on empty ground to add an area; move areas, resize them at the corners, "
            "Del removes the selected one.",
        "Auf freiem Grund ziehen legt eine Fläche an. Flächen verschieben, an den Ecken "
        "die Größe ändern; Entf löscht, Esc beendet.":
            "Drag on empty ground to add an area. Move areas, resize them at the corners; "
            "Del removes, Esc finishes.",
        "Form": "Shape",
        "Ellipse": "Ellipse",
        "Rechteck": "Rectangle",
        "Wirkung": "Effect",
        "Mosaik": "Mosaic",
        "Weichzeichnen": "Blur",
        "Schwarz füllen": "Fill black",
        "Raster": "Grid",
        "Blöcke über die Breite einer Fläche. Weniger ist sicherer: feine Mosaike "
        "lassen sich teilweise zurückrechnen.":
            "Blocks across the width of an area. Fewer is safer: fine mosaics can be "
            "partly reversed.",
        "Fläche löschen": "Remove area",
        "Alle löschen": "Remove all",
        "Ohne GPS und Seriennummern speichern": "Save without GPS and serial numbers",
        "Nimmt beim Speichern GPS-Position, Seriennummern von Kamera und Objektiv, den "
        "Besitzernamen und die Herstellerdaten aus den Metadaten.":
            "Removes the GPS position, the camera and lens serial numbers, the owner name "
            "and the maker notes from the metadata when saving.",
        "Standort und Seriennummern werden nicht mitgespeichert.":
            "Location and serial numbers will not be saved.",
        "{n} Flächen. Das Mosaik wird beim Speichern fest ins Bild gerechnet.":
            "{n} areas. The mosaic is burned into the image when saving.",
        "Gesichter, Kennzeichen oder Hausnummern unkenntlich machen.":
            "Make faces, number plates or house numbers unrecognisable.",
        "Die Gesichtserkennung ist fehlgeschlagen.": "Face detection failed.",
        "Keine Gesichter gefunden – Flächen von Hand aufziehen.":
            "No faces found – drag areas by hand.",
        "{n} Gesichter gefunden – bitte prüfen und nachbessern.":
            "{n} faces found – please check and correct.",
        # Metadaten
        "Metadaten": "Metadata",
        "Titel": "Title",
        "Beschreibung": "Description",
        "Stichwörter": "Keywords",
        "durch Komma getrennt": "separated by commas",
        "Urheber und Copyright in jedes Bild": "Creator and copyright in every image",
        "Region": "Region",
        "Bundesland, Kanton …": "State, province …",
        "Stadt": "City",
        "Land": "Country",
        "Datum": "Date",
        "Bewertung": "Rating",
        "etwa © 2026 Name": "e.g. © 2026 Name",
        "2024-05-17 14:30, 17.05.2024 oder 1965": "2024-05-17 14:30, 17.05.2024 or 1965",
        "Mehrere Stichwörter durch Komma oder Semikolon trennen.":
            "Separate several keywords with commas or semicolons.",
        "Mehrere Urheber durch Semikolon trennen.": "Separate several creators with semicolons.",
        "Aufnahmedatum. Bei alten Abzügen genügt das Jahr oder Jahr und Monat.":
            "Date taken. For old prints the year, or year and month, is enough.",
        "Merkt sich Urheber und Copyright von hier und trägt sie in jedes Bild ein, das selbst "
        "keine hat. Gespeichert wird beides wie alles andere erst mit dem Bild.":
            "Remembers the creator and copyright entered here and adds them to every image "
            "that has none of its own. Like everything else, they are only written when the "
            "image is saved.",
        "Alle Metadaten …": "All metadata …",
        "Zeigt alles, was die Datei an EXIF, GPS, IPTC und XMP enthält.":
            "Shows everything the file contains in EXIF, GPS, IPTC and XMP.",
        "Nimmt nur die Änderungen an den Metadaten zurück – Regler und Bild bleiben.":
            "Undoes only the changes to the metadata – sliders and image stay as they are.",
        "Titel, Beschreibung, Urheber, Ort und mehr – geschrieben beim Speichern.":
            "Title, description, creator, location and more – written when saving.",
        "In der Datei: {formate}. Änderungen werden beim Speichern geschrieben.":
            "In the file: {formate}. Changes are written when saving.",
        "Die Datei enthält keine Metadaten. Angaben hier werden beim Speichern geschrieben.":
            "The file contains no metadata. Details entered here are written when saving.",
        "Das Datum ist nicht lesbar – etwa 2024-05-17, 17.05.2024 oder nur 1965.":
            "The date cannot be read – try 2024-05-17, 17.05.2024 or just 1965.",
        "Metadaten von {name}": "Metadata of {name}",
        "So steht es in der Datei. Titel, Beschreibung, Stichwörter, Urheber, Copyright, Ort, "
        "Datum und Bewertung lassen sich in der Karte „Metadaten“ ändern; geschrieben wird "
        "erst beim Speichern.":
            "This is what the file contains. Title, description, keywords, creator, "
            "copyright, location, date and rating can be changed in the \"Metadata\" card; "
            "they are only written when saving.",
        "Filtern …": "Filter …",
        "Feld": "Field",
        "Wert": "Value",
        "Schließen": "Close",
        "Die Datei enthält keine Metadaten.": "The file contains no metadata.",
        "EXIF – Kamera und Aufnahme": "EXIF – camera and exposure",
        "GPS – Standort": "GPS – location",
        "IPTC (IIM) – ältere Beschreibung": "IPTC (IIM) – older description",
        "XMP – Beschreibung": "XMP – description",
        "Setzt alle Regler, Drehung, Zuschnitt und geänderte Metadaten zurück, holt "
        "entfernte Objekte zurück und verwirft eine KI-Erweiterung. Lässt sich mit "
        "„Rückgängig“ zurücknehmen.":
            "Resets all sliders, rotation, crop and changed metadata, brings back removed "
            "objects and discards an AI extension. Can be undone with “Undo”.",
        "Zu einer Karte springen": "Jump to a card",
        # Scan & Film
        "Scan & Film": "Scan & film",
        "Film": "Film",
        "Kein Film": "No film",
        "Farbnegativ": "Colour negative",
        "Schwarzweiß-Negativ": "Black-and-white negative",
        "Dia": "Slide",
        "Ein Negativ wird ins Positiv gewandelt – über die Dichte des Films, wie im "
        "Labor. Filmmaske sowie Schwarz- und Weißpunkt schätzt Silberkorn dabei selbst.":
            "A negative is converted into a positive – via the density of the film, as in "
            "the lab. Silberkorn estimates the film base as well as black and white point "
            "by itself.",
        "Filmmaske anklicken": "Pick film base",
        "Ein Klick auf unbelichteten Film – den Rand oder den Steg zwischen zwei Bildern "
        "– misst die Farbe der Filmmaske genau.":
            "A click on unexposed film – the border or the gap between two frames – "
            "measures the colour of the film base exactly.",
        "Automatisch": "Automatic",
        "Schätzt Filmmaske, Schwarz- und Weißpunkt neu aus dem Bild – etwa nach einem "
        "Klick mit der Pipette.":
            "Estimates film base, black and white point again from the image – for "
            "instance after a click with the eyedropper.",
        "Auf unbelichteten Film klicken – den Rand oder den Steg zwischen zwei "
        "Bildern. Esc bricht ab.":
            "Click on unexposed film – the border or the gap between two frames. Esc "
            "cancels.",
        "Umgewandelt. Weißabgleich, Licht und Kurven wirken danach wie gewohnt. "
        "Ist der Filmrand mitgescannt, misst die Pipette die Maske genauer.":
            "Converted. White balance, light and curves then work as usual. If the film "
            "border is part of the scan, the eyedropper measures the film base more exactly.",
        "Dias sind schon positiv und werden nicht umgewandelt.":
            "Slides are positive already and are not converted.",
        "Wandelt gescannte oder abfotografierte Negative ins Positiv – am besten "
        "als ersten Schritt, vor den KI-Karten.":
            "Converts scanned or photographed negatives into positives – best as the "
            "first step, before the AI cards.",
        "Empfindlichkeit": "Sensitivity",
        "Wie schwach eine Stelle im Infrarot sein darf, um als Staub zu gelten. Mehr "
        "findet auch feine Fusseln, kann aber Bildteile erfassen.":
            "How faint a spot in the infrared may be to count as dust. More also finds fine "
            "fibres, but may catch parts of the image.",
        "Fundstellen zeigen": "Show findings",
        "Färbt in der Vorschau blau, was als Staub oder Kratzer gefunden ist.":
            "Colours in blue in the preview what has been found as dust or scratches.",
        "Staub entfernen": "Remove dust",
        "Füllt alle Fundstellen: kleine Punkte und dünne Kratzer die Grafikkarte, breite "
        "Stellen LaMa, wenn das Modell von „Objekte entfernen“ geladen ist.":
            "Fills all findings: small specks and thin scratches on the graphics card, wide "
            "spots with LaMa if the model of \"Remove objects\" is downloaded.",
        "Zurückholen": "Bring back",
        "Nimmt das Füllen von Staub und Kratzern zurück.":
            "Undoes the filling of dust and scratches.",
        "Der Infrarotkanal zeigt das Motiv selbst, nicht den Film – etwa bei "
        "Luftbildern. Staub lässt sich daraus nicht erkennen.":
            "The infrared channel shows the scene itself, not the film – for instance in "
            "aerial images. Dust cannot be detected from it.",
        "{n} Stellen gefüllt. Ändert sich die Empfindlichkeit, füllt „Staub "
        "entfernen“ neu.":
            "{n} spots filled. If the sensitivity changes, \"Remove dust\" fills again.",
        "{n} Stellen gefunden.": "{n} spots found.",
        "Bei Schwarzweißfilm hält das Silber selbst Infrarot auf – dann findet "
        "die Suche oft das Bild statt Staub. Mit „Fundstellen zeigen“ prüfen.":
            "With black-and-white film the silver itself blocks infrared – the search then "
            "often finds the image instead of dust. Check with \"Show findings\".",
        "Der Scan hat einen Infrarotkanal: Staub und Kratzer sind darin dunkel "
        "und lassen sich finden und füllen.":
            "The scan has an infrared channel: dust and scratches are dark in it and can be "
            "found and filled.",
        "Staub wird entfernt …": "Removing dust …",
        "Staub entfernt ({s} s)": "Dust removed ({s} s)",
        "Staub entfernt": "Dust removed",
        "Staub zurückgeholt": "Dust brought back",
        "Fotos trennen …": "Split photos …",
        "Sucht auf einem Flachbett-Scan die einzelnen Abzüge, richtet sie gerade aus, "
        "beschneidet sie auf ihren Rand und speichert jeden als eigene Datei.":
            "Finds the individual prints on a flatbed scan, straightens them, crops them to "
            "their edge and saves each one as a file of its own.",
        "Auf diesem Scan sind keine einzelnen Fotos zu erkennen.":
            "No individual photos can be found on this scan.",
        "Die Fotos ließen sich nicht speichern.": "The photos could not be saved.",
        "Den Ordner gibt es nicht: {ordner}": "The folder does not exist: {ordner}",
        "{n} Fotos gespeichert in {ordner}": "{n} photos saved in {ordner}",
        "Fotos trennen": "Split photos",
        "{n} Fotos gefunden, gerade gerichtet und auf ihren Rand beschnitten. Gespeichert "
        "wird jedes gewählte Foto als eigene Datei – ausgeschnitten aus dem unbearbeiteten "
        "Scan.":
            "{n} photos found, straightened and cropped to their edge. Every selected photo "
            "is saved as a file of its own – cut from the unedited scan.",
        "Foto {n}": "Photo {n}",
        "Anklicken, um dieses Foto nicht zu speichern.": "Click to not save this photo.",
        "Ordner": "Folder",
        "Ändern …": "Change …",
        "Name": "Name",
        "Die Dateien heißen Name-01, Name-02 … – vorhandene "
        "Dateien werden nie überschrieben.":
            "The files are called Name-01, Name-02 … – existing files are never "
            "overwritten.",
        "Format": "Format",
        "Danach öffnen": "Open afterwards",
        "Dieses Foto wird nach dem Speichern zum Bearbeiten "
        "geöffnet.":
            "This photo is opened for editing after saving.",
        "Speichern": "Save",
        "Keines": "None",
        "Ordner wählen": "Choose folder",
        "{art} mit Infrarotkanal": "{art} with infrared channel",
        # Drucken
        "Drucken (Strg+P): Drucker, Papier und Bildgröße wählen, mit Vorschau auf dem "
        "Blatt. Gedruckt wird das bearbeitete Bild in voller Auflösung.":
            "Print (Ctrl+P): choose printer, paper and image size, with a preview of the "
            "sheet. The edited image is printed at full resolution.",
        "Drucken": "Print",
        "Drucker": "Printer",
        "Papier": "Paper",
        "Bildgröße": "Image size",
        "Seite füllen": "Fill the page",
        "Eigene Größe": "Custom size",
        "Bild": "Image",
        "Ganz zeigen": "Show all of it",
        "Fläche füllen (beschneidet)": "Fill the area (crops)",
        "Rand": "Margin",
        "Randlos": "Borderless",
        "Weißer Rand zusätzlich zu dem, den der Drucker braucht.":
            "White margin on top of the one the printer needs.",
        "Bis an die Kante drucken – nur, wenn Drucker und Papier das können. Sonst fehlt "
        "am Rand etwas.":
            "Print up to the edge – only if printer and paper support it. Otherwise "
            "something is missing at the edge.",
        "Exemplare": "Copies",
        "Rechnet das Bild vor dem Drucken mit dem Modell aus der Karte „KI-Hochskalieren“ "
        "größer – feine Details wirken dann schärfer.":
            "Enlarges the image before printing with the model from the “AI upscaling” "
            "card – fine details then look sharper.",
        "Vorher mit KI hochskalieren ({faktor} ×)": "Upscale with AI first ({faktor} ×)",
        "Auf dem Papier: {breite} × {hoehe} · {dpi} dpi":
            "On paper: {breite} × {hoehe} · {dpi} dpi",
        "Kein Drucker gefunden.": "No printer found.",
        "Die Bildgröße passt nicht aufs Papier – verkleinert.":
            "The image size does not fit on the paper – reduced.",
        "Für diese Größe hat das Bild wenig Pixel – der Druck kann weich wirken.":
            "The image has few pixels for this size – the print may look soft.",
        "Mit einem geladenen Modell der Karte „KI-Hochskalieren“ ließe es sich vorher "
        "vergrößern.":
            "With a downloaded model from the “AI upscaling” card it could be enlarged "
            "first.",
        "Drucken abgebrochen.": "Printing cancelled.",
        "Das Bild ließ sich nicht drucken.": "The image could not be printed.",
        "An {drucker} gesendet.": "Sent to {drucker}.",
        # Verlauf: Rueckgaengig und Wiederholen
        "Rückgängig (Strg+Z)": "Undo (Ctrl+Z)",
        "Rückgängig: {schritt} (Strg+Z)": "Undo: {schritt} (Ctrl+Z)",
        "Wiederholen (Strg+Y)": "Redo (Ctrl+Y)",
        "Wiederholen: {schritt} (Strg+Y)": "Redo: {schritt} (Ctrl+Y)",
        "Rückgängig: {schritt}": "Undone: {schritt}",
        "Wiederholt: {schritt}": "Redone: {schritt}",
        "Änderung": "Change",
        "mehrere Änderungen": "several changes",
        "Objekt entfernt": "Object removed",
        "Entferntes Objekt zurückgeholt": "Removed object brought back",
        "Entfernte Objekte zurückgeholt": "Removed objects brought back",
        "Drehen": "Rotate",
        "Spiegeln": "Flip",
        "Zuschnitt": "Crop",
        "Objektivprofil": "Lens profile",
        "KI-Erweitern": "AI extend",
        "Doppelklick setzt den Regler zurück.": "Double-click resets the slider.",

        # Reglergruppen und Regler
        "Weißabgleich": "White balance",
        "Licht": "Light",
        "Präsenz": "Presence",
        "Gradationskurve": "Tone curve",
        "Hell": "Lum",
        "R": "R",
        "G": "G",
        "B": "B",
        "Klicken setzt einen Punkt, Ziehen verschiebt ihn, Doppelklick entfernt ihn.":
            "Click to add a point, drag to move it, double-click to remove it.",
        "Klarheit": "Clarity",
        "Dunst entfernen": "Dehaze",
        "Rauschminderung": "Noise reduction",
        "Luminanz": "Luminance",
        "Die Vorschau ist verkleinert und zeigt Rauschen schwächer als das "
        "gespeicherte Bild.":
            "The preview is scaled down and shows less noise than the saved image.",
        "Farbbereiche": "Colour ranges",
        "Schwarzweiß & Tönung": "Black & white & toning",
        "In Schwarzweiß umwandeln": "Convert to black & white",
        "Die Regler darunter bestimmen, wie hell jede Farbe als Grau wird – wie ein "
        "Farbfilter vor dem Objektiv bei Schwarzweißfilm.":
            "The sliders below set how bright each colour turns out as grey – like a colour "
            "filter in front of the lens with black-and-white film.",
        "Eigene Mischung": "Custom mix",
        "Mischung wie ein klassischer Farbfilter: Rot und Orange dunkeln den Himmel ab, "
        "Grün hellt Laub auf.":
            "Mix like a classic colour filter: red and orange darken the sky, green "
            "brightens foliage.",
        "Ohne Filter": "No filter",
        "Rotfilter": "Red filter",
        "Orangefilter": "Orange filter",
        "Gelbfilter": "Yellow filter",
        "Grünfilter": "Green filter",
        "Blaufilter": "Blue filter",
        "Teiltonung": "Split toning",
        "Eigene Tönung": "Custom toning",
        "Lichter und Schatten getrennt einfärben – auf Schwarzweiß wie im Labor getönt, "
        "auf Farbbildern als Farblook.":
            "Tint highlights and shadows separately – toned as in the darkroom on black and "
            "white, a colour look on colour images.",
        "Ohne Tönung": "No toning",
        "Sepia": "Sepia",
        "Selen": "Selenium",
        "Cyanotypie": "Cyanotype",
        "Lichter warm, Schatten kalt": "Warm highlights, cool shadows",
        "Lichter: Farbton": "Highlights: hue",
        "Lichter: Sättigung": "Highlights: saturation",
        "Schatten: Farbton": "Shadows: hue",
        "Schatten: Sättigung": "Shadows: saturation",
        "Balance": "Balance",
        "Schwarzweiß-Filter": "Black & white filter",
        "Tönungsvorlage": "Toning preset",
        "Schwarzweiß": "Black & white",
        "Farbton": "Hue",
        "Rot": "Red",
        "Orange": "Orange",
        "Gelb": "Yellow",
        "Grün": "Green",
        "Aqua": "Aqua",
        "Blau": "Blue",
        "Lila": "Purple",
        "Magenta": "Magenta",
        "LUT": "LUT",
        "Geometrie": "Geometry",
        "KI-Hochskalieren": "AI upscaling",
        "Aus": "Off",
        "Schnell": "Fast",
        "Hohe Qualität": "High quality",
        "Entrauschen": "Denoise",
        "KI-Funktionen brauchen mindestens 4 GB Grafikspeicher.":
            "AI features need at least 4 GB of video memory.",
        "Dieses Modell braucht mindestens Funktionsstufe {stufe}.":
            "This model needs at least feature tier {stufe}.",
        "Dieses Modell ist noch nicht geladen.": "This model has not been downloaded yet.",
        "Modell herunterladen ({mb} MB)": "Download model ({mb} MB)",
        "Silberkorn lädt {mb} MB von:\n{quelle}\n\n"
        "Das Modell stammt von {herkunft} und wird nach dem Laden gegen seine "
        "Prüfsumme geprüft.\n\n"
        "Ablage: {ordner}\n\nJetzt herunterladen?":
            "Silberkorn downloads {mb} MB from:\n{quelle}\n\n"
            "The model comes from {herkunft} and is checked against its checksum "
            "after downloading.\n\n"
            "Location: {ordner}\n\nDownload now?",
        "KI-Entrauschen": "AI denoise",
        "Für dieses Bild berechnet. Der Regler mischt zwischen Original und "
        "entrauschtem Bild.":
            "Computed for this image. The slider blends between the original and the "
            "denoised image.",
        "Rechnet einmal über das ganze Bild – bei 24 Megapixeln 10 bis 30 "
        "Sekunden. Danach wirkt der Regler sofort.":
            "Runs once over the whole image – 10 to 30 seconds for 24 megapixels. "
            "After that the slider responds instantly.",
        "Entrauschen berechnen": "Compute denoise",
        "KI entrauscht das Bild …": "AI is denoising the image …",
        "KI-Entrauschen abgebrochen.": "AI denoise cancelled.",
        "Das KI-Entrauschen ist fehlgeschlagen.": "AI denoise failed.",
        "KI-Entrauschen fertig ({s} s, über {weg})": "AI denoise done ({s} s, via {weg})",
        "KI-Schärfen": "AI sharpen",
        "Für dieses Bild berechnet. Der Regler bestimmt, wie stark die Schärfung wirkt.":
            "Computed for this image. The slider sets how strongly the sharpening applies.",
        "Gegen leichte Fokus-Unschärfe. Rechnet einmal über das ganze Bild – bei 24 "
        "Megapixeln {zeit}. Erst entrauschen, sonst schärft die KI das Rauschen mit.":
            "For slight focus blur. Runs once over the whole image – {zeit} for 24 "
            "megapixels. Denoise first, otherwise the AI sharpens the noise too.",
        "knapp eine Minute": "just under a minute",
        "etwa drei Minuten": "about three minutes",
        "Schärfen berechnen": "Compute sharpening",
        "Motiv & Hintergrund": "Subject & background",
        "Motiv erkennen": "Detect subject",
        "Maske zeigen": "Show mask",
        "Umkehren": "Invert",
        "Hintergrund durchsichtig speichern": "Save background as transparent",
        "Unschärfe": "Blur",
        "Kante weicher": "Soften edge",
        "Kante verschieben": "Shift edge",
        "Färbt den Hintergrund in der Vorschau rot ein – nur zur Kontrolle, nicht im "
        "gespeicherten Bild.":
            "Tints the background red in the preview – only to check, not in the saved image.",
        "Die Regler dieser Karte wirken auf das Motiv statt auf den Hintergrund.":
            "The sliders of this card affect the subject instead of the background.",
        "Beim Speichern als PNG oder TIFF wird der Hintergrund transparent.":
            "When saving as PNG or TIFF, the background becomes transparent.",
        "Das Erkennen ohne Klick braucht 6 GB Grafikspeicher.":
            "Detection without clicking needs 6 GB of graphics memory.",
        "Motiv erkannt. Die Regler wirken auf den Hintergrund.":
            "Subject detected. The sliders affect the background.",
        "Die KI erkennt das Motiv – bei 24 Megapixeln in wenigen Sekunden – oder wählt "
        "aus, was man anklickt. Danach lässt sich der Hintergrund getrennt bearbeiten oder "
        "durchsichtig speichern.":
            "The AI detects the subject – in a few seconds for 24 megapixels – or selects what "
            "you click. After that the background can be edited separately or saved as "
            "transparent.",
        "Motiv erkennen · {mb} MB": "Detect subject · {mb} MB",
        "Objekt anklicken": "Click object",
        "Objekt anklicken · {mb} MB": "Click object · {mb} MB",
        "Ein Objekt im Bild per Klick auswählen – die Regler dieser Karte wirken dann auf "
        "alles andere.":
            "Select an object in the image by clicking – the sliders of this card then affect "
            "everything else.",
        "Klick zurück": "Undo click",
        "Den letzten Klick zurücknehmen (Strg+Z)": "Undo the last click (Ctrl+Z)",
        "Linksklick ins Bild nimmt einen Bereich dazu, Rechtsklick nimmt einen weg. Strg+Z "
        "nimmt den letzten Klick zurück, Esc beendet.":
            "Left-click in the image adds an area, right-click removes one. Ctrl+Z undoes the "
            "last click, Esc finishes.",
        "Objekt ausgewählt. Die Regler wirken auf alles andere.":
            "Object selected. The sliders affect everything else.",
        "Die Auswahl per Klick ließ sich nicht starten.": "Click selection could not be started.",
        "Die Auswahl ist fehlgeschlagen.": "The selection failed.",
        "Bereit zum Klicken ({s} s)": "Ready for clicking ({s} s)",
        "Objekte entfernen": "Remove objects",
        "Anklicken": "Click",
        "Anklicken · {mb} MB": "Click · {mb} MB",
        "Ein Objekt per Klick markieren – Rechtsklick nimmt einen Bereich wieder weg.":
            "Mark an object by clicking – right-click removes an area again.",
        "Pinsel": "Brush",
        "Kleinigkeiten übermalen, etwa Flecken oder Leitungen – die rechte Maustaste "
        "radiert.":
            "Paint over small things such as spots or wires – the right mouse button erases.",
        "Pinselgröße": "Brush size",
        "Entfernen · {mb} MB": "Remove · {mb} MB",
        "Markierung löschen": "Clear marking",
        "Letzte Entfernung zurücknehmen": "Undo last removal",
        "Zurücknehmen": "Undo",
        "Die blaue Markierung verwerfen, ohne etwas zu entfernen.":
            "Discard the blue marking without removing anything.",
        "Füllt die blau markierte Stelle mit passendem Hintergrund.":
            "Fills the area marked in blue with matching background.",
        "Lädt zuerst das KI-Modell ({mb} MB) aus den Releases von Silberkorn "
        "auf GitHub – nach einer Rückfrage mit Quelle, Größe und Lizenz.":
            "First downloads the AI model ({mb} MB) from Silberkorn's releases on GitHub "
            "– after asking, with source, size and licence.",
        "Berechnet das Ergebnis einmal für das ganze Bild; mit „Stärke“ lässt "
        "es sich danach stufenlos einblenden.":
            "Computes the result once for the whole image; “Strength” then blends it "
            "in smoothly.",
        "Die KI erkennt das Hauptmotiv – die Regler dieser Karte wirken dann auf den "
        "Hintergrund.":
            "The AI detects the main subject – the sliders of this card then affect the "
            "background.",
        "Schätzt die Tiefe des ganzen Bildes – danach wirken Unschärfe, Fokus und "
        "Schärfentiefe.":
            "Estimates the depth of the whole image – then blur, focus and depth of field "
            "take effect.",
        "Linksklick markiert ein Objekt, Rechtsklick nimmt einen Bereich weg. Strg+Z nimmt "
        "den letzten Klick zurück, Esc beendet.":
            "Left-click marks an object, right-click removes an area. Ctrl+Z undoes the last "
            "click, Esc finishes.",
        "Mit der linken Maustaste übermalen, was weg soll; die rechte radiert. Die mittlere "
        "verschiebt das vergrößerte Bild, Esc beendet.":
            "Paint over what should go with the left mouse button; the right one erases. The "
            "middle one moves the zoomed image, Esc finishes.",
        "Blau markiert ist, was verschwindet. „Entfernen“ füllt die Stelle mit passendem "
        "Hintergrund.":
            "What is marked in blue will disappear. “Remove” fills the spot with "
            "matching background.",
        "Ein Objekt anklicken oder übermalen – die KI füllt die Stelle mit dem, was dahinter "
        "liegen könnte.":
            "Click or paint over an object – the AI fills the spot with what could be behind "
            "it.",
        "Bisher entfernt: {n}.": "Removed so far: {n}.",
        "Das Entfernen ist fehlgeschlagen.": "Removing failed.",
        "Entfernt ({s} s)": "Removed ({s} s)",
        "Mit KI erweitern statt beschneiden": "Extend with AI instead of cropping",
        "Statt das Bild auf das Seitenverhältnis zuzuschneiden, erfindet die KI die "
        "fehlenden Ränder dazu. Das Original bleibt unverändert.":
            "Instead of cropping the image to the aspect ratio, the AI invents the missing "
            "borders. The original stays unchanged.",
        "KI-Erweitern braucht mindestens 8 GB Grafikspeicher.":
            "Extending with AI needs at least 8 GB of graphics memory.",
        "Ein Seitenverhältnis wählen – die KI erfindet, was dafür fehlt.":
            "Choose an aspect ratio – the AI invents what is missing for it.",
        "Das Bild hat dieses Seitenverhältnis schon.":
            "The image already has this aspect ratio.",
        "Neue Größe: {breite} × {hoehe} px. Die KI rechnet rund eine halbe Minute.":
            "New size: {breite} × {hoehe} px. The AI takes about half a minute.",
        "Über 25 % je Seite erfindet die KI mehr, als sie sieht – das Ergebnis kann "
        "unstimmig werden.":
            "Beyond 25 % per side the AI invents more than it sees – the result may not "
            "fit together.",
        "Erweitern · {mb} MB": "Extend · {mb} MB",
        "Erweitern": "Extend",
        "Neu erzeugen": "Regenerate",
        "Erfindet die Ränder noch einmal, mit anderem Zufall.":
            "Invents the borders once more, with a different random seed.",
        "Erfindet die fehlenden Ränder für das gewählte Seitenverhältnis. Das Original "
        "bleibt unverändert.":
            "Invents the missing borders for the chosen aspect ratio. The original stays "
            "unchanged.",
        "Erweiterung verworfen.": "Extension discarded.",
        "KI erweitert das Bild …": "AI is extending the image …",
        "KI-Erweitern abgebrochen.": "Extending with AI cancelled.",
        "Das KI-Erweitern ist fehlgeschlagen.": "Extending with AI failed.",
        "KI-Erweitern fertig ({s} s)": "Extended with AI ({s} s)",
        "Tiefe & Bokeh": "Depth & bokeh",
        "Fokus (fern – nah)": "Focus (far – near)",
        "Schärfentiefe": "Depth of field",
        "Fokus ins Bild klicken": "Click focus in image",
        "Ein Klick ins Bild stellt auf diese Entfernung scharf.":
            "A click in the image focuses at that distance.",
        "Tiefenkarte zeigen": "Show depth map",
        "Zeigt in der Vorschau die geschätzte Tiefe: hell ist nah, dunkel fern.":
            "Shows the estimated depth in the preview: bright is near, dark is far.",
        "Motiv scharf halten": "Keep subject sharp",
        "Ist das Motiv erkannt oder angeklickt, bleibt es scharf, gleich wie tief es liegt.":
            "If the subject is detected or clicked, it stays sharp, whatever its depth.",
        "Tiefe geschätzt. Die Unschärfe wächst mit dem Abstand zur Fokusebene, nach vorn "
        "wie nach hinten.":
            "Depth estimated. The blur grows with the distance from the focal plane, towards "
            "the front as well as the back.",
        "Die KI schätzt, wie weit alles im Bild entfernt ist – in Sekundenbruchteilen. "
        "Danach lässt sich der Hintergrund wie mit einem lichtstarken Objektiv "
        "weichzeichnen.":
            "The AI estimates how far away everything in the image is – in a fraction of a "
            "second. After that the background can be blurred as with a fast lens.",
        "Tiefe berechnen": "Estimate depth",
        "Die Tiefe ließ sich nicht schätzen.": "The depth could not be estimated.",
        "Tiefe geschätzt ({s} s)": "Depth estimated ({s} s)",
        "RAW": "RAW",
        "Schnell (GPU)": "Fast (GPU)",
        "Beste Qualität": "Best quality",
        "Schnell: Demosaicing nach Malvar, He und Cutler auf der Grafikkarte, eine 24-MP-RAW "
        "in rund 0,2 s. Beste Qualität: LibRaw mit dem Verfahren DHT auf dem Prozessor, etwa "
        "1,5 s, mit weniger Farbsäumen an feinen Mustern. Gilt beim nächsten Öffnen einer RAW.":
            "Fast: demosaicing after Malvar, He and Cutler on the graphics card, a 24 MP RAW in "
            "about 0.2 s. Best quality: LibRaw with the DHT method on the processor, about "
            "1.5 s, with fewer colour fringes on fine patterns. Applies the next time a RAW "
            "is opened.",
        "Das Motiv ließ sich nicht erkennen.": "The subject could not be detected.",
        "Motiv erkannt ({s} s, über {weg})": "Subject detected ({s} s, via {weg})",
        "Gespeichert: {name} – ohne durchsichtigen Hintergrund, das kann JPEG nicht. Als PNG "
        "oder TIFF speichern.":
            "Saved: {name} – without a transparent background, JPEG cannot do that. Save as "
            "PNG or TIFF.",
        "KI schärft das Bild …": "AI is sharpening the image …",
        "KI-Schärfen abgebrochen.": "AI sharpen cancelled.",
        "Das KI-Schärfen ist fehlgeschlagen.": "AI sharpen failed.",
        "KI-Schärfen fertig ({s} s, über {weg})": "AI sharpen done ({s} s, via {weg})",
        "KI-Modell herunterladen": "Download AI model",
        "TensorRT bereitet das Modell einmalig für diese Grafikkarte vor – das dauert "
        "einige Minuten. Danach rechnet die KI rund doppelt so schnell.":
            "TensorRT is preparing the model for this graphics card once – this takes a few "
            "minutes. After that, the AI runs about twice as fast.",
        "Gespeichert: {name} ({ms} ms, KI über {weg})": "Saved: {name} ({ms} ms, AI via {weg})",
        "nicht installiert (optional, siehe README)": "not installed (optional, see README)",
        "TensorRT ließ sich nicht vorbereiten – die KI rechnet mit CUDA.":
            "TensorRT could not be prepared – the AI computes with CUDA.",
        "Modell wird heruntergeladen …": "Downloading model …",
        "Herunterladen abgebrochen.": "Download cancelled.",
        "Das Modell ließ sich nicht herunterladen.": "The model could not be downloaded.",
        "KI-Modell geladen: {ordner}": "AI model downloaded: {ordner}",
        "Wird beim Speichern angewendet. KI ergänzt Details, die im Original "
        "nicht vorhanden waren.":
            "Applied when saving. AI adds details that were not present in the original.",
        "KI vergrößert das Bild …": "AI is upscaling the image …",
        "Abbrechen": "Cancel",
        "Speichern abgebrochen.": "Saving cancelled.",
        "Die KI-Vergrößerung ist fehlgeschlagen.": "AI upscaling failed.",
        "Objektiv": "Lens",
        "Begradigen": "Straighten",
        "Perspektive senkrecht": "Vertical perspective",
        "Perspektive waagrecht": "Horizontal perspective",
        "Verzeichnung": "Distortion",
        "Vignette": "Vignetting",
        "Farbsaum Rot/Cyan": "Fringe red/cyan",
        "Farbsaum Blau/Gelb": "Fringe blue/yellow",
        "↺ Links": "↺ Left",
        "↻ Rechts": "↻ Right",
        "⇋ Spiegeln": "⇋ Flip",
        "Zuschneiden": "Crop",
        "Rahmen auf dem Bild ziehen; Eingabetaste übernimmt, Esc bricht ab.":
            "Drag the frame on the image; Enter applies, Esc cancels.",
        "Voll": "Full",
        "Zuschnitt zurücksetzen": "Reset crop",
        "Frei": "Free",
        "Original": "Original",
        "Einpassen: das ganze Bild zeigen (Strg+0)": "Fit: show the whole image (Ctrl+0)",
        "100 %: ein Bildpixel je Bildschirmpixel (Strg+1). Mausrad zoomt, Ziehen "
        "verschiebt, Doppelklick wechselt.":
            "100 %: one image pixel per screen pixel (Ctrl+1). Mouse wheel zooms, dragging "
            "pans, double-click toggles.",
        "Stärke": "Strength",
        "LUT laden …": "Load LUT …",
        "Entfernen": "Remove",
        "Geladen: {name}": "Loaded: {name}",
        "Keine LUT geladen.": "No LUT loaded.",
        "LUT laden": "Load LUT",
        "Die LUT lässt sich nicht lesen.": "The LUT cannot be read.",
        "Farbe": "Colour",
        "Details": "Detail",
        "Temperatur": "Temperature",
        "Tönung": "Tint",
        "Belichtung": "Exposure",
        "Kontrast": "Contrast",
        "Lichter": "Highlights",
        "Tiefen": "Shadows",
        "Dynamik": "Vibrance",
        "Sättigung": "Saturation",
        "Schärfen": "Sharpening",
        "Radius": "Radius",

        # Öffnen und Speichern
        "Bild öffnen": "Open image",
        "Bilder": "Images",
        "Bild speichern": "Save image",
        "Dieses Dateiformat wird nicht unterstützt.": "This file format is not supported.",
        "Die Datei lässt sich nicht öffnen.": "The file cannot be opened.",
        "Das Bild lässt sich nicht speichern.": "The image cannot be saved.",
        "Für dieses Bild reicht der Grafikspeicher nicht.":
            "There is not enough video memory for this image.",
        "Ungespeicherte Änderungen": "Unsaved changes",
        "Die Änderungen an {name} sind nicht gespeichert. Trotzdem fortfahren?":
            "The changes to {name} have not been saved. Continue anyway?",
        "{name} geöffnet – {breite} × {hoehe} Pixel, {art}":
            "{name} opened – {breite} × {hoehe} pixels, {art}",
        "8 Bit": "8-bit",
        "16 Bit": "16-bit",
        "Alle Bilder": "All images",
        "RAW wird entwickelt …": "Developing RAW …",
        "Gespeichert: {name} ({ms} ms)": "Saved: {name} ({ms} ms)",

        # Reiter Info & Copyright, Statuszeile
        "Grafikkarte": "Graphics card",
        "Nur klassische Filter – für KI-Funktionen sind mindestens "
        "4 GB Grafikspeicher nötig.":
            "Classic filters only – AI features need at least 4 GB of video memory.",
        "Klassische Filter und kleine KI-Modelle, in kleinen Kacheln gerechnet.":
            "Classic filters and small AI models, processed in small tiles.",
        "Klassische Filter und alle Restaurierungsmodelle: Hochskalieren, "
        "Entrauschen, Freistellen und Objektauswahl.":
            "Classic filters and all restoration models: upscaling, denoising, "
            "background removal and object selection.",
        "Zusätzlich größere Modelle, größere Kacheln und generative Füllung.":
            "In addition larger models, larger tiles and generative fill.",
        "Voller Umfang, auch große generative Modelle und mehrere Modelle "
        "gleichzeitig im Speicher.":
            "Full feature set, including large generative models and several models "
            "held in memory at once.",

        # Reiter Info & Copyright
        "Ein quelloffener, GPU-beschleunigter KI-Bild- und Fotoverbesserer "
        "auf Basis neuronaler Netze.":
            "An open-source, GPU-accelerated AI image & photo enhancer powered by "
            "neural networks.",
        "Erstellt mit Unterstützung von Claude AI": "Created with assistance of Claude AI",
        "Veröffentlicht unter der MIT-Lizenz.": "Released under the MIT licence.",
        "Technisches": "Technical details",
        "Grafikspeicher": "Video memory",
        "CUDA-Architektur": "Compute capability",
        "Treiber": "Driver",
        "Funktionsstufe": "Feature tier",
        "Rechengenauigkeit": "Precision",
        "Python": "Python",
        "PySide6 / Qt": "PySide6 / Qt",
        "CuPy / CUDA": "CuPy / CUDA",
        "Einstellungen": "Settings",
        "Marken & Hinweise": "Trademarks & notices",
        "NVIDIA, RTX, GeForce, CUDA und TensorRT sind Marken oder eingetragene Marken "
        "der NVIDIA Corporation in den USA und anderen Ländern. Silberkorn ist ein "
        "unabhängiges Projekt und steht in keiner Verbindung zur NVIDIA Corporation; "
        "es wird von ihr weder unterstützt noch gesponsert.":
            "NVIDIA, RTX, GeForce, CUDA and TensorRT are trademarks or registered "
            "trademarks of NVIDIA Corporation in the U.S. and other countries. "
            "Silberkorn is an independent project and is not affiliated with, "
            "endorsed or sponsored by NVIDIA Corporation.",
        "Qt ist eine Marke der The Qt Company Ltd., Python eine Marke der Python "
        "Software Foundation, Windows eine Marke der Microsoft Corporation. Alle "
        "weiteren Marken gehören ihren jeweiligen Inhabern.":
            "Qt is a trademark of The Qt Company Ltd., Python a trademark of the Python "
            "Software Foundation, Windows a trademark of Microsoft Corporation. All "
            "other trademarks are the property of their respective owners.",
        "KI-Verfahren ergänzen Bilddetails, die im Original nicht vorhanden waren. "
        "Bearbeitete Bilder eignen sich deshalb nicht als Beweis- oder "
        "Dokumentationsmittel.":
            "AI methods add image details that were not present in the original. "
            "Processed images are therefore not suitable as evidence or for "
            "documentation purposes.",
        "Verwendete Fremdkomponenten und ihre Lizenzen stehen in der Datei NOTICE.":
            "Third-party components and their licences are listed in the NOTICE file.",

        # Startmeldungen
        "Keine NVIDIA-Grafikkarte gefunden": "No NVIDIA graphics card found",
        "Silberkorn benötigt eine NVIDIA-RTX-Grafikkarte (ab der RTX-2000-Serie) "
        "mit installiertem NVIDIA-Treiber. Auf diesem Rechner wurde weder eine "
        "NVIDIA-Grafikkarte noch ein NVIDIA-Treiber gefunden.":
            "Silberkorn requires an NVIDIA RTX graphics card (RTX 2000 series or "
            "newer) with the NVIDIA driver installed. Neither an NVIDIA graphics card "
            "nor an NVIDIA driver was found on this computer.",
        "Der NVIDIA-Treiber ist installiert, meldet aber keine Grafikkarte. "
        "Silberkorn benötigt eine NVIDIA-RTX-Grafikkarte (ab der RTX-2000-Serie).":
            "The NVIDIA driver is installed but reports no graphics card. Silberkorn "
            "requires an NVIDIA RTX graphics card (RTX 2000 series or newer).",
        "Keine RTX-Grafikkarte gefunden": "No RTX graphics card found",
        "Gefunden: {karte}. Silberkorn benötigt eine RTX-Grafikkarte mit "
        "Tensor Cores (ab der RTX-2000-Serie). GTX-Karten und ältere Modelle "
        "werden nicht unterstützt.":
            "Found: {karte}. Silberkorn requires an RTX graphics card with Tensor "
            "Cores (RTX 2000 series or newer). GTX cards and older models are not "
            "supported.",
        "Grafiktreiber zu alt": "Graphics driver too old",
        "Gefunden: {karte} mit Treiber {treiber}. Silberkorn benötigt den "
        "NVIDIA-Treiber {mindestens} oder neuer. Bitte den Grafiktreiber "
        "aktualisieren und das Programm danach erneut starten.":
            "Found: {karte} with driver {treiber}. Silberkorn requires NVIDIA driver "
            "{mindestens} or newer. Please update the graphics driver and then start "
            "the program again.",
        "Die vollständigen Systemvoraussetzungen stehen in der README.":
            "The full system requirements are listed in the README.",
        "Treiber herunterladen": "Download driver",
        "Beenden": "Quit",
        "NVIDIA-Bibliotheken einrichten": "Set up NVIDIA libraries",
        "Silberkorn rechnet mit CUDA und cuDNN von NVIDIA. Diese Bibliotheken "
        "werden nicht mit dem Programm ausgeliefert, sondern einmalig aus NVIDIAs "
        "offiziellen Paketen vom Python Package Index (pypi.org) geladen – "
        "{laden} GB, ausgepackt rund {platz} GB. Jede Datei wird gegen ihre "
        "Prüfsumme geprüft.":
            "Silberkorn computes with NVIDIA's CUDA and cuDNN. These libraries are not "
            "shipped with the program but downloaded once from NVIDIA's official "
            "packages on the Python Package Index (pypi.org) – {laden} GB, about "
            "{platz} GB unpacked. Every file is verified against its checksum.",
        "Für diese Bibliotheken gelten die Lizenzbedingungen von NVIDIA:":
            "These libraries are subject to NVIDIA's licence terms:",
        "Mit „Zustimmen und herunterladen“ werden sie anerkannt.":
            "Clicking “Agree and download” accepts them.",
        "Ablage: {ordner}": "Location: {ordner}",
        "Zustimmen und herunterladen": "Agree and download",
        "CuPy ließ sich nicht laden": "CuPy could not be loaded",
        "Das Hauptfenster ließ sich nicht öffnen": "The main window could not be opened",
        "Die Einzelheiten stehen unter „Details“ und in {log}.":
            "The details are under “Details” and in {log}.",
        "Die Einzelheiten stehen unter „Details“.": "The details are under “Details”.",
        "NVIDIA-Bibliotheken werden heruntergeladen …": "Downloading NVIDIA libraries …",
        "Die NVIDIA-Bibliotheken ließen sich nicht einrichten. "
        "Beim nächsten Start versucht Silberkorn es erneut.":
            "The NVIDIA libraries could not be set up. Silberkorn will try again at "
            "the next start.",

        # KI-Kolorieren
        "KI-Kolorieren": "AI colourise",
        "Kolorieren berechnen": "Compute colours",
        "Für Schwarzweiß- und Sepiabilder: Die KI schätzt die Farben aus der Helligkeit – "
        "glaubwürdig, aber geraten. Rechnet in unter einer Sekunde.":
            "For black-and-white and sepia images: the AI estimates the colours from the "
            "brightness – plausible, but guessed. Takes less than a second.",
        "Für dieses Bild berechnet. Der Regler mischt zwischen Original und kolorierter "
        "Fassung; Weißabgleich, Sättigung und Farbbereiche wirken danach wie gewohnt.":
            "Computed for this image. The slider blends between the original and the "
            "colourised version; white balance, saturation and colour ranges work as usual "
            "afterwards.",
        "KI koloriert das Bild …": "AI is colourising the image …",
        "KI-Kolorieren abgebrochen.": "AI colourising cancelled.",
        "Das KI-Kolorieren ist fehlgeschlagen.": "AI colourising failed.",
        "KI-Kolorieren fertig ({s} s, über {weg})": "AI colourising done ({s} s, via {weg})",
        # Objektivprofile (lensfun)
        "%d.%m.%Y": "%Y-%m-%d",
        "Objektivprofil anwenden": "Apply lens profile",
        "Gleicht Verzeichnung, Farbsäume und Vignette nach der Objektivdatenbank "
        "lensfun aus. Die Regler darunter wirken zusätzlich.":
            "Corrects distortion, colour fringes and vignetting from the lensfun lens "
            "database. The sliders below act on top of it.",
        "Objektivdatenbank laden": "Load lens database",
        "Nach neuer Datenbank suchen": "Check for a newer database",
        "Fragt bei lensfun nach, ob es eine neuere Objektivdatenbank gibt. Silberkorn "
        "fragt nie von selbst.":
            "Asks lensfun whether a newer lens database exists. Silberkorn never asks on "
            "its own.",
        "Die Objektivdatenbank ist noch nicht geladen (etwa 0,5 MB).":
            "The lens database has not been loaded yet (about 0.5 MB).",
        "Objektivdatenbank vom {datum}.": "Lens database of {datum}.",
        "Die Datei nennt kein Objektiv.": "The file does not name a lens.",
        "Kein Profil für „{objektiv}“ gefunden.": "No profile found for “{objektiv}”.",
        "Farbsäume": "Colour fringes",
        "Profil für: {arten}": "Profile for: {arten}",
        "Kamera-JPEGs sind oft schon in der Kamera korrigiert – deshalb hier nicht "
        "automatisch.":
            "Camera JPEGs are often already corrected in the camera – so not applied "
            "automatically here.",
        "Silberkorn lädt die Objektivdatenbank (etwa 0,5 MB) von:\n{quelle}\n\n"
        "Sie stammt vom Projekt {herkunft}.\n\n"
        "Ablage: {ordner}\n\nJetzt herunterladen?":
            "Silberkorn downloads the lens database (about 0.5 MB) from:\n{quelle}\n\n"
            "It comes from the {herkunft} project.\n\n"
            "Location: {ordner}\n\nDownload now?",
        "Objektivdatenbank wird geladen …": "Loading the lens database …",
        "Die Objektivdatenbank ließ sich nicht laden.": "The lens database could not be loaded.",
        "Objektivdatenbank geladen: {ordner}": "Lens database loaded: {ordner}",
        "Ob es eine neuere Objektivdatenbank gibt, ließ sich nicht feststellen.":
            "Could not determine whether a newer lens database exists.",
        "Objektivdatenbank": "Lens database",
        "Die Objektivdatenbank ist aktuell (Stand {datum}).":
            "The lens database is up to date (as of {datum}).",
        "Es gibt eine neuere Objektivdatenbank vom {datum} (etwa 0,5 MB, von {quelle})."
        "\n\nJetzt laden?":
            "A newer lens database of {datum} is available (about 0.5 MB, from {quelle})."
            "\n\nLoad it now?",
        # Für Veröffentlichung speichern
        "Fürs Netz …": "For the web …",
        "Verkleinert, mit Wasserzeichen und Rechteangaben speichern – etwa für Bilder "
        "im Netz. Das Original bleibt unverändert.":
            "Save downsized, with watermark and rights information – for images on the "
            "web, for instance. The original stays unchanged.",
        "Für Veröffentlichung speichern": "Save for publishing",
        "Für Veröffentlichung gespeichert: {name} – {breite} × {hoehe} Pixel ({ms} ms)":
            "Saved for publishing: {name} – {breite} × {hoehe} pixels ({ms} ms)",
        "Speichern …": "Save …",
        "Größe": "Size",
        "Längste Kante": "Longest edge",
        "Prozent": "Percent",
        "Kleinere Bilder werden nicht vergrößert.": "Smaller images are not enlarged.",
        "Das Bild bleibt {breite} × {hoehe} Pixel groß.":
            "The image stays {breite} × {hoehe} pixels.",
        "Ergebnis: {breite} × {hoehe} Pixel (Original {b0} × {h0})":
            "Result: {breite} × {hoehe} pixels (original {b0} × {h0})",
        "Wasserzeichen": "Watermark",
        "Text": "Text",
        "z. B. Spieltitel oder Webadresse": "e.g. game title or web address",
        "Logo": "Logo",
        "kein Logo": "no logo",
        "Wählen …": "Choose …",
        "Logo entfernen": "Remove logo",
        "Logo wählen": "Choose logo",
        "Die Datei lässt sich nicht als Bild lesen.": "The file cannot be read as an image.",
        "Position": "Position",
        "Unten rechts": "Bottom right",
        "Unten links": "Bottom left",
        "Oben rechts": "Top right",
        "Oben links": "Top left",
        "Mitte": "Centre",
        "Textfarbe": "Text colour",
        "Weiß": "White",
        "Schwarz": "Black",
        "Deckkraft": "Opacity",
        "Als Muster über das ganze Bild": "As a pattern across the whole image",
        "Schwerer zu entfernen als ein Zeichen in der Ecke, stört aber mehr beim Ansehen.":
            "Harder to remove than a mark in the corner, but more distracting to look at.",
        "Logo am besten als PNG mit durchsichtigem Hintergrund.":
            "Ideally a PNG logo with a transparent background.",
        "Rechte & Metadaten": "Rights & metadata",
        "Urheber": "Creator",
        "Copyright": "Copyright",
        "Webadresse": "Web address",
        "z. B. © 2026 Name": "e.g. © 2026 Name",
        "KI-Training und Data-Mining untersagen": "Prohibit AI training and data mining",
        "Schreibt einen maschinenlesbaren Nutzungsvorbehalt nach IPTC in die Datei. "
        "Suchmaschinen dürfen das Bild weiterhin finden.":
            "Writes a machine-readable reservation of rights (IPTC) into the file. Search "
            "engines may still find the image.",
        "Alle Kameradaten entfernen": "Remove all camera data",
        "Kamera, Objektiv, Belichtung und Aufnahmezeit. GPS-Position und "
        "Seriennummern werden in jedem Fall entfernt.":
            "Camera, lens, exposure and capture time. GPS position and serial numbers are "
            "always removed.",
        "Das Bild enthält von der KI erfundene Teile – das wird in den Metadaten vermerkt.":
            "The image contains parts invented by AI – this is noted in the metadata.",
        # Voreinstellungen und Begleitdatei
        "Voreinstellungen": "Presets",
        "Voreinstellung": "Preset",
        "Einstellungen unter einem Namen sichern und auf andere Bilder legen – oder "
        "von einem Bild aufs nächste kopieren.":
            "Save settings under a name and apply them to other images – or copy them from "
            "one image to the next.",
        "Anwenden": "Apply",
        "Die gewählte Voreinstellung auf dieses Bild legen. Lässt sich mit „Rückgängig“ "
        "zurücknehmen.":
            "Apply the selected preset to this image. Can be reverted with “Undo”.",
        "Sichern …": "Save …",
        "Die Einstellungen dieses Bildes als Voreinstellung sichern – welche, steht im "
        "nächsten Schritt zur Wahl.":
            "Save this image's settings as a preset – the next step lets you choose which.",
        "Löschen": "Delete",
        "Die gewählte Voreinstellung löschen": "Delete the selected preset",
        "Voreinstellungen importieren und exportieren": "Import and export presets",
        "Importieren …": "Import …",
        "Exportieren …": "Export …",
        "Kopieren": "Copy",
        "Einstellungen dieses Bildes merken, um sie auf ein anderes zu legen "
        "(Strg+Umschalt+C)":
            "Remember this image's settings to apply them to another one (Ctrl+Shift+C)",
        "Einfügen": "Paste",
        "Die kopierten Einstellungen auf dieses Bild legen (Strg+Umschalt+V)":
            "Apply the copied settings to this image (Ctrl+Shift+V)",
        "Die LUT lässt sich nicht mehr lesen.": "The LUT can no longer be read.",
        "Voreinstellung ersetzen": "Replace preset",
        "Die Voreinstellung „{name}“ gibt es schon. Ersetzen?":
            "The preset “{name}” already exists. Replace it?",
        "Die Voreinstellung lässt sich nicht sichern.": "The preset cannot be saved.",
        "Voreinstellung „{name}“ gesichert.": "Preset “{name}” saved.",
        "Die Voreinstellung lässt sich nicht lesen.": "The preset cannot be read.",
        "Voreinstellung „{name}“ angewendet.": "Preset “{name}” applied.",
        "Voreinstellung löschen": "Delete preset",
        "Die Voreinstellung „{name}“ löschen?": "Delete the preset “{name}”?",
        "Die Voreinstellung lässt sich nicht löschen.": "The preset cannot be deleted.",
        "Voreinstellung importieren": "Import preset",
        "Voreinstellung (*.json)": "Preset (*.json)",
        "Die Datei ist keine lesbare Voreinstellung.": "The file is not a readable preset.",
        "Dieser Name taugt nicht für eine Voreinstellung.":
            "This name cannot be used for a preset.",
        "Voreinstellung „{name}“ importiert.": "Preset “{name}” imported.",
        "Voreinstellung exportieren": "Export preset",
        "Die Voreinstellung lässt sich nicht exportieren.": "The preset cannot be exported.",
        "Voreinstellung exportiert: {name}": "Preset exported: {name}",
        "Einstellungen kopiert – mit Strg+Umschalt+V auf ein anderes Bild legen.":
            "Settings copied – apply them to another image with Ctrl+Shift+V.",
        "Einstellungen eingefügt.": "Settings pasted.",
        "Einstellungen eingefügt": "Settings pasted",
        "Einige Werte waren ungültig und wurden übergangen.":
            "Some values were invalid and have been skipped.",
        "Voreinstellung sichern": "Save preset",
        "Einstellungen kopieren": "Copy settings",
        "z. B. Kodak Portra": "e.g. Kodak Portra",
        "Was mitgenommen wird:": "What to include:",
        "Gemessene Filmmaske mitnehmen": "Include the measured film base",
        "Für Bilder vom selben Filmstreifen. Sonst wird die Filmmaske an jedem Bild neu "
        "geschätzt.":
            "For images from the same strip of film. Otherwise the film base is estimated "
            "anew for each image.",
        "Grundregler": "Basic adjustments",
        "KI-Stärken": "AI strengths",
        "Weißabgleich, Licht, Präsenz, Farbe und Details":
            "White balance, light, presence, colour and details",
        "Die Filmart – und auf Wunsch die gemessene Filmmaske":
            "The film type – and, if wanted, the measured film base",
        "Nur die Stärke von KI-Entrauschen, -Schärfen und -Kolorieren. Berechnet "
        "werden muss jedes Bild selbst.":
            "Only the strength of AI denoise, sharpen and colourise. Each image has to be "
            "computed itself.",
        "Die Regler für den Hintergrund – sie wirken erst mit einer Maske.":
            "The background sliders – they only take effect with a mask.",
        "Bokeh, Fokus und Schärfentiefe – sie wirken erst mit einer Tiefe.":
            "Bokeh, focus and depth of field – they only take effect with a depth map.",
        "Verzeichnung, Vignette, Farbsäume und ob das Objektivprofil gilt":
            "Distortion, vignette, colour fringing and whether the lens profile applies",
        "Drehen, Spiegeln, Zuschnitt, Begradigen und Perspektive – meist nur für "
        "ein bestimmtes Bild richtig":
            "Rotate, flip, crop, straighten and perspective – usually only right for one "
            "particular image",
        "Die Flächen zum Anonymisieren – sie gehören zu einem bestimmten Bild":
            "The areas to anonymise – they belong to one particular image",
        "Titel, Beschreibung, Urheber, Ort, Datum und Bewertung":
            "Title, description, creator, location, date and rating",
        "Begleitdateien": "Sidecar files",
        "Die Bearbeitung beim Wechsel des Bildes und beim Beenden in einer kleinen Datei "
        "neben dem Bild sichern (foto.jpg.silberkorn). Beim nächsten Öffnen ist alles wie "
        "zuvor; das Bild selbst bleibt unverändert.":
            "Save the edit in a small file next to the image when switching images and on "
            "exit (photo.jpg.silberkorn). The next time it is opened, everything is as "
            "before; the image itself stays unchanged.",
        "Bearbeitung neben dem Bild sichern?": "Save the edit next to the image?",
        "Silberkorn kann die Bearbeitung in einer kleinen Begleitdatei neben dem Bild "
        "sichern – „{name}“. Wird das Bild später wieder geöffnet, ist alles wie zuvor: "
        "Regler, entfernte Objekte, Staub, Maske und KI-Erweiterung. Das Bild selbst "
        "bleibt unverändert.\n\nBegleitdateien anlegen? Das lässt sich oben über "
        "„Begleitdateien“ jederzeit ändern.":
            "Silberkorn can save the edit in a small sidecar file next to the image – "
            "“{name}”. When the image is opened again later, everything is as before: "
            "sliders, removed objects, dust, mask and AI expansion. The image itself stays "
            "unchanged.\n\nCreate sidecar files? This can be changed at any time via "
            "“Sidecar files” at the top.",
        "Die Bearbeitung ließ sich nicht neben dem Bild sichern – der Ordner ist "
        "schreibgeschützt oder nicht erreichbar.":
            "The edit could not be saved next to the image – the folder is read-only or "
            "not reachable.",
        "Begleitdatei passt nicht": "Sidecar file does not match",
        "Die Begleitdatei zu {name} gehört zu einer anderen Fassung des Bildes – das Bild "
        "wurde seither verändert. Nur die Reglerwerte übernehmen? Entfernte Objekte, Staub, "
        "Maske und KI-Erweiterung gehen dabei nicht mit.":
            "The sidecar file for {name} belongs to a different version of the image – the "
            "image has been changed since. Apply only the slider values? Removed objects, "
            "dust, mask and AI expansion are left out.",
        "Die Begleitdatei lässt sich nicht lesen – das Bild ist unbearbeitet geöffnet.":
            "The sidecar file cannot be read – the image has been opened unedited.",
        "KI-Schritte neu berechnen": "Recompute AI steps",
        "Die gesicherte Bearbeitung nutzt {schritte}. Diese Ergebnisse stehen nicht in der "
        "Begleitdatei, sie werden für das Bild neu berechnet. Jetzt berechnen?":
            "The saved edit uses {schritte}. These results are not stored in the sidecar "
            "file; they are recomputed for the image. Compute now?",
        "{name} geöffnet – mit der gesicherten Bearbeitung": "{name} opened – with the saved edit",
        # Ordneransicht und Vorschau-Cache
        "Ordner wählen …": "Choose folder …",
        "Ordner neu einlesen": "Reload folder",
        "Übergeordneter Ordner": "Parent folder",
        "Vorschau-Cache …": "Preview cache …",
        "Größe, Ort und Ausnahmen des verschlüsselten Caches für Vorschaubilder":
            "Size, location and exceptions of the encrypted preview cache",
        "Einen Ordner wählen, um seine Bilder zu sehen.": "Choose a folder to see its images.",
        "{anzahl} Bilder in {ordner}": "{anzahl} images in {ordner}",
        "1 Bild in {ordner}": "1 image in {ordner}",
        "Der Vorschau-Cache lässt sich nicht anlegen: {grund}":
            "The preview cache cannot be created: {grund}",
        "Vorschau-Cache": "Preview cache",
        "Vorschau-Cache einrichten": "Set up the preview cache",
        "Vorschaubilder großer Dateien – etwa Scans – kosten Zeit. Silberkorn kann sie "
        "in einer Datei mit fester Größe sichern, verschlüsselt für die eigene "
        "Windows-Anmeldung. Der Platz wird gleich belegt, damit es später keine "
        "Überraschung gibt. 0 MB: kein Cache.":
            "Previews of large files – such as scans – take time. Silberkorn can keep them "
            "in a file of fixed size, encrypted for your own Windows sign-in. The space is "
            "reserved right away so there are no surprises later. 0 MB: no cache.",
        "Belegt: {belegt} von {groesse} MB, {anzahl} Vorschaubilder":
            "In use: {belegt} of {groesse} MB, {anzahl} previews",
        "Ort": "Location",
        "Nie in den Cache (Ordner und alles darunter):":
            "Never cache (folders and everything below):",
        "Ordner hinzufügen …": "Add folder …",
        "Cache jetzt leeren": "Clear the cache now",
        "Ort des Vorschau-Caches": "Location of the preview cache",
        "Ordner ausnehmen": "Exclude folder",
        "Dort ist nicht genug Platz frei. Möglich sind höchstens {mb} MB.":
            "There is not enough free space there. At most {mb} MB are possible.",
        # Stapel
        "Stapel": "Batch",
        "Stapel …": "Batch …",
        "Die gewählten Bilder auf einmal bearbeiten: eine Voreinstellung darauflegen, "
        "Staub entfernen, als Begleitdatei sichern oder ausgeben. Mehrere Bilder wählen "
        "mit Strg oder Umschalt.":
            "Process the selected images in one go: apply a preset, remove dust, save as a "
            "sidecar file or export. Select several images with Ctrl or Shift.",
        "Stapel: {anzahl} Bilder": "Batch: {anzahl} images",
        "Keine – nur die vorhandene Bearbeitung": "None – only the existing edit",
        "Kopierte Einstellungen": "Copied settings",
        "Staub über den Infrarotkanal entfernen, wo es einen gibt":
            "Remove dust via the infrared channel where there is one",
        "Bearbeitung als Begleitdatei neben jedem Bild sichern":
            "Save the edit as a sidecar file next to each image",
        "Bilder ausgeben": "Export images",
        "bearbeitet": "edited",
        "Namenszusatz": "Name suffix",
        "KI-Entrauschen, -Schärfen und -Kolorieren rechnen, wo eingestellt":
            "Compute AI denoise, sharpen and colourise where set",
        "Mit KI-Hochskalieren ({faktor}, wie in der Karte eingestellt)":
            "With AI upscaling ({faktor}, as set in the card)",
        "Vorhandene Dateien werden nie überschrieben – dann heißt die neue Datei etwa "
        "„Name-bearbeitet-2“.":
            "Existing files are never overwritten – the new file is then called e.g. "
            "“Name-edited-2”.",
        "Starten": "Start",
        "Ordner für die Ausgabe": "Folder for the export",
        "Begleitdatei passte nicht mehr – nur die Reglerwerte übernommen":
            "Sidecar file no longer matched – only the slider values were applied",
        "ungültige Werte übergangen": "invalid values skipped",
        "KI-Schritt ausgelassen – Modell nicht geladen": "AI step skipped – model not downloaded",
        "Bearbeite {name} …": "Processing {name} …",
        "{fertig} von {anzahl} Bildern fertig.": "{fertig} of {anzahl} images done.",
        "Abgebrochen.": "Cancelled.",
    },
}
