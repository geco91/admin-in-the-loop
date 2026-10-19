# Lokale Commandanalyse mit sh-guard

Entwicklungsstand AITL 0.9.14. Der Reviewer unterstützt die menschliche Prüfung
von **AI→Terminal**. Rechts im AI-Bereich unter „Befehlsprüfung“ die Prüfung „sh-guard“ aktivieren
und den Download unter „Einrichtung & Einstellungen“ im Dienstreiter bestätigen.
AITL wählt das gepinnte Binary für Linux/macOS, jeweils
x86_64 oder ARM64. Danach analysiert es den finalen Command-Snapshot lokal.
Es führt den vorgeschlagenen Command dabei nicht aus.

Die Aktivierung wird zusammen mit den übrigen lokalen Einstellungen gespeichert.
Nach Neustart prüft AITL die bestehende Installation erneut. Fehlt das Binary,
ist vor einem Download wieder eine Bestätigung nötig. Ohne vorherige Aktivierung
startet keine Toolvorbereitung. Ein manuell gesetzter PATH wird nicht als
Toolquelle übernommen. Die Mehrfachauswahl im Seitenbereich bleibt beim Aktivieren
mehrerer Prüfungen geöffnet; „Fertig“ oder Escape schließt sie. Links unter
„Rückgabeprüfung“ werden die Prüfungen für Terminal→AI unabhängig eingestellt.
Die Auswahl wird pro Richtung lokal gespeichert. Eine zuvor global aktivierte
Zeichenprüfung gilt zunächst für beide Richtungen und lässt sich danach getrennt ändern.
Über der mittleren Codefläche steht keine Auswahlleiste mehr. „Code“ ist immer
der Hauptreiter. Nur aktivierte, zur aktuellen Richtung passende Prüfungen erhalten
einen weiteren Reiter: sh-guard für Befehle sowie optional „Zeichen & Bytes“.
Jeder Prüfreiter zeigt Farbsignal und Textwert; sh-guard nutzt
ROT/GELB/GRÜN mit Score, unvollständige oder fehlgeschlagene Analysen GELB mit
Fragezeichen. Laufende, veraltete oder nicht anwendbare Analysen bleiben grau.

Ein neuer oder bearbeiteter Command-Snapshot öffnet „Code“ mit dem finalen Text
und den Risikomarkierungen. Der sh-guard-Reiter enthält die Unterreiter „Befund“,
„Technik“ und „Einrichtung & Einstellungen“ sowie alle Analyseaktionen.
„Befund“ enthält die lesbare
Zusammenfassung und Einzelbefehle. „Technik“ enthält Version, Quelle, Prüfsummen,
JSON, Fehlercode und „Tool entfernen“. Unter dem Code stehen keine Analyseaktionen;
dort bleibt die kompakte Freigabezeile mit der Return-Einstellung.
Ein zusätzliches Analysefenster wird nicht geöffnet. Bei Terminal→AI heißt der
Hauptreiter „Ausgabe“; eine Inhaltsanalyse des Outputs erfolgt weiterhin nicht.
Die Auswahl weist ausdrücklich darauf hin, dass ein Inhalts-/Datenschutzscan
noch nicht verfügbar ist. „Zeichen & Bytes“ prüft die jeweils aktivierte Richtung auf
Nicht-ASCII-/Steuerzeichen und zeigt deren Anzahl, Codepoints und Byteansicht.
Diese Zahl sind Zeichenhinweise, keine Risikopunkte; auch erlaubte Umlaute zählen.
Die bestehende Normalisierung bleibt unabhängig von der Auswahl aktiv.
Bei einem fehlgeschlagenen Speichervorgang wird die laufende Prüfung trotzdem
deaktiviert; die gemeldete Einstellungsspeicherung muss vor dem Neustart korrigiert werden.

## Dienste einrichten und erneut initialisieren

Neben jedem verfügbaren Review-Eintrag führt ein Zahnrad mit Textbeschriftung
zu seinen Einstellungen. Dies aktiviert den Dienst nicht automatisch. Während
einer solchen Inspektion darf ein ausgeschalteter Dienst vorübergehend als
Reiter sichtbar sein; „Schließen“ blendet ihn wieder aus und kehrt zum Code zurück.
Die erste Aktivierung von sh-guard öffnet die Einrichtung im Dienstreiter.
Dort werden Status, Version, Downloadgröße, Quelle, Installationsziel und
Prüfsummen angezeigt. „Installieren“ ist eine ausdrückliche Bestätigung;
„Abbrechen“ deaktiviert die Prüfung. „Schließen“ lässt eine anstehende
Bestätigung offen. Ein veralteter Klick aus einer früheren Aktivierung kann
keine neue Installation bestätigen. Ein separater Installationsdialog entfällt.

Beim App-Start wird eine gespeicherte Aktivierung durch den vorhandenen
Installations-/Integritätscheck erneut initialisiert. Ein fehlendes Binary
führt zu „Einrichtung nötig“ im Reiter, Fehler zu einem gelben Fragezeichen.
Fortschritt, Fehlercode, erneute Initialisierung und Entfernen sind über die
Einstellungen erreichbar. Passive Zustandswechsel öffnen keine Fenster und
nehmen dem Code nicht den Fokus. sh-guard braucht keine dauerhafte Verbindung;
„Zeichen & Bytes“ braucht weder Download noch Verbindungsdaten. Es existiert
weiterhin kein externer Ausgabe-/Datenschutzdienst mit Zugangseinstellungen.

## Befund und Freigabe

Die Hauptansicht verwendet die Stufen „Unauffällig“, „Vorsicht“, „Hohes Risiko“
und „Kritisch“ zusammen mit dem Score und einer kurzen Erklärung. „Unauffällig“
ist keine Sicherheitszusage. Bei laufender Analyse erscheint ein unbestimmter
Fortschrittsindikator mit „Abbrechen“; diese Aktion schaltet die Analyse aus.
Bei einem Fehler ist „Erneut prüfen“ direkt erreichbar. Die sichtbare Aktion
wird durch einen gleichzeitig eintreffenden Befund nicht umgedeutet.

Enter betätigt das fokussierte Analyse-Steuerelement, ohne einen Command
freizugeben. Ctrl+Tab wechselt zwischen den sichtbaren Reitern. Escape aus Befund/Technik
und „Zum Code“ wählen den Hauptreiter und geben dem Commandtext den Fokus.
Ein eintreffender Befund wechselt den Reiter nicht und erhält Scrollposition sowie
Textauswahl im unveränderten Code. Ein Mausklick auf markierten Code öffnet keinen
Befund; dafür dienen der Reiter und die Kontextmenü-Aktion „Analysebefund anzeigen“.
Die Bereiche „Befund“ und „Technik“ sind per Tastatur wechselbar; ihr Text ist
scrollbar und kopierbar. Normale Sprache bleibt lesbar; nicht druckbare Zeichen
aus Analyzertexten werden explizit dargestellt. Die Hauptansicht einschließlich der Einrichtung wurde bei
960×560 und 1360×850 geprüft.

Gesamt-Score, Risikostufe und verlässlich zuordenbare Subcommands erscheinen im
Review. Beispiele sind rekursives Löschen, Rechteausweitung, Secret-Exposition,
Datenabfluss und Download→Ausführung. Wenn etwa Substitutionen die genaue
Textzuordnung verhindern, bleibt der Gesamtbefund sichtbar; Einzelmarkierungen
werden weggelassen. Unvollständige Parserergebnisse heißen „Analyse unvollständig“;
Startfehler, Timeouts oder beschädigte Binaries heißen „Prüfung nicht verfügbar“.
Keiner dieser Zustände darf als bestandene Prüfung verstanden werden.

Der Befund gehört zu Textrevision, finalem Return, Sitzung und Bridgebindung.
Änderungen entwerten ihn; ein neuer Review wird neu analysiert. Eine bereits
angezeigte Analyse kann am unveränderten gesendeten Snapshot sichtbar bleiben.
Sie ersetzt weder Commandfreigabe noch die gesonderte Outputfreigabe und löst
keinen Terminaltransfer aus. Upstream-Labels wie `safe` oder `blocked` sind
Analysebefunde, keine AITL-Freigaben. Auch bei hohem Risiko entscheidet der Mensch.

Terminal→AI erhält hierdurch keine personenbezogene-Daten-/Secret-Erkennung oder
Schwärzung. Terminalsteuerzeichenbereinigung und Inhaltsprüfung sind verschiedene Funktionen.

## Installation und Herkunft

Tool: [sh-guard v0.1.10](https://github.com/aryanbhosale/sh-guard/releases/tag/v0.1.10),
Quellstand `92005d65b1232946924b524bcad267a29d8a2cb5`,
[GPL-3.0-only / Lizenztext](https://github.com/aryanbhosale/sh-guard/blob/v0.1.10/LICENSE).
AITL bleibt eine separate Python-Anwendung und ruft das eigenständig
heruntergeladene CLI auf. Im Repository werden keine Upstream-Binaries verteilt.
Die Pinzulassung ist keine Rechts-/Sicherheitszertifizierung und kein Nachweis
eines reproduzierbaren Upstream-Builds oder vollständigen SBOM-Audits.

Bei allen vier offiziellen Archiven wurden Archivgröße/-SHA-256 und die Größe/
SHA-256 des enthaltenen CLI gegen `RISK_RELEASES` geprüft. Der Installer wiederholt
diese Prüfungen, begrenzt die Dekompression, akzeptiert keine zusätzlichen Dateien
oder Links und veröffentlicht Binary und Installationsbeleg erst nach einem
nativen Versions-/JSON-Schema-Probelauf. macOS-Quarantäne wird beibehalten.
Die gepinnten Werte sind in `admin_in_the_loop.py` festgelegt; es gibt kein
automatisches Update auf einen ungeprüften neuesten Release.

Nur die Installation benötigt HTTPS zu `github.com` und dessen freigegebenem
Asset-Host `release-assets.githubusercontent.com` (gegebenenfalls
`objects.githubusercontent.com`). AITL berücksichtigt den konfigurierten
HTTPS-Proxy und die vorhandene CA-Vertrauenskette. Downloads bleiben zeitlich
begrenzt und abbrechbar, auch während CONNECT/TLS und Redirects.

Der Analysepfad verwendet ausschließlich `--version` und die JSON-Analyse mit
Bash-Syntax sowie einer leeren expliziten Regeldatei in einem privaten
Arbeitsverzeichnis. Upstream-`--setup`, MCP-Server und Agent-Konfigurationsänderungen
werden nicht verwendet. Die Analyseumgebung enthält keine übernommenen
Credential-/Proxyvariablen. Commandtext ist kurzzeitig in lokalen Prozessargumenten
sichtbar; dies ist keine Sandbox gegen Prozesse derselben Benutzerkennung.

## Prüfung

Die echte Linux-x86_64-Installation wurde über den konfigurierten HTTPS-Proxy
heruntergeladen, geprüft und ausgeführt. Native Tests decken Installation,
harmlosen/gefährlichen Command, Pipeline, Revisionswechsel, fehlende
Einzelzuordnung, Richtungswechsel, gespeicherte Aktivierung, Neustart, Entfernung
und die Tk-Review-Anzeige ab. Die vorgeschlagenen Commands werden dabei nicht ausgeführt.
Die anderen drei Archive wurden auf Integrität geprüft; native ARM-/macOS-Läufe
sind in dieser Linux-x86_64-Umgebung nicht belegt. Dort muss vor Installation der
eingebaute native Probelauf bestehen.

Reproduzierbare Tests aus dem Repository-Verzeichnis:

```bash
python3 -m unittest discover -s tests -p 'test_*risk*.py' -v
python3 tests/test_shguard_integration.py
xvfb-run -a -s '-screen 0 1920x1080x24' python3 tests/test_shguard_ux.py
# Für die echte CLI und ihre GUI-Integration das offizielle Plattformarchiv angeben:
AITL_TEST_SH_GUARD_ARCHIVE=/absoluter/pfad/sh-guard-x86_64-unknown-linux-gnu.tar.gz \
  xvfb-run -a -s '-screen 0 1920x1080x24' python3 tests/test_shguard_integration.py
```

Ohne Archiv werden die echten Binary-Tests ausdrücklich übersprungen. Die übrigen
Tests verwenden selbst erzeugte Fixtures und lokale HTTPS-/CONNECT-Server.

Prüfstand des funktionalen Ausbaus (0.9.6): 60 bestehende Risiko-Tests, 9 Integrationstests
(einschließlich echtem CLI und Tk), 49 Selbsttests und 42 allgemeine GUI-Tests
bestanden. Der breite Lauf mit 307 Tests hatte zwei HTTP-Fehler und vier externe
Skips. Die HTTP-Fehler betreffen die bestehenden ControllerTakeFlow-Tests
`test_note_output_binding_is_deliberate_only` und
`test_pending_discard_restores_prior_state_and_late_ack_is_ignored`:
Ihre schnellen Status-Polls können `429 rate_limit` auslösen. Beide Fehler
wurden auch mit dem unveränderten Ausgangscode reproduziert; ein isolierter
Lauf der gesamten betroffenen Testklasse bestand sowohl vorher als auch nachher.
Das Rate-Limit wurde für diese Integration nicht gelockert. Drei der neun neuen
Integrationstests wurden nach dem breiten Lauf ergänzt und separat ausgeführt.

UI-/UX-Folgeprüfung (0.9.7): 8 gezielte UX-Tests, 60 Risiko-Tests,
9 Integrationstests mit echtem Linux-Binary und 42 allgemeine GUI-Tests bestanden.
Die UX-Tests prüfen unter anderem sichtbare Aktionen bei kleinen Fenstern,
Tastaturbedienung/Fokus, unveränderte Commandbytes, verständliche Fehler und
Textkontrast von mindestens 4,5:1 auf hellen und dunklen Analyseflächen.
Das ist ein automatisierter Linux-/Tk-Prüfnachweis, keine native macOS-Abnahme
oder vollständige Barrierefreiheitszertifizierung.

Reiter-Folgeprüfung (0.9.8): 11 gezielte UX-Tests prüfen zusätzlich den Code-Start,
passive Analyseupdates, Markieren/Kopieren, Scrollposition, Tastaturwechsel und
die inline angeordneten Aktionen. Beispielbilder wurden aus den echten Tk-Widgets
mit dem gepinnten Linux-Binary und einer lokalen PTY-Testinstanz gerendert.
Der gezeigte Beispielcommand blieb dabei unfreigegeben und wurde nicht ausgeführt.

Kompaktlayout-Folgeprüfung (0.9.9): 13 UX-Tests, 10 Integrations-/Einstellungstests
mit echtem Linux-Binary, 60 Risiko-Tests, 42 allgemeine GUI-Tests, 49 Selbsttests
und der Versionskonsistenztest bestanden. Geprüft wurden insbesondere die
Mehrfachauswahl ohne automatisches Schließen, getrennt gespeicherte Tooloptionen,
Ausblenden deaktivierter Reiter, Ampel/Score/Zeichenanzahl sowie Freigabeaktionen
bei 960×560 und 1360×850. Der Codebereich hat in den gerenderten Beispielen
345 bzw. 635 Pixel Höhe. Die Bilder für Code, Auswahl, Befund und Technik stammen
aus der aktuellen Anwendung mit sh-guard 0.1.10; der Beispielcommand wurde
analysiert, aber nicht freigegeben oder ausgeführt.

Einrichtungs-Folgeprüfung (0.9.10): 15 UX-Tests, 11 Integrations-/Einstellungstests,
60 Risiko-Tests, 42 allgemeine GUI-Tests und der Versionskonsistenztest bestanden.
Die Tests prüfen insbesondere ausdrückliche Installationsentscheidungen direkt
im Reiter, veraltete Klicks aus früheren Aktivierungen, Einstellungen ohne
Aktivierung, erneute Initialisierung und gespeicherte Aktivierung bei fehlendem
Tool. Echte Tk-Renderings zeigen die erste Aktivierung ohne vorhandenes Binary
bei 1360×850 und 960×560 sowie die Zahnräder im Review-Set. Dabei wurde kein
Download bestätigt und kein Beispielcommand ausgeführt.
