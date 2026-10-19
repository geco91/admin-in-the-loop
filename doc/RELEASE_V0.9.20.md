# v0.9.20 · Zwischenablage ohne Terminal und Tunnel-Health-Korrektur

## Zwischenablage

In v0.9.19 blieb „Prüfen“ auch für die Zwischenablage ohne verbundene lokale
Shell deaktiviert. Zwischenablagetext kann jetzt bei geschlossenem oder
getrenntem Terminal übernommen, bearbeitet, in der Byteansicht geprüft und
nach ausdrücklicher Freigabe geteilt werden. Dieser Review ist nicht an eine
Terminalsitzung gebunden und bleibt bei deren Trennung gültig. Bridge-Bindung,
Pause und Übertragungssperren gelten weiterhin. Commands und echte
Terminalausgaben brauchen unverändert die passende lokale Terminalsitzung.

## Tunnel-Regression aus v0.9.18

Die Bridge verlangte bei einem erfolgreichen Healthcheck zusätzlich einen
expliziten `details.http_status` zwischen 200 und 299. Der offizielle Client
v0.0.15 setzt seinen internen HTTP-Fehlerstatus bei Erfolg auf null und lässt
das Feld beim JSON-Encoding aus. So konnte der Tunnel bereits MCP-Anfragen
weiterleiten, während unsere Bridge weiter „starting“ meldete und den Client
nach 120 Sekunden mit `tunnel_status_timeout` beendete.

Belegt im offiziellen Quellstand v0.0.15:
[PollHealth.Succeeded / Snapshot](https://github.com/openai/tunnel-client/blob/v0.0.15/pkg/controlplane/health.go)
und [PollingDetails / omitempty](https://github.com/openai/tunnel-client/blob/v0.0.15/pkg/healthstate/operations.go).

Die Bridge akzeptiert das gemäß Vertrag fehlende Feld. Explizit vorhandene
Werte müssen weiterhin echte ganze Zahlen im 2xx-Bereich sein; null, nullwertiger
Status, boolesche Werte, Strings und Fehlercodes werden nicht als Erfolg
anerkannt. Zusätzlich nötig bleiben Status „ok“, ein höchstens 90 Sekunden alter
Erfolg, keine Fehlerkategorie und null aufeinanderfolgende Fehler. Ein alter
Erfolg verdeckt weder aktuelle Drosselung noch Key-/Rechtefehler. Wiederanlauf-
Grenzen, Authentifizierung und gespeicherte Konfiguration bleiben erhalten.

## Prüfung und Grenzen

Bestehende unittest-/Tk-/PTY-/HTTP-Infrastruktur, keine neuen Abhängigkeiten.
Bestanden unter Linux/Python 3.12 mit Xvfb: 50 GUI-/Statusfälle, 11 Übernahme-/
Rückgabefälle, 49 Selbsttests, 11 Updatefälle und 10 Bridge-Tunnelfälle.
Ein zusätzlicher Roundtrip mit dem echten offiziellen Tunnel-Client v0.0.15
bestand ebenfalls: SHA-256-geprüftes gepinntes Release, lokaler HTTP-Control-
Plane-Testserver, echter MCP-/PTY-Freigabeablauf und Auswertung der unveränderten
Health-Antwort durch den Bridge-Parser. Insgesamt 132 bestandene Fälle.
`git diff --check` ist sauber.

Der neue GUI-Fall führt die Zwischenablage bei nie geöffneter Shell durch Lesen,
Bearbeiten, Pause und ausdrückliche Bridge-Rückgabe. Terminal-Lifecycle-Wechsel
bewahrt den Review; Bridge-Trennung entwertet ihn. Terminalprüfungen bleiben
ohne lokale Sitzung gesperrt. Die erweiterten Healthfälle prüfen ausgelassenes
Statusfeld, ungültige vorhandene Werte, Fehlerkategorie, Drosselung und Alter.

Die echte Providerverbindung zum Nutzergerät, native Qubes-/macOS-Abnahme und
die Werkzeugbereitstellung in einem konkreten Chat sind hier nicht belegt.
Ein einzelnes „mcp: abgewiesen“ braucht bei fortbestehenden Problemen seinen
genauen Fehlercode; diese Meldung allein belegt weder ungültige Credentials
noch die Ursache des Tunnel-Timeouts. Die lokalen Clipboard-Grenzen aus
[v0.9.19](RELEASE_V0.9.19.md) gelten weiterhin, die Terminalpflicht entfällt.

## Aktualisieren

[Python-Datei](https://raw.githubusercontent.com/geco91/admin-in-the-loop/refs/tags/v0.9.20/admin_in_the_loop.py) ·
[ZIP](https://github.com/geco91/admin-in-the-loop/archive/refs/tags/v0.9.20.zip)

Controller und Bridge auf v0.9.20 bringen. Bei geschlossener Controller-App:
`python3 admin_in_the_loop.py update geco91`. Für die Bridge dieselbe neue Datei
am Bridge-Standort bereitstellen und den Bridge-Prozess mit dem bisherigen
Startbefehl und **demselben State-Verzeichnis** neu starten. Kein Löschen von
Kopplung, Pins oder Credentials. Das Controller-Update allein behebt die
Bridge-seitige Health-Auswertung nicht.
