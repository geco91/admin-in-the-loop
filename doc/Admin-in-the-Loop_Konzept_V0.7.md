# Admin in the Loop

## Konsolidiertes MVP-Konzept – fortgeschrieben auf MVP 0.8

**AI assists. Admin decides.**

AI-assisted terminal work, with you reviewing every command and choosing what output to share.

Stand: 30. September 2026, Europe/Berlin. Projekt: https://github.com/GeektankLabs/admin-in-the-loop

Fortschreibung 18. Oktober 2026: Für AI→Terminal ist die optionale lokale
sh-guard-Analyse in AITL 0.9.11 mit kompakter Review-Auswahl und Statusreitern direkt in der Review-Fläche integriert. Sie ergänzt den menschlichen Review;
Terminal→AI-Inhaltsanalyse/Redaction und automatische Freigaben sind weiterhin
nicht enthalten. Bedienung, Pinzulassung und plattformspezifische Prüfnachweise:
[SH_GUARD.md](SH_GUARD.md). Die übrigen MVP-0.8-Angaben behalten ihren historischen Bezug.

AITL 0.9.11 ergänzt automatische Wiederherstellung gespeicherter Bridge-Verbindungen
mit bestehender Vertrauensbindung und einen vereinfachten Verbindungsdialog.
Der Qubes-Ablauf mit Beispielbildern und klaren Prüfnachweisgrenzen steht in
[CONNECTION_UX.md](CONNECTION_UX.md).

Die vollständig gelesene V0.7 ist die jüngste mitgelieferte Konzeptrevision: Sie ersetzt ausdrücklich V0.3 bis V0.6. Diese Fortschreibung integriert den dokumentierten MVP-0.8-Stand und die statische Repository-Inventur in dieselbe maßgebliche Konzeptdatei. Der Quelldateiname bleibt zur Kontinuität erhalten; es gibt keine konkurrierende Konzeptfassung und keine Nachtragsrangfolge. Produktziel und übernommene Nutzerentscheidungen bleiben bestehen. Die importierten Produktdateien sind derzeit unversioniert; Git enthält bislang nur `LICENSE`. Eine Veröffentlichung ist weder nachgewiesen noch durch diese Konzeptarbeit beauftragt.

**Dokumentrollen:** Dieses Konzept ist die maßgebliche Produkt- und Konzeptreferenz. Alle aktive Implementierungs-, Validierungs- und Abnahmearbeit wird ausschließlich im Taskboard geführt; Ticketstatus und aktuelle Ausführungsplanung werden nicht aus Projektdateien abgeleitet. Die hier beschriebene Architektur und der Umsetzungsstand beziehen sich auf den dokumentierten MVP 0.8; eine mögliche Weiterentwicklung gilt nicht als beschlossen, solange sie nicht konzeptionell abgestimmt und hier abgebildet ist. „MVP 0.8“ bezeichnet vorhandene Implementierung beziehungsweise ausdrücklich zugeordnete historische Prüfnachweise, keine hier neu ausgeführten Tests. „Soll/offen“ beschreibt eine Produktanforderung oder den hier festgehaltenen Abnahmerahmen, nicht den aktuellen Ticketstatus. Dateien allein beweisen keine funktionierende Integration. Das verbundene lokale MVP ist implementiert; native Plattform-, echte Cloud- und Isolationsnachweise waren zum historischen Prüfstichtag teilweise offen. Es liegt keine Sicherheitsabnahme für kritische Infrastruktur vor. [TASKBOARD_PROPOSAL.md](TASKBOARD_PROPOSAL.md) und [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md) sind historische Planungs-/Evidenzreferenzen, keine aktiven Todo-Listen.

## 1. Ziel und Grenzen der Zusage

Admin in the Loop unterstützt den Austausch zwischen AI und einem gewöhnlichen administrativen Terminal. AI-Vorschläge landen in einer Inbox. Der Benutzer übernimmt einen Vorschlag bewusst in einen lokalen Review, prüft den finalen Inhalt und gibt genau diesen Transfer frei. In der Gegenrichtung wählt er Terminalausgabe aus, prüft sie und gibt ihre Übermittlung gesondert frei.

Die AI erhält keine Ausführungsfunktion und keine Funktion zum Auslesen des Terminals, lokaler Dateien oder Tastatureingaben. Nur die lokale Controller-Oberfläche kann einen AI-veranlassten Transfer in das Terminal autorisieren. Ein Netzwerkfeld, ein Skill oder ein fremder Status kann das nicht.

Die Zusage schützt die Übergabeentscheidung. Sie garantiert weder die Ungefährlichkeit eines freigegebenen Befehls noch die Unbedenklichkeit einer freigegebenen Ausgabe. Ein Befehl kann selbst Daten auslesen, über das Netz versenden oder spätere Aktionen installieren. Ein sichtbarer Review verhindert das nicht automatisch.

Keine autonome Bridge-Schleife: Jeder weitere AI-veranlasste Terminaltransfer und jeder neue Terminalupload brauchen eine neue lokale Freigabe. Bereits autorisierte Programme laufen unter den normalen Rechten der Shell weiter.

## 2. Übernommene Entscheidungen und neue Präzisierungen

| Thema | Konsolidierte Festlegung / Realitätsstand | Herkunft |
|---|---|---|
| Projektname | Admin in the Loop | Nutzerentscheidung |
| Auslieferung | Eine eigene Python-Datei als Controller-, Helfer- und Bridge-Entry-Point mit expliziten lokalen Laufzeitrollen | MCP-1, bei unveränderter Prozessgrenze |
| Plattformpriorität | Debian und macOS gleich wichtig; beide früh praktisch testen | Nutzerantwort in dieser Runde |
| Shell | Gewöhnliche interaktive Shell an einem kontrollierten Unix-PTY | Übernommen |
| GUI | Drei-Spalten-Tkinter-Controller und separates Systemterminal | V0.7-Architektur, MVP 0.8 lokal implementiert; native Plattformabnahme offen |
| Review | Inbox und Review getrennt; Inhalt wird nur durch lokale Benutzeraktion übernommen | Übernommen |
| Blöcke | Begrenzte mehrzeilige Vorschläge zulässig | Nutzerentscheidung |
| Finales Return | Sichtbarer lokaler Schalter; vor Review auf null oder genau eins normalisieren | Übernommen, Normalisierung präzisiert |
| Return-Erststart und Blöcke | Return beim Erststart an; danach gespeicherte Wahl. SINGLE/SMALL/MEDIUM/LARGE sind Komfortpräferenzen | MVP-0.8-Bedienstand; ersetzt die frühere Empfehlung „aus“ |
| Prompt | Heuristik, bei fehlender Erkennung zusätzliche ausdrückliche Bestätigung | Nutzerentscheidung |
| Mitschnitt | Ausgabe seit beobachtetem Transferereignis, keine exakten Befehlsgrenzen | Übernommen, zeitliche Grenze präzisiert |
| Transport | Controller eröffnet HTTPS-Long-Polling; keine Bridge-Callbacks | Nutzerentscheidung |
| MCP und Tunnel | Vier rollenbegrenzte MCP-Tools; separat installierter offizieller OpenAI-Tunnel-Client | MVP 0.8 implementiert, echter Provider-Round-Trip offen |
| Bridge-Identität | Selbstsigniertes Zertifikat; SHA-256 des SPKI öffentlich vergleichen und pinnen | Übernommen, Format präzisiert |
| Kopplung | Abtippbarer Kurzzeitcode; anschließend individueller langer Schlüssel | Übernommen, Zustände und Limits präzisiert |
| Isolation | Lokaler Komfortmodus; getrenntes Qube/Gateway für kritische Nutzung | Übernommen |
| Guards | Optionale lokale sh-guard-Commandanalyse; kein Ersatz menschlicher Freigabe, keine Output-/PII-Analyse | Beauftragter Ausbau vom 18. Oktober 2026; ersetzt den früheren reinen Erweiterungspunkt |

Das Fensterkonzept weicht von der zuletzt bevorzugten eingebetteten V0.6-Variante ab. Grund ist die jetzt ausdrücklich gleich hohe Priorität beider Plattformen bei knappem Budget. Der Benutzer hatte ein separat positioniertes normales Terminal als ursprüngliches Wunschbild genannt; die neue Empfehlung greift dieses wieder auf, mit kontrolliertem PTY-Helfer statt fremdem Terminalzugriff.

Ein eingebettetes Terminal bleibt außerhalb dieses MVP. GTK/VTE beziehungsweise ein vergleichbarer macOS-Baustein sind nur bedingte spätere Alternativen bei geändertem Fensterwunsch, keine offenen Implementierungsaufträge. Automatische Fensteranordnung ist ebenfalls nicht Bestandteil der aktuellen Umsetzung.

## 3. Umfang in drei überprüfbaren Etappen

**P0: Machbarkeitsprototyp.** Eine Python-Datei startet eine Shell am PTY, prüft Mitschnitt und Eingaben sowie die flüchtige Review-/Freigabelogik. Feste lokale Testvorschläge ersetzen die AI. Kernprüfungen laufen ohne GUI; anschließend werden Controllerfenster und normale Terminalsitzung auf Debian und macOS zusammen betrieben.

**P1: Offline-MVP.** Inbox mit bewusst importierten Testvorschlägen, beide Review-Richtungen, mehrzeilige Blöcke, Return-Schalter, weiche Prompt-Erkennung mit Override, Ausgabebereiche und konservative Fehlerbehandlung. Kein echter MCP nötig. Lokaler Testimport ist keine automatische Dateilesefähigkeit der AI.

**P2: Verbundenes MVP.** Rollenbegrenzte Bridge, Long-Polling, lokaler Sidecar, verifizierte Remote-Kopplung, Outputzustellung und ein Orchestrator-Skill. Vollständiger Round Trip mit einer bekannten Testshell.

Diese Etappen strukturieren den MVP, sind aber kein neuer Auftrag zur Wiederimplementierung. P0, P1 und der lokale P2-Transportpfad sind im importierten MVP 0.8 vorhanden. Der vollständige lokale MCP→Review→Bash/PTY→Outputreview→MCP-Round-Trip ist historisch getestet, einschließlich eines realen Tunnel-Clients gegen eine simulierte Kontrollplattform. P0 oder P1 allein gelten weiterhin nicht als verbundenes MVP; ein lokaler P2-Nachweis ersetzt keine echte ChatGPT-/OpenAI- oder Plattformabnahme (§17).

Nicht enthalten: eigener beziehungsweise eingebetteter Vollterminalemulator, harte Prompt-Sperre, exakte Befehls-/Exitcode-Korrelation, automatische Output-/Secret-Erkennung/Redaction, automatische Commandfreigaben, autonome Agents, Multi-User-UI, Plugins, automatisch heruntergeladene Updates, große lokale Modelle, Qubes-RPC und zertifizierter Hochsicherheitsbetrieb. Ausschlüsse und lediglich bedingte Alternativen erzeugen keine MVP-Tasks.

## 4. Python Datei und Prozessarchitektur

Die einzige herunterladbare Python-Anwendungsdatei heißt `admin_in_the_loop.py`. Ohne Argument startet sie die Controller-GUI; `--gui` bleibt als explizite Form gültig. Weitere lokale Rollen sind Terminal-Helfer, Headless-Selbsttest und der explizite headless Bridge-Dienst (`--bridge`). Die Rolle wird lokal durch CLI beziehungsweise GUI-Launcher gewählt, niemals durch Netzwerkdaten.

Im historischen MVP 0.8 lag die Transportimplementierung im separaten Programm `aitl_bridge.py`; mit MCP-1 ist dessen Bridge-only-Code in `admin_in_the_loop.py` konsolidiert und das separate Programm entfällt. Bridge-Komponenten bleiben intern abgegrenzt und importieren keine Controller-/PTY-Fähigkeiten. Der offizielle Tunnel-Client ist ein drittes, extern installiertes Programm und nicht Teil des Repository-Pakets. Der Controller startet die lokale Bridge durch Selbstaufruf des kanonischen Dateipfads mit `--bridge`.

| Prozess | Aufgaben | Darf nicht erhalten |
|---|---|---|
| Controller | GUI, Inbox, Review, Freigabe, Netzclient, Konfiguration | Keine ungeprüfte Ausführung aus Metadaten |
| Terminal-Helfer | Einziger Leser/Schreiber des Shell-PTY; normale Terminalbedienung; begrenzter Outputmitschnitt | Bridge-/Tunnel-Credentials |
| Shell | Normale lokale und SSH-Administration | Automatisch vererbte Controller- oder Tunnel-Token |
| Bridge/MCP | Vorschläge und freigegebene Antworten transportieren | PTY, Eingabekanal, SSH-Agent, nicht freigegebener Mitschnitt |
| Tunnel-Client | Authentisierten MCP-Transport zur Kontrollplattform vermitteln | Controller-Token, Terminal-IPC, SSH-Agent, nicht freigegebener Mitschnitt |

Ein-Datei-Auslieferung heißt nicht Ein-Prozess-Architektur. Lokale Bridge und Controller bleiben getrennte Prozesse; die Shell läuft als Kind des Terminal-Helfers. Der Helfer gehört zur vom Controller gezielt gestarteten und gebundenen Sitzung; je nach Systemterminal ist er nicht zwingend dessen direkter Betriebssystem-Kindprozess.

**PTY-Eigentum:** Genau der Terminal-Helfer liest den Master des Shell-PTY. Der Controller liest eine begrenzte Kopie seines Outputstroms über lokale IPC. Zwei unabhängige Leser am selben Master sind verboten, weil ein Read konsumiert und keine Broadcast-Kopie liefert.

Das Systemterminal stellt den Helfer über seine eigene normale Terminalsitzung dar. Der Helfer leitet Eingaben vorübergehend zur inneren Shell und deren Ausgabe zum Systemterminal. Das ist eine gezielte PTY-Vermittlung, kein Zugriff auf beliebige offene Terminalfenster. Kein tmux und keine simulierten globalen Tastendrücke.

Dieser Helfer muss raw-Modus der äußeren Verbindung, Fenstergrößen, Signale, Job Control, EOF und Aufräumen korrekt behandeln. Die Umsetzung verwendet `openpty()` und eine frische interne Python-Kindrolle zum Binden des kontrollierenden TTY und Starten von Bash, kein Fork aus einem laufenden GUI-/Netzthread. Die Shell startet ohne Benutzerprofile oder persistente History; ab v0.9.17 besitzt das interaktive Terminal eine auf 1000 Einträge begrenzte Bash-History im RAM für Pfeil hoch/runter. Historydateien werden nicht importiert oder geschrieben; History-Ersetzung ist ausgeschaltet. Die vorhandene Alltagsshell-Konfiguration wird nicht übernommen. Linux-PTY-/Socket-/Job-Control-Nachweise liegen vor; macOS bleibt praktisch abzunehmen. Die Python-Warnung zu `pty.fork()` und höheren macOS-System-APIs bleibt ein technischer Hintergrund, kein Nachweis dieser Plattform. [Q1]

GUI und Headless-Tests verwenden denselben `AppCore`. Aktionen und `pump()` gehören auf denselben Ereignisthread. Der begrenzte Netzwerkworker liefert Daten/Ereignisse und kann weder `AppCore.approve()` noch die Terminalfreigabe auslösen. `AppCore()` ohne explizite Stores ist flüchtig. Diese privilegierte lokale Programmschnittstelle darf nicht als AI-Tool oder freigabeferner HTTP-Endpunkt veröffentlicht werden.

## 5. GUI und Installation auf beiden Plattformen

**Controller:** Tkinter aus der Python-Distribution. Plaintext-Review, feste lokale Labels, Inbox rechts, Outputauswahl links. Ein eigenes Fenster für die normale Terminalsitzung. Tkinter ist ein GUI-Toolkit und liefert keinen Terminalemulator. [Q2]

**Aktuelle Oberfläche mit UX-6:** Drei vollständig gerahmte Arbeitsbereiche mit ungefähr 1:2:1 Breitenverhältnis, verwandten Seitenflächen und primärem mittleren Review mit dauerhafter Überschrift; die historische MVP-0.8-Oberfläche verwendete 1:3:1. Der native Theme-Stil bleibt erhalten. Querformatiger Start, F11 für Vollbild und Esc zum Beenden des Vollbilds. Terminalstart und Verbindungseinstellungen stehen oben auf gleicher Höhe, beide Prüfen-Aktionen und Freigeben/Verwerfen auf gemeinsamer Footerhöhe. Die Seitenbereiche zeigen keine Inhaltsvorschau. Grün heißt „Vorschlag vorhanden“, Orange „Platz leer“, niemals „sicher“. Erst lokales Prüfen übernimmt den Vorschlag und leert den lokalen Platz. Der Review ist schreibgeschützt, weich umbrochen und nur vertikal scrollbar; Kontextbearbeitung beziehungsweise Ctrl+E/Cmd+E erzeugt einen neuen Snapshot. Linux-Tkinter-/xterm- und Layoutprüfungen unter Xvfb liegen vor; daraus folgt keine native Debian-/macOS-Sichtabnahme. Der konkrete Ticketplan und die Prüfnachweise stehen in [UX-6 Concept Plan](../planning/task-concepts/task_c7cbad1b-c8a8-5f3a-9eed-7a6a12c25075-concept-plan.md).

**Debian:** Unix, Python 3.11 oder neuer, Bash und grafische Sitzung. Debian 12/13 bleiben zu prüfende Zielreleases, keine bestätigte Kompatibilität. Der implementierte GUI-Launcher verwendet xterm; Controller-Pakete sind `python3`, `python3-tk`, `xterm`. Der Bridge-Modus benötigt `python3-aiohttp`, Remote-TLS auf den beteiligten Python-Seiten zusätzlich `python3-cryptography`. Der lokale Controller ohne Remote-TLS und seine 49 eingebetteten Tests verwenden die Standardbibliothek; Tests benötigen kein externes Testframework, die gesamte vernetzte Anwendung ist aber nicht paketfrei. Praktische Debian-Installation und Desktop-Abnahme sind offen. [Q3][Q4]

**macOS:** Python ab 3.11 mit funktionsfähigem Tkinter, vorzugsweise offizieller Python.org-Installer, wenn die vorhandene Installation nicht ausreicht. Terminal.app ist die erste Anzeige. Der Launcher über `/usr/bin/osascript` ist implementiert, seine native Abnahme einschließlich Automation-Berechtigungen, sicherer Argumentübergabe, PTY-Bedienung und Terminalfeatures ist offen. Netzwerkfunktionen benötigen die genannten Bibliotheken in der gewählten Python-Installation; ein eigener Installer wurde nicht gebaut. Eine Debian-Gateway-Bridge bleibt eine Betriebsalternative, kein Ersatz für die lokale macOS-Abnahme. [Q5]

Auf macOS wird keine globale Python-Installation umgebaut. Falls `cryptography` für P2 fehlt, ist eine einzelne dokumentierte Installation in einer kleinen lokalen Umgebung zulässig; alternativ wird ein gepflegter anderer Installationsweg geprüft. Python-Pakete lädt die App nicht automatisch. Der vereinfachte Local-Tunnel-Flow nutzt für einen fehlenden Client den offiziell unterstützten Homebrew-Weg; ohne Homebrew wird die Installationsvoraussetzung erklärt. Der Controller-/Terminalbetrieb selbst benötigt Homebrew nicht. Keine Installation nicht notarisierter macOS-ZIPs und kein Gatekeeper-Bypass.

Der Launcher verwendet feste Programmpfade und getrennte Argumente. Falls Terminal.app eine Shell-Startzeile benötigt, wird diese ausschließlich aus lokal kontrollierten, korrekt gequoteten Pfaden und Rollenparametern aufgebaut. Keine AI-Kommandos und keine Secrets in dieser Startzeile. Bei nicht bestandener Launcherprobe kann der Benutzer den festen lokalen Helferaufruf manuell in einem Terminal starten. Das ist ein kontrollierter Testfallback, keine zusätzliche AI-Ausführungsfunktion.

**Plattform-Abbruchkriterium:** Wenn der Helfer auf einer Plattform Shellbedienung, Resize oder Mitschnitt nicht zuverlässig abbildet, wird diese Technik dort nicht stillschweigend als abgenommen erklärt. Das Ergebnis wird vorgelegt; danach wird gegebenenfalls ein anderer Terminalbackend-Aufwand beschlossen. Der vorhandene Linux-Nachweis hebt dieses Kriterium für macOS/Debian nicht auf.

## 6. Lokale IPC und normale Bedienung

Für Controller↔Helfer wird ein Unix-Domain-Socket in einem frisch erzeugten lokalen Verzeichnis `0700` verwendet. Socket und eine einmalige Capability-Datei erhalten `0600`. Die Capability ist kryptografisch zufällig mit 256 Bit und wird nicht in Argumenten, Shellumgebung oder Logs geführt. Der Helfer liest sie beim gezielten Start; nach erfolgreicher Authentisierung wird die Datei entfernt. Fremde oder zweite Verbindungen werden abgewiesen.

IPC-Nachrichten sind längenbegrenzte Frames mit festem Typ und Schemaversion, nicht Pickle. Inhalt und Länge werden vor Verarbeitung geprüft. Der Bootstrap authentisiert beide Enden gegen dieselbe Capability mit frischen Nonces und HMAC-SHA-256; der geheime Wert selbst wird nicht als Argument oder Mitschnitt übertragen. Es gibt keinen Wiederaufbau mit alten Freigaben. Eine Sitzung hat eine lokale zufällige Instanz-ID; Nachrichten und Freigaben gelten nur für diese Instanz. Der Socket hat keine IP-Adresse und ist kein eingehender Netzwerkserver. Die Bridge bekommt weder Socketpfad noch Capability.

Der normale Terminaleingabestrom wird nur transient weitergeleitet. Er wird nicht protokolliert, nicht an den Controller kopiert und nicht zu Review-/Netzwerkdaten gemacht. Als Hinweis darf der Helfer ein inhaltsfreies Ereignis „Benutzereingabe beobachtet“ melden, um einen alten Prompt-Hinweis zu verwerfen. Er speichert dazu keine Tasten oder Passwortzeichen.

Ausgaben sind anders: Eingegebene Befehle können durch Shell-Echo im Output erscheinen und damit Teil des Mitschnitts werden. „Keine Tastaturaufzeichnung“ bedeutet deshalb nicht „keine Eingaben können jemals im Output sichtbar sein“. Bei deaktiviertem Echo soll der Passworttext dort nicht auftauchen; das wird separat getestet.

Der Helfer serialisiert lokale AI-Transfers und manuelle Eingaben. Ein freigegebener Block darf nicht durch gleichzeitige Tastatureingabe zerhackt werden. Während des kurzen Schreibens werden neue Eingaben nur begrenzt transient gehalten; Überlauf oder unklarer Zustand führen zu einer Störung und gesperrten weiteren AI-Transfers. Inhalte dieser Eingaben werden niemals geloggt.

Ein geschlossener Controller sperrt AI-Eingaben. Die manuelle Shell kann durch den weiterlaufenden Helfer benutzbar bleiben; ihr Mitschnitt wird dann eingestellt oder verworfen. Ein abgestürzter Helfer kann die PTY-Sitzung beenden – dieses Risiko wird beim Schließen transparent angezeigt. Eine Bridge-Störung allein beendet weder Helfer noch Shell.

**Realitätsstand:** Der Controller sendet beim Schließen ein Detach, der Helfer kann die manuelle Shell ohne weitere Controller-Aufzeichnung weiter bedienen; Bridge-Verlust entwertet gebundene Reviews. Eine ausdrückliche Bedienerklärung zum Unterschied zwischen Controller-Detach und Terminal-/Helfer-Ende ist in der aktuellen GUI nicht vorhanden. Sie bleibt eine offene Bedienanforderung, keine Behauptung, dass das Schließen des Controllers die Shell beendet.

## 7. Inbox und unveränderlicher Review

Neue AI-Vorschläge bleiben rechts in der Inbox. Sie stehlen keinen Fokus, ändern keinen Review und lösen keine Terminaleingabe aus. Der Benutzer wählt genau einen Vorschlag und übernimmt ihn auf die Review-Fläche.

Ein Review-Snapshot bindet Inhalt und dessen lokale Revision, Richtung, Terminalinstanz, Verbindungsgeneration, Konversation, Return-Modus und finale Bytes. Die lokale Freigabe verwendet diesen vorhandenen Snapshot; sie lädt nichts erneut vom Server. Jeder Inhalts-/Options-/Zielwechsel erzeugt eine neue Revision und entwertet ältere Freigaben.

Editieren ist vor Freigabe erlaubt. Der geänderte Inhalt wird als lokal bearbeitet gekennzeichnet und erneut vollständig angezeigt. Keine automatische Änderung nach dem Klick. Plaintext statt aktiver Markdown-/HTML-Darstellung; keine automatischen Link-, Datei- oder Bildaktionen.

Zeilenumbrüche werden zusätzlich zur Textdarstellung eindeutig markiert. Bidi-, Zero-Width- und andere unsichtbare Zeichen erhalten in der Review eine sichtbare Notation und gegebenenfalls einen Sperrgrund. Die Notation muss von tatsächlichem Nutztext unterscheidbar sein. Ein Detailmodus zeigt Codepoint und UTF-8-Bytes; diese Anzeige ist keine zusätzliche Payload.

**MVP 0.8:** Einzelne unveränderliche Reviews, sichtbare LF-Marker und eindeutige Codepoint-Notation sind implementiert. Anzeigezeichen werden nicht übertragen und dienen niemals zur Rekonstruktion eines Commands. Ein eigener Detailmodus für die exakten UTF-8-Bytes ist dagegen nicht implementiert; dieser Teil der ursprünglichen Review-Anforderung bleibt offen.

Die Zusage „What you see is what is sent“ umfasst den finalen Nutztext und die sichtbaren Transferoptionen. HTTP-JSON-Escaping und Terminalprotokoll-Framing werden als technische Hülle definiert und getrennt getestet. Shell-Expansionen und tatsächliche Auswirkungen sind davon nicht erfasst.

## 8. Mehrzeilige Blöcke und Return Semantik

Vor Erstellung des finalen Snapshots gilt weiterhin folgender Algorithmus; die Byte-Normalisierung ist in MVP 0.8 implementiert:

1. Gültiges UTF-8 verlangen; keine stillen Ersatzzeichen für fehlerhafte Befehlsbytes.
2. CRLF und einzelne CR als Zeilenumbruch auf LF normalisieren; Änderung im Review kenntlich machen.
3. Alle zusammenhängenden LF am Ende entfernen.
4. Bei eingeschaltetem „Finales Return senden“ genau ein LF anhängen; bei ausgeschaltetem keinen.
5. Interne LF unverändert erhalten, Zeichenregeln und Limits prüfen, Ergebnis vollständig anzeigen.

Diese Regel entfernt auch mehrere leere Abschlusszeilen. Im dokumentierten MVP 0.8 steht „Finales Return senden“ beim ersten Start **an**, danach gilt die ausdrücklich gespeicherte Benutzerwahl. Das ersetzt die frühere V0.7-Empfehlung „aus“, ohne die Freigaberegel zu verändern. Der Schalter erscheint ausschließlich bei Commands. Die Freigabeknöpfe heißen richtungsbezogen „Freigeben ins Terminal“ beziehungsweise „Freigeben an AI“; Return wird über den sichtbaren Schalter ausgewiesen. Fehlerhafte oder unsichere Präferenzen werden nicht still mit Return an zurückgesetzt.

SINGLE, SMALL, MEDIUM und LARGE sind persistente Blockgrößenpräferenzen, keine Berechtigungen. SINGLE bedeutet für die Orchestrierung einen Command; der Controller bewertet keine vollständige Shellsemantik. Der aktuelle Review zeigt die normalisierten finalen Bytes als sichere Textprojektion. Ein gesonderter Hinweis, dass CR/CRLF beziehungsweise Abschluss-LF gegenüber dem eingehenden Vorschlag normalisiert wurden, fehlt noch; die oben erhaltene Kennzeichnungsanforderung ist damit nur teilweise umgesetzt.

Bei einem mehrzeiligen Block können interne LF bereits frühere Zeilen ausführen, selbst wenn das finale Return ausgeschaltet ist. Dafür erscheint ein fester lokaler Hinweis. Die Präferenz ist keine generelle „nicht ausführen“-Option.

Zulässiger Befehlsinhalt: druckbarer UTF-8-Text, gewöhnliche Leerzeichen und LF. Gesperrt: NUL, ESC, TAB, sonstige C0-/C1-Steuerzeichen, Unicode-Format-/Richtungszeichen, Surrogates und weitere nicht dargestellte Zeilen-/Absatztrenner. Unicode wird nicht automatisch NFC-/NFKC-normalisiert. Nicht-ASCII-Zeichen werden in der Detailansicht kenntlich gemacht; eine vollständige Erkennung ähnlich aussehender Zeichen wird nicht zugesagt.

Heredocs und mehrzeilige Shellsyntax sind nur normale Textvorschläge; die App validiert ihre Shellsemantik nicht. Mehrzeilige Blöcke mit interaktiven Zwischenschritten können folgende Zeilen als Passwort, Editorbefehl oder Programmeingabe konsumieren. Der Skill soll deshalb interaktive Schritte separat vorschlagen. Die App arbeitet nicht selbstständig Zeile für Zeile ab und wartet dabei nicht automatisch auf Prompts.

Für den ersten Transferpfad werden die final geprüften Bytes direkt in das innere Shell-PTY geschrieben. Kein automatisch hinzugefügtes Bracketed-Paste-Framing und keine versteckten Markerkommandos. Manuelles Paste aus dem Systemterminal behält dessen normale Semantik. Eine spätere Paste-Option benötigt einen sichtbaren Modus und eigene Byte-/Wirkungstests.

## 9. Weiche Prompt Erkennung und Bestätigung

Es werden keine Shell-Startdateien verändert und kein dauerhafter Hook installiert. Die implementierte weiche Heuristik betrachtet den begrenzten Outputtail und typische Endzeichen `$`, `#` und `%`; beobachtete manuelle Eingabe macht den Zustand zunächst unbekannt. Lokales Echo oder Prozessgruppen sind keine sichere Shellbereitschaftserkennung. Eine spätere lokale Anpassung von Mustern darf keine AI-Einstellung werden; eine konfigurierbare Heuristik ist kein zusätzlicher MVP-Auftrag.

Positiver Zustand: „Prompt vermutlich erkannt“. Negativer oder nicht ausreichend aktueller Zustand: „Prompt nicht erkannt oder Zustand unbekannt“. Kein Zustand heißt „sicher bereit“. Ein Passwortprompt oder auffälliger TUI-Zustand zählt als unbekannt. Lokales Echo und Prozessgruppen sind nur Zusatzhinweise; bei SSH beweisen sie keine entfernte Shellbereitschaft.

Neue beobachtete Benutzereingabe, Terminalneustart, erkennbare Statusänderung oder unvollständiger Mitschnitt entwerten den letzten Hinweis. Direkt vor einem AI-Transfer wird die Heuristik im Helfer anhand des neuesten beobachteten Stands neu bewertet.

Der normale Review-Klick bleibt immer erforderlich. Bei unbekanntem Zustand öffnet sich zusätzlich: **„Shell-Prompt nicht erkannt. Trotzdem an diese Terminalsitzung senden?“** Er zeigt denselben gebundenen Snapshot und dieselbe Terminalinstanz. Bestätigung autorisiert ausschließlich diesen einen Transfer. Abbruch schreibt nichts. Eine zwischenzeitlich veränderte Sitzung oder Inhaltsrevision entwertet auch den Override. Der Override gilt nur für den Prompt-Hinweis: Authentisierung, Pinning, Sitzungsbindung, Zeichenregeln, Limits und einmalige Freigabe lassen sich damit nicht umgehen.

Es bleibt eine unvermeidbare zeitliche und semantische Unsicherheit: Auch ein sofort zuvor erkannter Prompt kann täuschen oder sich ändern. Die Heuristik ist eine testbare Bedienhilfe. Ein späterer harter Modus ist ein eigenes Vorhaben mit Shell-Integration und Nachweis der leeren Eingabezeile; nicht Bestandteil dieses MVP.

## 10. Mitschnitt und Outputauswahl

Der Helfer führt einen flüchtigen, begrenzten Mitschnitt ausschließlich der vom inneren PTY gelesenen Ausgabe. Jeder Chunk erhält einen monotonen lokalen Offset. Beim Beginn eines autorisierten Schreibens wird ein Transferereignis in derselben Ereignisreihenfolge eingetragen.

„Ausgabe seit Übertragung von Vorschlag #…“ bedeutet alle anschließend beobachteten Outputchunks bis zum vom Benutzer gewählten Endpunkt. Ausgabe kann vorher im Kernel gepuffert gewesen sein; der Marker ist deshalb eine Grenze der Beobachtung, kein exakter Erzeugungszeitpunkt. Hintergrundausgaben, Echo und spätere manuelle Arbeit sind eingeschlossen.

Die Funktion sucht nicht nach dem Befehlswortlaut. Sie behauptet keine Ausführung, keinen Exitcode und keine ausschließliche Kausalität. Verlorene Chunks und bereits verworfene frühere Pufferbereiche werden angezeigt; sie ergeben niemals stillschweigend einen vollständigen Output.

Mit einem normalen externen Terminal ist die aktuelle gerenderte Bildschirmansicht nicht portabel auslesbar. Für diesen MVP beziehen sich „letzte N Zeilen“ und der Outputreview deshalb auf die **bereinigte lokale Mitschnittprojektion**, nicht auf eine heimlich ausgelesene Systemterminalansicht. MVP 0.8 bietet Letzte Zeile, Seit letztem Command sowie Letzte 20/50/100/500. Der aktuelle UX-6-Startwert ist **Letzte 20**; nach dem ersten bestätigten Terminaltransfer folgt „Seit letztem Command“, spätere eigene Auswahl bleibt bestehen. Es gibt keine zusätzliche Mitschnittvorschau im Seitenbereich. Erst die bewusste Übernahme erzeugt den eingefrorenen mittleren Review; dessen Text kann lokal bearbeitet werden. Eine eigenständige manuelle Bereichsauswahl oder ein separater Clipboard-Import ist im MVP nicht zugesagt; es gibt kein Clipboard-Monitoring.

Die Mitschnittprojektion ist kein selbst entwickelter Terminalemulator. Der implementierte begrenzte streamingfähige Sanitizer verarbeitet UTF-8 und ANSI-/OSC-/DCS-Sequenzen über Chunkgrenzen, entfernt Sequenzinhalte passiv und macht ungültige, unvollständige oder verbleibende unsichtbare Daten kenntlich. Er puffert keine unbegrenzten OSC-/DCS-Payloads. Der Review repräsentiert die bereinigte Fassung, keine rekonstruierte Terminalansicht und keine automatische Secret-Redaction. Genau die lokal geprüfte Textfassung wird versendet.

Vim, top und andere TUIs bleiben im Systemterminal normal benutzbar, aber ihr Mitschnitt kann unübersichtlich sein und ist kein rekonstruierter Bildschirm. Dafür gibt es keine Vollständigkeitszusage. Bevorzugte Diagnosebefehle erzeugen Plaintext, beispielsweise ohne Pager und Farbcodes.

## 11. Ressourcen und Bedienungsschutz

Konzeptionelle Limits, mit dem implementierten MVP-0.8-Verhalten abgeglichen:

| Ressource | MVP Standard |
|---|---|
| Vorschlag | 4 KiB finaler UTF-8-Text; höchstens 50 physische Zeilen |
| Wartende Vorschläge | Höchstens 20 unbeobachtete Bridge-Vorschläge; lokal genau ein Vorschlagsplatz |
| Lokaler Output-Ring | 4 MiB Rohbytes; Anzeige zusätzlich begrenzt |
| Ein freigegebener Output | 64 KiB UTF-8 |
| Netzantwort/IPC-Frame | 128 KiB inklusive begrenzter Metadaten |
| Nicht abgeschlossene Terminalsequenz | Nach 4 KiB sichtbare Verwerfung; begrenzter Zustand, weiteres Verwerfen bis zum Terminator |
| Long-Poll-Batch | Höchstens ein Vorschlag; ersetzt die frühere Obergrenze von zehn |

Bei Überschreitung sperrt der Transfer oder fordert eine kleinere Auswahl; kein verborgenes Truncation-Verhalten. Auch die JSON-Hülle eines zulässigen 64-KiB-Outputs muss in das 128-KiB-Limit passen; starke Escape-Expansion wird abgewiesen. Ringspeicherüberlauf ist erlaubt, aber sichtbar. Rohoutput und bereinigte Projektion sind getrennt begrenzt. Rückstau beim Mitschnitt darf die normale Shell nicht unbegrenzt blockieren: In MVP 0.8 wird ein überlasteter Controller-Kopierkanal getrennt; eine Offsetlücke sperrt den Controllerpfad. Die manuelle Shell bleibt soweit möglich benutzbar. Das ist keine Zusage eines lückenlosen Mitschnitts.

Freigabeknöpfe sind keine Standard-Enter-Aktion der GUI. Eingehende Nachrichten ändern den Fokus nicht. Doppelklicks, Event-Wiederholungen und gleiche Message-IDs erzeugen keinen zweiten Gebrauch derselben Freigabe. Die lokale Pause blockiert neue AI-Transfers sofort; sie widerruft keine bereits eingegebenen Bytes.

Die Pause ist im lokalen Kern vorhanden und blockiert Freigabe sowie Output-Retry. Eine vom Benutzer erreichbare Pause-/Fortsetzen-Aktion samt sichtbarem Pausenzustand fehlt in der GUI noch; sie bleibt eine offene Bedienanforderung. Ein bereits geschriebener Command oder laufender Prozess wird dadurch nicht gestoppt.

## 12. Bridge Transport und Rollen

Im Controller↔Bridge-Pfad eröffnet nur der Controller die Netzwerkverbindungen. Für getrennte Systeme HTTPS zu einer lokal festgelegten Bridge-Adresse; die Firewall erlaubt Controller→Bridge und den zugehörigen Antwortverkehr. Der separate Tunnel-Client hat seinen eigenen Provider-Transport. Keine Webhooks, eingehenden Controller-IP-Ports, automatischen Discovery-Scans oder WebSockets im MVP-Controllerpfad.

Long-Polling: Server wartet höchstens 25 Sekunden, Client-Lesetimeout 35 Sekunden, Verbindungstimeout 5 Sekunden. Der aktuelle Worker fordert kurze Polls mit einer Sekunde Wartezeit an. Leere Antwort ohne neue Daten ist normal. Netzfehler erhalten Backoff mit Jitter von ungefähr 1 bis maximal 30 Sekunden. Auth-/Pin-/Schemafehler starten keine unbegrenzte Retry-Schleife. Cursor sind opaque, bounded und pro Bindung zugeordnet; ein Cursor ist keine Autorisierung. Der nächste Vorschlag ersetzt niemals einen laufenden Review.

| Controller API | Zweck |
|---|---|
| `GET /v1/status` | Authentisiert: Protokollversion und Bridge-Instanz, keine Terminaldaten |
| `GET /v1/inbox?cursor=…&wait=25` | Zugeordnete, begrenzte Vorschläge |
| `POST /v1/approved-output` | Gebundener finaler Outputsnapshot mit Idempotenzschlüssel |
| `PUT /v1/preferences` | Bewusst veröffentlichte SINGLE/SMALL/MEDIUM/LARGE-Präferenz |
| `POST /v1/pair/claim` | Nur während lokal aktivierter Kopplung; Kurzzeitcode |
| `POST /v1/pair/confirm` | Bestätigung des neu gespeicherten Controller-Schlüssels |

Ein separater Einzelmessage-GET ist optional; der erste Batch enthält bereits den vollständigen unveränderlichen Vorschlag. Änderungen an einer Message-ID werden als Protokollfehler behandelt. Schemaversion 1, JSON und UTF-8; keine dynamischen Typen oder Codeobjekte.

AI-seitig existiert ausschließlich `POST /mcp` mit eigener Authentisierung und Rolle; Controller-Token werden nie als AI-Token akzeptiert. MCP ist ein separater Adapter, nicht die Controller-REST-API. Alle vier Tools verlangen zusätzlich `conversation`, den vom Menschen bewusst dem gewünschten Chat gegebenen lokalen Bindungscode:

| MCP-Tool | Weitere Argumente | Aussage |
|---|---|---|
| `submit_proposal` | `request_id`, `text` | Empfang/ID/Ablauf, keine Ausführung |
| `get_submission_status` | `submission_id` | Annahme und Vorhandensein freigegebenen Outputs, kein Review-/Ausführungsstatus |
| `get_approved_output` | optional `submission_id`, `cursor` | Nur ausdrücklich freigegebener Output |
| `get_preferences` | keine | Komfortpräferenz, keine Berechtigung |

Der Dienst verwendet `aiohttp` und einen bewusst begrenzten MCP-Tools-Adapter ohne offizielles MCP-SDK oder Agentenstack. Legacy-Initialisierung und neue Discovery sind implementiert; die genaue Protokollversion ist Bestandteil der Schnittstelle, kein allgemeines Kompatibilitätsversprechen. Resources, Sampling, Roots, Tasks, Shell-/Datei-/Tastatur-/Terminal-Lesefunktionen werden nicht angeboten. `http.server` wird nur in lokalen Simulationstests verwendet. Schemata, Body-/Header-/Zeitlimits, Rate Limits und Parallelität sind begrenzt. Doppelte JSON-Schlüssel, NaN, unbekannte Felder, fremde Origins/Hosts und ungültige Cursor werden abgewiesen. Metadaten bleiben Daten, niemals Code oder Freigabe.

`ACCEPTED` bedeutet ausschließlich angenommen, nicht geprüft, ausgeführt oder erfolgreich. Auch leerer Output beweist weder Erfolg noch Fehler. Freigegebener Text erscheint genau einmal als eigener MCP-Textblock; Metadaten stehen im ersten Block und in `structuredContent`, `text_content_index` verweist auf den Payloadblock. Hosts ohne Auswertung von `structuredContent` können so ebenfalls den Text lesen.

Die Bridge meldet der AI zunächst nur Nachrichtenannahme und ausdrücklich freigegebene Antworten. Keine ungefragten Review-/Prompt-/Ausführungszustände. Auch Hashes von geheimen Befehlen werden nicht veröffentlicht. Technische IP-/Zeitmetadaten der Verbindung sind sichtbar. Mit dem lokalen Verbindungsaufbau stimmt der Benutzer dem beschriebenen Polling und der veröffentlichten Komfortpräferenz zu.

Die AI bestimmt niemals Terminalinstanz oder aktive Konversation im Controller. Die Chatbindung ist ein bewusst geteilter **Bearer-Code**, keine vom Provider kryptografisch bestätigte Chat-ID. Wer App-Zugriff und diesen Code besitzt, kann die für diese Bridge freigegebenen Daten lesen. Ohne Code sind Toolaufrufe gesperrt; Tools können ihn nicht entdecken. Das MVP unterstützt eine Chatbindung und einen aktiven Controller je Bridge. IDs sind opake Daten, keine Dateien, URLs oder Callback-Ziele.

### 12.1 Tunnel, Skill und erster Round Trip

Die Verbindungseinrichtung erfolgt mit UX-6 in einem einzigen größenveränderbaren, vertikal scrollbaren Dialog. Local und Remote bezeichnen weiterhin den Betriebsort; der OpenAI Secure MCP Tunnel ist die Transportanbindung, kein dritter Bridge-Modus. Im vereinfachten Local-Flow sind nur Tunnel-ID und **OpenAI Runtime API key** normale Eingaben, mit **Starten & testen** als primärer Aktion. Client-Suche/Installation sowie lokale Bridge/Secrets sind intern; Local zeigt keinen normalen Binary-Pfad oder separaten Bridge-Start. Der Remote-Teil behält den shell-quotierten Startbefehl, HTTPS-/Pin-/Code-Kopplung und die Gateway-Tunnelanleitung. Chatbindung anzeigen/kopieren bleibt bewusst. Standortwahl allein startet nichts; Schließen des Dialogs beendet keine laufende Einrichtung/Kopplung/Verbindung. Erfolgreiches Remote-Setup bedeutet unverändert eine authentifizierte Bridge-Verbindung; Gateway-Tunnel-Health wird nicht beobachtet, ein ChatGPT-Nachweis bleibt dort wie lokal der bestehende manuelle Round Trip.

Die lokale Bridge startet durch die ausdrückliche Local-Aktion als eigener Prozess per Selbstaufruf von `admin_in_the_loop.py --bridge`, mit zwei zufälligen Loopback-Ports und zufällig erzeugten getrennten Controller-/AI-Credentials. Bootstrap und Ready laufen über private Pipes; der Prozess erhält eine allowlist-Umgebung und ausschließlich die nötigen vererbten Deskriptoren. Auf einem Remote-Gateway startet der Betreiber dieselbe Datei explizit mit `--bridge`; die GUI startet dort keinen lokalen Bridge- oder Tunnelprozess und liefert den shell-quotierten Startbefehl aus den Remote-Pfaden und Bridge-Verbindungsdaten. Der MCP-Port bleibt auch beim Remote-Gateway auf `127.0.0.1` und wird dynamisch ausgegeben. Der Client bleibt ein separates externes Programm: Local findet ihn automatisch oder installiert unter Linux amd64/arm64 den geprüften offiziellen v0.0.15-Runtime-Download (fest gepinnte SHA-256, beschränktes Archiv, private/atomare Dateien), auf macOS über vorhandenes Homebrew. Remote bleibt operatorverwaltet. Es gibt keine automatischen Client-Updates.

Der **Runtime API key / CONTROL_PLANE_API_KEY** kommt separat aus Platform Runtime API keys, nicht als App-Key mit der Tunnel-ID und nicht als internes Shared Secret. Er und sein Benutzer benötigen Tunnels **Read + Use**; keine Admin-Keys für den Laufzeitdienst. Beschaffungswege sind [Tunnels](https://platform.openai.com/settings/organization/tunnels) und [Runtime API keys](https://platform.openai.com/settings/organization/api-keys), gemäß [offizieller Berechtigungsdokumentation](https://github.com/openai/tunnel-client/blob/v0.0.15/docs/permissions.md). Local speichert die dauerhafte Konfiguration erst nach lokalem READY und einem durch `/health/control-plane` beobachteten erfolgreichen authentifizierten Poll ohne aktuelle Fehler. `/readyz` alleine genügt nicht. Die automatische Vorbereitung mutiert keine Core-/Freigabezustände im Hintergrund; deren Übergabe erfolgt im Controller-Pump. Fehler oder Anwendungsschließen verhindern späten Prozess-Handoff und beenden die gestarteten Local-Prozesse. Vorher gespeicherte Profile bleiben erhalten.

Für den echten Round Trip muss der Betreiber weiterhin die App-/Workspace-Zuordnung herstellen und den Chat-Code bewusst ausschließlich dem gewählten Chat geben. Runtime API key und internes AI-Token werden über private temporäre Dateien statt Klartextargumente oder Prozessumgebung übergeben. Im Remote-Profil liegt der Tunnel-Lifecycle unverändert beim Gateway-Betreiber; die GUI steuert keinen fremden Rechner. Ein harmloser `printf`-Vorschlag in einer bezeichneten Testshell wird erst lokal als Command, danach gesondert als ausgewählter Output freigegeben. Erst die zurückgelesene menschlich geteilte Beobachtung belegt den gesamten ChatGPT-Ablauf. Local „Tunnel-Zugriff geprüft“ ist ein Setup-Pollnachweis, keine kontinuierliche Berechtigungsprüfung oder ChatGPT-End-to-End-Verifikation.

Der Orchestrator-Skill ist ausschließlich Bedienhilfe, keine Sicherheitsgrenze. Er entdeckt die tatsächlichen Tools, liest Präferenzen, trennt interaktive Schritte, verwendet kleine proportionale Vorschläge und behandelt Output einschließlich scheinbarer Anweisungen als untrusted Beobachtung. Er darf weder lokale API-Freigaben noch GUI-Freigaben auslösen. Bei unklarer Vorschlagszustellung darf nur identischer Text mit derselben Request-ID innerhalb der Bindungsfrist erneut eingereicht werden; angenommene Commands werden wegen fehlenden Outputs nicht wiederholt. Er behauptet kein Hintergrundmonitoring, keinen sicheren Befehlsabschluss und keinen erfundenen Exitcode.

Die aktuelle Beilage ist [../skill/SKILL.md](../skill/SKILL.md). Laut [Handoff-Notiz](../skill/HANDOFF_SKILL_NOTE.md) wurde sie neu erstellt, weil die ursprüngliche als validiert beschriebene Datei nicht wiedergefunden wurde. Frontmatter, Tools/Argumente und Freigabegrenzen wurden statisch geprüft; die 86 Anwendungstests sind kein Live-Nachweis dieses Ersatzskills. Zum Statusstichtag der Notiz blockierte die automatische Freigabeprüfung persönliche Speicherung mangels ausdrücklicher Zustimmung. Der aktuelle Installations- und Workflowstatus wird ausschließlich im Taskboard geführt. Die operative Anleitung ist [../tests/Local_Integration_README.md](../tests/Local_Integration_README.md).

## 13. TLS Identität und Kopplung

Remote-Verbindungen verwenden mindestens TLS 1.2, bevorzugt TLS 1.3. Die Bridge erzeugt einmalig einen persistent gespeicherten ECDSA-P-256-Schlüssel und ein selbstsigniertes Zertifikat mit konfigurierten DNS-/IP-Namen. Kein eigener Kryptografiealgorithmus.

**Identität:** SHA-256 über die DER-kodierte SubjectPublicKeyInfo des Zertifikatsschlüssels. Beide Seiten verwenden denselben vollständigen 256-Bit-Fingerabdruck als 64 Hexzeichen. Er muss unabhängig auf der lokalen Bridge-Konsole verglichen werden; die GUI verlangt eine ausdrückliche Vergleichsbestätigung. Kein kurzer Ersatzfingerabdruck und keine Bestätigung eines nur über denselben ungeprüften Netzwerkkanal gelieferten Werts. Für die Ablesbarkeit bleibt die Darstellung in 16 Vierergruppen das Soll; MVP 0.8 gibt den vollständigen Pin ungruppiert aus und akzeptiert gruppierte Eingabe. Der gruppierte Vergleich ist noch offene Darstellungsarbeit, kein neuer Identitätsmechanismus.

Der Controller verwendet für Extraktion und X.509-Prüfung eine gepflegte `cryptography`-Bibliothek, den TLS-Kanal aus Python `ssl`. Pin, Gültigkeit, konfigurierte Namensbindung und erforderliche Zertifikatseigenschaften werden vor jeder HTTP-Nutzdaten-/Tokenübertragung am tatsächlich benutzten Socket geprüft. Ein self-signed Profil benötigt bewusst implementierte pinbasierte Vertrauensprüfung; es ist keine allgemeine Option „Zertifikate ignorieren“. Beim ersten Kontakt erlaubt die App vor Prüfung nur die Erhebung des Zertifikats über TLS, keine vertraulichen HTTP-Anfragen. [Q6][Q7]

Pin gilt für genau die lokal konfigurierte Bridge-Verbindung und Host/Port. Unerwarteter Schlüsselwechsel blockiert. Zertifikatserneuerung mit demselben SPKI ist nach vollständiger Eigenschaftsprüfung zulässig. Schlüsselrotation ist eine lokale Neuprüfung, keine AI-/Server-Anweisung. MVP 0.8 implementiert lokale Erneuerung bei gleichem SPKI, Laufzeit ein Jahr und Warnung bei weniger als 30 Tagen Restlaufzeit. Remote-Klartext, Umleitungen und geerbte Proxyeinstellungen werden nicht verwendet. Reale lokale TLS-Tests belegen den Pin-/Namensvergleich vor HTTP-Credentials, nicht den menschlichen unabhängigen Vergleich.

**Kurzzeitcode:** 12 gleichverteilte Crockford-Base32-Zeichen aus sicherem Zufall, angezeigt als drei Vierergruppen; 60 Bit Entropie. Groß-/Kleinschreibung und Gruppierung sind reine Eingabeformatierung. Gültigkeit zwei Minuten, höchstens fünf fehlgeschlagene Versuche pro lokal geöffnetem Kopplungsfenster, zusätzlich globales Rate-Limit. Nur eine aktive Kopplung gleichzeitig. Nach einem Fehlversuchlimit ist eine neue lokale Aktivierung erforderlich. Denial-of-Service gegen dieses Fenster bleibt möglich und wird als Fehler angezeigt.

Ablauf:

1. Benutzer aktiviert Kopplung lokal auf der Bridge; die Konsole zeigt Fingerabdruck und Code. Der Controller wird erst nach geprüftem Pin für die Codeübertragung freigegeben.
2. Controller sendet Code und zufällige lokale Request-ID über den verifizierten TLS-Socket. Die Bridge verbraucht den Code atomar; ein zweiter Claim kann nicht gewinnen.
3. Bridge erzeugt einen individuellen 256-Bit-Controller-Token, liefert ihn genau in dieser Antwort und hält die neue Berechtigung vorerst im Zustand `PAIR_PENDING`.
4. Controller speichert Token geschützt und bestätigt mit diesem Token. Danach lautet der Status `PAIRED` und erst dann sind gewöhnliche APIs zugänglich.
5. Nicht bestätigte Kopplungen verfallen nach zwei Minuten. Bei verlorener Claim-Antwort wird kein Token aus einem ungesicherten Recovery-Endpunkt nachgeliefert; lokale Neukopplung erforderlich. Eine unklare Confirm-Antwort darf mit demselben bereits gespeicherten Token idempotent geprüft/wiederholt werden.

Token im Authorization-Header, nicht in URLs. Bridge speichert für Authentisierung Token-Hash und zugeordnete Rolle/Controller-ID in SQLite; benötigte lokale Runtime-Secrets liegen zusätzlich in privaten Dateien. Hochentropische Token sind keine Benutzerpasswörter. Temporäre Klartextkopien während Zustellung werden nicht geloggt. Bestätigung einer neuen Kopplung widerruft die anderen Controller-Token dieser Bridge. Widerruf erfolgt lokal auf der Bridge. Für den MVP ersetzt Widerruf plus Neukopplung eine komplexe automatische Rotation; mTLS bleibt eine nicht beauftragte spätere Option.

**Sidecar:** Controller startet `admin_in_the_loop.py --bridge` als getrennten lokalen Prozess, initialisiert starke Tokens über eine geerbte private Pipe und wartet auf Ready-Bestätigung. Die Bridge lauscht ausschließlich auf Loopback und verlangt den Token. Remote-Pinning und Abtippen entfallen nur in diesem Komfortprofil. Keine Token in Prozessargumenten/Umgebung/Logs. Der Sidecar erhält keine Terminal-IPC oder SSH-Agent-Deskriptoren.

## 14. Freigabe und Zustandsautomat

Ein Terminaltransfer lautet lokal:

`INBOX → REVIEW → CHECKING → [OVERRIDE_REQUIRED] → TRANSFERRING → TRANSFERRED`

`REJECTED`, `STALE` und `TRANSFER_UNCERTAIN` sind weitere Endzustände. Der Helfer reserviert die Freigabe einmalig mit Snapshot-/Sitzungsbindung; kein Netzwerkprozess kann dieses Ereignis erzeugen. Nach begonnenem Schreiben gibt es keinen automatischen Gesamt-Retry. `TRANSFERRED` bedeutet nur übergebene Bytes, niemals „ausgeführt“ oder „erfolgreich“.

Ausgabe lautet:

`SELECTED → REVIEW → SENDING → ACKNOWLEDGED` oder `DELIVERY_UNCERTAIN`.

Diese Diagramme beschreiben konzeptionelle Transferphasen, nicht eine Zusage zusätzlicher öffentlich beobachtbarer Ausführungszustände. Im MVP 0.8 fasst der Kern den laufenden Terminaltransfer unter `CHECKING` zusammen; der Helfer verbraucht die Freigabe vor dem ersten Write. Ohne Bridge endet eine Outputfreigabe als `ACKNOWLEDGED_LOCAL`: lokale Testfreigabe, keine Übertragung an einen AI-Anbieter.

Ein Retry verwendet ausschließlich denselben schon freigegebenen Snapshot, Empfänger und Idempotenzschlüssel. Keine neue Terminalauswahl. Bridge lehnt denselben Schlüssel mit anderem Body ab. Ein Schlüssel bleibt für die dokumentierte 24-Stunden-Nachrichtenfrist gebunden; abgelaufene Zustellungen benötigen neuen Review. Persistierter Zustand darf nie eine lokale Freigabe nach Neustart restaurieren.

Transport-Reconnects erzeugen eine neue Verbindungsgeneration und entwerten aktive Freigabemöglichkeiten. Der Text kann lokal als ungeprüfter Entwurf bleiben. `DELIVERY_UNCERTAIN` darf erst nach erneuter authentisierter Bindungsprüfung denselben bereits autorisierten Output nachliefern; Zielwechsel erfordern eine neue Freigabe.

## 15. Betriebsprofile und Datenhaltung

**Lokaler Komfortmodus:** Prozesse desselben Benutzers sind keine starke Isolation. Dateirechte und Capability schützen vor versehentlichen fremden Verbindungen, nicht vor kompromittiertem Root oder beliebigem Code desselben Benutzers. Sidecar wird nicht für kritische Infrastruktur als abgeschottet beworben.

**Getrennter Modus:** Controller, Helfer und Terminal in dedizierter Admin-Umgebung; Bridge/Tunnel in anderem Qube oder auf anderer Maschine. Keine gemeinsamen Admin-Homes, PTYs, Socketpfade, Agent-Zugänge oder automatisch geteilten Clipboards. Qubes-Betrieb im App-Qube, nicht dom0. Konkrete Firewall-/Credential-/Dateisystemprüfung vor sensibler Nutzung.

Konfiguration: JSON, Verzeichnis `0700`, Dateien `0600`, geprüfter Eigentümer, atomare Speicherung und abgewiesene Symlinks. Token, Pin und Profil liegen geschützt lokal; keine Shell-Ausführung von `.env`, keine automatische Variablenexpansion. Linux verwendet `~/.config/admin-in-the-loop/`, macOS `~/Library/Application Support/Admin in the Loop/`. `preferences.json` enthält finales Return und Blockgröße; `connection.json` enthält Remote-Profil und/oder Tunnelkonfiguration. Lokale Bridge-Token und Freigaben werden nicht wiederhergestellt. Der gespeicherte Runtime-Key ist eine private lokale Datei, kein Betriebssystem-Credential-Store. Im MVP ist keine zusätzliche Config-Verschlüsselung nötig; Datei-/OS-Rechte und das Betriebsprofil bestimmen ihren Schutz.

Logs sind standardmäßig aus beziehungsweise auf minimale Fehlertypen begrenzt. Falls ein optionaler Testmodus genutzt wird, darf er nur Zeit, Ereignistyp und opake IDs sowie Prompt-Befund/Override enthalten. Keine Commands, Terminaltexte, Review-Payloads, Tokens, Codes, Auth-Header oder HTTP-Bodies – auch nicht in Debuglogs oder Ausnahmeausgaben. Ausgabe-/Requestinhalte werden in Fehlern nicht interpoliert.

Bridge hält Vorschläge, freigegebenen Output und Cursor höchstens 24 Stunden abrufbar, mit festgelegtem Ablauf und periodischer Bereinigung; Nachricht bleibt nach Ablauf nicht abrufbar, selbst wenn physische Bereinigung kurz später erfolgt. Persistente Verbindungs-/Authentisierungstoken sind davon zu unterscheiden und werden lokal widerrufen. Crash-Wiederanlauf respektiert Ablaufzeit und Idempotenz. Das ist keine Löschgarantie für Datenträger, Backups oder bereits an AI-Anbieter übermittelte Inhalte. Lokaler Output bleibt flüchtig. Python-Speicherfreigabe ist keine garantierte sichere Löschung; Swap und Dumps sind OS-Themen.

## 16. Feindlicher Output und spätere Erweiterungen

Terminaloutput geht an einen echten Systemterminalemulator und kann dessen Steuerfunktionen ansprechen. Der Renderer bleibt Teil der Vertrauensbasis. Clipboard-Zugriffe, Links, Bilder und Fenstersteuerung dürfen im gehärteten Betrieb keine unerwünschten Aktionen ermöglichen. Die tatsächlich gewählten Debian-/macOS-Terminalversionen werden geprüft. Ist eine relevante Funktion nicht zuverlässig abschaltbar oder begrenzbar, wird das Profil nicht als gehärtet abgenommen.

Der Linux-xterm-Launcher deaktiviert Fenster-, Font-, Titel-, Farb-, Tcap- und Send-Events-Funktionen; der historische GUI-Test belegt speziell den Schutz des isolierten Clipboards gegen OSC 52. Daraus folgt keine vollständige Prüfung aller Terminalrückkanäle oder von Terminal.app. Die Plattformabnahmen müssen die konkreten Terminalversionen und automatische Protokollantworten einbeziehen. Gleiche Benutzerkennung isoliert Bridge/Tunnel nicht zuverlässig vom Dateisystem des Controllers; eingeschränkte Umgebung und fehlende vererbte Deskriptoren ändern diese Grenze nicht.

Die Controller-Review führt keine Terminalsequenzen aus. Notwendige Status-/Größenantworten des Systemterminals sind automatische Terminalprotokollantworten, keine AI-Freigaben; sie werden dennoch auf unerwünschte Informationsrückgabe getestet. Kein pauschales Versprechen eines rückkanalfreien Terminals.

Spätere Execution-/Disclosure-Analyse hängt ausschließlich vor dem finalen Snapshot. Treffer sind Hinweise, kein automatisches Approve. Automatische Redaktion benötigt neuen Review. Der Skill darf Output-Anweisungen nicht als Nutzerauftrag behandeln und muss Transportannahme, Benutzerangabe und beobachtetes Ergebnis unterscheiden.

## 17. Abnahme und Implementierungsreihenfolge

**P0:** Kontrollierte Shell und einzelne PTY-Verantwortung; Tests zu Echo an/aus, Teilschreiben, EOF, Resize, Ctrl-C, Hintergrundausgabe und Mitschnittverlust. Danach auf beiden Plattformen echte GUI-/Launcherprobe. Keine lokale dauerhafte Shell-Konfigurationsänderung.

**P1:** Snapshot- und Freigabegleichheit, Return-Normalisierung, Unicode-/Steuerzeichensperren, Blocklimits, manueller Override, Outputauswahl. Bedienprobe bei SSH, sudo, Passwortprompt, offener Shell-Quote, vim/top und gleichzeitigem Tippen.

**P2:** Long-Polling, Rollen, Pinning am verwendeten Socket, Kopplungszustände, Widerruf, Auth-Fehler, Schema-/Bodylimits, Idempotenz und konservative Logs. Danach realer MCP-Round-Trip.

Diese Prüffelder sind der konzeptionelle Abnahmerahmen. Bereits vorhandene Linux-/lokale Nachweise sind in §19 zusammengefasst. Aktuelle offene Arbeit, Ticketzuordnung und Ausführungsreihenfolge werden ausschließlich auf dem Taskboard verwaltet. Die historische Migration dieser Anforderungen samt damaligen Taskbeschreibungen und Board-ID-Zuordnung ist in [TASKBOARD_PROPOSAL.md](TASKBOARD_PROPOSAL.md) archiviert; dieses Dokument ist kein aktiver Aufgabenplan.

Erhaltene Bedienanforderungen wie Byte-Detailansicht, sichtbare Normalisierung, GUI-Pause, Lifecycle-Erklärung und lesbare Fingerabdruckdarstellung bleiben konzeptionelle Qualitätsanforderungen. Ob sie aktuell offen, priorisiert oder abgeschlossen sind, ist ausschließlich anhand der zugehörigen Taskboard-Tickets zu bestimmen. Gleiches gilt für den Live-Nachweis der Skill-Beilage; nichts davon ist durch die historischen Anwendungstests als abgenommen ausgewiesen.

| Kritischer Test | Erwartung |
|---|---|
| Vorschlag trifft ein oder behauptet `approved` | Keine lokale Übernahme oder PTY-Eingabe |
| Neue Inbox-Nachricht/Option/Ziel während Review | Snapshot unverändert oder Freigabe ungültig |
| Mehrzeiliger Text, mehrere finale LF, Return an/aus | Genau die normalisierten und dargestellten Bytes |
| Prompt falsch positiv/negativ, Benutzer tippt | Nur weicher Hinweis; bei unbekanntem Zustand Override |
| Override abgebrochen oder alte Instanz | Keine Eingabe |
| Doppelklick, FD-Schreibfehler nach Teiltransfer | Einmaliger Transfer; unklar ohne Gesamt-Retry |
| Passwort mit deaktiviertem Echo | Keine Eingabekopie in Mitschnitt, Review, IPC-Output, Netz oder Logs |
| Passwort mit manipuliertem Echo | Kann Output sein; keine falsche Secret-Garantie |
| Hintergrundoutput vor/nach Transfer und Kernelrückstau | Ehrliche Beobachtungsgrenze, kein Command-Ergebnisversprechen |
| Mitschnittkanal voll oder getrennt | Begrenzter Verlustmarker, normale Shell soweit möglich bedienbar |
| Terminalsequenz über Chunks oder unbeendet | Sanitizer bleibt begrenzt; keine aktive Review-Sequenz |
| Pin falsch/geändert oder Token vor Pinprüfung | Verbindung gesperrt, keine vertraulichen HTTP-Bytes |
| Code abgelaufen/mehrfach verwendet/Confirm verloren | Atomare Kopplung, definierter Pending-/Recovery-Zustand |
| Fremde Rolle/Konversation, ungültiger Cursor/Body | Keine fremden Inhalte oder Fähigkeitserweiterung |
| Reconnect und erneute Zustellung | Keine wiederholte Terminalfreigabe; gebundener Output-Retry |
| Canary-Secrets in allen Eingabe-/Fehlerpfaden | Keine unerwünschten Inhaltslogs |

Erfolg am Fake-PTY beweist Bytegleichheit, nicht reale Shellwirkung. Die reale Bedienprobe beweist einen getesteten Ablauf, keine generelle Hochsicherheit. Für kritische Infrastruktur folgt ein unabhängiges Review der konkreten Umsetzung und Isolation.

## 18. Standardannahmen und bedingte spätere Optionen

Die Fortschreibung benötigt keine neue Geschäfts- oder Architekturentscheidung. Der MVP-0.8-Bedienstand ersetzt die früheren Startempfehlungen, ohne die Sicherheitszusagen auszuweiten:

| Thema | Aktueller MVP-0.8-Standard | Bedingte Alternative / Grenze |
|---|---|---|
| Ein oder zwei Fenster | Tkinter plus kontrolliertes Systemterminal; lokal implementiert | Ein eingebettetes Fenster ist ausgeschlossen und benötigt einen gesondert geänderten Auftrag |
| Finales Return beim Erststart | An, danach lokale gespeicherte Wahl | Ausschalten verhindert nicht die Wirkung interner LF |
| Shellprofil | Kontrollierte interaktive Bash ohne Benutzerprofile; begrenzte History nur im RAM | Keine persistente History oder Übernahme der Alltagsshell-Konfiguration; Pfeiltasten-History ab v0.9.17 |
| Headless und GUI | Gemeinsamer Kern, historische Linux-/Xvfb-Nachweise | Native Debian-/macOS-Proben bleiben offen |
| Bridge-Scope | Lokaler/Remote-Transport und Tunnel-Lifecycle implementiert; Offline-Modus bleibt bewusst wählbar | Echter Providerbetrieb und Betriebstrennung verlangen die noch offenen Abnahmen |

Eine spätere Korrektur des Fensterwunsches ändert nicht Freigabemodell, Netzrollen oder Kopplung. Ebenso erzeugen optionale Paste-Modi, mTLS, Einzelmessage-GET, Guards oder ein anderer Terminalbackend ohne gesonderten Bedarf keinen aktuellen Backlog. Credentials, konkrete Prüfgeräte und Installationsziel sind Ausführungsvoraussetzungen der jeweiligen Tasks, keine hier fehlenden Produktentscheidungen.

## 19. Tatsächliche Evidenz und Quellen

### 19.1 Historischer Implementierungs- und Testnachweis

Die V0.7 konsolidierte laut ihrem Inhalt die V0.6 und frühere Nutzerentscheidungen. Frühere Revisionen sind nicht mitgeliefert. Die nun importierten Dateien gehen darüber hinaus: PTY/IPC, unveränderliche Reviews, Drei-Spalten-GUI, Return-/Blockpräferenzen, Streaming-Sanitizer, separate HTTP-/MCP-Bridge, Long-Polling/Backoff, TLS-Pinning/Kopplung/Widerruf, private atomare Speicherung, gebundener Output-Retry und lokaler Tunnel-Lifecycle sind in der Quelle vorhanden und im mitgelieferten Bericht als geprüft beschrieben. Onboarding ist beschrieben und lokal getestet, Qubes/Gateway ist Betriebsarchitektur mit implementiertem generischem Remote-Transport, kein nachgewiesener isolierter Qubes-Betrieb.

Der [MVP-0.8-Testbericht](../tests/MVP_0.8_TEST_REPORT.md) dokumentiert am 30. September 2026 **86 bestandene Tests**: 49 eingebettete Controller-/PTY-/IPC-Tests, 36 verbundene Integrationstests und einen GUI-Smoke-Test. Die zugehörigen Protokolle sind [lokale Headless-Tests](../tests/Local_Integration_HEADLESS_TESTS.txt), [verbundene Headless-Tests](../tests/Connected_MVP_HEADLESS_TESTS.txt) und [GUI-Smoke-Test](../tests/GUI_SMOKE_TEST.txt). Headless bedeutete ohne Desktop, nicht ohne reale PTYs, Sockets oder Subprozesse. Framework ist Python-`unittest`/`mock`; ein externer Testframework- oder Agentenstack ist nicht erforderlich.

Historische Umgebung: Ubuntu 24.04.3/Linux x86_64, Python 3.12.14, aiohttp 3.13.5, cryptography 46.0.0, Tk 9.0.4, xterm 390. Das echte offizielle Tunnelbinary v0.0.15 wurde gegen eine lokale simulierte Kontrollplattform eingesetzt; sein Paket und echte Provider-Credentials sind nicht enthalten. Zwei Tests sind ohne `AITL_TEST_TUNNEL_BINARY` ausdrücklich übersprungen. Die im Bericht gespeicherten SHA-256-Werte aller vier Python-Dateien stimmen mit den heutigen Quelldateien überein. Das belegt Quellenkontinuität, nicht die Funktionsfähigkeit verschobener Einstiegspfade, menschliche Aufmerksamkeit, die Sicherheit aller Shellwirkungen oder eine Abnahme der heutigen Umgebung.

### 19.2 Repository-Anordnung und Reorganisationsbefunde der Erstinventur

Dieser Abschnitt hält die Pfadbefunde der ursprünglichen Inventur als historische Momentaufnahme fest, nicht als aktuellen Fehler-/Aufgabenstatus. Ob L01/L02 oder weitere Tickets seither umgesetzt wurden, ist ausschließlich im Taskboard zu prüfen.

| Pfad ab Projektroot | Rolle |
|---|---|
| `admin_in_the_loop.py` | Aktueller einzelner Anwendungs-Entry-Point mit GUI-, Helfer-, Selbsttest- und Bridge-only-Rollen |
| `tests/test_connected_mvp.py`, `tests/gui_smoke_test.py` | Verschobene Integration-/GUI-Tests |
| `tests/Local_Integration_README.md` | Operative Anleitung, die zum Inventurzeitpunkt noch alte Pfade enthielt |
| `tests/MVP_0.8_TEST_REPORT.md` und benachbarte Protokolle | Historische Nachweise, keine neuen Testergebnisse |
| `skill/SKILL.md`, `skill/HANDOFF_SKILL_NOTE.md` | Aktuelle Skill-Beilage und Provenienz |
| `doc/Admin-in-the-Loop_Konzept_V0.7.md` | Diese fortgeschriebene maßgebliche Konzeptdatei |
| `doc/TASKBOARD_PROPOSAL.md` | Historische Planung, Inhaltszuordnung und Querverzeichnis der Board-Tickets; kein aktiver Backlog |

Die damalige statische Inventur fand Reorganisationsprobleme: Beide verschobenen Tests importierten Rootmodule ohne eingerichteten Root-Importpfad; der GUI-Test erwartete zusätzlich einen unqualifizierten Geschwisterimport. Die Testeinstiege fügen jetzt den Projektroot hinzu. Die Bridge-Datei `aitl_bridge.py` gehörte zum historischen MVP-0.8-Stand und wurde im MCP-1-Task in den einzigen Anwendungs-Entry-Point migriert. Anleitung und GUI-Test-Docstring nannten die ehemaligen Root-Einstiegspfade. Die Handoff-Notiz nannte das nicht mehr vorhandene `skills/admin-in-the-loop-orchestrator/SKILL.md`; der Skill nannte die Anleitung ohne deren `tests/`-Pfad. Diese Befunde waren Kandidaten der damaligen Planung; sie sind hier keine Aussage über ihren heutigen Ticket- oder Implementierungsstatus. Zum Inventurstichtag gab es weder Projekt-/Paketmanifest noch eingerichteten Testrunner oder CI-Workflow; deren Einführung ist nicht automatisch beauftragt.

Dieses Konzept ist die Produkt-/Konzeptreferenz; das Taskboard ist die alleinige Quelle aktiver Arbeit. Der Initial-Handoff ist laut Operator abgeschlossen: Die Board-Ticket-IDs stehen als historische Zuordnung in `doc/TASKBOARD_PROPOSAL.md`. `IMPLEMENTATION_STATUS.md` bleibt gemäß aktueller Anweisung erhalten, jedoch ausschließlich als historischer Implementierungs-/Evidenzstand; weder Status noch Vorschlag bilden einen parallelen Backlog. Auch diese Migrationsnotiz dokumentiert nur Provenienz und verweist für aktuelle Zustände auf das Taskboard. Die beigefügte operative Anleitung benennt den früheren Abnahmestand als historisch und verweist aktive Arbeit ebenfalls ausschließlich dorthin.

### 19.3 Technische Primärquellen

Primärquellen für technische Grundlagen, recherchiert am 30. September 2026:

- **[Q1] Python PTY:** Unix-Unterstützung, Funktionen und macOS-Warnung. https://docs.python.org/3/library/pty.html
- **[Q2] Python Tkinter:** GUI-Bindung und Prüfung der installierten Runtime. https://docs.python.org/3/library/tkinter.html
- **[Q3] Debian Pakete:** Tkinter und xterm. https://packages.debian.org/stable/python/python3-tk und https://packages.debian.org/de/trixie/xterm
- **[Q4] Debian cryptography:** Gepflegtes Betriebssystempaket. https://packages.debian.org/trixie/python3-cryptography
- **[Q5] Apple Automation Scripting Guide:** Scriptbare Terminal.app und sichere Behandlung von Shellargumenten. https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/CallCommandLineUtilities.html
- **[Q6] Python SSL:** TLS-Sockets und Zertifikatserhebung. https://docs.python.org/3/library/ssl.html
- **[Q7] cryptography Key Serialization:** DER und SubjectPublicKeyInfo. https://cryptography.io/en/latest/hazmat/primitives/asymmetric/serialization/

Die Quellen stützen die Plattform-/Bibliotheksgrundlagen, nicht automatisch die Sicherheit der Implementierung. Sie wurden für diese Dokumentmigration nicht erneut über das Netz geprüft. Vorhandene lokale Nachweise und noch offene native, Cloud- und Isolationsprüfungen sind bewusst getrennt.
