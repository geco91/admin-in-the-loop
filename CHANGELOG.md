# Changelog

## 0.9.34 — Terminalziel und AI-Anbieter im Hauptfenster

- Beide Seitenleisten öffnen ihre Einstellungen direkt unter dem Logo. Links stehen das Befehlsziel und im Terminalmodus der Ausgabebereich.
- Der Terminaldialog speichert das finale Return für neue Befehle und den optionalen Start neuer Terminals im Home-Verzeichnis.
- Beim Start einer Shell bindet ein kleiner Python-Prozess Bash direkt an das Pseudoterminal. Das verkürzt den Weg zum ersten Prompt auf langsamen Systemen.
- Rechts ist ChatGPT Secure MCP als AI-Anbieter ausgewählt. Bei der Auswahl von Local AI erscheint „Noch nicht implementiert.“

## 0.9.33 — Gemeinsame Bridge-Verbindung und Standortwahl pro Dienst

- Das Zahnrad unten links öffnet die Einrichtung oder Verwaltung der externen Bridge. Eine gespeicherte Kopplung bleibt auch offline sichtbar.
- sh-guard und Secure MCP Tunnel lassen sich unabhängig voneinander lokal oder auf der gekoppelten Bridge betreiben. Die Erstkopplung führt zum gewählten Dienst zurück.
- Die Standortwahl liegt in einer eigenen Einstellungsdatei. Bestehende Kopplungen und empfängergebundene Freigaben bleiben lesbar.

## 0.9.32 — Rückwechsel vom Bridge-Testbranch zu main

- `update geco91 main` unterstützt den Rückwechsel zu 0.9.30 auch mit einer in
  0.9.31 gespeicherten sh-guard-Aktivierung. Der Empfänger einer Remote-Freigabe
  wird separat gespeichert. Die stabile Version kann die gemeinsamen Einstellungen
  lesen und bearbeiten, beim späteren Wechsel auf den Testbranch gilt weiterhin
  die Freigabe für denselben Empfänger.

## 0.9.31 — sh-guard auf der Bridge

- Eine lokale oder gekoppelte Bridge lädt, prüft und installiert sh-guard und
  analysiert den ausgewählten Befehlsstand über ihre authentifizierte Controller-API.
- Die Dienstverwaltung zeigt den Standort im Einstellungsreiter, als Unterfenster
  und auf dem Bridge-Rechner mit `--bridge --gui`. Eine lokale Aktivierung aus
  früheren Versionen gilt für die lokale Bridge. Eine Remote-Analyse wird für
  ihren konkreten Empfänger aktiviert.
- Im Verwaltungsfenster zeigt **Allgemein** Standort und Verbindung. Auf der
  Bridge lässt sich hier das Hauptprogramm koppeln. **Dienste** öffnet die
  Installations- und Prüfaktionen für sh-guard.

## 0.9.30 — Zuletzt geteilte Ausgabe einmalig abholen

- Der allgemeine Abruf bietet ausschließlich die jüngste Freigabe an, solange sie
  aussteht. Ältere offene Freigaben sind bis zum Ablauf gezielt per Ausgabe- oder
  Vorschlags-ID abrufbar.
- Nach dem Schreiben der MCP-Antwort entfernt die Bridge den Text aus der Datenbank.
  Der normale Abruf funktioniert damit auch in Connectors ohne separates ACK-Tool.
  Metadaten für den Vorschlagsstatus und idempotente Upload-Wiederholungen verfallen
  wie zuvor. Beim Update werden bereits bestätigte Texte bereinigt.
- Ein erkannter Schreibfehler lässt die Freigabe abrufbar. Gleichzeitige Abrufe
  reservieren dieselbe Ausgabe für höchstens eine laufende Antwort. Event-ACKs
  bestätigen weiterhin ausschließlich die Benachrichtigung.
- UI und Bridge melden 0.9.30.

## 0.9.29 — Freigegebenen Output ausdrücklich als gelesen bestätigen

- `get_approved_output` liefert Text plus Empfangsbeleg; `acknowledge_output`
  bestätigt ihn idempotent. Erst diese Lese-ACK entfernt gebundene und ungebundene
  Ausgaben aus dem gemeinsamen Ungelesen-Abruf. Inhalte bleiben bis zur bisherigen
  Aufbewahrungsgrenze erhalten und per `output_id` oder `submission_id` wieder lesbar.
- Event-/Webhook-ACKs bestätigen nur die Verfügbarkeitsmeldung. Sie konsumieren den
  Text nicht; nach Lese-ACK werden spätere Event-Jobs übersprungen.
- Empfangsbelege sind an AI-Principal und Chatbindungs-Generation gebunden. Clients
  mit gleicher gültiger Chatbindung teilen ein Postfach; andere Clients können
  keine fremden Belege zum Konsumieren verwenden. ACK prüft die Autorisierung atomar.
- Abgelaufene, entfernte und Legacy-Cursor führen mit `cursor_reset` zu einem neuen
  Scan unbestätigter Ausgaben. Cursor anderer Principals/Abfragen bleiben ungültig
  und geben einen ausdrücklichen Hinweis zum Wiederholen ohne diesen Cursor.
- SQLite erhält einen Bestätigungszeitpunkt, keine pauschale Löschung oder geratenen
  Lesebestätigungen für Altbestand. Clients müssen den aktualisierten ACK-Ablauf verwenden.
- UI und Bridge: 0.9.29. Die funktionierende Qubes-Wiederherstellung bleibt erhalten.

## 0.9.28 — Sicherer lokaler Ausweichport bei Qubes-Portkonflikten

- Bei `qrexec_port_conflict` versucht die gespeicherte Qubes-Wiederherstellung
  einmal einen freien lokalen Port. Ziel-Qube und Remote-Port bleiben unverändert;
  der vorhandene Listener wird weder übernommen noch beendet. Bei unsicherer
  Prozesseigentümerschaft gibt es diesen Fallback nicht.
- Der alternative Port gilt nur für die TCP-Verbindung dieser Sitzung. Gespeicherte
  URL, HTTP-Host, TLS-Hostname und Pin sowie Controller-/Chatbindung bleiben gleich.
  Die bestehenden TLS-Prüfungen erfolgen weiterhin vor dem Senden von Zugangsdaten.
- Ein gesunder eigener Ausweich-Forwarder wird bei erneutem Retry/Prüfen wiederverwendet.
  Ein zweiter Portkonflikt beendet den Fallback, statt beliebig weitere Ports zu suchen.
- UI und Bridge melden 0.9.28. Die native Qubes-Prüfung bleibt ausstehend;
  die konkrete Identität des belegenden Prozesses wird nicht behauptet.

## 0.9.27 — Dual-Stack-Listener und konkrete Recovery-Fehler

- Eigene IPv6-/Dual-Stack-Listener werden anhand ihres Socket-Inodes und derselben
  verifizierten Prozessidentität erkannt. 0.9.26 konnte sie trotz erreichbarem
  IPv4-Loopback fälschlich als Portkonflikt ablehnen und nach Versuch 1 stoppen.
- Echte oder nicht zugeordnete Portbelegungen bleiben geschützt; konkurrierende
  IPv4-Listener werden nicht aufgrund eines eigenen IPv6-Sockets übernommen.
- Die kurze Recovery-Statuszeile zeigt den festen Fehlercode. Der ausführliche
  Fehlergrund steht vor der allgemeinen Anleitung. Gespeicherte Angaben werden
  ausdrücklich nicht als Nachweis einer laufenden oder erreichbaren Bridge dargestellt.
- UI und Bridge melden 0.9.27. Kopplung, TLS-Pins und die Retry-Grenzen bleiben
  erhalten. Ob dieser reproduzierte Codefehler den Gerätetest erklärt, ist offen.

## 0.9.26 — Begrenzte Wiederaufnahme unterbrochener Qubes-Verbindungen

- Nach abgebrochenem Launcher, fehlendem eigenen Listener oder vorübergehendem
  Verbindungsfehler höchstens zwei zusätzliche Wiederaufnahmen mit kurzer Wartezeit.
  Jeder bewusste Retry erhält ein neues Budget; Erfolg setzt das Budget nicht zurück.
- Recovery erkennt beendete Vorbereitung und begrenzt Vorbereitung/Verbindungsaufbau
  auf 30 Sekunden pro Versuch. Während noch bereinigt wird, startet kein zweiter
  Forwarder. Trennen oder bewusstes Stoppen beendet anstehende Wiederholungen.
- Ein gesunder Forwarder benötigt einen eigenen Listener. Prozesse werden über
  beobachtete Kernel-Startzeit, Session, Gruppe und UID zugeordnet; Signale gehen
  gezielt über geprüfte pidfds. Namen, belegte Ports und alte PIDs reichen nicht.
- Unsichere Eigentümerschaft, fremde Listener, Pin- und Authentifizierungsfehler
  stoppen die Automatik. Gespeicherte Kopplung und TLS-Pins bleiben erhalten;
  Einrichtung/Startanleitung bzw. eine bekannte HTTPS-Bridge bleiben manuelle Wege.
- UI und Bridge melden 0.9.26. Deutsch/Englisch aus 0.9.25 bleiben erhalten.
  Die Ursache einer externen Meldung „Killed“ ist damit nicht diagnostiziert;
  ein beendeter Gesamtprozess benötigt einen erneuten manuellen App-Start.

## 0.9.25 — Deutsche/englische UI und orange wartende Vorschläge

- Ein wartender Command-Vorschlag bei bereits offener Command-Review erscheint
  hellorange mit dunkler Schrift; die bestehende Reviewsperre bleibt erhalten.
- Hauptfenster, Verbindungsassistent, Prüfdetails, Meldungen und Kontextmenüs
  unterstützen Deutsch und Englisch. Deutsche Systemlocale wählt Deutsch,
  andere Locales Englisch (`LC_ALL` vor `LC_MESSAGES` vor `LANG`).
- Die Sprachwahl unten im Fenster speichert Systemstandard, Deutsch oder English
  in den vorhandenen Einstellungen und gilt ab dem nächsten App-Start.
  Commands, Ausgaben, IDs und Freigaben werden nicht übersetzt oder verändert.
- Der Übersetzungskatalog bleibt für Einzeldatei-Updates eingebettet.
  App und Bridge: 0.9.25. [Prüfnachweis](doc/RELEASE_V0.9.25.md).

## 0.9.24 — Wiederherstellung sichtbar erneut starten

- Jeder Wiederherstellungsversuch zeigt eine neue Versuchsnummer und seinen
  Zustand, auch wenn derselbe Fehler sofort wieder auftritt. Der Startklick
  zeigt vor der Vorbereitung eine unmittelbare Rückmeldung.
- „Verbindung prüfen“ darf eine passende gespeicherte Verbindung nach einem
  fehlgeschlagenen Versuch erneut authentifiziert öffnen. `BLOCKED` wird nicht
  mehr als laufender Verbindungsaufbau behandelt; aktive Versuche bleiben geschützt.
- Enthält die direkte Chat-Code-Erneuerung in der AI/MCP-Leiste, die sichtbare
  Fehleranzeige im Wiederherstellungsbereich und präzisierte Bridge-/MCP-Logs
  aus dem vorherigen Main-Stand. UI und eingebettete Bridge melden beide 0.9.24.

## 0.9.23 — Zusätzliche Titelzeile entfernen

- Die zusätzliche Überschrift „Admin in the Loop“ innerhalb des Hauptfensters
  entfällt. Die drei Arbeitsbereiche nutzen die frei gewordene Höhe; der native
  Fenstertitel mit Versionsnummer bleibt erhalten.
- Geprüft mit den bestehenden Layout-/Einzeldatei-GUI-Fällen bei mehreren
  Fensterbreiten und beiden Farbschemata. [Prüfnachweis](doc/RELEASE_V0.9.23.md).

## 0.9.22 — Gemeinsamer Zwischenablage-/Terminalmodus

- Ohne Terminal sind Rückgabequelle und AI-Ziel standardmäßig Zwischenablage;
  Vorschläge lassen sich ohne Terminal übernehmen und prüfen. Nach „Terminal
  bereit“ sind Terminal und „Letzter Command“ der Standard für neue Vorgänge.
  Bei Terminaltrennung wird wieder Zwischenablage gewählt.
- Die Auswahl „Ausgabebereich → Zwischenablage“ schaltet jetzt auch das AI-Ziel
  um. Zuvor blieb dieses unabhängig auf Terminal stehen. Im Zwischenablage-Modus
  werden Vorschläge ausschließlich kopiert; der Terminalfreigabeweg ist gesperrt.
- Manuelles Umschalten eines offenen Commands erzeugt einen neuen Review mit
  neuer Revision und passender Return-Behandlung. Submission-Zuordnung und
  Ablaufzeit bleiben erhalten, alte Freigaben werden ungültig. Ein automatischer
  Standardwechsel beim Shellstart ändert kein bereits festgehaltenes Kopierziel.
- Modusänderungen während Übernahme oder Zustellung sind gesperrt. Ohne erste
  Command-Freigabe erklärt „Letzter Command“ die Situation; manuelle Ausgaben
  können weiterhin über Zeilenbereiche geprüft werden.

Prüfnachweis und Grenzen: [v0.9.22](doc/RELEASE_V0.9.22.md).

## 0.9.21 — Zwischenablage als Ziel für AI-Vorschläge

- Rechts ist „Ziel für AI-Vorschläge“ mit Terminal oder Zwischenablage wählbar,
  unabhängig von der Rückgabequelle links. Ziel Zwischenablage ermöglicht die
  Übernahme eines AI-Vorschlags ohne geöffnete Shell, mit Bearbeitung, vorhandenen
  Prüfreitern und ausdrücklichem Button „In Zwischenablage kopieren“.
- Das Ziel wird bei Übernahme fest gebunden und beim Bearbeiten erhalten.
  Während einer aktiven Prüfung oder Übernahme bleibt die Zielauswahl gesperrt.
  Kopieren ändert die Zwischenablage erst nach Freigabe, hängt kein finales
  Return an und bestätigt keine Terminalausführung. Schreibfehler erlauben
  einen erneuten Versuch; Pause und Bridge-/Ablaufbindung bleiben wirksam.
- Offene Terminalrückgaben und die Zuordnung früher ausgeführter Commands bleiben
  erhalten. Die vorhandene sh-guard-Prüfung arbeitet auch ohne Terminalsitzung.
  Die rechte Spalte ist für kleine Fenster kompakter angeordnet.

Prüfnachweis und Grenzen: [v0.9.21](doc/RELEASE_V0.9.21.md).

## 0.9.20 — Zwischenablage ohne Terminal und Tunnel-Start-Timeout beheben

- „Prüfen“ ist für die Quelle Zwischenablage auch ohne geöffnetes Terminal
  verfügbar. Bearbeiten, Byteansicht und ausdrückliche Rückgabe sind unabhängig
  von der Terminalsitzung; Bridge-Bindung, Pause und Übertragungssperren gelten
  weiter. Terminalausgaben und Commands benötigen weiterhin ihre lokale Sitzung.
- Korrektur einer Regression aus 0.9.18: Der offizielle Tunnel-Client v0.0.15
  lässt `http_status` nach erfolgreichem Poll weg. Die Bridge verlangte dieses
  Feld irrtümlich auch bei Erfolg und konnte bis zum Start-Timeout warten.
  Das fehlende Feld wird jetzt gemäß Upstream-Vertrag akzeptiert; frischer
  Erfolg, Status „ok“, keine Fehlerkategorie und null laufende Fehler sind
  weiterhin erforderlich. Explizite HTTP-Fehler bleiben gesperrt.
- Für die Tunnelkorrektur auch die Bridge aktualisieren und mit unverändertem
  State-Verzeichnis neu starten. Keine neue Kopplung oder Key-Eingabe nötig.

Prüfnachweis und Grenzen: [v0.9.20](doc/RELEASE_V0.9.20.md).

## 0.9.19 — Zwischenablage zur Rückgabe prüfen

- Links im Ausgabebereich ist „Zwischenablage“ als weitere Quelle verfügbar.
  Erst „Prüfen“ liest den aktuellen Text; zentrale Prüfung, Bearbeitung und
  ausdrückliche Freigabe verwenden den bestehenden Rückgabeablauf.
- Die Quelle bleibt beim Bearbeiten erkennbar. Standardmäßig unabhängige
  Beobachtung, keine automatische Zuordnung zum letzten Command. Eine offene
  Terminalrückgabe wird weder durch Freigeben noch Verwerfen geschlossen.
- Aktive Prüfungen werden nicht überschrieben. Leere oder nicht verfügbare
  Text-Zwischenablage erhält einen Hinweis; bestehende Größen-/Zeichengrenzen,
  Sitzungsbindung und Freigabesperren gelten weiterhin. Keine Terminalausführung.

Prüfnachweis und Grenzen: [v0.9.19](doc/RELEASE_V0.9.19.md).

## 0.9.18 — Tunnel nach Controller-Kontakt frisch prüfen

- Der authentifizierte Controller-Confirm stößt im Hintergrund einen frischen
  Healthcheck des Bridge-eigenen Tunnels an. Ein gesunder Client bleibt bestehen;
  bei behebbaren Fehlern gibt es einen begrenzten Wiederanlauf mit der gespeicherten
  Konfiguration, maximal einmal innerhalb von 30 Sekunden. Keine neue Kopplung,
  kein Auslesen oder Zurückgeben des Runtime Keys und keine Terminalaktion.
- Ein früheres „connected“ wird weiter geprüft. Der Control-Plane-Erfolg muss
  aktuell sein (höchstens 90 Sekunden alt), fehlerfrei und zu einem erfolgreichen
  HTTP-Status gehören. Der Controller beobachtet den Remote-Tunnel nach dem
  ersten Erfolg weiter; GET-Statusabfragen starten selbst keinen Client.
- Key-/Rechtefehler, nicht gefundene Tunnel, Provider-Drosselung und nicht
  unterstützte Clients lösen keinen solchen Wiederanlauf aus. Abbruch/Beenden
  verhindert einen verspäteten Start. Bereits laufender Start und wiederholte
  Bestätigungen erzeugen keine parallelen Clients.
- Die Bridge muss für diese Änderung ebenfalls aktualisiert und mit bestehendem
  State-Verzeichnis neu gestartet werden. Tunnelstatus ist weiterhin kein Beleg
  für geladene Werkzeuge in einem konkreten Chat.

Prüfnachweis und Bezug: [v0.9.18](doc/RELEASE_V0.9.18.md).

## 0.9.17 — Pfeiltasten-History im Terminal

- Das interaktive Terminal nutzt die bestehende Bash-/Readline-History: Pfeil
  hoch ruft frühere Befehle auf, Pfeil runter geht zur aktuellen Eingabe zurück.
  Aufrufen führt nichts aus; erst Enter startet die Zeile als manuelle Eingabe.
- Maximal 1000 Einträge pro Shell im RAM. Kein Lesen oder Schreiben der
  persönlichen Historydatei. Neue Terminals starten leer; frühere Eingaben aus
  Versionen ohne History lassen sich nicht nachträglich wiederherstellen.
- Manuelle und lokal freigegebene Befehle teilen die Shell-History. Direkt
  aufeinanderfolgende Duplikate und Zeilen mit führendem Leerzeichen werden
  ausgelassen. Bash-History-Ersetzung ist ausgeschaltet, damit etwa `!!` einen
  freigegebenen Commandtext nicht umschreibt. Keine zusätzlichen Abhängigkeiten.

Prüfnachweis und Bezug: [v0.9.17](doc/RELEASE_V0.9.17.md).

## 0.9.16 — Sperrgrund für „Prüfen“ sichtbar machen

- Reproduziert: Bridge/Tunnel verbunden und Vorschlag vorhanden, aber noch keine
  lokale Terminalsitzung. Die bestehende Sitzungsbindung sperrt dann „Prüfen“;
  v0.9.15 zeigte dafür keinen Hinweis beim Vorschlag an.
- Der Vorschlagsstatus nennt jetzt den nächsten Schritt: Terminal links öffnen,
  Terminalstart abwarten, aktiven Commandreview freigeben/verwerfen oder laufende
  Übernahme/Übertragung abschließen. Ein geparkter Vorschlag wird als solcher
  angezeigt. Grün bedeutet prüfbar; gesperrte Vorschläge sind orange markiert.
- Review-, Übernahme- und Freigabesperren bleiben bestehen. Das Öffnen eines
  Terminals oder eines Reviews führt keinen vorgeschlagenen Command aus.

Gezielte Prüfung und Grenzen: [v0.9.16](doc/RELEASE_V0.9.16.md).

## 0.9.15 — Einzeldatei-Download und ausdrückliches Selbstupdate

- `update` bzw. `--update` ohne Zusatz verwendet GeektankLabs/admin-in-the-loop,
  Branch main. Ein GitHub-Nutzername wählt dessen gleichnamiges Repository;
  ein zweiter Parameter wählt den Branch, einschließlich Namen mit Schrägstrich.
- Download ausschließlich per HTTPS aus der angegebenen öffentlichen GitHub-Quelle.
  Syntax, App-/Bridge-Identität und Version werden ohne Ausführung des Downloads
  geprüft. Die einzelne Anwendungsdatei wird atomar ersetzt, vorheriger Inhalt
  als `.py.bak` gesichert; Einstellungen bleiben erhalten. Kein automatischer
  App-/Bridge-Neustart und kein Update durch eingegangene AI-Vorschläge.
- Ältere Versionsnummern werden nur bei ausdrücklich angegebenem Branch erlaubt.
  Ungültige Quellen, veränderte lokale Dateien, Symlinks und fehlerhafte Downloads
  überschreiben die Installation nicht. Keine zusätzlichen Python-Abhängigkeiten.
- Download- und Update-Anleitung für den veröffentlichten Fork ergänzt;
  der Originalstand kann davon abweichen. Quelle/Branch werden nicht gespeichert.

Gezielte Prüfung: 11 neue Updatefälle in der bestehenden lokalen Testsuite
bestanden, einschließlich Rollback-Sicherung, Fehlerfällen und CLI-Varianten.
Gesamtnachweis und Grenzen: [v0.9.15](doc/RELEASE_V0.9.15.md).

## 0.9.14 — Prüfauswahl in den passenden Seitenbereichen

- Links im Terminalbereich „Rückgabeprüfung“, rechts im AI-Bereich „Befehlsprüfung“;
  die bisherige Auswahlleiste über dem Code entfällt. Beide Mehrfachauswahlen
  behalten Zahnräder und öffnen vollständig innerhalb des Appfensters.
- Zeichenprüfung und Einstellungen sind pro Richtung unabhängig gespeichert.
  Bisherige globale Aktivierung wird für beide Richtungen übernommen. sh-guard
  steht nur für Befehle bereit; die Ausgabeauswahl benennt den noch fehlenden
  Inhalts-/Datenschutzscan ausdrücklich.
- Die Mitte zeigt Code/Ausgabe und die passenden aktiven Prüfreiter mit Ampel
  und Befundzahl. Ein neuer Snapshot startet im Hauptreiter. Die Codefläche
  gewinnt im gerenderten Beispiel bei beiden Fenstergrößen 34 Pixel Höhe.

Prüfung: 18 UX-Tests, 12 Integrations-/Einstellungstests mit echtem sh-guard,
45 allgemeine GUI-Tests, 49 Selbsttests und der Versionstest bestanden.
[Echte Linux-Renderings](doc/REVIEW_LAYOUT.md) mit analysiertem, nicht ausgeführtem
Pipelinebeispiel und tatsächlicher Ausgabe einer harmlosen lokalen PTY-Testinstanz.
Native Qubes-/macOS-Darstellung wurde nicht geprüft.

## 0.9.13 — Kopieren und Einfügen per Maus

- Ein gemeinsames Kontextmenü deckt Eingabefelder, Comboboxen, Spinboxen und
  native Textfelder ab, einschließlich neu geöffneter Einrichtungsdialoge.
  Schreibgeschützte Felder erlauben Kopieren, sperren aber Einfügen.
- Der Code-/Ausgabereview bietet „Einfügen“ über den bestehenden Bearbeitungsdialog.
  Auswahl bzw. Einfügeposition werden auf den Originaltext abgebildet, auch bei
  Unicode-/Codepointnotation. Erst „Übernehmen“ ändert den Review; keine Freigabe
  oder Terminalübertragung durch diese Aktion.
- Der Linux-Launcher verwendet XFCE Terminal mit nativem Rechtsklick-Copy/Paste.
  Debian-Voraussetzung ist jetzt `xfce4-terminal`; macOS verwendet Terminal.app.
  Terminal-Paste bleibt eine manuelle Terminaleingabe.

Prüfung: 45 GUI-Tests, 15 sh-guard-UX-Tests und der Versionstest bestanden.
Native XFCE-Mausaktionen Copy/Paste wurden unter Xvfb zusätzlich ausgeführt;
Code-Paste, Unicode-Auswahl und Übernehmen wurden in bestehenden GUI-Tests geprüft.
Einfügen im Terminal ist manuelle Eingabe; Terminal.app wurde nicht nativ geprüft.

## 0.9.12 — Terminalausgabe erneut prüfen und zurückgeben

- „Prüfen“ lädt auch bei bereits offener Rückgabeprüfung einen frischen
  Ausgabesnapshot; der Klick wird nicht mehr ignoriert. Noch nicht freigegebene
  Bearbeitungen werden durch diesen ausdrücklich angeforderten Snapshot ersetzt.
- Nach einer bestätigten Rückgabe kann der bestehende Ausgabeauswahlweg späteren
  Output desselben Commands erneut zur Prüfung und Freigabe laden. Submission-
  Zuordnung und eigenständige Rückgabe-IDs bleiben erhalten; keine Neuausführung.
- Ein Regressionstest mit bestehender Tk-/PTY-/MCP-Testinstanz prüft zwei lokal
  bearbeitete Rückgaben eines wartenden Commands, genau eine Ausführung und
  unveränderte Sperren während einer laufenden Rückgabeübertragung.

Prüfung: 4 GUI-Stage-Tests und 21 Core-/Roundtrip-/Versionstests bestanden.
Ein bestehender externer ChatGPT-Work-Test wurde mangels Workspace übersprungen.

## 0.9.11 — Verbindung vereinfachen und beim Start wiederherstellen

- Gespeicherte Remote-/Qubes-Verbindungen werden beim App-Start mit bestehendem
  Pin und Controller-Zugang wiederverbunden. Die eigene Qrexec-Weiterleitung wird
  im Hintergrund vorbereitet; Abbruch verhindert ihre spätere Übernahme.
- Eine gespeicherte lokale Einrichtung startet wieder mit ihren Tunnelwerten.
  Wiederherstellung und Fehler werden sichtbar; neue Kopplung oder Chat-Code-
  Rotation sind davon getrennte bewusste Aktionen.
- Der Dialog zeigt Bridge, Secure Tunnel und Chatstatus dauerhaft getrennt.
  Navigation bleibt auch bei kleinen Fenstern außerhalb des scrollbaren Inhalts.
  Gespeicherte Verbindungen erhalten eine kurze Wiederherstellungsansicht.
- Qubes führt mit kürzeren Anweisungen durch fünf Schritte; Startbefehl-Kopieren
  berücksichtigt individuelle Ports. Technische Details, Verwaltung und Code-
  Rotation sind eingeklappt. Ein Tunnel allein gilt nicht als verifizierter AI-Chat.
- Zehn reproduzierbare Renderings mit expliziten Qubes-/Provider-Beispielzuständen
  dokumentieren die Seiten und Fehlerpfade in `doc/CONNECTION_UX.md`.

## 0.9.10 — Dienste im Prüfreiter einrichten

- Jeder verfügbare Eintrag im Review-Set hat ein Zahnrad mit „Einstellungen“.
  Einstellungen können auch ohne Aktivierung geöffnet werden.
- Die erste sh-guard-Aktivierung öffnet „Einrichtung & Einstellungen“ innerhalb
  des Dienstreiters. Downloadbestätigung, Fortschritt, erneute Initialisierung
  und Entfernen bleiben dort erreichbar; der separate Installationsdialog entfällt.
- Gespeicherte Aktivierungen werden beim Start erneut geprüft. Fehlt das Binary,
  zeigt der Reiter „Einrichtung nötig“ und wartet auf eine neue Installationsfreigabe.
  Passive Updates wechseln die gewählte Ansicht nicht.
- Die integrierte Zeichenprüfung erläutert ihre lokale Arbeitsweise und benötigt
  keine Verbindungsdaten. Das Zahnrad wird als Grafik unabhängig von Fontglyphen angezeigt.

## 0.9.9 — Kompakte Review-Auswahl und Statusreiter

- Eine einzeilige Mehrfachauswahl ersetzt den mehrzeiligen Review-Kopf.
  Nur aktive Prüfungen bekommen Reiter, jeweils mit Farbsignal und Score bzw.
  Zeichenanzahl. Code bleibt bei neuen Reviews die Hauptansicht.
- Befund, Technik, Installation und Wiederholungsaktionen liegen im sh-guard-Reiter.
  Unter dem Code bleibt die Freigabezeile mit der Return-Einstellung.
- „Zeichen & Bytes“ ist separat wählbar; seine Zeichenhinweise sind keine
  Risikopunkte. Ein Datenschutzscan für Terminalausgaben ist noch nicht verfügbar.
- Beide Prüfoptionen bleiben lokal gespeichert. Mehrfachauswahl, Fokus und
  kleine Fenster werden mit echten Tk-Widgets geprüft.

## 0.9.8 — Code als Hauptreiter

- Code, Befund und Technik liegen direkt in der mittleren Review-Fläche;
  das separate Analysefenster entfällt. Neue oder bearbeitete Snapshots öffnen
  den Code-Reiter, Terminalausgaben den entsprechend benannten Ausgabe-Reiter.
- Eintreffende Analyseergebnisse erhalten Reiterauswahl, Scrollposition und
  Textauswahl. Markierter Code lässt sich per Maus auswählen und kopieren;
  der Befund ist gezielt über Reiter oder Kontextmenü erreichbar.
- Ctrl+Tab wechselt die Reiter; Escape und „Zum Code“ führen zurück zur
  Hauptansicht. Technische Installationsaktionen stehen unter Technik.

## 0.9.7 — sh-guard UI/UX

- Deutsche Risikostufen mit Kurzbegründung, lesbarer Schrift und kontrastreicher
  Darstellung; Farbe ist nicht der einzige Hinweis auf den Befund.
- „Befund anzeigen“ öffnet zuerst eine verständliche Zusammenfassung mit
  Einzelbefehlen. JSON, Prüfsummen und Fehlercodes stehen separat unter „Technik“.
- Sichtbarer Fortschritt sowie direkte Wiederholungs-/Abbruchaktionen; die
  Installation erklärt Zweck, Downloadgröße und lokale Verarbeitung.
- Enter und Escape mit Fokus-Rückgabe geprüft; Aktionen bleiben auch im auf
  480×320 verkleinerten Dialog erreichbar. Hauptansicht bei 960×560 geprüft.
- Entfernen ist während laufender Arbeit und nach erfolgreicher Entfernung
  deaktiviert. Keine Änderung der menschlichen Transferfreigaben.

## 0.9.6 — sh-guard-Integration, 2026-10-18

- Optionalen AI→Terminal-Reviewer mit den offiziellen sh-guard-0.1.10-Archiven
  verbunden: Archiv-/Binary-Pins geprüft, Download nach Installationsbestätigung,
  nativer Versions-/Schema-Probelauf vor atomarer Installation.
- Aktivierung lokal speichern und nach Neustart die bestehende Installation
  prüfen; deaktivieren und laufende Vorbereitung auch bei Speicherfehlern abbrechen.
- HTTPS-Proxy/CONNECT mit unveränderter Zertifikatsprüfung unterstützen und
  Download-/Prüfphasen anzeigen.
- Gesamtbefund auch dann anzeigen, wenn sich Subcommands nicht verlässlich auf
  einzelne Textbereiche abbilden lassen; keine spekulativen Farbmarkierungen.
- Echte Linux-x86_64-Binary- und GUI-Integration geprüft; ARM/macOS-Archive auf
  Integrität geprüft, native Abnahme dieser Plattformen separat offen.
- Getrennte menschliche Freigaben bleiben erforderlich; keine Output-/PII-Analyse.

## 0.9.0 — 2026-10-04

Reguläre persönliche Testversion, lokal auf Main festgeschrieben; nicht
veröffentlicht und nicht getaggt. Basis ist der unabhängig geprüfte, kombinierte
Integrationsstand `6108390d927c9247fdf4627ef0bc2a1b345d901c`.

- Kurzer, vorlesbarer Chat-Code mit acht Zufallszeichen, getrennter Conversation-ID,
  24-h-Gültigkeit, persistentem Versuchsschutz, Rotation und permanenter AI-Anzeige.
- Generationgebundene Events/ACKs sowie atomare Limiterwrites und fail-closed
  Korruptionsprüfung; F1–F4 unabhängig geschlossen und lokal kombiniert geprüft.
- Konsolidierte stdlib-Bridge mit approved-output Events und kanonischem Pull-Fallback.
- Optionales lokales sh-guard-Plumbing einschließlich Review-UI integriert;
  standardmäßig OFF, alle realen Pins weiterhin `approved=False`.
- Die Hauptfenstertitelleiste zeigt die App-Version dynamisch aus der kanonischen
  MCP-Versionsmetadatenquelle.
- Die zentrale Command-/Output-Review-Fläche verwendet eine maßvoll kleinere
  Monospace-Schrift für mehr Übersicht bei großen Blöcken.
- Schwarzer Hintergrund und grüne Standardschrift im zentralen Review; Sonder-
  und Risikomarkierungen bleiben mit der dunklen Kontrastpalette unterscheidbar.

Operatorentscheidung vom 4. Oktober 2026, 23:06 Europe/Berlin: Der alleinige Tester
nimmt diesen Stand für persönliche Tests an; externe Vorab-Abnahmen sind kein
Versionsgate. Hosted-/Tunnelbinary-/native Prüfungen bleiben NOT_RUN beziehungsweise
separate Skips. Die Mac-Vorschau `cff53d8804935f7d58337264b00b5ebb6b0495e6` ist nicht
integriert. Keine Produktions-Pinfreigabe oder Änderung menschlicher Approvalgrenzen.
