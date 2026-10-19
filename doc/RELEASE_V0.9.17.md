# v0.9.17 · Pfeiltasten-History im Terminal

Die innere Bash startete bisher mit `HISTSIZE=0`. Deshalb konnten die an das echte
Terminal weitergereichten Pfeiltasten keine früheren Befehle aufrufen.
Der interaktive Helfer aktiviert jetzt die vorhandene Bash-/Readline-History
mit `HISTSIZE=1000`; die isolierten Low-Level-Probes behalten ihren bisherigen
Standard ohne History. Es gibt keinen zusätzlichen Verlaufsspeicher im Controller
und keine neue Bridge-Schnittstelle zum Abfragen der History.

Pfeil hoch/runter navigiert durch manuelle und bereits freigegebene Shellbefehle.
Das Aufrufen allein führt nichts aus; Enter führt die aktuelle Zeile als bewusste
manuelle Terminaleingabe aus. Diese ist wie bisher von den AI-Freigaben getrennt.
Nach dem Update ein neues Terminal öffnen; bereits laufende Shells übernehmen
geänderte Startoptionen nicht automatisch.

`HISTFILE=/dev/null` und `HISTFILESIZE=0` verhindern eine persistente Historydatei.
Ein neues Terminal importiert weder alte Sitzungen noch die persönliche
`.bash_history`. Direkt aufeinanderfolgende Duplikate und mit Leerzeichen
beginnende Zeilen werden nicht aufgenommen. Die Shell-History bleibt beim
Detach im weiterlaufenden Terminal erhalten und endet mit dieser Shell.
Readline verwendet die Standardbelegung ohne persönliche Inputrc-Datei.
Bash-History-Ersetzung ist mit `+H` deaktiviert: `!!` wird nicht vor der Ausführung
in einen anderen Befehl umgeschrieben. Die bestehenden Review-/Transferfreigaben
bleiben bestehen; die AI kann keine Pfeiltasten außerhalb ihrer regulären,
lokal zu prüfenden Vorschläge einschleusen.

## Bezug und Prüfung

[Python-Datei](https://raw.githubusercontent.com/geco91/admin-in-the-loop/refs/tags/v0.9.17/admin_in_the_loop.py) ·
[ZIP](https://github.com/geco91/admin-in-the-loop/archive/refs/tags/v0.9.17.zip)

Bei geschlossener Controller-App: `python3 admin_in_the_loop.py update geco91`,
danach App und ein neues Terminal starten. Der Controller-/Terminalhelfer enthält
die Änderung; eine separat laufende Bridge benötigt dafür kein Update.

Drei neue Tests in der bestehenden lokalen Testsuite verwenden echte PTYs,
den echten Helfer und Bash/Readline. Sie prüfen Aufrufen mit Hoch/Runter ohne
Ausführung, bewusste manuelle Wiederholung erst nach Enter, gemeinsame History
manueller und freigegebener Befehle, RAM-Konfiguration und leere neue Sitzung
sowie die unveränderte Ausführung eines freigegebenen `!!`-Literals.
Bestanden unter Linux/Python 3.12: drei neue Historyfälle, 49 vorhandene
Selbsttests, 47 GUI-/Statusfälle unter Xvfb, elf Updater-Fälle und der
Versionskonsistenztest, insgesamt 111 Fälle. Die Tastaturprüfung deckt normale
und Application-Cursor-Sequenzen ab. `git diff --check` ist sauber.

Native Qubes-/macOS-Abnahme und ein Live-OpenAI-Roundtrip sind hier nicht belegt.
Persistente, sitzungsübergreifende History ist nicht Teil dieser Erweiterung.
