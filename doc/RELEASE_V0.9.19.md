# v0.9.19 · Zwischenablage als Rückgabequelle

Links unter **Ausgabebereich → Zwischenablage** wählen und **Prüfen →** klicken.
Erst dieser Klick liest die aktuelle lokale Text-Zwischenablage. Der Text liegt
anschließend als fester Schnappschuss im mittleren Reiter „Zwischenablage“.
Änderungen der Zwischenablage ändern diesen Review nicht. Bearbeiten und
anschließendes ausdrückliches Freigeben verwenden den bestehenden Ausgabeablauf.
Nach Abschluss kann „Prüfen“ einen neuen Schnappschuss übernehmen.

Die Ausgabe ist standardmäßig eine unabhängige Beobachtung. Eine automatische
Zuordnung zum zuletzt ausgeführten Command findet nicht statt. Der vorhandene
Zuordnungswähler erlaubt weiterhin eine ausdrückliche Zuordnung. Eine offene
Terminalrückgabe bleibt auch dann offen; weder Freigeben noch Verwerfen einer
Zwischenablageprüfung schließt sie ab. Die Quellenkennzeichnung überlebt das
Bearbeiten. Eine aktive Prüfung wird nicht überschrieben: Sie muss zuerst
abgeschlossen oder ausdrücklich verworfen werden. Pause, Sitzungsbindung und
bestehende Freigabesperren gelten weiter. Es wird kein Command ausgeführt.

## Grenzen

Nur lokal verfügbarer Text, keine Bilder oder Dateien. Die bestehenden Grenzen
von 64 KiB UTF-8 und der Nachrichtenhülle gelten; insbesondere viele Escapezeichen
können das Hüllenlimit früher erreichen. Unsichtbare Steuerzeichen einschließlich
Tabs werden wie bei Terminalausgaben abgewiesen. Leere oder nicht verfügbare
Text-Zwischenablage erhält einen Hinweis. Die bestehende verbundene lokale
Terminalsitzung ist weiterhin Voraussetzung. Unter Qubes den Text zunächst in
die Zwischenablage des App-Qubes übertragen; keine Umgehung der Qube-Grenzen.

## Prüfnachweis

Die bestehende unittest-/Tk-/PTY-/HTTP-Infrastruktur wird verwendet, ohne neue
Abhängigkeiten oder Testinfrastruktur. Neue Fälle prüfen tatsächliches Lesen der
Tk-Zwischenablage erst beim Klick, Quellenanzeige, unveränderlichen Schnappschuss,
erneutes Einlesen nach Freigabe, fehlenden Text und Schutz der aktiven Prüfung.
Der echte lokale MCP-/PTY-Roundtrip prüft Bearbeiten, Pause, ausdrückliche
Freigabe, unabhängige sowie bewusst gewählte Command-Zuordnung und Fortbestand
der ursprünglichen Terminalrückgabe. Eine gesperrte Terminal-Schreibfunktion
belegt, dass dieser Ablauf keine Terminaleingabe sendet.

Bestanden unter Linux/Python 3.12 mit Xvfb: 11 Übernahme-/Rückgabefälle,
11 lokale Connected-Roundtrip-Fälle, 49 Selbsttests, 11 Updatefälle und 49
GUI-/Statusfälle. Ein zusätzlicher Roundtrip-Fall für einen externen Chat-Host
wurde übersprungen. Die beiden gezielten Clipboard-Core-Fälle wurden nach der
Ergänzung des ausdrücklich zugeordneten Rückgabefalls erneut erfolgreich geprüft.
`git diff --check` ist sauber. Native Qubes-/macOS-Abnahme und ein Roundtrip zum
Nutzergerät bzw. konkreten Chat-Host sind hier nicht belegt.

## Bezug

[Python-Datei](https://raw.githubusercontent.com/geco91/admin-in-the-loop/refs/tags/v0.9.19/admin_in_the_loop.py) ·
[ZIP](https://github.com/geco91/admin-in-the-loop/archive/refs/tags/v0.9.19.zip)

Bei geschlossener Controller-App: `python3 admin_in_the_loop.py update geco91`.
Für diese Erweiterung genügt das Controller-Update; gegenüber v0.9.18 ändert sich
kein Bridge-Protokoll. Der Tunnel-Wiederanlauf aus v0.9.18 benötigt weiterhin eine
Bridge ab v0.9.18.
