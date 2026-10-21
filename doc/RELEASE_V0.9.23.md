# v0.9.23 · Mehr Platz ohne doppelte Titelzeile

Die zusätzliche Überschrift „Admin in the Loop“ oberhalb der drei Arbeitsbereiche
ist entfernt. Ihre reservierte Layoutzeile entfällt ebenfalls; die Arbeitsfläche
beginnt direkt am oberen Inhaltsrand. Der native Fenstertitel enthält weiterhin
App-Namen und Version.

Vier bestehende GUI-Fälle bestanden unter Linux/Python 3.12 mit Xvfb, darunter
Einzeldateistart aus fremdem Verzeichnis, helle/dunkle Darstellung, Logo-Fallback
und Spalten-/Buttonanordnung bei verschiedenen Fensterbreiten. Der bestehende
Versionskonsistenztest bestand ebenfalls; `git diff --check` ist sauber.
Native Qubes-/macOS-Darstellung wurde hier nicht geprüft.

[Python-Datei](https://raw.githubusercontent.com/geco91/admin-in-the-loop/refs/tags/v0.9.23/admin_in_the_loop.py) ·
[ZIP](https://github.com/geco91/admin-in-the-loop/archive/refs/tags/v0.9.23.zip)

Bei geschlossener App: `python3 admin_in_the_loop.py update geco91`.
Nur das Controller-Update ist nötig; die bereits aktualisierte Bridge kann
weiterlaufen. Der [Zwischenablage-/Terminalmodus aus v0.9.22](RELEASE_V0.9.22.md)
ist weiterhin enthalten.
