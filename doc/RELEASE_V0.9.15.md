# v0.9.15 · persönliche Testversion

Veröffentlichungsziel ist der bestehende Fork
[geco91/admin-in-the-loop](https://github.com/geco91/admin-in-the-loop), Branch
`main`, mit Git-Tag `v0.9.15`. Dies ist kein Installerpaket und keine Änderung
am Original-Repository `GeektankLabs/admin-in-the-loop`.

## Download und Umfang

- [Anwendungsdatei](https://raw.githubusercontent.com/geco91/admin-in-the-loop/refs/tags/v0.9.15/admin_in_the_loop.py)
- [Quellcode, Dokumentation und Tests als ZIP](https://github.com/geco91/admin-in-the-loop/archive/refs/tags/v0.9.15.zip)
- [Start und Update](../README.md#herunterladen-und-ausprobieren)

Controller, GUI, Terminalhelfer und headless Bridge sind in der Python-Datei
enthalten. Der Download benötigt zum Start keine Dateien aus dem Repository.
Python/Tkinter, Systemterminal, optionale TLS-Bibliothek und offizieller
OpenAI-Tunnel-Client bleiben separate Laufzeitvoraussetzungen.

Der Stand bündelt die bisherigen lokalen Änderungen v0.9.6–v0.9.14:
sh-guard-Integration und Einrichtung, große Code-/Ausgabeansicht mit seitlich
einstellbaren Prüfreitern, überarbeitete AI-Verbindung und Wiederherstellung,
erneutes Prüfen und Teilen späterer Ausgabe desselben Commands sowie
Copy/Paste-Kontextmenüs einschließlich XFCE Terminal. v0.9.15 ergänzt das
ausdrückliche Selbstupdate. Details stehen im [Changelog](../CHANGELOG.md).

## Updatequelle und Rückkehr

`python3 admin_in_the_loop.py update` verwendet das Original GeektankLabs/main.
`update geco91` verwendet den hier veröffentlichten Fork; `update geco91 BRANCH`
einen ausdrücklich gewählten Branch. `--update` ist gleichwertig. Ein anderes
Konto setzt ein öffentliches Repository mit demselben Namen und Aufbau voraus.

Es gibt keine automatische Updateprüfung und keine Änderung des Codes durch
eine AI-Freigabe. Nur der lokale CLI-Aufruf aktualisiert diese Datei. Ein Update
vertraut dem angegebenen GitHub-Konto und Branch; die Strukturprüfung ist keine
Codeprüfung oder unabhängige Herausgebersignatur. Der angezeigte SHA-256-Wert
dokumentiert den heruntergeladenen Inhalt und stammt nicht aus einer zweiten
Vertrauensquelle. Bei einem Fehler vor dem Dateitausch bleibt die alte Datei
erhalten; ein Backup enthält jeweils die vorherige Fassung. Ein expliziter
Branchwechsel kann auch eine ältere Version installieren.

Zum Rückwechsel bei geschlossener App die `.bak`-Datei an Stelle der aktuellen
Python-Datei kopieren. Einstellungen werden dabei nicht zurückgesetzt. Getrennt
installierte Bridge-/Controller-Kopien separat aktualisieren und neu starten.

## Prüfnachweis und verbleibende Grenzen

Die vorhandenen unittest-/Tk-/PTY-Suiten werden verwendet; keine zusätzliche
Testinfrastruktur. 11 neue Updatetests in `tests/test_local_setup.py` prüfen
Default/Fork/Branch, CLI-Rollentrennung, Quellenvalidierung, HTTPS-Download,
Größenlimit, Syntax-/Versionsprüfung ohne Ausführung, idempotentes Update,
Dateimodus, Backup und unveränderte Einstellungen sowie Fehler vor dem Dateitausch.

Prüfung am 19. Oktober 2026 unter Linux/Python 3.12 mit Xvfb:

- unittest-Gesamtlauf: 354 Fälle, davon zunächst 348 bestanden, vier externe
  Prüfungen übersprungen und zwei Testprobleme. Ein Roundtrip wählte Ausgabe vor
  deren tatsächlichem Eintreffen; er wartet nun auf den echten zweiten Marker.
  Die Qrexec-Prüfung erwartete noch den alten Hinweistext und prüft nun die neue
  Formulierung mit weiterhin offener Ursachenklärung.
- Nachlauf der beiden betroffenen Klassen: 17 Fälle, 16 bestanden, ein externer
  ChatGPT-Work-Fall übersprungen. Damit sind alle 350 lokal ausführbaren Fälle
  über Gesamtlauf und gezielten Nachlauf bestanden; kein erneuter Gesamtlauf
  nach den beiden reinen Testkorrekturen.
- 45 GUI-/Statusfälle bestanden, einschließlich Kopieren/Einfügen, wiederholtem
  Ausgabereview und getrennten Freigaben; 49 Selbsttests bestanden.
- Alle elf neuen Updatefälle bestanden. `--version`, CLI-Hilfe und
  `git diff --check` geprüft. Die sh-guard-Integration verwendete das echte
  gepinnte Linux-Archiv v0.1.10.

Die vier externen Fälle benötigen einen echten ChatGPT-Work-Host bzw. ein
bereitgestelltes offizielles Tunnel-Client-Binary; sie sind keine bestätigten
Live-Providerprüfungen. Download-/Tagkontrolle und ein Update einer temporären
Einzeldatei gegen den veröffentlichten Fork erfolgen beim Veröffentlichungsabschluss.

Kein nativer Qubes-/macOS-Test und kein echter ChatGPT-/OpenAI-Tunnel-Roundtrip
für diesen Stand. Qrexec-/Providerzustände in Beispielbildern sind als Testfälle
ausgewiesen. Die Review-Layoutbilder stammen aus den echten Linux-Tk-Widgets.
Ein Inhalts-/Datenschutzscan von Terminalausgabe ist weiterhin nicht integriert.
Die App bleibt eine persönliche Testversion mit den im README beschriebenen Grenzen.
