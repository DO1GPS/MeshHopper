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

Die vorhandenen Befehlsfamilien teilen sich die Empfangsauswertung:
`ping` und `reping` führen zu `PONG`, `test` und `retest` zu `TEST`,
`room` zu `ROOM`. `ping test` und `test ping` führen jeweils zu einer
`TEST`-Antwort. Die Wörter sind nicht beliebig austauschbar oder kombinierbar;
`PONG` ist eine Antwort und kein auslösender Befehl.

Für eine Textänderung ist `bot_report.py` der Einstieg. Der Test
`test_ping_test_room_real_packet_roundtrip_hare_snr_no_rssi_or_hex_line`
zeigt das vollständige erwartete Format und kontrolliert auch das tatsächlich
vorbereitete Paket. Erwartung und Text müssen zusammenpassen; Nachweise und
Größenprüfungen bleiben erhalten.

Ein Emoji braucht mehrere UTF-8-Bytes. Ein längerer Botname lässt weniger
Platz für den Weg. RSSI bleibt in den Empfangsdaten; der kurze Antworttext
zeigt SNR. Ein nicht eindeutig aufgelöster Repeater bleibt etwa `b5?`.
Ein Kontaktname ist keine bestätigte Funkidentität. Ein fehlender Rückweg
darf nicht durch einen geschätzten ersetzt werden.

Der öffentliche Botkern verwendet den neutralen Anzeigenamen `MeshHopper`.
Eigene Anzeigenamen werden in `services/bot/bot_identity.py` festgelegt.
Danach die Pakettests erneut ausführen: Die Namenslänge beeinflusst das
verbleibende Textbudget. Der Autorenhinweis DO1GPS steht davon getrennt in
README, Lizenz und Quellenhinweisen.

## Betriebsprofil und bekannte Einschränkungen

Eine Sperre der gemeinsamen Chatdatenbank konnte gültige Anfragen vor dem
Senden abbrechen. Der Bot speichert Antwortversuche deshalb jetzt getrennt
in `bot-replies.sqlite3`.

Ein synthetischer Test des vollständigen Nachrichtenhandlers zeigt: Auch
bei gesperrter alter Chatdatenbank erreicht eine gültige `test`-Anfrage die
simulierte Sendefunktion genau einmal. Das Annahmeergebnis wird gespeichert;
ein Duplikat löst keinen zweiten Versuch aus. Der Speicherfix hat außerdem
eine vollständige Linux-Prüfung mit 461 Tests ohne Fehler oder ausgelassene
Prüfungen bestanden.

Die ergänzte Startlogik ist geprüft; die bestehende Home-Assistant-Installation
ist mit dem getrennten Antwortspeicher wieder angelaufen. Die Zustellung
bei einer fremden Funkstation und der Dauerbetrieb bleiben gesondert
nachzuweisen. Die bestandenen Tests sind keine allgemeine Betriebsfreigabe.

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
gesperrt. Die Profiltests prüfen dies ausschließlich mit erfundenen Daten,
nicht mit einem echten Funkgerät. Die laufende Installation wird durch
diese öffentliche Profilfassung nicht verändert.

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
