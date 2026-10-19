# v0.9.18 · Frische Tunnelprüfung nach Controller-Kontakt

Nach App-Neustart bzw. erneutem Verbindungsaufbau bestätigt der Controller seine
gespeicherte authentifizierte Bridge-Verbindung. Bisher blieb ein einmal als
„connected“ eingestufter Tunnel ohne weitere Healthchecks verbunden angezeigt;
auch die Controller-Beobachtung endete beim ersten Erfolg. Nach Ruhezustand oder
Netzverlust konnte daher ein alter Erfolgsstatus stehen bleiben.

## Verhalten

Die bestätigte Controller-Verbindung löst einen Hintergrundcheck aus, ohne neue
Kopplung oder Rotation des Chat-Codes. Die Bridge fragt den lokalen offiziellen
Tunnel-Client unter `/health/control-plane` ab. Ein verbundener Tunnel benötigt
einen erfolgreichen HTTP-Status, `status=ok`, keine aufeinanderfolgenden Fehler
und einen erfolgreichen Providerkontakt innerhalb von 90 Sekunden. Zeitstempel
über 30 Sekunden in der Zukunft werden ebenfalls nicht als aktuell akzeptiert.

Ein gesunder eigener Client läuft weiter. Ein behebbarer Ausfall (z. B. beendeter
Prozess, veralteter Poll oder Netzfehler) kann nach Controller-Confirm mit der
bereits geschützten Konfiguration einmal neu gestartet werden. Wiederholte
Bestätigungen starten weder parallele Clients noch weitere Versuche während
eines laufenden Starts. Zwischen Wiederanläufen liegen mindestens 30 Sekunden.
Fehlende Konfiguration, falsche Keys, fehlende Rechte, unbekannte Tunnel,
Provider-Drosselung, ungeeignete Clients und Installationsfehler werden nicht
auf diese Weise automatisch behoben. Abbruch und Beenden verhindern verspäteten
Prozessstart; nur der Bridge-eigene Client wird verwaltet.

Die Remote-Statusbeobachtung läuft bei verbundenem Controller weiter. Ein
gesunder Zustand endet nicht mehr nach dem früheren Gesamtzeitlimit; eine nicht
bestätigte Wiederverbindung bleibt zeitlich begrenzt. GET-Abfragen beobachten
nur und lösen keinen Wiederanlauf aus. Bei Ausfall im laufenden Betrieb kann
der bestehende Client zunächst selbst wieder verbinden. Bleibt der Fehler,
zeigt der Controller diesen an; ein erneuter authentifizierter Controllerkontakt
kann den begrenzten Wiederanlauf auslösen. Es gibt keine unbeschränkte Retry-Schleife.

Diese Prüfung verbraucht keine MCP-Arbeit und sendet keine Terminalcommands.
Ein verbundener Tunnel belegt weiterhin nicht, dass ein Chat-Host dessen
Werkzeuge geladen hat. Der echte Tunnel zum Nutzergerät wurde hier nicht geprüft.

## Aktualisieren

[Python-Datei](https://raw.githubusercontent.com/geco91/admin-in-the-loop/refs/tags/v0.9.18/admin_in_the_loop.py) ·
[ZIP](https://github.com/geco91/admin-in-the-loop/archive/refs/tags/v0.9.18.zip)

Controller und Bridge auf v0.9.18 bringen. Bei geschlossener Controller-App:
`python3 admin_in_the_loop.py update geco91`. Für die Bridge dieselbe neue Datei
an ihrem Betriebsort bereitstellen und den alten Bridge-Prozess anschließend
mit dem bisherigen Startbefehl und **demselben State-Verzeichnis** neu starten.
Kein Löschen oder Zurücksetzen der Konfiguration; Pin, Controller-Zugang und
Tunnelwerte bleiben bestehen. Eine alte Bridge ohne Updatefunktion kann die
Datei über den direkten Download erhalten. Nur ein Controller-Update reicht
für den Bridge-seitigen Wiederanlauf nicht aus.

## Prüfnachweis

Die bestehende unittest-/HTTP-/TLS-/Tk-/PTY-Infrastruktur wird verwendet.
Gezielte Tests prüfen gesunden Client ohne Neustart, veralteten Poll, aktuelle
Provider-Drosselung trotz älterem Erfolg, Wiederanlauf und Cooldown, fehlende
Konfiguration, Key-/Rechtefehler, Abbruch während des Healthchecks sowie die
Controller-Authentifizierung vor dem Recovery-Auslöser. Ein echter lokaler
HTTP-Healthserver liefert kontrollierte Zeitstempel und Statuswechsel. Weitere
Tests prüfen kontinuierliche Beobachtung und begrenzte Wartezeit nach Ausfall
sowie die Wiederherstellung einer echten lokalen TLS-Bridge mit unverändertem Pin.

Bestanden unter Linux/Python 3.12 mit Xvfb: Gesamtlauf mit 361 Fällen,
davon 357 bestanden und vier externe Fälle übersprungen; zusätzlich 47
GUI-/Statusfälle und 49 Selbsttests bestanden. Nach der abschließenden
Healthcheck-Verschärfung bestanden die 21 gezielten Tunnel-/Recovery-Fälle
erneut. Der echte lokale Bridge-/PTY-Roundtrip ist enthalten. Die vier externen
Fälle benötigen einen ChatGPT-Work-Host bzw. ein bereitgestelltes offizielles
Tunnel-Client-Binary. `git diff --check` ist sauber.

Native Qubes-/macOS-Abnahme, ein Live-OpenAI-Tunnel und die Werkzeugbereitstellung
im konkreten Nutzerchat sind hier nicht belegt. Es werden keine Zugangsdaten in
Logs oder Statusantworten ergänzt und keine neuen Python-Abhängigkeiten benötigt.
