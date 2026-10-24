# Funktionen

*Zurück zur [README](../README.md) · English: [funktionen.en.md](funktionen.en.md)*

- **Grundregler auf der GPU**: Weißabgleich (Temperatur, Tönung), Belichtung,
  Kontrast, Lichter, Tiefen, Dynamik, Sättigung und Schärfen mit einstellbarem
  Radius.
- **Gradationskurve** für die Helligkeit und für Rot, Grün und Blau einzeln, mit
  Histogramm im Hintergrund. Klicken setzt einen Punkt, Ziehen verschiebt ihn,
  Doppelklick entfernt ihn; die Helligkeitskurve verändert die Farben nicht.
- **Histogramm und Warnung bei Über- und Unterbelichtung**: Über den Karten steht ein
  Histogramm mit Rot, Grün, Blau und Helligkeit – immer vom ganzen Bild, auch in der
  100-%-Ansicht. Die Dreiecke oben links (Tiefen) und oben rechts (Lichter) schalten
  eine Warnung ein: Pixel, in denen ein Kanal 255 erreicht, sind im Bild rot, solche
  bei 0 blau. Ein Dreieck füllt sich, sobald im Bild wirklich Pixel abgeschnitten sind.
  Die Markierung ist nur Anzeige – sie landet nie in gespeicherten, gedruckten oder
  veröffentlichten Bildern und fehlt bei „Vorher“ und in der linken Vergleichshälfte.
  Taste `J` schaltet beide Warnungen; sie bleiben beim nächsten Start so.
- **Automatik**: „Auto“ in der Karte Licht stellt Belichtung, Kontrast, Lichter und
  Tiefen für ein ausgewogenes Bild ein; „Auto“ und „Pipette“ in der Karte Weißabgleich
  machen das Bild im Mittel neutral oder die angeklickte Stelle grau. Gemessen wird im
  Zuschnitt, jede Aktion ist ein Schritt für „Rückgängig“, alle anderen Regler bleiben.
  Weißabgleich-Automatik und Pipette gibt es bei Schwarzweiß nicht.
- **Klarheit**: mehr oder weniger lokaler Kontrast in den Mitteltönen.
- **Dunst entfernen** nach dem Dark-Channel-Prior-Verfahren – auch umgekehrt, um
  Dunst hinzuzufügen.
- **Farbbereiche (HSL)**: Farbton, Sättigung und Luminanz getrennt für Rot,
  Orange, Gelb, Grün, Aqua, Blau, Lila und Magenta. Gerechnet wird im
  wahrnehmungsgleichmäßigen Farbraum OkLCh, mit weichen Übergängen zwischen den
  Bereichen; Grautöne bleiben unberührt.
- **Schwarzweiß & Tönung**: Umwandeln in Schwarzweiß mit einem Mischer für
  dieselben acht Farbbereiche – wie hell wird jede Farbe als Grau? Vorlagen
  wirken wie klassische Farbfilter vor dem Objektiv (Rot, Orange, Gelb, Grün,
  Blau). Dazu eine **Teiltonung**: Lichter und Schatten getrennt einfärben, mit
  Balance – auf Schwarzweiß wie im Labor getönt (Vorlagen Sepia, Selen,
  Cyanotypie), auf Farbbildern als Farblook. Die Helligkeit bleibt dabei, Weiß
  und Schwarz bleiben neutral.
- **Lokale Anpassungen**: Regler nur für einen Bereich – bis zu zehn Masken,
  jede aus Teilen, die sich hinzufügen, abziehen, schneiden und umkehren
  lassen: Verlauf, Radial und Pinsel; dazu mit KI das **Motiv** (BiRefNet),
  ein **Objekt per Klick** (SAM 2) und ein **Tiefenbereich** (Depth Anything),
  ohne KI ein **Helligkeits-** und ein **Farbbereich** (mit Pipette). Motiv und
  Objekte stehen in der Begleitdatei; in Voreinstellungen und im Stapel
  rechnet jedes Bild Motiv und Tiefe selbst. Der Pinsel malt mit Größe, weichem
  Rand und Deckkraft, radiert mit der rechten Maustaste oder `Alt`; `[` und
  `]` ändern die Größe. Je Maske Temperatur, Tönung, Belichtung,
  Kontrast, Lichter, Tiefen, Klarheit, Dunst, Sättigung und Schärfe (negativ
  zeichnet weich). Linien und Griffe liegen direkt im Bild; die Masken folgen
  Drehen, Begradigen und Zuschnitt, „Maske zeigen“ (`O`) färbt den Bereich
  ein.
- **LUTs**: Looks als `.cube`-Datei (3D und 1D) laden, tetraedrisch
  interpoliert, mit Stärkeregler.
- **Rauschminderung**: Luminanzrauschen mit Non-Local Means, Farbrauschen mit
  einem farbgeführten Filter, der Farbkanten erhält – auch zwischen Farben
  gleicher Helligkeit. Die verkleinerte Vorschau zeigt Rauschen schwächer als
  das gespeicherte Bild – zum Beurteilen gibt es die 100-%-Ansicht.
- **Filmkorn**: einfarbiges Korn mit Stärke, Größe und Rauheit, in den
  Mitteltönen am stärksten, Schwarz und Weiß bleiben rein. Die Rauheit lässt es
  klumpen wie bei echtem Film. Die Größe gilt
  relativ zum Bild – die 100-%-Ansicht zeigt genau das Korn des gespeicherten
  Bildes, und beim KI-Hochskalieren kommt das Korn erst danach dazu, statt von
  der KI geglättet zu werden.
- **KI-Entrauschen** mit SCUNet, trainiert auf echtes Kamerarauschen und auf
  Treue statt auf erfundene Details: einmal über das ganze Bild gerechnet (ein
  18-MP-Foto braucht auf einer RTX 4060 rund 20 Sekunden, mit TensorRT 11),
  danach mischt ein Stärkeregler sofort zwischen Original und entrauschtem
  Bild – in Vorschau, 100-%-Ansicht und Export gleichermaßen. Lichter über
  Weiß, etwa aus RAWs, bleiben erhalten.
- **KI-Schärfen** gegen leichte Fokus-Unschärfe mit Restormer, trainiert auf
  echte, unscharf fotografierte Bilder einer Spiegelreflexkamera und auf Treue:
  Wimpern, Haare und Hautstruktur werden wieder klarer, ohne die Säume des
  klassischen Schärfens. Einmal über das ganze Bild gerechnet (24 MP auf einer
  RTX 4060: rund drei Minuten, mit TensorRT 45 Sekunden), danach regelt ein
  Stärkeregler ohne Wartezeit. Geschärft wird das entrauschte Bild, falls
  KI-Entrauschen berechnet ist; übernommen wird nur der feine Anteil, Helligkeit
  und Farbe bleiben unverändert.
- **Motiv & Hintergrund** mit BiRefNet: Die KI erkennt das Motiv – Personen,
  Tiere, Gegenstände – samt Haaren in rund zwei Sekunden. Danach lassen sich
  Belichtung, Kontrast, Sättigung, Temperatur und Unschärfe des Hintergrunds
  getrennt einstellen, etwa um ihn abzudunkeln oder weichzuzeichnen; „Umkehren“
  wendet die Regler aufs Motiv an. Die Kante lässt sich weicher machen und
  verschieben, eine Maskenansicht färbt den Hintergrund zur Kontrolle ein. Beim
  Speichern als PNG oder TIFF wird der Hintergrund auf Wunsch durchsichtig.
  Braucht mindestens 6 GB Grafikspeicher.
- **Objekt per Klick auswählen** mit Segment Anything 2 (SAM 2.1), in derselben
  Karte: Linksklick ins Bild nimmt ein Objekt oder einen Bereich dazu,
  Rechtsklick nimmt einen weg, Strg+Z den letzten Klick zurück. Jeder Klick
  zeigt die Auswahl nach Bruchteilen einer Sekunde; die Regler, „Umkehren“ und
  das Freistellen wirken darauf wie auf das erkannte Motiv. Geht schon ab 4 GB
  Grafikspeicher.
- **Objekte entfernen** mit LaMa: Ein Objekt anklicken (SAM 2) oder mit dem
  Pinsel übermalen, etwa Flecken oder Leitungen – „Entfernen“ füllt die Stelle
  in Bruchteilen einer Sekunde mit dem, was dahinter liegen könnte. Mehrere
  Entfernungen bauen aufeinander auf, die letzte lässt sich zurücknehmen; die
  Regler wirken weiter auf das ganze Bild. Ab 4 GB Grafikspeicher.
- **Tiefe & Bokeh** mit Depth Anything V2: Die KI schätzt in Sekundenbruchteilen,
  wie weit alles im Bild entfernt ist. Danach zeichnet „Unschärfe“ das Bild wie
  ein lichtstarkes Objektiv weich – umso stärker, je weiter etwas vor oder hinter
  der Fokusebene liegt. Den Fokus setzt ein Klick ins Bild oder ein Regler,
  „Schärfentiefe“ bestimmt, wie viel scharf bleibt; ein erkanntes Motiv bleibt
  auf Wunsch ganz scharf. Gerechnet wird in linearem Licht, damit Lichter
  aufblühen, und Scharfes läuft nicht als Schein ins Unscharfe. Ab 4 GB
  Grafikspeicher.
- **KI-Kolorieren** mit DDColor: Schwarzweiß- und Sepiabilder bekommen Farbe.
  Die KI sieht nur die Helligkeit und schätzt daraus die Farben – glaubwürdig,
  aber geraten, nicht historisch belegt. Die Helligkeit bleibt Pixel für Pixel
  die des Originals, auch bei großen Scans; ein Regler mischt die Farbe
  stufenlos ein, Weißabgleich, Sättigung und Farbbereiche wirken danach wie
  gewohnt. Rund 0,1 s, ab 4 GB Grafikspeicher.
- **KI-Erweitern** mit FLUX.2 [klein] 4B und der Outpaint-LoRA von fal: Statt
  auf ein Seitenverhältnis zuzuschneiden, erfindet die KI die fehlenden Ränder
  passend zum Bild dazu – etwa um ein 4:3-Foto auf 16:9 zu bringen. Das Original
  bleibt Pixel für Pixel erhalten und wird mit weichem Saum eingesetzt, ein
  Farbstich der KI wird am Original gemessen und herausgenommen. „Neu erzeugen“
  würfelt die Ränder neu; die Regler wirken danach auf das ganze Bild. Kommt
  mehr als ein Viertel je Seite dazu, weist das Programm darauf hin, dass die KI
  dann mehr erfindet, als sie sieht. Rund 15 Sekunden auf einer RTX 4060;
  braucht 8 GB Grafikspeicher.
- **Anonymisieren**: Gesichter, Kennzeichen oder Hausnummern verpixeln,
  weichzeichnen oder schwarz füllen – als Rechteck oder Ellipse. „Gesichter
  finden“ legt um jedes erkannte Gesicht eine Fläche (YuNet, liegt dem Programm
  bei, rechnet auf dem Prozessor); Flächen lassen sich verschieben, in der Größe
  ändern, löschen und von Hand aufziehen. Sie folgen Drehen und Zuschnitt. Das
  Mosaik ist standardmäßig grob, denn feine Mosaike lassen sich teilweise
  zurückrechnen. Auf Wunsch speichert Silberkorn ohne GPS-Position,
  Seriennummern von Kamera und Objektiv, Besitzernamen und Herstellerdaten.
  Bewusst nicht angeboten wird das Gegenteil, ein „Entpixeln“: Eine KI könnte
  ein verpixeltes Gesicht nicht zurückholen, nur ein fremdes erfinden.
- **Metadaten**: Die Karte zeigt Kamera, Objektiv und Belichtung und lässt
  Titel, Beschreibung, Stichwörter, Urheber, Copyright, Ort, Aufnahmedatum und
  Bewertung ändern – beim Datum genügt für alte Abzüge auch nur das Jahr.
  Gelesen wird EXIF, IPTC und XMP, auch aus RAW; „Alle Metadaten …“ zeigt alles,
  was die Datei mitbringt. Geschrieben wird erst beim Speichern, als XMP nach
  IPTC und wo möglich auch als EXIF; „Zurücksetzen“ nimmt die Änderungen
  zurück. Auf Wunsch trägt Silberkorn Urheber und Copyright in jedes Bild ein,
  das selbst keine hat. Technische Werte wie Belichtungszeit oder ISO bleiben
  unverändert. Die Drehung und Entwicklungseinstellungen anderer Programme
  (Lightroom, darktable) fallen aus dem XMP weg, damit sie dort nicht ein
  zweites Mal wirken.
- **Für Veröffentlichung speichern**: Bilder fürs Netz in einem Schritt –
  verkleinert auf eine längste Kante (Schnellwahl 1280, 1920, 2560 Pixel) oder
  einen Prozentsatz, nie vergrößert. Dazu ein sichtbares Wasserzeichen aus Text
  und/oder Logo, in einer Ecke, in der Mitte oder als Muster über das ganze
  Bild, mit Größe und Deckkraft. In die Datei kommen Urheber, Copyright und
  Webadresse (EXIF und XMP nach IPTC) und auf Wunsch ein maschinenlesbarer
  Vorbehalt gegen KI-Training und Data-Mining (IPTC „Data Mining“, Suchmaschinen
  bleiben erlaubt). GPS-Position und Seriennummern fallen immer weg, die übrigen
  Kameradaten auf Wunsch. Enthält das Bild von der KI erfundene Teile, wird das
  vermerkt (IPTC „Digital Source Type“). Eine Vorschau zeigt das Ergebnis; die
  Einstellungen bleiben als Vorlage erhalten. Das Original bleibt unverändert.
  Ganz verhindern lässt sich das Kopieren veröffentlichter Bilder nicht – das
  Wasserzeichen und die Rechteangaben machen es aber unattraktiv und belegen,
  woher ein Bild stammt.
- **Drucken** (🖶 oder `Strg`+`P`): Drucker und Papier wählen, das Bild auf die
  ganze Seite oder auf 9 × 13, 10 × 15, 13 × 18, 20 × 30 cm oder eine eigene
  Größe bringen – ganz gezeigt oder die Fläche füllend und beschnitten, mit
  Rand oder randlos. Eine Vorschau zeigt das Blatt; angezeigt wird auch die
  Auflösung auf dem Papier. Ist sie knapp, bietet der Dialog an, das Bild
  vorher mit KI zu vergrößern. Gedruckt wird das bearbeitete Bild in voller
  Auflösung als sRGB; den Farbabgleich übernimmt der Druckertreiber. Ohne
  Angabe wählt der Dialog Papier in 10 × 15 cm, wenn der Drucker es kennt.
- **Geometrie**: um 90° drehen, spiegeln, begradigen, Perspektive senkrecht
  und waagrecht, Zuschneiden mit Rahmen und festen Seitenverhältnissen. Leere
  Ecken nach dem Begradigen werden automatisch weggeschnitten. „Auto“ stellt das
  Begradigen an den waagrechten und senkrechten Linien im Bild ein (bis ±20°); ohne
  klare Linien bleibt der Regler, wie er ist.
- **Objektiv**: Verzeichnung, Vignette und Farbsäume (chromatische Aberration)
  ausgleichen – von Hand oder automatisch mit **Objektivprofilen** aus der
  Datenbank von [lensfun](https://lensfun.github.io) (CC BY-SA 3.0). Kamera,
  Objektiv, Brennweite und Blende kommen aus der Datei, auch für adaptierte
  Objektive. Bei RAW wird ein gefundenes Profil gleich angewendet, bei JPEG nur
  auf Wunsch (die Kamera hat dort oft schon korrigiert). Die Datenbank (etwa
  0,5 MB) lädt Silberkorn auf Knopfdruck und sucht ebenso auf Knopfdruck nach
  einer neueren – nie von selbst. Alle Geometrie- und Objektivkorrekturen
  werden in einem einzigen bikubischen Schritt abgetastet.
- **KI-Hochskalieren** um 2 × oder 4 × beim Speichern, mit Real-ESRGAN über ONNX
  Runtime auf der GPU: ein schnelles Modell mit Regler für die Entrauschstärke
  (ab 4 GB Grafikspeicher) und ein großes Modell mit mehr Schärfe (ab
  Funktionsstufe M). Gerechnet wird in halber Genauigkeit (FP16) auf den
  Tensorkernen und in Kacheln, deren Größe sich nach dem Grafikspeicher
  richtet; ein 24-MP-Bild ist mit dem schnellen Modell auf einer RTX 4060 in
  knapp 6 Sekunden auf 96 MP vergrößert. Mit dem optionalen
  [TensorRT](../README.md#3-tensorrt-optional) geht es noch einmal rund doppelt so schnell.
- **100-%-Ansicht**: Zoom auf 100, 200 und 400 % per Mausrad, Verschieben durch
  Ziehen, Doppelklick wechselt zwischen eingepasst und 100 %. Gezeigt wird ein
  Ausschnitt des Bildes in voller Auflösung – genau das, was gespeichert wird.
  Die Zoomstufe steht dabei oben rechts im Bild.
- **Nicht-destruktiv**: Jede Änderung wird aus dem unveränderten Original neu
  gerechnet. Doppelklick setzt einen Regler zurück, „Vorher“ zeigt das Original,
  solange der Knopf gedrückt ist. Der Knopf ◧ (Taste `Y`) legt eine verschiebbare
  Trennlinie über das Bild: links das Original, rechts das bearbeitete Bild – in
  derselben Drehung und demselben Zuschnitt. Die Linie bleibt beim Zoomen und
  Verschieben im Fenster stehen; Doppelklick auf den Griff setzt sie in die Mitte.
- **Kartenauswahl**: Ein Auswahlfeld über den Karten springt direkt zu jeder
  Karte und zeigt beim Rollen, welche gerade oben steht.
- **Rückgängig und Wiederholen** mit ↶ ↷ oder `Strg`+`Z` / `Strg`+`Y`: für
  Regler, Kurven, Zuschnitt, Metadaten und auch für KI-Schritte wie Entrauschen,
  ein entferntes Objekt oder eine Erweiterung – und für „Zurücksetzen“. Ein Zug
  am Regler ist ein Schritt; der Tooltip nennt, was zurückgenommen wird.
  Überholte KI-Ergebnisse belegen höchstens ein Fünftel des Grafikspeichers
  zusätzlich, ältere Schritte fallen dafür weg.
- **Begleitdatei**: Beim Wechsel des Bildes und beim Beenden sichert Silberkorn
  die Bearbeitung in einer kleinen Datei neben dem Bild (`foto.jpg.silberkorn`) –
  Regler, Kurven, LUT, entfernte Objekte, Staub, Maske, Tiefe und KI-Erweiterung.
  Beim nächsten Öffnen ist alles wie zuvor. KI-Entrauschen, -Schärfen und
  -Kolorieren stehen nicht darin – sie kosteten Hunderte MB – und werden auf
  Nachfrage neu berechnet. Beim ersten Mal fragt Silberkorn, ob es Begleitdateien
  anlegen darf; oben über „Begleitdateien“ lässt sich das ändern. Passt eine
  Begleitdatei nicht mehr zum Bild, weil es verändert wurde, übernimmt Silberkorn
  auf Nachfrage nur die Reglerwerte. Ist alles zurückgesetzt, verschwindet sie.
- **Ordneransicht** (Reiter „Ordner“): die Bilder eines Ordners als Kacheln,
  ein Doppelklick öffnet zum Bearbeiten. Ein Punkt markiert Bilder mit
  Begleitdatei; ihre Kachel zeigt das bearbeitete Bild. Vorschaubilder entstehen
  im Hintergrund und nur für das, was zu sehen ist – aus dem eingebetteten
  Vorschaubild einer RAW, aus einem auf ein Achtel verkleinert gelesenen JPEG oder,
  bei großen TIFFs und PNGs, aus dem **Vorschau-Cache**: einer Datei mit fester,
  selbst gewählter Größe (Vorschlag 200 MB, 0 = aus), die gleich vorbelegt wird.
  Jedes Vorschaubild und jeder Pfad darin ist mit der Windows-Datenschutz-API für
  die eigene Anmeldung verschlüsselt; Gelöschtes wird überschrieben, Ordner lassen
  sich ganz ausnehmen.
- **Bewertung** (Reiter „Ordner“): Fährt die Maus über ein Bild, erscheinen fünf Sterne
  und ein Papierkorb; ein Klick auf Stern *n* vergibt *n* Sterne, derselbe Stern nimmt sie
  zurück. Der Papierkorb markiert das Bild als **Ausschuss** (abgeblendet, in jeder
  Sortierung am Ende) – er **löscht nichts** und verändert die Datei nicht. Eine Liste
  sortiert nach Name, Datum (neueste zuerst) oder Sternen. Gespeichert wird in einer
  kleinen XMP-Datei neben dem Bild (`foto.jpg.xmp`, nur die Bewertung), wenn
  Begleitdateien erlaubt sind. **Fremde XMP-Dateien gleichen Namens** (etwa von
  darktable) bleiben unberührt: Ihre Bewertung wird nur gezeigt. Das Feld „Bewertung“
  im Reiter Bearbeiten und die Sterne in „Speichern unter“ gehören dazu; Ausschuss
  wird dort nicht mitgespeichert.
- **Stapel**: In der Ordneransicht mehrere Bilder wählen (`Strg`/`Umschalt`) und
  mit „Stapel …“ auf einmal bearbeiten – eine Voreinstellung oder kopierte
  Einstellungen darauflegen, Staub über den Infrarotkanal entfernen, die
  Bearbeitung als Begleitdatei sichern und/oder die Bilder ausgeben: in einen
  Ordner, als JPEG, PNG, TIFF, WebP oder AVIF, mit Namenszusatz, auf Wunsch mit
  KI-Entrauschen, -Schärfen, -Kolorieren und KI-Hochskalieren. Vorhandene Dateien
  werden nie überschrieben. Ein Bild nach dem anderen, abbrechbar; ein Fehler
  betrifft nur sein Bild, am Ende steht ein Bericht.
- **Kontaktbogen**: Der Knopf 🖶 in der Ordneransicht legt die gewählten Bilder –
  sonst alle des Ordners – in der Reihenfolge der Ansicht als Raster auf Papier:
  2 bis 8 Spalten, jedes Bild ganz, darunter Dateiname und Sterne, oben Ordner und
  Seitenzahl. Hoch- oder Querformat, auf einen Drucker oder als PDF-Datei;
  Ausschuss lässt sich weglassen. Die Bilder kommen mit ihrer Bearbeitung aus der
  Begleitdatei (ohne KI-Ergebnisse), in 300 dpi für ihre Zelle. Die Vorschau zeigt
  die Seiten mit den Kacheln; Abbrechen gibt nichts aus.
- **Voreinstellungen**: Einstellungen unter einem Namen sichern und auf andere
  Bilder legen – mit Auswahl, was mitgeht: Grundregler, Kurven, Farbbereiche,
  Schwarzweiß & Tönung, LUT, Rauschminderung, Filmkorn und Film sind vorgewählt, Geometrie, Anonymisieren und
  Metadaten gehören meist nur zu einem Bild. Beim Film wahlweise mit der
  gemessenen Filmmaske, für Bilder vom selben Streifen, sonst wird sie je Bild
  neu geschätzt. Mit `Strg`+`Umschalt`+`C` / `V` gehen Einstellungen direkt von
  einem Bild aufs nächste. Voreinstellungen liegen als JSON im Ordner
  `voreinstellungen` neben dem Programm und lassen sich importieren und
  exportieren.
- **Schnell**: Die Vorschau entsteht in Bildschirmauflösung in wenigen
  Millisekunden; die Rechenzeit steht in der Statuszeile. Gespeichert wird in
  voller Auflösung.
- **Farbrichtig**: Gerechnet wird in linearem Licht mit 32-Bit-Gleitkomma.
  RGB-Farbprofile wie Adobe RGB, ProPhoto RGB oder Display P3 werden auf der GPU
  nach sRGB umgerechnet, ohne Umweg über 8 Bit; Farben außerhalb von sRGB
  bleiben bis zur Ausgabe erhalten. Die EXIF-Ausrichtung wird angewendet,
  Metadaten (EXIF, IPTC, XMP) und ein Alphakanal bleiben beim Speichern in
  jedem Format erhalten – auch die Kameradaten einer RAW. Mit „Monitorprofil“
  oben rechnet die Anzeige in das Farbprofil des Bildschirms um, auf dem das
  Fenster steht – für Bildschirme mit großem Farbraum; Speichern, Druck und
  Histogramm bleiben sRGB.
- **16 Bit und RAW**: TIFF und PNG mit 16 Bit je Kanal öffnen und speichern.
  RAW-Dateien praktisch aller Kameras (CR2, CR3, NEF, ARW, RAF, ORF, RW2, DNG
  und weitere) werden linear und ohne automatische Aufhellung entwickelt – der
  volle Umfang des Sensors bleibt erhalten, die Helligkeit regelt die
  Belichtung. Bei Sensoren mit Bayer-Mosaik, also bei fast allen Kameras,
  läuft das Demosaicing auf der GPU – nach Malvar, He und Cutler. Eine
  24-Megapixel-RAW ist in rund 0,2 s offen statt in gut einer Sekunde. Auch
  Fujis X-Trans-Sensoren entwickelt die GPU, mit einem eigenen kantenbewussten
  Verfahren für das 6×6-Muster – im Ergebnis kaum von LibRaw zu unterscheiden,
  aber in Millisekunden statt Sekunden. Wer an feinen Mustern noch weniger
  Farbsäume will, wählt oben „RAW: Beste Qualität“ – dann entwickelt LibRaw auf
  dem Prozessor, mit dem Verfahren DHT bzw. bei X-Trans mit Markesteijn (etwa
  1,5 bis 3 s). Andere Sensoren (Foveon …) entwickelt immer LibRaw.
- **Scan & Film**: Gescannte oder mit der Kamera abfotografierte Negative –
  Farbe oder Schwarzweiß – werden ins Positiv gewandelt, über die Dichte des
  Films wie im Labor. Silberkorn schätzt die orange Filmmaske sowie Schwarz- und
  Weißpunkt je Farbkanal selbst und nimmt so den Farbstich heraus; den
  unbelichteten Filmrand kann man auch mit der Pipette anklicken. Danach wirken
  alle Regler und KI-Karten auf das Positiv. TIFF-Scans mit Infrarotkanal
  (RGBI, etwa aus VueScan oder SilverFast) werden als solche erkannt statt als
  halb durchsichtiges Bild. Über diesen Kanal findet die Karte Staub, Fusseln
  und Kratzer – Film lässt Infrarot durch, Staub nicht – und füllt sie: kleine
  Punkte auf der GPU, breite Stellen mit LaMa. Bei 24 Megapixeln dauert das
  unter einer Sekunde; „Vorher“ und Rückgängig wirken wie gewohnt. Ein
  Infrarotkanal, der das Motiv selbst zeigt (Luftbilder, Schwarzweißfilm mit
  Silber, Kodachrome), wird erkannt und nicht für Staub gehalten.
  „Fotos trennen …“ findet auf einem Flachbett-Scan mehrere aufgelegte Abzüge,
  auch schräg liegende, richtet jeden gerade aus, beschneidet ihn auf seinen
  Rand und speichert ihn als eigene Datei (Name-01, Name-02 …, ohne etwas zu
  überschreiben); eines davon öffnet Silberkorn danach zum Bearbeiten.
- **Formate**: Öffnen von JPEG, PNG, TIFF, WebP, AVIF, BMP und RAW (HEIC mit dem
  optionalen Paket `pillow-heif`), Speichern als JPEG, WebP und AVIF mit 8 Bit,
  PNG und TIFF wahlweise mit 8 oder 16 Bit. AVIF wird bei gleicher Güte etwa halb
  so groß wie JPEG; Bilder mit mehr als 8 Bit liest Silberkorn als 8 Bit. Bilder mit mehr als 8 Bit schlägt der
  Speichern-Dialog als 16-Bit-TIFF vor.

| Kartenauswahl | Scan & Film |
|---|---|
| ![Die aufgeklappte Kartenauswahl über den Karten](bilder/de/kartenwahl.png) | ![Ein umgewandeltes Farbnegativ, die über Infrarot gefundenen Staubstellen sind blau markiert](bilder/de/scan-und-film.png) |
| **Fotos trennen** | **Ordneransicht** |
| ![Dialog „Fotos trennen“ mit drei gefundenen Abzügen einer Scannerplatte](bilder/de/fotos-trennen.png) | ![Reiter „Ordner“ mit Unterordnern und Bildern als Kacheln; ein Bild mit Begleitdatei zeigt seine Bearbeitung und einen blauen Punkt, zwei Bilder sind für den Stapel gewählt](bilder/de/ordneransicht.png) |

*Die Motive sind gerechnet, keine Fotos – erzeugt mit `werkzeuge/bildschirmfotos.py`.*

| Taste | Wirkung |
|---|---|
| `Strg`+`O` | Bild öffnen (oder Datei auf die Fläche ziehen) |
| `Strg`+`S` | Speichern … – immer unter neuem Namen, das Original wird nie stillschweigend überschrieben |
| `Strg`+`P` | Drucken … |
| `Strg`+`Z` / `Strg`+`Y` | Rückgängig / Wiederholen (auch `Strg`+`Umschalt`+`Z`); bei der Auswahl per Klick nimmt `Strg`+`Z` zuerst die Klicks zurück |
| `Strg`+`Umschalt`+`C` / `V` | Einstellungen kopieren / auf ein anderes Bild einfügen |
| `Strg`+`0` / `Strg`+`1` | eingepasst / 100 % |
| `Y` | Vergleich Vorher/Nachher mit verschiebbarer Trennlinie ein- / ausschalten |
| `J` | Warnung vor abgeschnittenen Tiefen und Lichtern (blau / rot) ein- / ausschalten |
| Mausrad, Ziehen, Doppelklick | zoomen, verschieben, zwischen eingepasst und 100 % wechseln |
| `Eingabe` / `Esc` | Zuschnitt übernehmen / abbrechen |
