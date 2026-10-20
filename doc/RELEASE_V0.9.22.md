# v0.9.22 · Automatischer Zwischenablage-Fallback und gemeinsame Moduswahl

Ohne geöffnete lokale Shell startet die App mit Zwischenablage als Rückgabequelle
und als Ziel für AI-Vorschläge. Ein vorhandener Vorschlag kann sofort übernommen,
geprüft, bearbeitet und ausdrücklich kopiert werden. Der bisherige Hinweis
„Zuerst links Terminal öffnen“ erscheint in diesem Modus nicht.

Nach dem bestätigten Terminalstart gelten Terminal und **Letzter Command** als
Standard für neue Vorgänge. Bei Terminaltrennung wird wieder Zwischenablage
gewählt. Ein bereits zur Zwischenablage übernommener Review bzw. ausstehender
Take behält beim Shellstart sein festes Kopierziel; der Standardwechsel erteilt
keine Terminalfreigabe. Manuelle Auswahl bleibt bis zum nächsten solchen
Lifecycle-Wechsel erhalten; der erste bestätigte Command-Transfer setzt wie
bisher die Rückgabeauswahl auf die Ausgabe seit diesem Command.

## Manuelle Moduswahl

**Ausgabebereich → Zwischenablage** schaltet jetzt auch das AI-Ziel auf
Zwischenablage. In v0.9.21 waren beide Auswahlen unabhängig: Links konnte bereits
Zwischenablage stehen, während der rechte Freigabeweg weiterhin Terminal war.
Beide Anzeigen werden nun synchronisiert. Eine Terminalausgabe-/Zeilenauswahl
schaltet zurück zum Terminalziel; die rechte Zielauswahl aktualisiert entsprechend
den Ausgabebereich. Während Übernahme oder Zustellung ist Umschalten gesperrt.

Wird ein offener Command manuell umgeschaltet, entsteht ein neuer Review mit
neuer ID/Revision und passender Return-Behandlung. Submission-Zuordnung,
Ablaufzeit und Bearbeitungsstatus bleiben erhalten. Der vorherige Snapshot und
seine Analyse/Freigabe werden ungültig. Im Zwischenablage-Modus ist außerdem
der normale Terminalfreigabeweg im Core gesperrt. Der Kopierbutton schreibt
nur den neu geprüften Text; kein finales Return wird angehängt und keine
Terminalrückgabe oder Ausführung wird dadurch erzeugt. Offene Rückgaben früherer
Commands bleiben erhalten.

**Letzter Command** ist auch direkt nach dem Terminalstart auswählbar. Noch ohne
freigegebenen Command zeigt „Prüfen“ einen verständlichen Hinweis. Die Auswahl
meint die vorhandene, aus der App freigegebene Command-Übertragung. Manuelle
Shell-Befehle bekommen durch diese Änderung keine neue automatische Zuordnung;
für deren Ausgabe bleibt die Auswahl eines Zeilenbereichs verfügbar.

## Validierung

Bestehende unittest-/Tk-/PTY-/HTTP-Infrastruktur, keine neuen Abhängigkeiten.
Neue Fälle prüfen Start ohne Terminal, Annahme eines Vorschlags ohne zusätzliche
Zielwahl, Standardwechsel bei „bereit“ und Trennung, Erhalt eines bereits
festgehaltenen Kopierziels, Umschalten eines offenen Terminalvorschlags und
Invalidierung seiner alten Freigabe. Der GUI-Fall verwendet eine echte lokale
Bridge und ein Terminal: Nach Umschalten auf Zwischenablage führt der Vorschlag
keine Terminal-Schreiboperation aus und legt seine Testdatei nicht an. Kopieren
ändert die Zwischenablage erst beim ausdrücklichen Klick.

Unter Linux/Python 3.12 mit Xvfb bestanden 52 GUI-/Statusfälle, 49 Selbsttests,
22 Risikoanalysefälle, 19 Installations-UI-Fälle, 18 sh-guard-UX-Fälle, 13
Review-Korrekturfälle, 12 native sh-guard-/Proxy-Integrationsfälle und 11 Updatefälle.
Synthetisch als verbunden gesetzte Test-Shells wählen jetzt explizit den
Terminalmodus, entsprechend dem echten „bereit“-Event.

Der Connected-Gesamtlauf umfasste 218 Fälle: zunächst 212 bestanden, drei Fehler
und drei übersprungene optionale/externe Fälle. Zwei alte Review-Testobjekte
wurden um die bereits vorhandene Quellenangabe ergänzt. Ein Beobachtungstest
wartet jetzt auf die tatsächliche Ausgabe und fragt den Status höchstens fünfmal
pro Sekunde ab, statt durch enge Polls das bestehende Rate-Limit zu verbrauchen.
Alle drei betroffenen Fälle bestanden danach gezielt. Die zwei zunächst mangels
Binary übersprungenen offiziellen Tunnel-Client-Fälle bestanden anschließend mit
dem SHA-256-geprüften Client v0.0.15. Damit sind alle 217 hier ausführbaren
Connected-Fälle belegt; der externe ChatGPT-Work-Host-Fall bleibt offen.
Insgesamt 413 bestandene Fälle, ein externer Fall nicht ausführbar.
`git diff --check` ist sauber.

Native Qubes-/macOS-Abnahme, der echte Nutzer-Tunnel und Werkzeuge im konkreten
Chat sind hier nicht belegt. Das Qubes-Clipboard muss weiterhin vom Nutzer in
den App-Qube übertragen werden. Es gibt kein Umgehen von Qube-Grenzen, keine
zusätzliche Terminalausführung und kein automatisches Teilen von Clipboardtext.

## Aktualisieren

[Python-Datei](https://raw.githubusercontent.com/geco91/admin-in-the-loop/refs/tags/v0.9.22/admin_in_the_loop.py) ·
[ZIP](https://github.com/geco91/admin-in-the-loop/archive/refs/tags/v0.9.22.zip)

Bei geschlossener Controller-App: `python3 admin_in_the_loop.py update geco91`.
Für diese Änderung genügt das Controller-Update. Das Bridge-Protokoll bleibt
unverändert; die Tunnelkorrektur aus v0.9.20 benötigt weiterhin eine Bridge ab
v0.9.20. Eine bereits auf v0.9.21 laufende Bridge muss dafür nicht neu gestartet
werden.
