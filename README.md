# MeshHopper für MeshCore

MeshHopper ist ein Ping- und Testbot für MeshCore. Er beantwortet
`ping`-, `test`- und `room`-Anfragen automatisch mit einem kompakten
Empfangsbericht. Dieser enthält die Anzahl der Hops (Weiterleitungsschritte),
den SNR (Signal-Rausch-Abstand) am Monitor und den aus den Empfangsdaten
erkennbaren Weg über Repeater (weiterleitende Funkstationen). So lässt sich
nachvollziehen, wie eine Anfrage am Monitor angekommen ist und welche
Repeater in ihrer Empfangskette erkennbar sind.

Eine `ping`-Anfrage wird mit `PONG` beantwortet, `test` mit `TEST` und
`room` mit `ROOM`. Die Befehle verwenden dieselbe Empfangsauswertung;
weitere Schreibweisen lassen sich in der Befehlserkennung ergänzen.

Das Projekt enthält Quellcode, Beispiele und Tests für Interessierte und
Funkamateure, die den Empfangsbericht nachvollziehen oder den Bot selbst
weiterentwickeln möchten.

Projektautor und GitHub-Konto: DO1GPS.

## Was in dieser Fassung steckt

Der Botkern lässt sich ohne Funkgerät prüfen und weiterentwickeln.
Eine fertige Home-Assistant-App gehört noch nicht zum öffentlichen Paket.
Der bisher geprüfte Empfangsbericht verwendet einen Seeed Wio Tracker L1
als MeshCore-Companion (Funkgerät mit App-Anbindung), mit Firmware
`1.17.1-d929643`. Andere Geräte oder Firmwarestände sind für diesen
Sendepfad nicht freigegeben.

In der öffentlichen Codefassung wird der eigene Geräteanzeigename lokal
über die Umgebungsvariable (lokale Programmeinstellung)
`MESHCORE_COMPANION_NAME` gesetzt. Es gibt keinen persönlichen Vorgabewert.
Die Geräteprüfung bricht bei fehlender Angabe oder einem abweichenden
Gerätenamen ab; Modell und Firmware werden weiterhin geprüft.

Eine allgemeine Neuinstallation benötigt noch einen eigenen, getesteten
Einrichtungsweg.
Die vorhandenen Geräte- und Übernahmeprüfungen bleiben erhalten.

Diese Entwicklungsfassung steht unter der [MIT-Lizenz](LICENSE).
Sie ist keine offizielle MeshCore-Software. Die öffentliche Entwicklungsfassung
wird unter `DO1GPS/MeshHopper` geführt.

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
nachzuweisen. Der öffentliche Stand bleibt eine Entwicklungsfassung.

## Diese Befehle kennt der Bot

| Anfrage | Antwort |
| --- | --- |
| `ping`, `reping`, `PING` | `PONG` |
| `test`, `retest`, `Test` | `TEST` |
| `ping test`, `test ping` | `TEST` |
| `room` | `ROOM` |
| `ping 123` | `PONG`; die Zahl kennzeichnet die Anfrage |
| `#ping`, `#test`, `#room` | Wie der entsprechende Befehl ohne `#` |
| `danke`, `thanks`, `danke 73` | `🤖 Gern geschehen ✌🏻, 73` |

Die Erkennung unterscheidet nicht zwischen Groß- und Kleinschreibung.
Ein einzelnes `#` darf direkt vor dem ersten Befehlswort stehen, auch bei
`#reping`, `#retest` und `#ping test`. `##ping`, `# ping` und `ping #test`
sind keine gültigen Befehle. Sätze wie „Ping von 55566“ bleiben ebenfalls
ohne automatische Antwort.
Die Zahl darf ein bis sechs Ziffern
`0–9` haben und muss mit einem Leerzeichen oder Tab getrennt sein.
Sie kennzeichnet keine Anzahl von Wiederholungen. Nur vollständige
Befehlsformen lösen eine Antwort aus; Gesprächssätze wie „bitte ping mich“
und fremde `PONG`-Antworten bleiben ohne Reaktion.

Die Dankantwort hat eigene, vollständige Befehlsformen: `danke`, `thanks`
und jeweils der Zusatz `73`; auch `@MeshHopper danke` ist möglich.
`#danke` und längere Gesprächssätze lösen sie nicht aus. Bekannte
Bot-Absender lösen mit einem Danktext keine weitere Dankantwort aus.

`reping` und `retest` sind alternative Schreibweisen. Befehle sind nicht
beliebig kombinierbar: `ping test` ergibt eine `TEST`-Antwort, während
`room test` und `ping ping` nicht als gültige Anfrage erkannt werden.

Für das folgende Offline-Beispiel (Prüfung ohne Funkverbindung) ist
Python 3.11 oder 3.12 erforderlich. Aufruf im Projektordner:

```shell
python examples/inspect_meshhopper_commands.py
python examples/inspect_meshhopper_commands.py "ReTest" "ping test" "bitte ping mich"
```

Der zweite Aufruf zeigt zweimal `TEST` und einmal „keine Antwort“.
Das Beispiel prüft nur die Befehlserkennung. Es braucht keine Zusatzpakete,
startet keinen Bot und öffnet keine Verbindung.

## Antworttext und Erläuterung

Beispiel mit erfundenen Stationsbezeichnungen:

```text
PONG @Mobile
TX: de-he
RX: 2 🐇 | SNR +11.5 dB
Weg: Nord→Mitte
QTH: nicht gesetzt
```

`TX:` nennt den verwendeten Scope (eingestellten Weiterleitungsbereich),
hier `de-he`. Das Wort `he` im Anfragewortlaut ändert diesen Bereich nicht.

`RX:` bedeutet Empfang am Monitor. `2 🐇` sind zwei Hops
(Weiterleitungsschritte), nicht zwingend zwei verschiedene Repeater.
`SNR` ist der Signal-Rausch-Abstand dieses Empfangs. Er beschreibt nicht
die Qualität aller Zwischenstationen. Der kurze Text enthält keine RSSI
(Empfangsleistung); vorhandene Rohmesswerte werden dadurch nicht gelöscht.

`Weg:` nennt die erkennbaren eingehenden Stationen in ihrer Reihenfolge.
Kann eine kurze Repeaterkennung nicht eindeutig einem Kontakt zugeordnet
werden, bleibt etwa `b5?` stehen. Das Fragezeichen bedeutet, dass der Name
nicht eindeutig aufgelöst ist. `...` kennzeichnet ausgelassene
Zwischenstationen in einem gekürzten Bericht. `→` trennt die Stationen;
`letzter` bezeichnet ausdrücklich nur den letzten erfassten Hop.

`QTH:` bezeichnet den Standort des Monitors, nicht den Standort des
Anfragenden. Die öffentliche Fassung hat keinen voreingestellten
Betreiberstandort. `MESHCORE_MONITOR_QTH` setzt ihn lokal; ohne Angabe
steht `nicht gesetzt`. Das Bytebudget gilt auch für diese Zeile.

Der Antworttext behauptet keinen bestätigten Rückweg. Ein lokales OK oder
der Empfang einer eigenen Funkkopie beweist keine Zustellung beim Absender.

Die Zuordnung zur Anfrage bleibt intern; der Antworttext enthält keine
zusätzliche technische Zuordnungsnummer. Fehlen passende Empfangsdaten,
steht `RX: unbekannt` und `Weg: nicht erfasst`. Bei mehreren gültigen
Empfangskopien verwendet der Bericht die erste vollständig geprüfte Kopie:
Hops, SNR und Weg stammen zusammen aus diesem Empfang. Die interne
Mehrdeutigkeit bleibt erhalten; der Text behauptet weder einen einzigen
Funkweg noch eine Übersicht aller Kopien. Nicht belegte Werte werden nicht
ergänzt.

## Quellcode und Erweiterungen

Die Anleitung für eigene Änderungen steht in
[MeshHopper entwickeln](docs/public/DEVELOPMENT.de.md).

Die wichtigsten Bereiche sind getrennt:

- [bot_commands.py](services/bot/bot_commands.py) erkennt Befehle.
- [reception_evidence.py](services/bot/reception_evidence.py) prüft eine
  Empfangskopie und ihre Messwerte.
- [bot_report.py](services/bot/bot_report.py) macht daraus einen kurzen Text.
- [report_engine.py](services/bot/report_engine.py) ordnet Anfrage und
  Empfang zusammen und bereitet ein Antwortpaket vor.
- [meshcore_room_bot.py](services/bot/meshcore_room_bot.py) hält die
  Verbindung und entscheidet, ob ein einmaliger Sendeversuch zulässig ist.

Der Anzeigename des Bots ist keine neue kryptografische Funkidentität.
Der öffentliche Botkern verwendet den neutralen Anzeigenamen `🐇 MeshHopper`.
Eigene Anzeigenamen lassen sich in `services/bot/bot_identity.py` festlegen;
das Textbudget wird dabei aus der Länge des Namens berechnet.
Der persönliche Name des angeschlossenen Geräts wird durch diesen
Sendepfad nicht umbenannt.

## Voraussetzungen für den Dauerbetrieb

In der bestehenden Home-Assistant-Installation laufen Gerätebrücke,
Nachrichtenverteiler, Bot und Dashboard-Server zusammen. Der Server holt
Nachrichten im Hintergrund ab; ein geöffneter Browser ist dafür nicht
nötig. Meshterm ebenfalls nicht. Ohne diesen Server ist der vorgesehene
Empfangsweg jedoch unterbrochen.

Es darf genau einen Nachrichtenabholer am Gerät geben. Mehrere Leser
können sich sonst Nachrichten wegnehmen. Ebenso gehören Datensicherung
und ein getesteter Wiederanlauf dazu. Eigene Chatdaten, Kanalschlüssel,
Geräteadressen und Zugangsdaten bleiben außerhalb des GitHub-Projekts.

Automatische Antworten nur in dafür vereinbarten Kanälen betreiben.
Eine dauerhafte Sperre gegen doppelte Antworten ist kein Zustellnachweis.
Nach einem unklaren Sendeergebnis sendet der Bot dieselbe Anfrage nicht
automatisch erneut. Datenspeicher und Anspruchsregister nicht zur
Fehlersuche löschen.

## Lizenz und Beiträge

Die eigenen MeshHopper-Quellen stehen unter der [MIT-Lizenz](LICENSE),
Copyright (c) 2026 DO1GPS. Externe Bibliotheken und übernommene Bestandteile
behalten ihre eigenen Lizenzen und Autorenhinweise. Die Quellenübersicht
im öffentlichen Paket ist `THIRD_PARTY_NOTICES.md`.

Für Fehlerberichte reichen zunächst Befehl, Kanalindex, ungefähre Zeit und
erwartetes Verhalten. Private Nachrichtentexte, Kanalgeheimnisse oder ganze
Datenbanken nicht öffentlich anhängen.
