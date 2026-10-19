# v0.9.21 · AI-Vorschläge nach Prüfung in die Zwischenablage kopieren

Rechts **Ziel für AI-Vorschläge → Zwischenablage** wählen. Dann wie gewohnt den
AI-Vorschlag über **← Prüfen** übernehmen. Code und aktive Prüfreiter bleiben in
der Mitte verfügbar. Bearbeiten ist möglich; **In Zwischenablage kopieren**
übernimmt anschließend exakt den geprüften UTF-8-Text in die lokale Zwischenablage.
Dafür muss kein Terminal geöffnet sein. Die Rückgabequelle links ist unabhängig
wählbar und ändert dieses Ziel nicht.

Beim Anzeigen oder Bearbeiten wird nichts kopiert. Das Ziel wird schon bei der
Übernahme festgehalten, auch während der Bridge-Bestätigung, und bleibt beim
Bearbeiten erhalten. Während der aktiven Prüfung ist die Zielauswahl gesperrt.
Ein Clipboard-Review kann über den normalen Terminalfreigabeweg nicht gesendet
werden. Pause, Bridge-Bindung und Ablaufzeit werden vor dem Kopieren geprüft.
Scheitert das Schreiben der Zwischenablage, bleibt der Review für einen erneuten
Versuch offen. Der Status nach Erfolg lautet „In Zwischenablage kopiert · nicht
ausgeführt“. Der Freigabebutton ist danach bis zur nächsten Prüfung deaktiviert.

Kein automatisches finales Return: Die Terminalpräferenz bleibt erhalten, wird
für dieses Ziel aber nicht angehängt. Interne Zeilenumbrüche werden weiterhin
angezeigt; manuelles Einfügen mehrzeiligen Textes in eine Shell kann dort Befehle
ausführen. Einfügen und Ausführen in einer anderen Anwendung liegen beim Nutzer.
Die App legt durch Kopieren keinen Transfer-/Ausführungsnachweis und keine neue
Terminalrückgabe an. Eine frühere offene Terminalrückgabe bleibt erhalten.
Bridge-seitig bleibt der Vorschlag TAKEN; manuelle Ausführung andernorts wird
nicht behauptet. Rückgaben aus der Zwischenablage bleiben standardmäßig
unabhängige Beobachtungen, wie in v0.9.19 beschrieben.

## Prüfung und Grenzen

Die bestehende unittest-/Tk-/PTY-/HTTP-Infrastruktur wird weiter verwendet.
Neue Tests prüfen einen echten lokalen MCP-Vorschlag bei nie geöffneter Shell,
verzögertes Kopieren erst nach Klick, Bearbeiten, festes Ziel, Pause, Schreibfehler
mit Wiederholung, exakten Text ohne angehängtes Return und keine Ausführung.
Ein PTY-Fall prüft, dass Kopieren eine frühere Terminalrückgabe nicht schließt
oder neu zuordnet. Ein bestehendes Analyzer-Fixture prüft die asynchrone
Risikoanalyse ohne Terminalsitzung und Erhalt ihres Befunds nach dem Kopieren.

Bestanden unter Linux/Python 3.12 mit Xvfb: 51 GUI-/Statusfälle, 12 Übernahme-/
Rückgabefälle, 22 Risikoanalysefälle, 18 sh-guard-UX-Fälle, 49 Selbsttests und 11
Updatefälle. Insgesamt 163 Fälle. Beim ersten GUI-Lauf fiel die Platzverteilung
in kleinen Fenstern auf; nach kompakterer Anordnung und Wiederherstellung der
bestehenden Dropdown-Reihenfolge wurde der GUI-Lauf vollständig wiederholt.
`git diff --check` ist sauber. Keine neue Testinfrastruktur oder Abhängigkeiten.

Quelle und Ziel verwenden nur die Text-Zwischenablage des lokalen App-Qubes.
Qubes-übergreifendes Einfügen muss der Nutzer selbst vornehmen. Verfügbarkeit
nach App-Ende hängt vom Clipboard-Manager ab. Native Qubes-/macOS-Abnahme,
ein Live-Provider-Tunnel zum Nutzergerät und Werkzeuge im konkreten Nutzerchat
sind hier nicht belegt. Die Tunnelkorrektur aus v0.9.20 ist unverändert enthalten;
ihr eigener Prüfnachweis steht im [vorigen Bericht](RELEASE_V0.9.20.md).

## Aktualisieren

[Python-Datei](https://raw.githubusercontent.com/geco91/admin-in-the-loop/refs/tags/v0.9.21/admin_in_the_loop.py) ·
[ZIP](https://github.com/geco91/admin-in-the-loop/archive/refs/tags/v0.9.21.zip)

Bei geschlossener Controller-App: `python3 admin_in_the_loop.py update geco91`.
Die Zielerweiterung braucht kein neues Bridge-Protokoll. Für die ebenfalls
enthaltene Tunnelkorrektur muss die Bridge mindestens v0.9.20 verwenden. Bei
älterem Bridge-Stand dort dieselbe aktuelle Datei bereitstellen und mit dem
bisherigen Startbefehl sowie **demselben State-Verzeichnis** neu starten.
