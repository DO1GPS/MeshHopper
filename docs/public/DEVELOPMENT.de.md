# MeshHopper verstehen und entwickeln

Diese Anleitung richtet sich an Interessierte und Funkamateure, die die
Empfangsauswertung von MeshHopper prüfen oder den Bot erweitern möchten.
Der Einstieg erfolgt ohne Funkgerät: Beispiele und Tests verwenden
erfundene Daten und senden keine Nachrichten ins Mesh. Eine installierbare
Home-Assistant-App oder Bluetooth-Brücke ist in dieser Entwicklungsfassung
noch nicht enthalten.

## Befehlserkennung ohne Funkgerät prüfen

Voraussetzung ist Python 3.11 oder 3.12. Aufruf im Projektordner:

```shell
python examples/inspect_meshhopper_commands.py
python examples/inspect_meshhopper_commands.py "ReTest" "ping test" "bitte ping mich"
```

Das zweite Beispiel zeigt zweimal `TEST` und einmal „keine Antwort“.
Es erkennt nur Befehle; es sendet keine Nachricht und benötigt keine
Zusatzpakete, Kanalschlüssel oder Verbindung.

Je nach Installation heißt der Python-Aufruf `python`, `py` oder `python3`.
Für die folgenden Schritte muss derselbe Interpreter verwendet werden.

## Die Programmlogik testen

Eine virtuelle Python-Umgebung hält die Bibliotheken des Projekts getrennt
von anderen Programmen. Sie wird im Projektordner angelegt:

```shell
python -m venv .venv
```

Unter Windows werden Installation und Test mit diesem Interpreter aufgerufen:

```shell
.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.venv\Scripts\python.exe -B -m unittest discover -s tests
```

Unter Linux oder macOS lautet der Aufruf:

```shell
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -B -m unittest discover -s tests
```

Die Installation lädt PyCryptodome, eine Kryptografie-Bibliothek. Die Tests
selbst arbeiten ohne Netzwerk und Geräte. Sie prüfen unter anderem
Befehle, Paketaufbau, Zuordnung der Empfangswerte und das Bytebudget
(maximale Länge des codierten Textes). Alle Schlüssel und Stationen der
Tests sind erfunden. Bestandene Tests beweisen keine Funkzustellung.

Der Testlauf muss ohne Fehler enden und `OK` ausgeben.

!!! Bei einem fehlgeschlagenen Test keinen Funkbetrieb starten. Zuerst die
Fehlermeldung und die abweichende Erwartung prüfen.

## Eine Nachricht durch den Code verfolgen

1. `bot_commands.py` erkennt eine vollständig erlaubte Befehlsform.
2. `reception_evidence.py` prüft eine Empfangskopie und deren Messwerte.
3. `report_engine.py` ordnet Originaltext, Senderzeit und Kanal exakt zu.
4. `bot_report.py` formatiert die belegten Werte als kurzen Antworttext.
5. `group_sender.py` bereitet das verschlüsselte Paket vor.
6. `meshcore_room_bot.py` prüft im Betrieb, ob genau ein Versuch zulässig ist.

Die Befehlserkennung ignoriert Groß- und Kleinschreibung. Für die
Zuordnung bleibt die Originalnachricht trotzdem unverändert. Sonst könnten
Messwerte einer anderen Anfrage zugeordnet werden.

## Befehlsvarianten und Antwortformat erweitern

Eine überschaubare Erweiterung ist eine zusätzliche Befehlsvariante oder
ein angepasstes Antwortformat. Ein Alias (alternative Schreibweise) benötigt
zwei Änderungen in
`bot_commands.py`: Er muss zum Muster `COMMAND` passen und in `FAMILIES`
dem richtigen Befehl zugeordnet sein. Der zugehörige Test in
`tests/test_bot_public_core.py` muss die neue Schreibweise und einen ähnlichen
Gesprächssatz abdecken, der keine Antwort auslösen darf. Anschließend wird
die vollständige Testsuite ausgeführt. Das prüft den Botkern, nicht die
Zustellung im Funknetz.

`ping` und `reping` führen zu `PONG`, `test` und `retest` zu `TEST`.
`room` zeigt den aktuellen Kanal und die weiteren eingerichteten
Botkanäle aus dem abgefragten Sitzungsprofil. Es benötigt keine Funkmessung.
`ping test` und `test ping` führen jeweils zu einer
`TEST`-Antwort. Die Wörter sind nicht beliebig austauschbar oder kombinierbar;
`PONG` ist eine Antwort und kein auslösender Befehl.

Ein einzelnes `#` darf direkt vor dem ersten Befehlswort stehen, etwa
`#test` oder `#ping test`. `##test` und `# test` sind keine Befehle.
`danke`, `thanks` und jeweils der Zusatz `73` erzeugen
`🤖 Gern geschehen ✌🏻, 73`; `@MeshHopper danke` wird ebenfalls erkannt.
Diese Dankformen verwenden keinen Hashtag. Bekannte Bot-Absender lösen
keine Dankantwort auf ihre eigenen Danktexte aus.

`pfad` und `#pfad` geben den vollständigen Empfangspfad des zuletzt
angenommenen Ping/Test im gleichen Kanal aus. Die PFAD-Anfrage
bestimmt nur, wer die Details anfordert; ihr eigener Empfangsweg wird
nicht stattdessen ausgegeben.
`hilfe`, `help`, `dir`, `#hilfe`, `#help` und `#dir` führen zur Familie
`help`. Sie liefern eine feste Übersicht, keine Empfangsmessung.
Für `dir` wird kein Verzeichnis gelesen und kein Systembefehl ausgeführt.

Für eine Textänderung ist `bot_report.py` der Einstieg. Der Test
`test_ping_test_room_real_packet_roundtrip_hare_snr_no_rssi_or_hex_line`
zeigt das vollständige erwartete Format und kontrolliert auch das tatsächlich
vorbereitete Paket. Erwartung und Text müssen zusammenpassen; Nachweise und
Größenprüfungen bleiben erhalten.

Ein Emoji braucht mehrere UTF-8-Bytes. Ein längerer Botname lässt weniger
Platz für den Weg. RSSI bleibt in den Empfangsdaten; der kurze Antworttext
zeigt SNR. Ein nicht eindeutig aufgelöster Repeater bleibt als Kurzkennung
wie `B5` sichtbar. Ortsnamen werden gekürzt, Rufzeichen bleiben ganz.
Ein Kontaktname ist keine bestätigte Funkidentität. Der Bericht beschreibt
den Empfang am Monitor, keinen bestätigten Rückweg. Bei mehreren passenden
Empfangskopien stammen Hops, SNR und Weg zusammen aus der ersten vollständig
geprüften Kopie. Die interne Mehrdeutigkeit wird dadurch nicht aufgehoben.

Der öffentliche Botkern verwendet den neutralen Anzeigenamen `🐇 MeshHopper`.
Eigene Anzeigenamen werden in `services/bot/bot_identity.py` festgelegt.
Danach die Pakettests erneut ausführen: Die Namenslänge beeinflusst das
verbleibende Textbudget. Der Autorenhinweis DO1GPS steht davon getrennt in
README, Lizenz und Quellenhinweisen.

Das Antwortformat hält die Angaben in vier Zeilen auseinander:

```text
🏁 PONG @Mobile
📡 8 🐇 | SNR +11.5 dB
📩 BF → 84 → … → 44 → 3C
🏠 nicht gesetzt
```

`QTH` ist der Standort des Monitors, nicht GPS des Anfragenden.
`MESHCORE_MONITOR_QTH` setzt ihn lokal; es gibt keinen Betreiberstandort
als Vorgabe. Beispiel mit erfundenem Standort unter PowerShell:

```powershell
$env:MESHCORE_MONITOR_QTH = "Teststation"
```

Unter Linux oder macOS:

```shell
export MESHCORE_MONITOR_QTH="Teststation"
```

Auch diese Angabe zählt zum Bytebudget. Zu lange Texte werden nicht durch
ein größeres Paketlimit ermöglicht. Nach eigenen Änderungen deshalb den
vollständigen Pakettest laufen lassen.

### Kurzpfad und vollständiger Pfad

`_route_choices` in `bot_report.py` erzeugt die normale Kurzfassung.
Bei mehr als vier Positionen werden zuerst die ersten zwei und letzten
zwei angeboten. Passt das nicht in 22 Textzeichen oder ins Paketbudget,
bleiben Anfang, `…` und Ende. Die erfasste Kette wird dabei nicht verändert.
Eine Textzeichengrenze ist keine Garantie für die Darstellung bei jeder
Smartphone-Schriftgröße.

`path_response_bodies` formatiert jede erfasste Position des ausgewählten
Ping-/Testbefehls einzeln. Die Kennung bleibt mit 2, 4 oder 6 Hexzeichen
vollständig, entsprechend dem empfangenen Funkformat. Vorhandene Namen
bleiben ausführlich und werden für die Textdarstellung bereinigt; die starke
Kürzung der normalen Antwort gilt hier nicht. Mehrdeutige Kennungen zeigen
die Anzahl der Kandidaten statt eines geratenen Namens. Wiederholte
Positionen werden nicht entfernt. Die Ausgabe ist nummeriert, mit einer
Position pro Zeile direkt unter `📩 PFAD @Station`. Bei mehreren Teilen
steht zusätzlich `· 1/3` im Kopf; die Positionsnummerierung läuft weiter.

Ein einzelner sehr langer Name samt Kopf und Kennung kann das Bytebudget
überschreiten. Dann bricht die Vorbereitung ab, statt Textbytes oder die
Kennung abzuschneiden. Mehrere Nachrichten lösen diese Grenze einer
einzelnen Zeile noch nicht.

`BotReportEngine.remember_probe` speichert nach der Zulassung einer neuen
Gerätenachricht das letzte Ping-/Testziel je Kanal. Entscheidend ist diese
Reihenfolge, nicht die Senderuhr. Rohdaten allein wählen kein Ziel aus.
Der Speicher ist sitzungsgebunden und wird bei neuer Verbindung nicht
übernommen. Es gibt keine zusätzliche Datenbank oder Geräteabfrage.

Auch ein neuer Ping ohne erfassten Pfad ersetzt den vorherigen. PFAD nennt
dann dessen Station und `Empfangspfad nicht erfasst`, nicht einen älteren
Weg. Ohne Ping/Test in dieser Sitzung heißt es
`📩 Noch kein Ping/Test in diesem Kanal`. ROOM, Hilfe, Dank und die
PFAD-Anfrage selbst ersetzen das Ziel nicht. Späte Rohdaten ergänzen nur
die exakt gleiche Kanal-/Zeit-/Textidentität des aktuellen Ziels.

`BotReportEngine.build_path` bereitet die ganze Reihe aus einer geprüften
Empfangskopie dieses Ziels vor, bevor es auf die Sendesperre wartet.
`retime_path` darf später den tatsächlichen Sendezeitpunkt
und die Pakete ändern, nicht den eingefrorenen Pfad. Unterschiedliche
Empfangskopien werden nicht zu einem vermeintlich vollständigen Weg gemischt.
Nach einem unklaren Versand hält der Laufzeitcode die Reihe an und versucht
sie nicht automatisch erneut. Eine lokale Annahme ist kein Zustellnachweis.
Ein neuer Ping ändert keine bereits vorbereitete Reihe. Rohdaten, die
erst nach deren Vorbereitung eintreffen, helfen erst der nächsten PFAD-Anfrage.

Die Pakettests prüfen alle drei Kennungsbreiten, Reihenfolge, wiederholte
Positionen, Teilnummern und das Rücklesen der verschlüsselten Pakete.

### ROOM, Kontakte und Zeitmessung

Das öffentliche Geräteprofil übergibt die wirklich abgefragten Kanalnamen
an `BotReportEngine`. `room_response_body` zeigt den Anfragekanal mit
`📍 … · hier` und die weiteren eingerichteten Botkanäle je in einer
`✅`-Zeile. Es werden keine fremden oder nicht freigegebenen Räume ergänzt.
Bei zu langen Namen werden genaue Kanalindizes verwendet, nicht Räume
weggelassen.

`bot_contact_catalog.py` verarbeitet eintreffende Kontaktmeldungen passiv,
also ohne neue Abfragen oder Hintergrundaufgaben. Eine Kennung ohne Namen
bleibt ein Kandidat und kann eine scheinbar eindeutige Zuordnung aufheben.
Jede Antwort verwendet einen unveränderlichen Stand des Katalogs. Veraltete
Sitzungsmeldungen werden nicht übernommen. Bei Überschreitung der begrenzten
Kapazität werden keine Namen mehr als eindeutig ausgegeben.

`bot_timing.py` ergänzt begrenzte Zeitmessungen für die lokale Verarbeitung.
Der Abschnitt um den SDK-Sendeaufruf (Gerätebibliothek) umfasst auch
Zulassung, Verteiler, Übertragung und Geräteantwort. Er misst weder reine
Bluetooth-Funkzeit noch entfernte Zustellung. Diagnosefehler dürfen den
Sendeablauf nicht verändern. Das optionale `meshcore_command_admission.py`
ordnet Gerätezugriffe über einen lokalen Steuerkanal; ohne dessen lokale
Konfiguration bleibt es inaktiv. Die zugehörige Gerätebrücke ist nicht
Teil dieses öffentlichen Pakets.

### Hilfetext ändern

Der feste Text steht in `HELP_REPLY` in `bot_report.py`. Die Erkennung
steht als `HELP` in `bot_commands.py`. Alle drei Wörter führen zu genau
einer Familie `help`, die den vorhandenen einmaligen Sendeweg verwendet.
Ein Emoji und ein Pfeil brauchen mehrere UTF-8-Bytes; auch die Hilfe muss
zusammen mit dem Anzeigenamen ins bestehende Paketlimit passen. Die
Pakettests prüfen außerdem, dass die Antwort keinen neuen Befehl auslöst.

## Betriebsprofil und bekannte Einschränkungen

Eine Sperre der gemeinsamen Chatdatenbank konnte gültige Anfragen vor dem
Senden abbrechen. Der Bot speichert Antwortversuche deshalb jetzt getrennt
in `bot-replies.sqlite3`.

Der vorhandene Bot verwendet eine TCP-Verbindung zu einer Gerätebrücke.
`requirements-bot.txt` nennt seine Entwicklungsabhängigkeiten. Sie sind
von den Beispielen getrennt. Für die Hauptbibliotheken stehen feste
Versionen darin; das ist noch keine vollständige Versionsliste aller
Zusatzpakete auf jedem Betriebssystem.

Die öffentliche Profilfassung liest den eigenen Geräteanzeigenamen lokal
aus `MESHCORE_COMPANION_NAME` (lokale Programmeinstellung). Es gibt keinen
persönlichen Vorgabewert. Die Geräteprüfung bricht bei fehlender Angabe
oder abweichendem Namen ab. Sie verlangt außerdem einen Seeed Wio Tracker L1
mit Firmware `1.17.1-d929643`; andere Modelle und Firmwarestände bleiben
gesperrt.

Beispiel für einen erfundenen Gerätenamen unter PowerShell:

```powershell
$env:MESHCORE_COMPANION_NAME = "Mein Companion"
```

Unter Linux oder macOS:

```shell
export MESHCORE_COMPANION_NAME="Mein Companion"
```

!!! Für eine eigene Installation muss die Angabe exakt dem Anzeigenamen
des angeschlossenen Companion entsprechen. Kanalgeheimnisse und andere
Zugangsdaten nur lokal speichern, nicht ins Repository übernehmen.

Der Prozess startet standardmäßig im älteren Antwortmodus `legacy`.
Für das beschriebene Format ist `raw_qsl` notwendig. Kanalindizes,
alleiniger Nachrichtenabholer und Datensicherung müssen separat zu der
Installation passen. Ein Aufruf ohne `--live` verhindert Botantworten,
kann aber Geräteabfragen ausführen; er ist kein Offline-Test.

Der Quellcode hat als Standard die Kanalindizes `1, 2, 5`. Das sind
Slotnummern, keine weltweit festgelegten Kanalnamen. Vor eigenem Funkbetrieb
die freigegebenen Indizes über `--channels` ausdrücklich auswählen.

Im bestehenden Home-Assistant-Betrieb startet die App Gerätebrücke,
Nachrichtenverteiler, Bot und Dashboard-Server. Der Server holt Nachrichten
im Hintergrund, auch wenn kein Browser offen ist. Der Bot erhält diese
Daten vom Verteiler. Meshterm wird dafür nicht benötigt; den Server
wegzulassen würde trotzdem den vorgesehenen Empfangsweg unterbrechen.
Diese Brücke und App gehören noch nicht zum öffentlichen Kernpaket.

!!! Vor echtem Funkbetrieb separat Geräteprofil, Verbindungsbesitz,
Kanäle, Sicherung und Wiederanlauf nachweisen. Danach muss eine vereinbarte
zweite Station genau eine Antwort empfangen. Keine alten Anfragen
automatisch erneut senden und keinen Anspruchsdatenspeicher löschen.

## Fehler melden

Nenne Python-Version, Testname, erwartetes und beobachtetes Verhalten.
Nutze erfundene Beispieldaten. Keine echten Kanalgeheimnisse, Nachrichten,
Geräteadressen oder vollständigen Datenbanken öffentlich anhängen.
Die eigenen MeshHopper-Beiträge stehen unter der MIT-Lizenz,
Copyright (c) 2026 DO1GPS; der vollständige Text liegt in `LICENSE`.
Quellen und Fremdlizenzen stehen in `THIRD_PARTY_NOTICES.md` im Projektordner.
