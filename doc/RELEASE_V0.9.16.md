# v0.9.16 · Hinweis bei deaktiviertem „Prüfen“

Die Prüfung benötigt eine verbundene lokale Terminalsitzung, an die der konkrete
Review gebunden wird. Eine authentifizierte Remote-Bridge und ein laufender
Secure Tunnel allein erfüllen diese Voraussetzung nicht. Nach einem App-Neustart
bleibt das Terminal zunächst geschlossen; die gespeicherte Bridge kann bereits
wiederhergestellt sein. In v0.9.15 steht dabei „Command-Vorschlag vorhanden“,
während „Prüfen“ ohne direkt zugeordneten Hinweis deaktiviert ist.

v0.9.16 nennt den Grund und den nächsten Schritt beim vorhandenen Vorschlag:
Terminal öffnen, Terminalstart abwarten, laufende Übernahme/Übertragung abwarten,
ungewisse Ausgabezustellung klären oder den aktiven Commandreview freigeben bzw.
verwerfen. Ein geparkter Vorschlag wird ebenfalls korrekt ausgewiesen.
Die vorhandenen Sperren und der Konfliktdialog beim Wechsel aus einer
Ausgabeprüfung bleiben erhalten. Der Patch ändert keine Core-, Bridge- oder
Freigabelogik und startet keine Terminals oder Commands automatisch.

Für den Fall „Terminal noch geschlossen“ genügt bereits in v0.9.15 links
„Terminal öffnen“. Das Update verbessert die Erklärung; ein Fehler bei bereits
verbundenem Terminal und freiem Review wurde in den untersuchten Fällen nicht
reproduziert. Die Anzeige des betroffenen Nutzergeräts wurde nicht direkt gelesen.

## Bezug

[Python-Datei](https://raw.githubusercontent.com/geco91/admin-in-the-loop/refs/tags/v0.9.16/admin_in_the_loop.py) ·
[ZIP](https://github.com/geco91/admin-in-the-loop/archive/refs/tags/v0.9.16.zip)

Bei geschlossener Controller-App: `python3 admin_in_the_loop.py update geco91`,
danach die App neu starten. Für diesen UI-Fix genügt die Aktualisierung des
Controllers. Der [v0.9.15-Prüfbericht](RELEASE_V0.9.15.md) dokumentiert den übrigen
Veröffentlichungsumfang.

## Prüfung

Die vorhandene Tk-/unittest-Infrastruktur wird verwendet. Zwei zusätzliche
GUI-Regressionen prüfen den Fall „Bridge/Tunnel verbunden, Terminal fehlt“,
den Übergang nach dem Terminal-Ready-Ereignis ohne erneuten Vorschlag, sichtbare
Hinweise bei 960×560 und 1360×850 sowie alle bestehenden Stage-/Übertragungssperren.
Die Prüfungen bestätigen, dass das bloße Laden in den Review nichts ins Terminal
überträgt.

Bestanden unter Linux/Python 3.12 mit Xvfb: 47 GUI-/Statusfälle einschließlich
der zwei neuen Regressionen und des echten lokalen Bridge-/PTY-Roundtrips,
18 sh-guard-UX-Fälle, elf Updater-Fälle und der Versionskonsistenztest.
`git diff --check` ist sauber. Keine zusätzlichen Testsuiten oder Abhängigkeiten.

Native Qubes-/macOS-Darstellung und ein Live-OpenAI-Tunnel wurden für diesen
Darstellungspatch nicht geprüft. Die Bridge-/Tunnelanzeige des neuen GUI-Falls ist
ein kontrollierter Testzustand; der bestehende GUI-Roundtrip nutzt eine echte
lokale Bridge und PTY-Sitzung.
