# Änderungen

Das Format folgt [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionsnummern der [semantischen Versionierung](https://semver.org/lang/de/).

## [Unveröffentlicht]

### Behoben

- **KI-Erweitern in der EXE**: Der Knopf „Erweitern“ rechnete kurz und ließ das Bild
  unverändert. Das Startrauschen brauchte eine NVIDIA-Bibliothek (cuRAND), die die EXE
  nicht mitlädt; es entsteht jetzt ohne sie.
- **Fehler verschwanden spurlos**: Scheiterte ein Schritt unerwartet, tat der Knopf einfach
  nichts – so etwa beim KI-Erweitern in der EXE. Jetzt erscheint ein Fenster mit den
  Einzelheiten, und der Fehler steht in `silberkorn-fehler.log` neben dem Programm.

## [0.13.0] – 2026-10-26

### Neu

- **Bilder vergleichen**: Der Knopf ⇆ in der Ordneransicht zeigt zwei oder mehr gewählte
  Bilder nebeneinander in einem eigenen Fenster – links der Favorit, rechts ein Kandidat.
  Bei mehr als zwei blättern ← und → rechts durch die übrigen; „Tauschen“ macht den
  Kandidaten zum Favoriten. Einpassen, 100 %, Mausrad und Verschieben wirken auf beide
  Seiten (mit 🔗 abschaltbar), bei verschieden großen Bildern an dieselbe Stelle im
  Verhältnis. Die Bilder tragen ihre Bearbeitung aus der Begleitdatei; darunter stehen
  Pixel, Datum und Aufnahmedaten. Sterne und Ausschuss lassen sich gleich setzen,
  „Bearbeiten“ öffnet das Bild. Gelöscht wird nichts.

## [0.12.0] – 2026-10-24

### Neu

- **Auto-Begradigen**: Der Knopf „Auto“ auf der Karte „Geometrie“ erkennt die Neigung
  des Bildes an den waagrechten und senkrechten Linien und stellt „Begradigen“ ein
  (bis ±20°). Ein Schritt für „Rückgängig“; ein zweiter Klick ergibt dasselbe. Ohne klare
  Linien (Wolken, Rauschen) bleibt der Regler, und die Statuszeile sagt es.
- **Monitorprofil**: Die neue Wahl oben rechnet alle Anzeigen – Leinwand, Kacheln der
  Ordneransicht und die Vorschauen in Drucken, Veröffentlichen und Trennen – in das
  Farbprofil des Bildschirms um, auf dem das Fenster steht. Bildschirme mit großem
  Farbraum (Display P3, Adobe RGB) zeigen Farben dann nicht mehr zu bunt. Beim Wechsel
  auf einen anderen Bildschirm gilt dessen Profil. Gespeicherte und gedruckte Bilder
  sowie das Histogramm bleiben sRGB. Anfangs aus; ausgegraut, wenn Windows kein Profil
  meldet oder es sRGB entspricht.
- **Kontaktbogen**: Der Knopf 🖶 in der Ordneransicht druckt die gewählten Bilder –
  sonst alle des Ordners – als Raster mit Dateinamen und Sternen, auf einen Drucker
  oder als PDF. 2 bis 8 Spalten, Hoch- oder Querformat, Ausschuss auf Wunsch weg; die
  Bilder tragen ihre Bearbeitung aus der Begleitdatei. Mit Vorschau zum Blättern;
  Abbrechen gibt nichts aus, eine vorhandene PDF bleibt dann unberührt.

### Geändert

- Die README ist kürzer und neu gegliedert; die ausführliche Funktionsliste, der
  Datenschutz und die KI-Modelle stehen in `docs/`. Das ZIP enthält diese Seiten und
  `SECURITY.md` (wie man eine Sicherheitslücke meldet) jetzt neben der EXE.

### Behoben

- `SECURITY.md` nennt jetzt auch die Objektivdatenbank als einzige Verbindung ohne
  hinterlegte Prüfsumme und alles, was in `silberkorn.json` steht.

## [0.11.0] – 2026-10-21

### Neu

- **Vergleich Vorher/Nachher** mit verschiebbarer Trennlinie: Der Knopf ◧ neben
  „Vorher“ (Taste `Y`) zeigt links das Original und rechts das bearbeitete Bild,
  deckungsgleich in Drehung, Zuschnitt, Perspektive und Objektivkorrektur; nach einem
  KI-Erweitern sind die erfundenen Ränder links neutral grau. Die Linie gehört zum
  Fenster und bleibt beim Zoomen und Verschieben stehen; Doppelklick auf den Griff
  setzt sie in die Mitte. Zuschnitt, Pinsel, Klick-, Flächen- und Maskenmodus
  pausieren den Vergleich. Das Originalbild wird nur neu gerechnet, wenn sich die
  Geometrie ändert, nicht bei jedem Reglerschritt.

- **Histogramm und Warnung bei Über- und Unterbelichtung**: Über den Karten steht ein
  festes Histogramm mit Rot, Grün, Blau (halbtransparent, überlagert) und Helligkeit,
  immer vom ganzen Bild – auch in der 100-%-Ansicht, dort aus einer Stichprobe des
  zwischengespeicherten Vollbilds, nicht nur vom sichtbaren Ausschnitt. Die Dreiecke
  oben links (Tiefen) und oben rechts (Lichter) schalten je eine Warnung ein, Taste `J`
  beide gemeinsam: Pixel, in denen ein Kanal 255 erreicht, sind im Bild rot, bei 0 blau.
  Ein Dreieck füllt sich, sobald Pixel abgeschnitten sind, auch bei ausgeschalteter
  Warnung. Die Markierung ist nur Anzeige: Sie fehlt beim Speichern, Exportieren,
  Drucken, bei „Für Veröffentlichung“, bei „Vorher“ und in der linken Vergleichshälfte;
  Farben der Masken- und Staubansicht zählen nicht als abgeschnitten. Der Zustand der
  Warnungen steht in `silberkorn.json`, nicht in der Begleitdatei oder den
  Voreinstellungen und nicht im Rückgängig-Verlauf.

- **Automatik**: Die Karte „Licht“ bekommt einen Knopf „Auto“, die Karte „Weißabgleich“
  die Knöpfe „Auto“ und „Pipette“. *Auto-Ton* setzt Belichtung, Kontrast, Lichter und
  Tiefen: der Median kommt auf Mittelgrau (höchstens ±2 EV, ohne die Lichter weit über
  das Weiß zu schieben), Lichter und Tiefen holen zugelaufene Stellen zurück, flaue Bilder
  bekommen Kontrast; ein gut belichtetes Bild bleibt fast unverändert. *Auto-Weißabgleich*
  macht das Bild im Mittel neutral (Grauwelt ohne abgeschnittene Stellen, nur die am
  wenigsten bunten Pixel, damit große farbige Flächen nicht ziehen). Die *Pipette*
  (Fadenkreuz, ein Klick, Esc bricht ab) macht die angeklickte Stelle neutral – gemittelt
  über 5 × 5 Pixel. Gemessen wird im Zuschnitt, mit den vier Tonwerten bzw. Temperatur und
  Tönung auf 0 gerechnet: mehrfaches Drücken gibt dasselbe. Jede Aktion ist ein Schritt für
  „Rückgängig“; es gibt keine neuen Einstellungen, Begleitdatei und Voreinstellungen
  kennen nur die Reglerwerte. Bei Schwarzweiß sind Auto-Weißabgleich und Pipette gesperrt.

- **Bewertung in der Ordneransicht**: Fährt die Maus über eine Bildkachel, erscheinen
  fünf leere Sterne und ein Papierkorb im Bild. Ein Klick auf Stern *n* setzt *n* Sterne,
  ein Klick auf den Stern der jetzigen Bewertung nimmt sie zurück. Der Papierkorb
  markiert das Bild als **Ausschuss** (nochmal klicken hebt es auf): Er **löscht, verschiebt
  und verändert nichts** – die Kachel wird nur abgeblendet. Gesetzte Sterne und Ausschuss
  bleiben auch ohne Maus sichtbar; ein Klick darauf wählt die Kachel nicht und öffnet sie
  nicht. Unterordner bekommen nichts, es gibt keine Tastenkürzel. Neben „Stapel …“ wählt
  eine Liste die Reihenfolge: nach **Name** (wie bisher), **Datum** (Änderungsdatum, neueste
  zuerst) oder **Sternen** (meiste zuerst, bei Gleichstand nach Name). Unterordner stehen
  immer vorn, Ausschuss immer am Ende; die Wahl steht in `silberkorn.json`. Nach einer
  Bewertung springt die Kachel nicht weg – „↻“ liest den Ordner neu und sortiert dann ein.
  Die Bewertung liegt in einer kleinen XMP-Datei neben dem Bild (`foto.jpg.xmp`: nur
  `xmp:Rating`, −1 für Ausschuss, dazu eine Kennung von Silberkorn) – atomar geschrieben,
  nur mit der Erlaubnis für Begleitdateien (beim ersten Mal wird gefragt; ohne sie wird
  nichts gespeichert und nichts als gesetzt gezeigt). **Fremde XMP-Dateien** mit diesem
  Namen – etwa von darktable – verändert, ersetzt und löscht Silberkorn nie, auch nicht
  über das Feld im Reiter Bearbeiten: Ihre Bewertung wird gezeigt, die Sterne sind dann
  ausgegraut. Dateien wie `foto.xmp` (Lightroom) liest und schreibt Silberkorn nicht. Eine
  kaputte, zu große oder sonst unlesbare Datei (auch eine Verknüpfung oder ein Ordner mit
  diesem Namen) ergibt keine Bewertung, bleibt unverändert und wird mit einem eigenen
  Hinweis gemeldet. Das Feld „Bewertung“ im Reiter Bearbeiten übernimmt die Sterne der
  eigenen Datei – sie hat immer Vorrang vor den Sternen im Bild, auch mit „–“ (0 Sterne);
  Ausschuss steht als „–“ – und schreibt Änderungen dorthin zurück, ebenso Rückgängig,
  Wiederholen und „Zurücksetzen“, wenn sie das Feld ändern (ein Ausschuss in der Datei
  bleibt, solange das Feld nicht wirklich geändert wird). „Speichern unter“ nimmt die
  Sterne mit, Ausschuss nicht, und legt keine Datei für die Ausgabe an.

### Geändert

- Das Histogramm der Gradationskurve zeigt die Helligkeit des ganzen Bildes (bisher nur
  des sichtbaren Ausschnitts in der 100-%-Ansicht) und ohne die Farben von Masken- und
  Staubansicht.
- Die Symbolknöpfe der Werkzeugleiste (🖶, ⤢, ◧) und deren Abstände sind etwas
  schmaler, damit das Fenster mit dem neuen Knopf weiterhin auf 1366 × 768 bei 125 %
  Skalierung passt.

### Behoben

- Die Ordneransicht stürzt bei Dateinamen mit hochgestellten Ziffern wie „Raum 1²“ nicht
  mehr ab.
- Wer das Herunterladen der NVIDIA-Bibliotheken, eines KI-Modells oder der
  Objektivdatenbank ablehnt, findet danach keinen leeren Ordner mehr: Silberkorn
  legt `nvidia` und `modelle` erst beim Herunterladen an.
- Die Programmeinstellungen (`silberkorn.json`) gehen nicht mehr verloren, wenn die
  Datei beim Speichern kurz gesperrt ist oder das Schreiben abbricht: Silberkorn
  schreibt sie jetzt atomar, überschreibt eine gerade unlesbare Datei nicht und legt
  eine kaputte vorher als `silberkorn.json.defekt` beiseite.

## [0.10.0] – 2026-10-19

### Neu

- **Schwarzweiß & Tönung** (neue Karte hinter den Farbbereichen): Schwarzweiß
  mit einem Mischer für die acht Farbbereiche und Vorlagen wie klassische
  Farbfilter (Rot, Orange, Gelb, Grün, Blau); Teiltonung für Lichter und
  Schatten mit Balance und den Vorlagen Sepia, Selen, Cyanotypie und „Lichter
  warm, Schatten kalt“. Gerechnet in OkLab auf der Grafikkarte im selben
  Durchlauf wie Kurven und Farbbereiche; gilt für Rückgängig, Begleitdatei,
  Voreinstellungen und Stapel.
- **Lokale Anpassungen** (neue Karte hinter „Schwarzweiß & Tönung“): bis zu
  zehn Masken aus Verläufen, Radialfiltern und Pinselstrichen (hinzufügen,
  abziehen, schneiden, umkehren), je Maske zehn Regler von Temperatur bis
  Schärfe. Der Pinsel malt mit Größe, weichem Rand und Deckkraft und radiert mit
  rechter Maustaste oder `Alt`; Pinselstriche gehören zum Bild und gehen nicht
  in Voreinstellungen mit. Dazu KI-Teile – Motiv, Objekt per Klick und
  Tiefenbereich – sowie Helligkeits- und Farbbereich mit Pipette; „Neue Maske“
  und „Teil dazu“ sind jetzt Menüs. Motiv und Objekte stehen in der
  Begleitdatei (ältere Silberkorn-Versionen können solche Begleitdateien nicht
  lesen); Voreinstellungen und Stapel rechnen Motiv und Tiefe je Bild. Linien und Griffe
  im Bild, „Maske zeigen“ mit `O`. Die Masken liegen relativ zum Original und
  folgen der Geometrie; gerechnet wird nach der Geometrie in einem Durchlauf
  für alle Masken. Rückgängig, Begleitdatei (strenge Prüfung) und
  Voreinstellungen (eigene Gruppe, nicht vorgewählt).
- **Filmkorn** (neue Karte hinter der LUT): einfarbiges Korn mit Stärke, Größe
  und Rauheit (lässt das Korn klumpen), in den Mitteltönen am stärksten. Die Größe gilt relativ zur
  langen Bildkante, das Korn ist an jeder Stelle fest bestimmt: Die
  100-%-Ansicht zeigt genau das gespeicherte Korn, beim KI-Hochskalieren kommt
  es erst nach der Vergrößerung dazu. Die verkleinerte Vorschau zeigt es
  schwächer, wie nach dem Verkleinern eines Bildes.

## [0.9.0] – 2026-10-17

### Neu

- **AVIF**: Öffnen und Speichern – auch bei „Für Veröffentlichung speichern“, in
  der Stapel-Ausgabe, als Wasserzeichen-Bild und in der Ordneransicht. Mit EXIF,
  XMP, Farbprofil und Alphakanal, bei gleicher Güte etwa halb so groß wie JPEG.
  AVIF mit mehr als 8 Bit liest Silberkorn als 8 Bit. Die EXE hatte den Codec
  über Pillow schon dabei; die Lizenzen von libaom und libyuv liegen jetzt bei.

## [0.8.0] – 2026-10-17

### Neu

- **Begleitdatei**: Die Bearbeitung wird beim Wechsel des Bildes und beim Beenden
  neben dem Bild gesichert (`foto.jpg.silberkorn`) und beim nächsten Öffnen
  wiederhergestellt – mit entfernten Objekten, Staub, Maske, Tiefe und
  KI-Erweiterung. KI-Entrauschen, -Schärfen und -Kolorieren werden auf Nachfrage
  neu berechnet. Beim ersten Mal fragt Silberkorn; der Schalter „Begleitdateien“
  oben ändert die Wahl. Fremde Begleitdateien werden streng geprüft gelesen.
- **Voreinstellungen**: eine neue Karte ganz oben. Einstellungen unter einem
  Namen sichern, anwenden, löschen, importieren und exportieren – mit Auswahl
  der Gruppen, die mitgehen, beim Film wahlweise mit gemessener Filmmaske.
  Einstellungen kopieren und einfügen mit `Strg`+`Umschalt`+`C` / `V`.
- **Ordneransicht**: ein neuer Reiter „Ordner“ mit den Bildern eines Ordners als
  Kacheln; Doppelklick öffnet, Bilder mit Begleitdatei zeigen ihre Bearbeitung.
  Vorschaubilder entstehen im Hintergrund, nur für sichtbare Kacheln.
- **Vorschau-Cache** für teure Vorschaubilder: eine Datei mit fester, selbst
  gewählter Größe, gleich vorbelegt, mit DPAPI verschlüsselt, mit Ausnahmen für
  Ordner und überschriebenen Löschungen.
- **Stapel**: mehrere Bilder der Ordneransicht auf einmal bearbeiten –
  Voreinstellung oder kopierte Einstellungen, Staub über Infrarot, Begleitdatei
  sichern, ausgeben (Format, Ordner, Namenszusatz, KI-Schritte und
  KI-Hochskalieren). Nie überschreiben, abbrechbar, mit Bericht.

### Geändert

- Nach KI-Entrauschen, -Schärfen oder -Kolorieren bleibt eine schon gesetzte
  Stärke erhalten, statt auf 100 % zu springen.
- Eine LUT mit ungültigen Zahlen (NaN, unendlich) wird abgelehnt.

## [0.7.0] – 2026-10-16

### Neu

- **Kartenauswahl**: Ein Auswahlfeld über den Karten springt direkt zu jeder
  Karte und zeigt beim Rollen, welche gerade oben steht. Die Liste ist so
  kompakt, dass alle Karten auch auf 768 Pixel hohen Bildschirmen hineinpassen.
- **Scan & Film**, eine neue Karte vor „Motiv & Hintergrund“:
  - Negative umwandeln – Farbe oder Schwarzweiß, gescannt oder mit der Kamera
    abfotografiert. Gerechnet wird über die Dichte des Films; Filmmaske sowie
    Schwarz- und Weißpunkt je Kanal schätzt Silberkorn selbst, den
    unbelichteten Filmrand kann man auch mit der Pipette anklicken.
  - Staub und Kratzer über den Infrarotkanal eines RGBI-Scans finden und
    füllen – kleine Punkte auf der GPU, breite Stellen mit LaMa. Ein
    Infrarotkanal, der das Motiv selbst zeigt (Luftbilder, Schwarzweißfilm mit
    Silber), wird erkannt und nicht für Staub gehalten.
  - „Fotos trennen …“: mehrere Abzüge auf einem Flachbett-Scan finden, auch
    schräg liegende, gerade richten, beschneiden und einzeln speichern; eines
    davon wird danach geöffnet.
  - Umwandlung und Staubentfernung lassen sich wie alles andere rückgängig
    machen; „Vorher“ zeigt den Scan.
- Bildschirmfotos in beiden READMEs, mit gerechneten Motiven
  (`werkzeuge/bildschirmfotos.py`).

### Behoben

- Ein TIFF mit vier Kanälen galt immer als Bild mit Alphakanal. Der
  Infrarotkanal eines Filmscans (RGBI) machte das Bild so teilweise
  durchsichtig; jetzt entscheidet das Feld ExtraSamples.
- War „Fokus ins Bild klicken“ (Tiefe & Bokeh) aktiv und wurde dabei ein
  Objekt entfernt, stürzte das Programm ab.

## [0.6.0] – 2026-10-15

### Neu

- **Rückgängig und Wiederholen** mit ↶ ↷ neben „Zurücksetzen“ oder `Strg`+`Z`
  / `Strg`+`Y` (auch `Strg`+`Umschalt`+`Z`): für Regler, Kurven,
  Farbbereiche, LUT, Drehen, Zuschnitt, Objektivprofil, Anonymisieren und
  Metadaten, ebenso für KI-Schritte – Entrauschen, Schärfen, Kolorieren,
  Maske, Tiefe, entfernte Objekte und Erweitern – und für „Zurücksetzen“
  selbst. Ein Zug am Regler ist ein Schritt; Tooltip und Statuszeile nennen,
  was zurückgenommen wird. Bei der Auswahl per Klick nimmt `Strg`+`Z` zuerst
  die Klicks zurück. Überholte KI-Ergebnisse belegen höchstens ein Fünftel des
  Grafikspeichers zusätzlich, ältere Schritte fallen dafür weg.
- **Drucken** mit 🖶 oder `Strg`+`P`: Drucker und Papier wählen – ohne Angabe
  10 × 15 cm, wenn der Drucker es kennt –, das Bild auf die ganze Seite oder
  auf 9 × 13, 10 × 15, 13 × 18, 20 × 30 cm oder eine eigene Größe bringen,
  ganz gezeigt oder die Fläche füllend, mit Rand oder randlos. Eine Vorschau
  zeigt das Blatt, dazu die Auflösung auf dem Papier; ist sie knapp, lässt
  sich das Bild vorher mit KI vergrößern. Gedruckt wird das bearbeitete Bild
  in voller Auflösung als sRGB.

### Geändert

- „Speichern unter …“ heißt jetzt „Speichern …“; der Tooltip sagt, dass immer
  nach einem neuen Namen gefragt und das Original nie überschrieben wird.
- Die Zoomstufe steht beim Zoomen oben rechts im Bild statt in der
  Werkzeugleiste. So passt das Fenster mit den neuen Knöpfen weiter auf
  1366 × 768 Pixel bei 125 % Skalierung.

### Behoben

- Stand KI-Entrauschen auf 100 %, schrieb die Vorschau entfernte Objekte in
  das entrauschte Bild hinein – „Vorher“ zeigte sie dann nicht mehr.

## [0.5.0] – 2026-10-11

### Neu

- **Metadaten**: Eine neue Karte zeigt Kamera, Objektiv und Belichtung und
  lässt Titel, Beschreibung, Stichwörter, Urheber, Copyright, Stadt, Region,
  Land, Aufnahmedatum und Bewertung ändern – beim Datum genügt für alte Abzüge
  auch nur das Jahr. Gelesen wird EXIF, IPTC und XMP, auch aus RAW; gibt es
  eine Angabe mehrfach, gilt XMP vor IPTC vor EXIF. Geschrieben wird erst beim
  Speichern, als XMP nach IPTC und wo möglich auch als EXIF. „Zurücksetzen“
  nimmt die Änderungen mit zurück, „Zurücksetzen“ in der Karte nur diese.
  „Alle Metadaten …“ zeigt den ganzen Inhalt der Datei, nur lesend und mit
  Filter. Auf Wunsch trägt Silberkorn Urheber und Copyright in jedes Bild ein,
  das selbst keine hat. „Fürs Netz …“ nimmt Titel, Beschreibung und
  Stichwörter mit, Ort, Datum und Bewertung nur, wenn die Kameradaten bleiben.

### Geändert

- Das XMP der Datei bleibt beim Speichern erhalten. Drehung, Bildgröße und
  Entwicklungseinstellungen anderer Programme (Lightroom, darktable) fallen
  dabei weg, damit sie dort nicht ein zweites Mal wirken. Was nur im alten
  IPTC-Block stand, wandert nach XMP.
- „Ohne GPS und Seriennummern speichern“ bereinigt auch das XMP: Es behält dort
  nur beschreibende Angaben, sodass auch GPS-Daten in Herstellerfeldern
  wegfallen, etwa die von DJI-Drohnen.
- „Zurücksetzen“ holt auch entfernte Objekte zurück und verwirft eine noch nicht
  entfernte Markierung.

### Behoben

- RAW-Dateien wurden ohne EXIF gespeichert; jetzt kommen Kamera, Objektiv und
  Belichtung mit.
- Ein Bild mit Kameradaten ließ sich nicht als 8-Bit-TIFF speichern, und
  16-Bit-TIFF wurde ohne EXIF geschrieben. Alle TIFFs tragen jetzt EXIF, GPS
  (sofern nicht entfernt) und XMP.
- Aus TIFF-Dateien gingen beim Öffnen die Objektivdaten verloren; Objektivprofile
  werden jetzt auch für TIFFs gefunden.
- „Vorher“ zeigt entfernte Objekte wieder, statt sie weiter auszublenden.

## [0.4.1] – 2026-10-10

### Geändert

- Kompaktere Werkzeugleiste, damit das Fenster auch auf schmalen Bildschirmen
  passt (etwa 1366 × 768 bei 125 % Skalierung): Die Zoom-Knöpfe heißen jetzt
  „⤢“ (Einpassen) und „1:1“ (100 %), „Für Veröffentlichung …“ heißt „Fürs
  Netz …“ und „Alles zurücksetzen“ heißt „Zurücksetzen“. Die Tooltips sagen
  weiter genau, was die Knöpfe tun. Die Mindestbreite des Fensters sinkt von
  rund 1240 auf rund 1065 Pixel.

## [0.4.0] – 2026-10-10

### Neu

- **KI-Kolorieren** mit DDColor (kleine Fassung, Apache-2.0): Schwarzweiß- und
  Sepiabilder bekommen Farbe. Das Netz sieht das Bild als Graubild auf
  512 × 512 und schätzt die Farbanteile a und b; die Helligkeit bleibt in
  voller Auflösung die des Originals. Ein Regler mischt die Farbe stufenlos
  ein. Rund 0,1 s auf einer RTX 4060. Das Modell (210 MB) kommt aus dem Release
  `modelle-9`. Kolorierte Bilder gelten beim Speichern für Veröffentlichung als
  KI-Inhalt.

### Geändert

- README: Der Abschnitt Datenschutz nennt jetzt auch das Laden der
  Objektivdatenbank.

## [0.3.0] – 2026-10-10

### Neu

- **Objektivprofile**: Verzeichnung, Farbsäume und Vignette automatisch nach der
  Objektivdatenbank von lensfun (CC BY-SA 3.0). Kamera, Objektiv, Brennweite und
  Blende stammen aus der Datei (auch adaptierte Objektive, etwa F an Z);
  zwischen kalibrierten Brennweiten und Blenden wird interpoliert. Bei RAW wird
  das Profil gleich angewendet, bei JPEG auf Wunsch; „Alles zurücksetzen“
  behält es. Die Korrektur gehört zur einzigen Abtastung der Geometrie und
  stimmt mit lensfun auf Bruchteile eines Pixels überein. Die Datenbank lädt
  Silberkorn auf Knopfdruck (etwa 0,5 MB) und sucht auf Knopfdruck nach einer
  neueren.
- **X-Trans auf der GPU**: Fujis RAW-Dateien werden jetzt ebenfalls auf der
  Grafikkarte entwickelt – mit einem kantenbewussten Verfahren für das
  6×6-Muster (Grün richtungsgewichtet, Rot und Blau über Farbdifferenzen). Eine
  26-Megapixel-RAF ist in rund 20 ms entwickelt statt in gut 2 s; das Ergebnis
  weicht von LibRaws Markesteijn-Verfahren kaum ab (PSNR 52 dB).

### Behoben

- RAW über LibRaw („Beste Qualität“ und Sensoren ohne GPU-Weg): Die Helligkeit
  hängt nicht mehr vom Motiv ab. LibRaw setzte den Weißpunkt auf den hellsten
  Bildwert, sobald dieser über 75 % lag (`adjust_maximum`) – das Bild wurde
  dann bis zu ⅓ Blende heller als auf der GPU.

## [0.2.0] – 2026-10-10

### Neu

- **Für Veröffentlichung speichern**: verkleinert (längste Kante oder Prozent,
  nie vergrößert), mit sichtbarem Wasserzeichen aus Text und/oder Logo – in
  einer Ecke, in der Mitte oder als Muster –, mit Urheber, Copyright und
  Webadresse in EXIF und XMP, auf Wunsch mit Vorbehalt gegen KI-Training und
  Data-Mining (IPTC) und ohne Kameradaten. GPS und Seriennummern fallen immer
  weg; von der KI erfundene Bildteile werden vermerkt. Mit Vorschau; die
  Einstellungen bleiben als Vorlage in `silberkorn.json`.

### Geändert

- Das Fenster startet 1280 Pixel breit und wird nicht schmaler, als die Knöpfe
  der Werkzeugleiste es verlangen – bisher wurden ihre Beschriftungen in der
  Standardgröße abgeschnitten.
- Pillow ab Version 11 (XMP in JPEG).

## [0.1.1] – 2026-10-09

### Behoben

- Waren die KI-Modelle schon geladen, blieben nach dem Start die Knöpfe und
  Hinweise der Karten KI-Entrauschen, KI-Schärfen, Motiv & Hintergrund,
  Objekte entfernen und Tiefe & Bokeh leer, bis ein Bild geöffnet wurde.

## [0.1.0] – 2026-10-09

### Geändert

- Das Mausrad blättert die Reglerspalte, auch wenn der Zeiger über einem Regler
  oder einer Auswahlliste steht; diese verstellt nur noch Ziehen, Klicken oder
  die Tastatur. Bisher hielt das Blättern am ersten Regler an und verstellte ihn.
- Verweise in Texten, etwa auf NVIDIAs Lizenzen beim ersten Start, erscheinen im
  Blau des Programms statt im grellen Hellblau des dunklen Windows-Schemas.
- README: Hinweis, dass das Programm beim ersten Bewegen eines Reglers einige
  Sekunden zu hängen scheint, weil die Grafikkarte die Filterprogramme übersetzt.
- Das Programm heißt jetzt **Silberkorn** (bisher Arbeitstitel Neuro-Enhance):
  Paket `silberkorn`, Startdatei `Silberkorn.pyw`, Einstellungen in
  `silberkorn.json`, Modelle bei schreibgeschütztem Programmordner unter
  `%LOCALAPPDATA%\Silberkorn\modelle`.
- RAW: Das Demosaicing auf der GPU arbeitet jetzt nach Malvar, He und Cutler.
  Neu ist die Wahl „RAW: Beste Qualität“ in der Kopfzeile; dann entwickelt
  LibRaw mit dem Verfahren DHT auf dem Prozessor (etwa 1,5 s bei 26 MP).
- Die Nachbauten fremder Netze liegen je Herkunft in eigenen Dateien
  `werkzeuge/netz_*.py` unter der Lizenz ihres Vorbilds; die Lizenztexte der
  Vorbilder (MIT, BSD-3-Clause, Apache-2.0) liegen in `LICENSES/`. README,
  NOTICE und `pyproject.toml` nennen die Ausnahmen von der MIT-Lizenz.
- Gesperrte Hauptknöpfe (etwa „Entfernen“ ohne Markierung) erscheinen grau
  statt in der Akzentfarbe.
- ONNX Runtime bekommt höchstens so viel Grafikspeicher, wie gerade frei ist.
  Ohne Grenze wuchs sein Speicherpool über die Karte hinaus, und Windows
  lagerte aus – ein Netz rechnete dann bis zu zwanzigmal langsamer.
- KI-Kacheln von KI-Entrauschen und KI-Schärfen werden in ihrer Überlappung
  weich ineinander geblendet statt hart aneinandergesetzt; Netze, die über die
  ganze Kachel schauen, liefern sonst sichtbare Nähte.
- Die Marke einer gebauten TensorRT-Engine enthält jetzt die Prüfsumme der
  Modelldatei; ändert sich ein Modell, wird die Engine neu gebaut.
- KI-Hochskalieren rechnet in halber Genauigkeit (FP16) und im Speicherformat
  NHWC auf den Tensorkernen – auf einer RTX 4060 doppelt so schnell wie bisher
  (24 MP × 2 mit dem schnellen Modell: 5,7 s statt 11,1 s; 12 MP × 2 mit dem
  großen: 54 s statt 111 s). Die Modelldateien bleiben FP32 und werden beim
  Laden im Speicher gewandelt; neue Abhängigkeit dafür: `onnx`. Die
  Abweichung zu FP32 liegt im Mittel bei 0,0002.

### Entfernt

- RCD-Demosaicing (`silberkorn/rcd.py`). Es war eine Übertragung von RCD
  (Luis Sanz Rodríguez) in der Fassung von RawTherapee und darktable, die unter
  der GPL-3.0 stehen; als solche durfte es nicht unter der MIT-Lizenz stehen.
  Die frühere Fassung bleibt in der Git-Historie (ab Commit 75bae17) und ist
  dort als GPL-3.0-Bearbeitung zu verstehen.

### Behoben

- Sprachwechsel: Die Auffrischung brach am ersten Text ohne Übersetzung
  („100 %“) ab, fast alles blieb in der alten Sprache. Auswahllisten und Qts
  eigene Knöpfe (Ja/Nein/Abbrechen) wechseln jetzt ebenfalls mit.
- Reglerleiste: Ihr Inhalt ist immer genau so breit wie sichtbar; ein zu
  breites Element schob vorher alle Karten nach rechts aus dem Bild.
- Darstellung: Aufklapplisten, Kästchen, Fortschrittsbalken, Kontextmenüs
  und das Detailfeld von Fehlermeldungen folgen dem Farbschema; Listen
  zeigen ihren längsten Eintrag ganz und flackern beim Aufklappen nicht mehr.
- KI-Knöpfe: kurze Beschriftungen („Anklicken · 147 MB“) statt abgeschnittener
  Texte; der Tooltip erklärt ohne Modell den Download, mit Modell die Aktion.
- `python -m silberkorn` startete das Programm auch in jedem Hilfsprozess
  erneut; der Start steht jetzt hinter `if __name__ == "__main__"`.
- Ein Bild mit Alphakanal ließ sich nach Zuschnitt oder Drehung nicht
  speichern: Der Alphakanal behielt seine alte Größe. Er bekommt jetzt
  dieselbe Geometrie wie das Bild (ohne Vignette und Farbsäume).
- RAWs der meisten Kameras (getestet mit Nikon NEF und Canon CR2) liefen nicht
  über die GPU, sondern fielen auf LibRaw zurück: rawpy gibt die Farbmatrix
  bei ihnen nur als Nullen heraus. Sie wird jetzt wie in LibRaw aus der
  Kameratabelle (XYZ → Kamera) berechnet. Die Farben stimmen mit LibRaw
  überein; eine 24-MP-RAW ist in rund 0,5 s offen statt in 1,3 s.

### Hinzugefügt

- Anonymisieren: Flächen als Rechteck oder Ellipse verpixeln, weichzeichnen oder
  schwarz füllen; „Gesichter finden“ mit YuNet (MIT, liegt bei, Prozessor),
  Flächen auf dem Bild verschieben, in der Größe ändern und aufziehen. Speichern
  auf Wunsch ohne GPS, Seriennummern, Besitzername und Herstellerdaten.
- KI-Erweitern (Outpainting) mit FLUX.2 [klein] 4B und der Outpaint-LoRA von
  fal (beide Apache-2.0): In der Karte „Geometrie“ erweitert „Mit KI erweitern
  statt beschneiden“ das Bild auf das gewählte Seitenverhältnis, statt es
  zuzuschneiden. Das Original kommt mittig auf eine reingrüne Leinwand von rund
  einem Megapixel, die KI füllt das Grün in 4 Schritten; danach wird ihr
  Farbstich am Original herausgenommen und das unveränderte Original mit
  weichem Saum eingesetzt. „Neu erzeugen“ rechnet mit neuem Zufall; über 25 %
  je Seite gibt es einen Hinweis. Die Erweiterung liegt vor allen Reglern und
  lässt sich wieder abwählen. Ab 8 GB Grafikspeicher; das Modell (rund 4,1 GB,
  Release „modelle-8“, auf mehrere Dateien verteilt) wird erst auf Wunsch
  geladen.
- `werkzeuge/outpaint_export.py`: rechnet die LoRA ein, exportiert Transformer
  und VAE nach ONNX, quantisiert den Transformer nach int8 (MatMulNBits,
  Block 128) und prüft jedes Netz sowie den ganzen Ablauf gegen diffusers.
  `werkzeuge/outpaint_referenz.py` ist der lokal geprüfte Stand in PyTorch.
- Zuschnitt: Seitenverhältnisse 4:5 (etwa für Instagram) und 5:4.
- Windows-EXE: `build.cmd` baut mit PyInstaller einen Programmordner und ein
  ZIP (ohne Installation). Die EXE bringt CUDA und cuDNN nicht mit, sondern
  lädt beim ersten Start nach Zustimmung zu NVIDIAs Lizenzen NVIDIAs
  offizielle Pakete von pypi.org (1,6 GB) und prüft sie gegen ihre
  Prüfsummen. Die Lizenztexte aller eingepackten Pakete liegen bei.
- Neue Karte „Tiefe & Bokeh“ mit Depth Anything V2 Small (Apache-2.0): Die
  Tiefe wird einmal geschätzt (0,16 s bei 26 MP, RTX 4060) und mit einem
  geführten Filter an die Kanten des Bildes gelegt. „Unschärfe“ zeichnet nach
  dem Abstand zur Fokusebene weich, „Fokus“ und „Schärfentiefe“ stellen ein,
  ein Klick ins Bild setzt den Fokus, eine Tiefenkarte zeigt die Schätzung.
  Das Bokeh mischt vier unterschiedlich stark weichgezeichnete Fassungen in
  linearem Licht; nur ähnlich Unscharfes trägt zu ihnen bei, damit Scharfes
  nicht ausblutet. Ein erkanntes Motiv bleibt auf Wunsch scharf. Nach dem
  Schätzen wird auf das Motiv bzw. das Nächste im Bild scharf gestellt. Das
  Modell (98 MB) kommt aus dem neuen Release `modelle-7`; es ist in
  `werkzeuge/netz_tiefe.py` ohne xFormers, OpenCV und torchvision nachgebaut.
- Neue Karte „Objekte entfernen“ mit LaMa (Big LaMa, Apache-2.0): Objekte per
  Klick (SAM 2) oder mit dem Pinsel markieren, „Entfernen“ füllt die Stelle.
  Gerechnet wird ein Ausschnitt um die Markierung, höchstens 768 bis 1536 Pixel
  je nach Grafikspeicher, in 0,1 bis 0,4 s (RTX 4060). Die Markierung wächst
  vorher um 5 % ihrer Ausdehnung, damit kein Umriss stehen bleibt. Entfernte
  Objekte liegen als Flicken über dem entrauschten und geschärften Bild,
  stapeln sich und lassen sich einzeln zurücknehmen; ungespeicherte
  Entfernungen zählen als Änderung. Die mittlere Maustaste verschiebt das
  vergrößerte Bild jetzt in jedem Modus. Das Modell (196 MB) kommt aus dem
  neuen Release `modelle-6`; es ist in `werkzeuge/netz_lama.py` mit der
  Fouriertransformation als DFT-Matrizen nachgebaut, der Checkpoint wird mit
  `werkzeuge/checkpoint_lesen.py` gelesen, ohne Code aus dem Pickle
  auszuführen.
- Objekt per Klick auswählen in der Karte „Motiv & Hintergrund“ mit
  Segment Anything 2 (SAM 2.1 small, Apache-2.0): Linksklick nimmt dazu,
  Rechtsklick weg, Strg+Z nimmt den letzten Klick zurück, Esc beendet. Der
  Encoder sieht das Bild einmal (0,1 s), jeder Klick kostet danach rund
  40 ms bei 24 MP (RTX 4060). Die Maske kommt grob aus SAM (256 × 256) und
  wird mit einem geführten Filter an die Kanten des Bildes gelegt. Klicks
  werden durch die Geometrie zurück ins Original gerechnet; bei 100 % lässt
  sich das Bild im Klickmodus weiter verschieben. Ab 4 GB Grafikspeicher.
  Das Modell (Encoder und Decoder, 147 MB) kommt aus dem neuen Release
  `modelle-5`; der Bildteil von SAM 2 ist in `werkzeuge/netz_sam2.py` ohne
  hydra, iopath und torchvision nachgebaut.
- Neue Karte „Motiv & Hintergrund“: BiRefNet (lite, 2K, MIT) erkennt das Motiv
  in rund zwei Sekunden (24 MP, RTX 4060). Belichtung, Kontrast, Sättigung,
  Temperatur und Unschärfe lassen sich für den Hintergrund getrennt einstellen
  (oder mit „Umkehren“ fürs Motiv); dafür rechnet die Kette das Bild ein
  zweites Mal und mischt beide über die Maske, die Unschärfe ohne Lichtsaum
  um das Motiv. Kante weicher und verschieben, Maskenansicht, Hintergrund
  beim Speichern als PNG oder TIFF durchsichtig. Ab 6 GB Grafikspeicher. Das
  Modell (177 MB) kommt aus dem neuen Release `modelle-4`; es ist in
  `werkzeuge/netz_birefnet.py` ohne einops, timm, kornia und torchvision
  nachgebaut.
- KI-Schärfen gegen leichte Fokus-Unschärfe mit Restormer
  (single_image_defocus_deblurring, MIT) in einer eigenen Karte: einmal über
  das ganze Bild gerechnet, danach regelt ein Stärkeregler ohne Wartezeit.
  Geschärft wird das KI-entrauschte Bild, falls vorhanden; gespeichert wird nur
  die Korrektur, und von ihr nur der feine Anteil (Hochpass, Sigma 10 px) –
  Restormer hellt nebenbei auf und verschiebt die Farbe je Kachel ein wenig.
  24 MP brauchen auf einer RTX 4060 rund 3 min, mit TensorRT 45 s. Das Modell
  (101 MB) kommt aus dem neuen Release `modelle-3`. Getestet und verworfen:
  NAFNet (GoPro/REDS) – es erzeugt bei Fotos in voller Auflösung Fehlmuster –
  und das Restormer-Modell gegen Verwacklung, das bei echten Fotos kaum wirkt.
- KI-Entrauschen mit SCUNet (scunet_color_real_psnr, Apache-2.0) in einer
  eigenen Karte: einmal über das ganze Bild gerechnet, danach mischt ein
  Stärkeregler ohne Wartezeit zwischen Original und entrauschtem Bild – in
  Vorschau, 100-%-Ansicht und Export. Gerechnet wird in sRGB wie beim
  Training; Lichter über Weiß bleiben, weil nur die Korrektur des Netzes aufs
  Original gelegt wird. 18 MP brauchen auf einer RTX 4060 rund 20 s, mit
  TensorRT 11 s. Das Modell (71 MB) kommt aus dem neuen Release `modelle-2`;
  `modelle-1` bleibt unverändert.
- `werkzeuge/modelle_exportieren.py` baut SCUNet ohne einops und timm nach
  (rechnet bitgenau wie das Original) und exportiert es für beliebige
  Bildgrößen; mit Argumenten lassen sich einzelne Modelle exportieren.

- TensorRT als optionales Zusatzpaket (`requirements-tensorrt.txt`, rund
  1,8 GB von NVIDIA): Ist es installiert, rechnet die KI darüber – auf einer
  RTX 4060 noch einmal rund doppelt so schnell (12 MP × 2 mit dem großen
  Modell: 24 s statt 54 s). Die Engine entsteht beim ersten Einsatz einmalig
  je Modell, Grafikkarte und Kachelgröße in einem eigenen Prozess (ein bis
  drei Minuten, mit Hinweisfenster) und liegt danach unter
  `modelle/tensorrt`. Scheitert TensorRT, rechnet das Programm mit CUDA
  weiter. „Info & Copyright“ zeigt die TensorRT-Fassung, die Statuszeile nach
  dem Speichern den Rechenweg.

- KI-Modelle per Knopfdruck laden: Die Karte „KI-Hochskalieren“ bietet
  „Modell herunterladen“ an, fragt mit Quelle, Größe und Lizenz nach und lädt
  aus dem Release `modelle-1` dieses Projekts. Jede Datei wird zuerst unter
  `.teil` gespeichert und erst nach bestandener SHA-256-Prüfung umbenannt;
  Abbrechen hinterlässt nichts. Ist der Programmordner schreibgeschützt,
  landen die Modelle unter `%LOCALAPPDATA%\Silberkorn\modelle`.
- KI-Hochskalieren um 2 × oder 4 × beim Speichern mit Real-ESRGAN über ONNX
  Runtime (CUDA): schnelles Modell (realesr-general-x4v3) mit Regler für die
  Entrauschstärke, für den die Gewichte zweier Modelle auf der GPU gemischt
  werden, und großes Modell (RealESRGAN_x4plus) ab Funktionsstufe M.
  Kacheln mit Überlappung, Größe je VRAM-Stufe, bei Speichermangel kleiner;
  Fortschritt mit Abbrechen. Jede Modelldatei wird vor dem Laden gegen ihre
  SHA-256-Prüfsumme geprüft.
- `werkzeuge/modelle_exportieren.py` wandelt die offiziellen Real-ESRGAN-
  Gewichte nach ONNX und prüft das Ergebnis gegen PyTorch.
- 100-%-Ansicht: Zoom auf 100, 200 und 400 % per Mausrad oder `Strg`+`1`,
  Verschieben durch Ziehen, Doppelklick wechselt zur Einpassung. Gerechnet
  wird das ganze Bild in voller Auflösung, gezeigt der sichtbare Ausschnitt –
  pixelgleich mit dem gespeicherten Bild. Verschieben braucht rund 2 ms je
  Ausschnitt, weil das Ergebnis auf der GPU liegen bleibt.
- Geometrie: 90° drehen, spiegeln, begradigen, Perspektive senkrecht und
  waagrecht, Zuschneiden mit Rahmen, Drittellinien und Seitenverhältnissen.
  Eine automatische Vergrößerung verhindert leere Ecken.
- Objektiv: Verzeichnung, Vignette, Farbsäume Rot/Cyan und Blau/Gelb.
- Alle Geometrie- und Objektivkorrekturen sind eine einzige Rückwärts-
  abbildung mit bikubischer Abtastung (Catmull-Rom), auf der GPU ein Kernel.
- Farbbereiche (HSL): Farbton, Sättigung und Luminanz für acht Bereiche, in
  OkLCh mit Kosinus-Übergängen; Grautöne bleiben unberührt. Bedienung über
  eine Karte mit Umschaltern für die drei Eigenschaften.
- LUTs im `.cube`-Format (3D und 1D, DOMAIN_MIN/MAX), tetraedrisch
  interpoliert, mit Stärkeregler; auf der GPU im selben Durchlauf wie Kurven
  und Farbe.
- Rauschminderung: Luminanz mit Non-Local Means (7 × 7 Suchfenster,
  3 × 3 Flecken), Farbe mit einem farbgeführten Fast Guided Filter. Das
  Ergebnis wird für die Vorschau zwischengespeichert; beim Ziehen an den
  Rauschreglern braucht eine Vorschau mit 10 Megapixeln 10 bis 40 ms.
- Mittelwertfilter auf der GPU über Kastenfilter statt Summentabellen:
  Dunst entfernen ist dadurch rund dreimal so schnell.
- RAW-Entwicklung auf der GPU für Bayer-Sensoren: LibRaw liest nur noch das
  Mosaik; Schwarzwert, Weißabgleich, Demosaicing und Farbmatrix rechnet die
  Grafikkarte. Als Verfahren dient RCD (Ratio Corrected Demosaicing) in vier
  CUDA-Durchläufen – an feinen Mustern etwa halb so viele Farbsäume wie
  Malvar-He-Cutler, das als schnellere Alternative im Code bleibt. Eine
  24-MP-RAW ist in rund 0,2 s offen statt in 0,85 s; die Farben stimmen mit
  LibRaw überein. X-Trans, Foveon und bereits entwickelte DNG entwickelt
  weiterhin LibRaw.
- 16 Bit: TIFF und PNG mit 16 Bit je Kanal öffnen und speichern (tifffile,
  imagecodecs). Der Speichern-Dialog bietet PNG und TIFF mit 8 oder 16 Bit an
  und schlägt für Bilder mit mehr als 8 Bit ein 16-Bit-TIFF vor. 16-Bit-PNG
  behält EXIF-Daten; 16-Bit-TIFF trägt das sRGB-Profil, aber noch keine
  EXIF-Daten.
- RAW: Entwicklung mit LibRaw (rawpy), linear in 16 Bit, mit dem
  Weißabgleich der Kamera und ohne automatische Aufhellung.
- Farbprofile: RGB-Matrixprofile (Adobe RGB, ProPhoto, Display P3 …) werden
  selbst gelesen und auf der GPU in lineares sRGB umgerechnet – bei jeder
  Bittiefe und ohne Farben außerhalb von sRGB vorzeitig abzuschneiden.
  CMYK-, Graustufen- und Tabellenprofile rechnet weiterhin LittleCMS.
- Die Vorschau wird auf der GPU in linearem Licht verkleinert.
- Gradationskurve für Helligkeit sowie Rot, Grün und Blau, monoton kubisch
  interpoliert, mit Histogramm der Vorschau im Hintergrund. Die
  Helligkeitskurve wirkt farbtreu, die Kanalkurven verschieben gezielt die
  Farbe.
- Klarheit: lokaler Kontrast in den Mitteltönen mit einem Radius relativ zur
  Bildgröße – Vorschau und Export wirken gleich.
- Dunst entfernen nach dem Dark Channel Prior mit Guided Filter; negative
  Werte fügen Dunst hinzu. Die Schätzung läuft auf einer Kopie mit 512 Pixeln
  Kantenlänge und wird beim Ziehen am Regler wiederverwendet. Mit allen
  Filtern zusammen braucht die Vorschau mit 10 Megapixeln rund 20 ms.
- Erste klassische Filter auf der GPU: Weißabgleich (Temperatur, Tönung),
  Belichtung, Kontrast, Lichter, Tiefen, Dynamik, Sättigung und Schärfen mit
  Radius. Gerechnet wird nicht-destruktiv in linearem Licht; die Kette läuft
  als drei zusammengefasste CUDA-Kernel (Vorschau mit 10 Megapixeln in rund
  12 ms auf einer RTX 4060, Export von 24 Megapixeln in unter 0,2 s).
- Bilder öffnen (JPEG, PNG, TIFF, WebP, BMP, optional HEIC) per Dialog,
  `Strg`+`O` oder Ziehen und Ablegen; speichern als JPEG, PNG, TIFF oder WebP.
  EXIF-Ausrichtung wird angewendet, eingebettete Farbprofile werden nach sRGB
  umgerechnet, EXIF-Daten und Alphakanal bleiben erhalten.
- „Vorher“-Knopf, Zurücksetzen per Doppelklick und „Alles zurücksetzen“;
  Nachfrage vor dem Verwerfen ungespeicherter Änderungen.
- Rechenzeit der GPU in der Statuszeile, CuPy- und NVRTC-Version im Reiter
  „Info & Copyright“.
- Grundgerüst der Anwendung mit PySide6: Kopfzeile mit Sprachwahl (Deutsch,
  Englisch) und dunklem Farbschema, Reiter „Bearbeiten" und „Info & Copyright",
  Statuszeile mit Grafikkarte und Funktionsstufe.
- Startprüfung über NVML, bevor CUDA-Bibliotheken geladen werden. Ohne
  NVIDIA-RTX-Grafikkarte oder mit einem Treiber älter als 570.65 meldet das
  Programm beim Start, was gefunden wurde und was fehlt, und beendet sich.
  GTX-Karten werden auch dann erkannt und abgelehnt, wenn sie zur
  Turing-Generation gehören.
- Funktionsstufen nach Grafikspeicher (–, S, M, L, XL) und Erkennung der
  Rechengenauigkeit (FP16, FP8 ab Ada, FP4 ab Blackwell).
- Programmsymbol, Marken- und Lizenzhinweise (NOTICE).

[Unveröffentlicht]: https://github.com/DerAlexmann/Silberkorn/compare/v0.13.0...HEAD
[0.13.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.13.0
[0.12.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.12.0
[0.11.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.11.0
[0.10.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.10.0
[0.9.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.9.0
[0.8.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.8.0
[0.7.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.7.0
[0.6.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.6.0
[0.5.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.5.0
[0.4.1]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.4.1
[0.4.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.4.0
[0.3.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.3.0
[0.2.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.2.0
[0.1.1]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.1.1
[0.1.0]: https://github.com/DerAlexmann/Silberkorn/releases/tag/v0.1.0
