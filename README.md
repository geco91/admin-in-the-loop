# Admin in the Loop

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="doc/assets/branding/admin-in-the-loop-lockup-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="doc/assets/branding/admin-in-the-loop-lockup-light.png">
  <img src="doc/assets/branding/admin-in-the-loop-lockup-light.png" alt="Admin in the Loop" width="600">
</picture>

**AI assists, Admin decides.**

Admin in the Loop vermittelt zwischen AI-Vorschlägen und einem vom Menschen
bedienten Terminal. Die AI stellt Command-Vorschläge bereit; der Admin prüft und
genehmigt den exakten Text vor der Übergabe ans Terminal. Terminalausgabe wird
separat ausgewählt, geprüft und erst nach einer weiteren Freigabe an die AI
weitergegeben. Das Terminal bleibt unabhängig manuell bedienbar.

## Aktuelle persönliche Testversion

**Aktuelle persönliche Testversion: v0.9.22 mit automatischem Zwischenablage-Fallback und gemeinsamer Moduswahl.**
Links im Terminalbereich wird die Rückgabeprüfung eingestellt, rechts im AI-Bereich
die Befehlsprüfung. Die Mitte bleibt für Code/Ausgabe und die passenden Prüfreiter
mit Ampel und Befundzahl frei. [Echte Beispielansichten](doc/REVIEW_LAYOUT.md).
Der Stand bündelt außerdem sh-guard, überarbeitete Verbindungseinrichtung,
erneutes Prüfen desselben Command-Outputs und Maus-Kontextmenüs. Änderungen
stehen im [Changelog](CHANGELOG.md).

Ohne geöffnetes Terminal startet die App im **Zwischenablage-Modus**: AI-Vorschläge
lassen sich bereits übernehmen, prüfen, bearbeiten und ausdrücklich in die
Zwischenablage kopieren. Kein Hinweis fordert dafür zum Öffnen des Terminals auf.
Sobald das Terminal verbunden ist, werden **Terminal** und **Letzter Command**
als Standard für neue Vorgänge gewählt. Bei Terminaltrennung gilt wieder
Zwischenablage. Eine laufende Kopierprüfung wird beim Öffnen der Shell nicht
automatisch zur Terminalfreigabe.

**Ausgabebereich → Zwischenablage** und das Ziel für AI-Vorschläge sind gekoppelt.
Diese Auswahl gilt deshalb auch bei geöffnetem Terminal: AI-Vorschläge werden
nur mit **In Zwischenablage kopieren** übernommen und nicht ins Terminal gesendet.
Ein Wechsel bei offenem Command erzeugt einen neuen Review; alte Freigaben gelten
nicht mehr. Während Übernahme oder Zustellung ist die Moduswahl gesperrt.
Zeilenbereiche bzw. **Letzter Command** schalten zurück zum Terminalmodus.

Links liest **Prüfen →** den aktuellen Zwischenablagetext zur Rückgabe an die AI.
Erst nach Prüfung und ausdrücklicher Freigabe wird er geteilt. Die Rückgabe ist
standardmäßig unabhängig vom letzten Command; dessen offene Rückgabe bleibt
erhalten. Kopieren an die Zwischenablage hängt kein automatisches finales Return
an. Ohne zuvor aus der App freigegebenen Command zeigt **Letzter Command** einen
Hinweis; für manuelle Terminalausgaben einen Zeilenbereich wählen.

Nur Text bis 64 KiB innerhalb des bestehenden Nachrichtenlimits; unsichtbare
Steuerzeichen einschließlich Tabs werden wie bei Terminalrückgaben abgewiesen.
Unter Qubes muss der Text vorher in die lokale Zwischenablage des App-Qubes
übertragen werden. Bilder und Dateien werden nicht übernommen.

Für die Modusänderung genügt das Controller-Update. Die enthaltene
Tunnelkorrektur benötigt eine Bridge ab v0.9.20; ältere Bridges mit demselben
State-Verzeichnis neu starten. Gespeicherte Kopplung und Credentials bleiben erhalten. [Details und Prüfnachweis](doc/RELEASE_V0.9.22.md).

## Herunterladen und ausprobieren

[Python-Datei v0.9.22 herunterladen](https://raw.githubusercontent.com/geco91/admin-in-the-loop/refs/tags/v0.9.22/admin_in_the_loop.py) ·
[Gesamtes Repository als ZIP](https://github.com/geco91/admin-in-the-loop/archive/refs/tags/v0.9.22.zip)

Die einzelne Python-Datei genügt für die Anwendung; Tests und Dokumentation
liegen zusätzlich im ZIP. In einem eigenen, leeren Verzeichnis herunterladen:

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  https://raw.githubusercontent.com/geco91/admin-in-the-loop/refs/tags/v0.9.22/admin_in_the_loop.py \
  --output admin_in_the_loop.py
python3 admin_in_the_loop.py
```

Python ≥ 3.11, Tkinter und XFCE Terminal müssen vorhanden sein; für Remote-TLS
zusätzlich `cryptography`. Debian-Paketbefehle stehen unter [Voraussetzungen](#voraussetzungen).
Unter Qubes wird die Controller-App im vorgesehenen App-Qube gestartet.

## Einfach aktualisieren

App schließen, dann im Verzeichnis der heruntergeladenen Datei ausführen:

```bash
# Original-Repository GeektankLabs, main
python3 admin_in_the_loop.py update

# Fork, weiterhin main — für diesen Entwicklungsstand geco91 verwenden
python3 admin_in_the_loop.py update geco91

# Ausdrücklich einen Entwicklungsbranch dieses Forks ausprobieren
python3 admin_in_the_loop.py update geco91 feature/mein-branch
```

`--update` funktioniert genauso wie `update`. Ohne Nutzernamen gilt immer
`GeektankLabs/admin-in-the-loop`; der Repo-Name bleibt gleich. Ohne Branch gilt
`main`. Die Quelle wird nicht dauerhaft umgestellt: Für weitere Updates aus
einem Fork dessen Namen wieder angeben. Der Entwicklungsbranch muss existieren.

Das Update prüft Python-Syntax sowie übereinstimmende App-/Bridge-Versionen,
führt den Download dabei nicht aus und ersetzt nur die Anwendungsdatei atomar.
`admin_in_the_loop.py.bak` enthält die unmittelbar vorherige Datei. Gleicher
Dateiinhalt wird nicht erneut geschrieben. Einstellungen, Verbindungen und
installierte Prüftools werden nicht überschrieben. App und gegebenenfalls eine
separat laufende Bridge anschließend neu starten; diese werden nicht automatisch
beendet oder aktualisiert. Bei getrennten Qubes die jeweilige Kopie aktualisieren.

Ohne ausdrücklich angegebenen Branch wird eine ältere Versionsnummer abgelehnt.
Das Original kann hinter dem Fork liegen. Mit beiden Parametern ist auch ein
bewusster Wechsel auf einen älteren Branch möglich. Die Python-Datei aus diesem
Branch kann weniger Funktionen besitzen; die Sicherung erlaubt die Rückkehr.
Updates vertrauen dem ausgewählten GitHub-Konto und Branch über HTTPS. Syntax-
und Versionsprüfung sind keine Signaturprüfung oder Sicherheitsbewertung des Codes.
Lokale Änderungen an der Anwendungsdatei werden im Backup gesichert und ersetzt.
Bei einem Git-Checkout stattdessen den üblichen Git-Workflow verwenden.

[Veröffentlichungsumfang und Prüfnachweis](doc/RELEASE_V0.9.18.md)

### Tunnel nach Ruhezustand oder erneutem App-Start prüfen

Nach „Controller-Kontakt: Kopplung bestätigt“ prüft die Bridge ihren konfigurierten
Tunnel frisch im Hintergrund. Ein gesunder eigener Client läuft weiter. Bei
behebbarem Ausfall wird einmal mit den gespeicherten Werten neu gestartet,
höchstens ein solcher Wiederanlauf innerhalb von 30 Sekunden. Key-/Rechtefehler
und Provider-Drosselung lösen dabei keinen Neustart aus. Eine neue Kopplung
oder das erneute Eingeben des Runtime Keys ist für die Wiederherstellung nicht nötig.

Der Controller beobachtet den Remote-Tunnel weiter, auch nachdem „verbunden“
erreicht wurde. Ein alter Erfolgsstatus bleibt dadurch nicht unbegrenzt grün.
Ein erfolgreicher Providerkontakt darf höchstens 90 Sekunden zurückliegen;
der Client muss einen aktuellen, fehlerfreien Status liefern. Dies belegt
weiterhin nicht, dass die Werkzeuge in einem konkreten AI-Chat geladen sind.

**Für diese Erweiterung Controller und Bridge aktualisieren und die Bridge
einmal neu starten.** Bei einer alten Bridge ohne Updatefunktion die neue
Python-Datei herunterladen und anschließend mit dem bisherigen Bridge-Startbefehl
und demselben State-Verzeichnis starten. Fingerprint, Kopplung und gespeicherte
Tunnelwerte werden dabei weiterverwendet. [Ablauf und Grenzen](doc/RELEASE_V0.9.18.md).

### Frühere Terminalbefehle mit Pfeiltasten aufrufen

Im geöffneten Terminal ruft **Pfeil hoch** frühere Shellbefehle auf; **Pfeil runter**
geht wieder vorwärts bis zur aktuellen Eingabe. Erst Enter führt die bearbeitete
Zeile aus. Manuelle und bereits freigegebene Befehle verwenden dieselbe Bash-History.

Die History hält höchstens 1000 Einträge im Speicher der jeweiligen Shell.
Sie wird nicht auf Festplatte gespeichert und nicht aus der persönlichen
`.bash_history` importiert. Ein neues Terminal startet leer; bisherige Eingaben
aus Versionen ohne History können nicht nachträglich übernommen werden.
Direkt aufeinanderfolgende Duplikate und Zeilen mit führendem Leerzeichen werden
nicht aufgenommen. Bash-History-Ersetzungen wie `!!` sind ausgeschaltet.
Nach dem Update ein neues Terminal öffnen, damit diese Startkonfiguration gilt.

### Vorschlag vorhanden, aber „Prüfen“ ausgegraut?

Die lokale Terminalsitzung muss verbunden sein. Nach einem App-Neustart kann
die gespeicherte Bridge bereits wieder verbunden sein, während links noch
„Terminal öffnen“ angeboten wird. Zuerst dieses Terminal öffnen; anschließend
wird „Prüfen“ freigeschaltet. Ein Vorschlag wird dabei nicht ausgeführt.

Der Vorschlagsstatus nennt ab v0.9.16 den jeweiligen Sperrgrund: fehlendes oder
startendes Terminal, laufende Übernahme/Übertragung oder ein bereits aktiver
Commandreview. Einen aktiven Commandreview zuerst freigeben oder verwerfen.
Eine offene Ausgabeprüfung lässt sich weiterhin über den bestehenden Dialog
verlassen, um den neuen Vorschlag zu prüfen.

Die Anwendung bleibt ein früher MVP, keine Abnahme für kritische Infrastruktur.
„Konzept V0.7“, „MVP 0.8“ und der alte v0.0.1-Veröffentlichungsentwurf sind
historische Stände. Die Runtime-Versionsquelle ist `APP_VERSION` in
`admin_in_the_loop.py`; die eingebettete Bridge führt dieselbe Version separat.

Hosted ChatGPT-Work, offizielles Tunnelbinary und native Desktop-Abnahmen bleiben
offene separate Schritte; der aktuelle Verbindungs-Prüfnachweis steht in
[CONNECTION_UX.md](doc/CONNECTION_UX.md). Die Mac-Vorschau ist
nicht integriert. Der optionale sh-guard-Reviewer bleibt beim Erststart aus;
die bewusste Aktivierung wird gespeichert. Installation und lokale Analyse sind
mit gepinnten v0.1.10-Binaries integriert; siehe [sh-guard-Anleitung und Prüfnachweise](doc/SH_GUARD.md).

Der [Testbericht vom 30. September 2026](tests/MVP_0.8_TEST_REPORT.md) dokumentiert
damalige Linux-/Ubuntu-Prüfungen. Er belegt keine aktuelle native macOS- oder
Debian-Desktop-Abnahme und keinen echten ChatGPT-/OpenAI-Round-Trip. Eine lokale
Bereitschaftsmeldung ist kein Nachweis, dass der gewünschte AI-Chat verbunden ist.

Der [bebilderte Qubes-Verbindungsablauf](doc/CONNECTION_UX.md) zeigt die fünf Schritte,
Wiederherstellung und Fehlerhilfe aus der aktuellen Oberfläche.

## Sicherheitsmodell in Kürze

- **Zwei getrennte Freigaben:** Command ins Terminal und ausgewählten Output an
  die AI. Ein eingegangener Vorschlag bedeutet nicht, dass er ausgeführt wurde.
- **Gebundener Review:** Freigaben beziehen sich auf den konkreten Snapshot und
  den jeweiligen Terminal-/Bridge-Empfänger. Bearbeitung oder Verbindungswechsel
  macht alte Freigaben ungültig; sie werden nach Neustart nicht wiederhergestellt.
- **Begrenzter AI-Zugang:** Die separate Bridge stellt MCP-Tools für Vorschläge,
  Status, freigegebenen Output und Präferenzen bereit. Sie bietet der AI keine
  Shell-, Datei- oder direkten Terminal-Lesetools und keine Freigabeaktion.
- **Keine automatische Command-Wiederholung:** Bei ungewisser Terminalzustellung
  wird ein Command nicht automatisch erneut übertragen.

Menschliche Zustimmung ist keine Garantie für sichere Shellcommands. Commands
können selbst Dateien lesen, löschen oder Daten versenden. Automatische
Secret-Redaction ist nicht integriert. Die optionale statische Commandanalyse
unterstützt den Review, garantiert aber keine sichere Einstufung. Ausgewählter Output kann Secrets enthalten; Ausgabeintervalle sind
keine verifizierten Commandgrenzen oder Exitcodes.

Prozesse unter derselben Benutzerkennung sind keine starke Dateisystemisolation.
Der bewusst geteilte Chat-Code ist eine Bearer-Bindung, keine vom Provider
kryptografisch bestätigte Chat-ID. Details und Remote-TLS-/Pinning-Verhalten
stehen im [Sicherheitsmodell der Betriebsanleitung](tests/Local_Integration_README.md#sicherheitsmodell-und-präzisierte-grenzen).

## Terminal-Lebenszyklus: Detach gegenüber Ende

Das Controllerfenster und das Terminalfenster sind getrennte Systeme. Der Status
im Controller kann die konkrete Ursache eines Endes nicht immer unterscheiden.

- **Controllerfenster schließen (Detach):** Der Controller meldet dem Helfer ein
  sauberes Detach und beendet nur die Output-Erfassung. Die Shell im
  Terminalfenster und laufende Commands laufen weiter; das Fenster bleibt voll
  manuell bedienbar und wird nie wieder erfasst. Ein erneutes „Terminal öffnen“
  startet ein neues Terminal samt Helfer.
- **Terminalfenster schließen:** Der Helfer erhält SIGHUP und beendet sich; beim
  Aufräumen versucht er, die Shell und die aktuelle Vordergrund-Prozessgruppe
  gestaffelt zu beenden (SIGHUP, dann SIGTERM, dann SIGKILL). Prozesse, die sich
  selbst abgekoppelt haben (z. B. per nohup/setsid/disown), werden von diesen
  Signalen nicht erfasst; ob sie weiterlaufen, hängt von ihrer eigenen Abkopplung
  ab.
- **Shell-Ende (`exit`, EOF):** Der Helfer meldet dem Controller das Ende und
  beendet sich.

Bleibt das Controllerfenster offen, zeigt der Status nach Shell-Ende oder
Verbindungsverlust „Terminal getrennt“; er behauptet keine bestimmte Ursache, weil
der Controller sie nicht sicher kennt. Beim Schließen des Controllerfensters
(Detach) endet die Anwendung selbst – es bleibt kein Controller-Status sichtbar.

## Voraussetzungen

| Bereich | Voraussetzungen |
|---|---|
| Lokaler Controller | Unix, Python ≥ 3.11, Bash, Tkinter und grafische Sitzung |
| Linux-Terminalstart | `xfce4-terminal` mit nativem Copy/Paste-Kontextmenü; Debian-Paketnamen siehe unten |
| macOS-Terminalstart | Terminal.app und `/usr/bin/osascript`; ggf. Automation-Erlaubnis. Native Abnahme ist nicht belegt. |
| Lokale oder Remote-Bridge | Nur Python-Standardbibliothek im selben Python, das die Bridge startet |
| Remote-Kopplung / TLS | Zusätzlich `cryptography` auf den beteiligten Python-Seiten |
| OpenAI-Tunnel | Separater offizieller Tunnel-Client und eigene Tunnel-/Runtime-Konfiguration; siehe Setup-Anleitung |

Der lokale Controller und die Bridge verwenden neben Tkinter (Controller) und
cryptography (Remote-TLS-Zertifikatsgenerierung) die Python-Standardbibliothek.
Python-Abhängigkeiten werden nicht automatisch installiert. Der lokale
Tunnel-Setup-Flow kann den separaten Client auf den unterstützten Plattformen
finden bzw. installieren; Details und Grenzen stehen in der Betriebsanleitung.

## Lokaler Start aus dem Quellverzeichnis

Die Anwendung hat einen einzelnen Python-Einstieg:
[`admin_in_the_loop.py`](admin_in_the_loop.py). Die folgenden Befehle werden im
Repository-Verzeichnis ausgeführt. Es wird kein separates Anwendungspaket oder
Installer vorausgesetzt.

Für eine Debian-Desktop-Umgebung beschreibt die bestehende Anleitung:

```bash
sudo apt install python3 python3-tk xfce4-terminal
python3 admin_in_the_loop.py
```

Ohne Option startet die GUI; `python3 admin_in_the_loop.py --gui` ist ebenfalls
gültig. Das echte Terminal öffnet sich über „Terminal öffnen“ als separates
Systemterminal. Der [lokale Probelauf ohne AI](tests/Local_Integration_README.md#oberfläche-und-lokaler-probelauf)
führt durch Vorschlag, Review und die getrennten Freigaben.

Für Remote-Kopplung und TLS zusätzlich:

```bash
sudo apt install python3-cryptography
```

Diese Paketbefehle sind keine Behauptung einer abgeschlossenen Debian-Abnahme.
Unter macOS müssen Python ≥ 3.11, Tkinter und die benötigten Netzwerkbibliotheken
im verwendeten Python vorhanden sein; hier wird kein ungeprüfter macOS-Installer
angegeben. Weitere Hinweise stehen unter
[Voraussetzungen und Start](tests/Local_Integration_README.md#voraussetzungen-und-start).

## AI-Verbindung und Secure-Tunnel-Setup

Die vorhandene [Anleitung für lokale Bridge und OpenAI-Tunnel](tests/Local_Integration_README.md#lokale-bridge-und-openai-tunnel)
beschreibt Tunnel-ID, separaten Runtime API key, Einrichtung über „Lokal“,
Client-Installation, Chatbindung und den manuellen Round-Trip-Nachweis.
Provider-Links stehen in dieser Anleitung; dieses README ergänzt keine
unbelegten Setup-URLs.

Für einen getrennten Betriebsort gibt es die
[Remote-Bridge-/Gateway-Anleitung](tests/Local_Integration_README.md#remote-bridge--gateway).
Bridge und Tunnel sind separate Prozesse; der Tunnel-Client ist nicht in der
Python-Anwendungsdatei enthalten.

## Dokumentation und Prüfungen

- [Betriebsanleitung, Schnittstellen und Testbefehle](tests/Local_Integration_README.md)
- [Produkt-/Konzeptreferenz V0.7](doc/Admin-in-the-Loop_Konzept_V0.7.md)
- [Historischer Implementierungsstand](IMPLEMENTATION_STATUS.md)
- [Historischer MVP-0.8-Testbericht](tests/MVP_0.8_TEST_REPORT.md)
- [Orchestrator-Skill-Beilage](skill/SKILL.md) – Bedienhilfe, keine Sicherheitsbarriere
- [Branding-Assets und Hintergrundvarianten](doc/assets/branding/README.md)
- [Changelog / aktuelle Testversion](CHANGELOG.md)
- [Historische v0.0.1-Release-Vorbereitung](doc/RELEASE_V0.0.1.md)

Aktuelle Arbeit und Abnahmen werden im Taskboard geführt; historische
Statusdateien und Berichte sind keine laufenden Aufgabenlisten.

## Lizenz

Die vorhandene [`LICENSE`](LICENSE) enthält die MIT License,
Copyright © 2026 Geektank Labs.
