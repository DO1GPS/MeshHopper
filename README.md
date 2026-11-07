# MeshHopper für MeshCore

Aktueller öffentlicher Entwicklungsstand: **Version 3.1**.

MeshHopper ist ein Ping- und Testbot für MeshCore. Er beantwortet
`ping`- und `test`-Anfragen automatisch mit einem kompakten
Empfangsbericht. Dieser enthält die Anzahl der Hops (Weiterleitungsschritte),
den SNR (Signal-Rausch-Abstand) am Monitor und den aus den Empfangsdaten
erkennbaren Weg über Repeater (weiterleitende Funkstationen). So lässt sich
nachvollziehen, wie eine Anfrage am Monitor angekommen ist und welche
Repeater in ihrer Empfangskette erkennbar sind.

Die normale Antwort bleibt kurz: Der Weg zeigt höchstens die ersten zwei
und letzten zwei Repeater, bei längeren Namen nur Anfang und Ende.
`…` kennzeichnet ausgelassene Zwischenstationen. Wer die ganze erfasste
Kette sehen möchte, sendet `pfad`, `path`, `weg`, `way` oder `route`.
Eine kurze Befehlsübersicht gibt es mit
`hilfe`, `help` oder `dir`. `version` und `#version` nennen den aktuellen
Botstand. Direkt angesprochen beantwortet MeshHopper außerdem kurze Grüße,
`wer bist du?` und `was kannst du?`.

Eine `ping`-Anfrage wird mit `PONG` beantwortet, `test` mit `TEST`.
`room` zeigt den aktuellen Kanal und die weiteren Kanäle, in denen der
Bot antwortet. Weitere Schreibweisen lassen sich in der Befehlserkennung
ergänzen.

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

## Diese Befehle kennt der Bot

| Anfrage | Antwort |
| --- | --- |
| `ping`, `reping`, `PING` | `PONG` |
| `test`, `retest`, `Test` | `TEST` |
| `ping test`, `test ping` | `TEST` |
| `room` | Aktueller Kanal und weitere eingerichtete Botkanäle |
| `ping 123` | `PONG`; die Zahl kennzeichnet die Anfrage |
| `#ping`, `#test`, `#room` | Wie der entsprechende Befehl ohne `#` |
| `danke`, `thanks`, `danke 73` | `🤖 Gern geschehen ✌🏻, 73` |
| `pfad`, `path`, `weg`, `way`, `route` (auch mit `#`) | Vollständiger RX-Weg des letzten angenommenen Ping/Tests im selben Kanal, bei Bedarf in mehreren Teilen |
| `hilfe`, `help`, `dir` | Kurze Befehlsübersicht in einer Nachricht |
| `#hilfe`, `#help`, `#dir` | Dieselbe Befehlsübersicht |
| `version`, `#version` | Aktueller Botstand |
| `@MeshHopper hallo` | Kurze Begrüßung; gilt auch für `hi`, `hey`, `moin`, `servus`, `gude`, `ahoi` und Tagesgrüße |
| `@MeshHopper wer bist du?` | Kurze Identitätsauskunft |
| `@MeshHopper was kannst du?` | Kurze Funktionsauskunft |

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

`version` und `#version` sind vollständige Befehle. Texte wie
`version 3.1`, `versionierung` oder `welche version` lösen keine
Versionsantwort aus. Grüße reagieren nur auf eine vollständige direkte
Ansprache des Bots; ein allgemeines `hallo` im Kanal bleibt still. So
entsteht kein Begrüßungsdialog zwischen mehreren Bots.

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
🏁 PONG @Mobile
📡 8 🐇 | SNR +11.5 dB
📩 BF → 84 → … → 44 → 3C
🏠 nicht gesetzt
```

Die Zielflagge markiert eine `PONG`- oder `TEST`-Antwort.
Die frühere `TX:`-Zeile entfällt. Der Scope (eingestellte
Weiterleitungsbereich) wird weiterhin aus dem Geräteprofil übernommen.
Das Wort `he` im Anfragewortlaut ändert diesen Bereich nicht und ist
kein eigener Befehl.

`📡` bedeutet Empfang am Monitor. `8 🐇` sind acht Hops
(Weiterleitungsschritte), nicht zwingend acht verschiedene Repeater.
`SNR` ist der Signal-Rausch-Abstand dieses Empfangs. Er beschreibt nicht
die Qualität aller Zwischenstationen. Der kurze Text enthält keine RSSI
(Empfangsleistung); vorhandene Rohmesswerte werden dadurch nicht gelöscht.

`📩` zeigt die Kurzfassung des eingehenden Wegs. Ortsnamen werden gekürzt,
zum Beispiel `Grünberg-Nord` zu `Grün-N`; erkennbare Rufzeichen bleiben ganz.
Bei unbekannten oder nicht eindeutig zugeordneten Repeatern stehen die
ersten zwei Hexzeichen der erfassten Kennung, etwa `BF`. Diese Kurzform ist
keine eindeutige Gerätekennung. `→` zeigt die Reihenfolge; `…` ersetzt
ausgelassene Positionen und behauptet keine direkte Verbindung dazwischen.
Die Pfadzeile ist auf 22 Textzeichen begrenzt. Das verkürzt die Darstellung,
garantiert aber nicht bei jeder Smartphone-Schriftgröße eine einzige Zeile.

`🏠` bezeichnet das QTH (den Standort) des Monitors, nicht den Standort des
Anfragenden. Die öffentliche Fassung hat keinen voreingestellten
Betreiberstandort. `MESHCORE_MONITOR_QTH` setzt ihn lokal; ohne Angabe
steht `nicht gesetzt`. Das Bytebudget gilt auch für diese Zeile.

Der Antworttext behauptet keinen bestätigten Rückweg. Ein lokales OK oder
der Empfang einer eigenen Funkkopie beweist keine Zustellung beim Absender.

Die Zuordnung zur Anfrage bleibt intern; der Antworttext enthält keine
zusätzliche technische Zuordnungsnummer. Fehlen passende Empfangsdaten,
steht `📡 unbekannt` und `📩 nicht erfasst`. Liefert ein dafür geprüftes
Firmwareformat nur Hops und SNR zur exakten Anfrage, dürfen diese Werte
erscheinen; daraus wird kein fehlender Pfad rekonstruiert. Bei mehreren gültigen
Empfangskopien verwendet der Bericht die erste vollständig geprüfte Kopie:
Hops, SNR und Weg stammen zusammen aus diesem Empfang. Die interne
Mehrdeutigkeit bleibt erhalten; der Text behauptet weder einen einzigen
Funkweg noch eine Übersicht aller Kopien. Nicht belegte Werte werden nicht
ergänzt.

## Vollständigen RX-Weg anfordern

Eine Station sendet `pfad`, `path`, `weg`, `way`, `route` oder die jeweilige
Hashtag-Form im freigegebenen Kanal. Der Bot
gibt den vollständigen erfassten Empfangspfad des zuletzt angenommenen
Ping/Test im gleichen Kanal aus. Beispiel: Mobile pingt,
Basis fragt danach `pfad` an — die Antwort nennt Mobile und zeigt deren
Empfangsweg. Der Weg der PFAD-Anfrage wird nicht stattdessen verwendet.

Maßgeblich ist die Reihenfolge, in der der Bot neue Anfragen angenommen
hat, nicht die Uhrzeit der fremden Station. Jeder Kanal hat sein eigenes
letztes Ziel. Eine PFAD-, ROOM-, Hilfe- oder Dankanfrage ersetzt es nicht.

Ein eigenes Beispiel mit erfundenen Kennungen:

```text
📩 RX-Weg @Mobile
01 → DB0KT [BF12]
02 → [8456]
03 → Grünberg-Nord [9900]
🏠 Ziel → nicht gesetzt
```

Jede Position ist nummeriert und steht auf einer eigenen Zeile. In den
Klammern bleibt der vollständige erfasste Präfix (Anfang der Repeaterkennung):
je nach Funkformat 2, 4 oder 6 Hexzeichen. Es werden keine fehlenden Zeichen
ergänzt. Auch wiederholte Kennungen bleiben als eigene Positionen erhalten.
Ein Name wird nur bei eindeutiger Zuordnung im vorhandenen Kontaktbestand
angezeigt; das ist kein kryptografischer Identitätsnachweis.
RX-Weg verwendet die vorhandenen vollständigen Namen, nicht die starken
Kürzungen der normalen Antwort. Bei mehreren passenden Kontakten wird
die Zahl der Kandidaten angegeben, kein Name geraten. Ein einzelner
überlanger Name samt Kopf und Kennung kann die Ausgabe noch verhindern;
der Bot schneidet dann kein Paket oder Teile einer Kennung ab.

Längere Wege werden auf mehrere Nachrichten verteilt. `· 1/3`, `· 2/3`,
`· 3/3` im Kopf geben Teilnummer und Gesamtzahl an. Bei genau einer Nachricht
entfällt der Zusatz vollständig; es gibt kein `1/1`.
Die Positionsnummerierung läuft weiter. Das konfigurierte lokale Ziel steht
als eigener Endpunkt unter der erfassten Repeaterfolge.
Der Bot hält das UTF-8-Bytebudget (Grenze des codierten Textes) pro Nachricht
ein. Nach einem fehlgeschlagenen oder unklaren Sendeversuch wird die Reihe
angehalten, nicht automatisch wiederholt. Fehlende Teile sind kein Beweis,
dass die bereits gesendeten Teile nicht angekommen sind.

Ein neuer Ping ohne erfassten Pfad ersetzt das vorige Ziel ebenfalls.
Die Antwort nennt dann diese Station und `Empfangspfad nicht erfasst`;
ein älterer Weg wird nicht untergeschoben. Ohne angenommenen Ping/Test
in der aktuellen Sitzung heißt es `📩 Noch kein Ping/Test in diesem Kanal`.
Bei Direkt-Empfang steht `direkt`, ohne erfundene Zwischenstationen.
Nach einer neuen Geräteverbindung wird kein Ziel aus der alten Sitzung
übernommen. Ein späterer Ping ändert eine bereits vorbereitete PFAD-Serie
nicht. Rohdaten, die erst danach eintreffen, helfen erst der nächsten Anfrage.

Direkt nach einer vollständig angenommenen RX-Weg-Serie kann eine Station den
Bot mit `pong from <Ort oder Station>` ansprechen. Nur derselbe Kanal und
dieselbe Verbindungssitzung zählen; das Zeitfenster beträgt 90 Sekunden und
wird genau einmal verbraucht. Die kurze Antwort lautet:

```text
Ich bin ein Bot und habe nur eine Wegabfrage beantwortet. Eine Antwort ist nicht nötig.
```

Ältere, unadressierte oder wiederholte Texte bleiben still. Die Erkennung der
Textform ist kein Identitätsnachweis für den Absender.

## Kanäle mit ROOM abfragen

`room` und `#room` verwenden die abgefragten Kanalnamen der aktuellen
Botsitzung. Angezeigt werden nur die eingerichteten Botkanäle, nicht alle
Kanäle des Geräts oder des Funknetzes. Beispiel mit erfundenen Namen:

```text
🏠 ROOM

📍 #test · hier
✅ #ping
✅ #beispiel
```

Passen die Namen nicht ins Paket, bleiben die genauen Kanalindizes
als `Kanal 2` sichtbar. ROOM behauptet keine zusätzliche Funkmessung.

## Hilfe im Kanal

`hilfe`, `help`, `dir`, `#hilfe`, `#help` und `#dir` liefern dieselbe
kurze Übersicht in einer Nachricht:

```text
🤖 HILFE
📡 ping/test
🏠 room
📩 pfad/path/weg
🙏 danke/73
📖 hilfe/help/dir (#)
🔖 version
```

Groß- und Kleinschreibung sind egal. `dir` ist hier nur ein Alias
(alternative Schreibweise) für Hilfe, kein Zugriff auf Dateien.
Die Hilfe nennt die drei gebräuchlichsten Wegbefehle; `way` und `route`
bleiben als weitere vollständige Aliase gültig.
Gesprächssätze wie `help me`, Zusätze wie `dir 1` und `# dir` lösen
keine Antwort aus. Die Hilfe benötigt keine Empfangsmesswerte.

## Quellcode und Erweiterungen

Die Anleitung für eigene Änderungen steht in
[MeshHopper entwickeln](docs/public/DEVELOPMENT.de.md).

Die wichtigsten Bereiche sind getrennt:

- [bot_commands.py](services/bot/bot_commands.py) erkennt Befehle.
- [bot_dialogue.py](services/bot/bot_dialogue.py) enthält kurze, terminale
  Dialogantworten, die keine weitere Bot-Schleife auslösen sollen.
- [reception_evidence.py](services/bot/reception_evidence.py) prüft eine
  Empfangskopie und ihre Messwerte.
- [bot_report.py](services/bot/bot_report.py) macht daraus einen kurzen Text.
- [report_engine.py](services/bot/report_engine.py) ordnet Anfrage und
  Empfang zusammen, merkt das letzte Ping/Test-Ziel je Kanal und bereitet
  Antwortpakete vor.
- [bot_contact_catalog.py](services/bot/bot_contact_catalog.py) übernimmt
  laufend empfangene Kontaktdaten ohne zusätzliche Geräteabfragen.
- [bot_timing.py](services/bot/bot_timing.py) misst begrenzte lokale
  Verarbeitungsschritte, nicht die Funkzustellung oder reine Bluetooth-Zeit.
- [path_inference.py](services/bot/path_inference.py) bewertet optionale
  Ortskontexte, ohne mehrdeutige Kennungen als sicher auszugeben.
- [bot_runtime_status.py](services/bot/bot_runtime_status.py) schreibt einen
  begrenzten lokalen Laufzeitstatus ohne Nachrichtentexte.
- [local_path_dispatch.py](services/bot/local_path_dispatch.py) übernimmt
  intern ausgelöste Weganfragen über einen lokalen, begrenzten Kanal.
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
